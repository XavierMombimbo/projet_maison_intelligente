from rest_framework import serializers

from .models import Camera


class CameraSerializer(serializers.ModelSerializer):
    maison_nom = serializers.CharField(source="maison.nom", read_only=True)

    class Meta:
        model = Camera
        fields = (
            "id",
            "nom",
            "maison",
            "maison_nom",
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


class DetectionEventSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    simulated = serializers.BooleanField(default=False)
    capture = serializers.FileField(write_only=True)
