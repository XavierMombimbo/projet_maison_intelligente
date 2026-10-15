from rest_framework import serializers

from .models import Camera


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        unknown = set(data.keys()) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {key: "Champ non autorisé." for key in sorted(unknown)}
            )
        return super().to_internal_value(data)


class CameraSerializer(serializers.ModelSerializer):
    maison_nom = serializers.CharField(source="maison.nom", read_only=True)
    endpoint_source = serializers.CharField(source="endpoint_source_expurge", read_only=True)

    class Meta:
        model = Camera
        fields = (
            "id",
            "nom",
            "maison",
            "maison_nom",
            "type_source",
            "endpoint_source",
            "statut_appairage",
            "surveillance_active",
            "derniere_connexion",
            "date_creation",
        )
        read_only_fields = fields


class PairingRequestSerializer(serializers.Serializer):
    code = serializers.RegexField(r"^\d{6}$", trim_whitespace=True)


class DeviceCredentialsSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=255, trim_whitespace=True)
    device_secret = serializers.CharField(max_length=255, trim_whitespace=True, write_only=True)


class DetectionObjectSerializer(StrictSerializer):
    label = serializers.RegexField(r"^[a-z0-9][a-z0-9._-]{0,63}$")
    confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    bbox = serializers.ListField(
        child=serializers.FloatField(min_value=0.0, max_value=1.0),
        min_length=4,
        max_length=4,
    )
    track_id = serializers.RegexField(
        r"^[A-Za-z0-9._:-]{1,64}$", required=False, allow_blank=False
    )
    face_status = serializers.ChoiceField(
        choices=("recognized", "unknown", "unavailable"), required=False
    )

    def validate_bbox(self, value):
        x, y, width, height = value
        if width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
            raise serializers.ValidationError("La boîte normalisée doit rester dans l’image.")
        return value


class RuleContextSerializer(StrictSerializer):
    id = serializers.RegexField(r"^[a-z0-9][a-z0-9._-]{0,63}$")
    version = serializers.IntegerField(min_value=1, max_value=1000)
    type = serializers.ChoiceField(choices=("presence_prolonged", "line_crossing"))
    duration_seconds = serializers.FloatField(min_value=0.0, max_value=3600.0)
    zone = serializers.DictField()
    line = serializers.DictField(required=False, allow_null=True)
    direction = serializers.ChoiceField(
        choices=("negative_to_positive", "positive_to_negative"),
        required=False,
        allow_null=True,
    )
    track_ids = serializers.ListField(
        child=serializers.RegexField(r"^[A-Za-z0-9._:-]{1,64}$"),
        min_length=1,
        max_length=64,
    )

    @staticmethod
    def _normalized_geometry(value, keys, label):
        if not isinstance(value, dict) or set(value) != set(keys):
            raise serializers.ValidationError(f"{label} invalide.")
        normalized = {}
        for key in keys:
            try:
                normalized[key] = float(value[key])
            except (TypeError, ValueError):
                raise serializers.ValidationError(f"{label} invalide.")
            if not 0 <= normalized[key] <= 1:
                raise serializers.ValidationError(f"{label} hors de l’image.")
        return normalized

    def validate_zone(self, value):
        zone = self._normalized_geometry(value, ("x", "y", "width", "height"), "Zone")
        if zone["width"] <= 0 or zone["height"] <= 0 or zone["x"] + zone["width"] > 1.000001 or zone["y"] + zone["height"] > 1.000001:
            raise serializers.ValidationError("Zone hors de l’image.")
        return zone

    def validate_line(self, value):
        if value is None:
            return None
        line = self._normalized_geometry(value, ("x1", "y1", "x2", "y2"), "Ligne")
        if line["x1"] == line["x2"] and line["y1"] == line["y2"]:
            raise serializers.ValidationError("Les extrémités de la ligne doivent différer.")
        return line

    def validate(self, attrs):
        if attrs["type"] == "line_crossing":
            if not attrs.get("line") or not attrs.get("direction"):
                raise serializers.ValidationError("Une ligne et une direction sont requises.")
        return attrs


class DetectionEventSerializer(StrictSerializer):
    contract_version = serializers.IntegerField(default=1, min_value=1, max_value=3)
    event_id = serializers.UUIDField()
    confidence = serializers.FloatField(min_value=0.0, max_value=1.0, required=False)
    simulated = serializers.BooleanField(default=False)
    observed_at = serializers.DateTimeField(required=False)
    model_name = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$", required=False)
    model_version = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._+:/@-]{0,79}$", required=False)
    objects = serializers.JSONField(binary=True, required=False)
    rule_context = serializers.JSONField(binary=True, required=False)
    capture = serializers.FileField(write_only=True)

    def validate_simulated(self, value):
        if value:
            raise serializers.ValidationError("La simulation n’est plus prise en charge.")
        return False

    def validate(self, attrs):
        version = attrs["contract_version"]
        supplied = set(self.initial_data.keys())
        if version == 1:
            if "confidence" not in attrs:
                raise serializers.ValidationError({"confidence": "Ce champ est obligatoire en v1."})
            forbidden = supplied & {"observed_at", "model_name", "model_version", "objects", "rule_context"}
            if forbidden:
                raise serializers.ValidationError(
                    {key: "Ce champ nécessite contract_version=2." for key in sorted(forbidden)}
                )
            attrs["objects"] = []
            return attrs

        required = ("observed_at", "model_name", "model_version", "objects")
        missing = [key for key in required if key not in attrs]
        if missing:
            raise serializers.ValidationError({key: "Ce champ est obligatoire en v2." for key in missing})
        if "confidence" in supplied:
            raise serializers.ValidationError(
                {"confidence": "La confiance v2 appartient à chaque objet."}
            )
        raw_objects = attrs["objects"]
        if not isinstance(raw_objects, list):
            raise serializers.ValidationError({"objects": "Une liste est attendue."})
        if not 1 <= len(raw_objects) <= 64:
            raise serializers.ValidationError({"objects": "Entre 1 et 64 objets sont autorisés."})
        serializer = DetectionObjectSerializer(data=raw_objects, many=True)
        serializer.is_valid(raise_exception=True)
        attrs["objects"] = serializer.validated_data
        has_face_status = any("face_status" in item for item in attrs["objects"])
        if has_face_status and version != 3:
            raise serializers.ValidationError(
                {"objects": "Le statut facial nécessite contract_version=3."}
            )
        if has_face_status and any(
            item["label"] != "person" for item in attrs["objects"] if "face_status" in item
        ):
            raise serializers.ValidationError(
                {"objects": "Le statut facial ne concerne qu’une personne détectée."}
            )
        if "rule_context" in attrs:
            rule_serializer = RuleContextSerializer(data=attrs["rule_context"])
            rule_serializer.is_valid(raise_exception=True)
            attrs["rule_context"] = rule_serializer.validated_data
        return attrs
