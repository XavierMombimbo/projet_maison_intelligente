from django.db import transaction
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from rest_framework import generics, pagination, permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied

from accounts.authentication import MobileJWTAuthentication

from .models import Camera, CaptureChiffree, Evenement, Maison, ObjetDetecte, StatutAppairage, StatutEvenement
from .audit import record_audit
from .forms import CameraForm
from .services import PairingError, create_pairing_code
from .throttling import check_rate_limit
from .models import ResultatAudit
from .crypto import decrypt_capture
from .realtime import publish_event


class MobilePagination(pagination.PageNumberPagination):
    page_size = 20
    max_page_size = 100
    page_size_query_param = "page_size"


class MobileHouseSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Maison
        fields = ("id", "nom", "fuseau_horaire", "role", "date_creation")
        read_only_fields = ("id", "role", "date_creation")

    def validate_fuseau_horaire(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Fuseau horaire inconnu.")
        return value

    def get_role(self, obj):
        user = self.context["request"].user
        if obj.proprietaire_id == user.pk:
            return "owner"
        membership = obj.membres.filter(utilisateur=user).only("role").first()
        return membership.role if membership else None


class MobileCameraSerializer(serializers.ModelSerializer):
    house_id = serializers.IntegerField(source="maison_id", read_only=True)
    house_name = serializers.CharField(source="maison.nom", read_only=True)
    can_control = serializers.SerializerMethodField()
    latest_capture_event_id = serializers.SerializerMethodField()

    def get_can_control(self, obj):
        return obj.maison.proprietaire_id == self.context["request"].user.pk and obj.statut_appairage != StatutAppairage.REVOQUEE

    def get_latest_capture_event_id(self, obj):
        event = obj.evenements.filter(capture__isnull=False).order_by("-horodatage").first()
        return str(event.pk) if event else None

    class Meta:
        model = Camera
        fields = (
            "id",
            "nom",
            "house_id",
            "house_name",
            "type_source",
            "statut_appairage",
            "surveillance_active",
            "surveillance_appliquee",
            "surveillance_appliquee_le",
            "derniere_connexion",
            "date_creation",
            "can_control",
            "latest_capture_event_id",
        )


class MobileDetectedObjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = ObjetDetecte
        fields = ("classe", "confiance", "boite", "identifiant_suivi")


class MobileEventSerializer(serializers.ModelSerializer):
    camera_name = serializers.CharField(source="camera.nom", read_only=True)
    house_id = serializers.IntegerField(source="maison_id", read_only=True)
    objects = MobileDetectedObjectSerializer(source="objets", many=True, read_only=True)
    alert_priority_label = serializers.CharField(source="get_priorite_alerte_display", read_only=True)
    has_capture = serializers.SerializerMethodField()
    can_control = serializers.SerializerMethodField()

    def get_has_capture(self, obj):
        return hasattr(obj, "capture")

    def get_can_control(self, obj):
        return Evenement.objects.controllable_by(self.context["request"].user).filter(pk=obj.pk).exists()

    class Meta:
        model = Evenement
        fields = (
            "id",
            "camera_id",
            "camera_name",
            "house_id",
            "type",
            "confiance_ia",
            "version_contrat",
            "horodatage_observation",
            "horodatage",
            "statut",
            "priorite_alerte",
            "alert_priority_label",
            "raison_priorite",
            "notification_supprimee",
            "evenement_principal_id",
            "objects",
            "has_capture",
            "can_control",
        )


class MobileAuthMixin:
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class HouseListAPIView(MobileAuthMixin, generics.ListCreateAPIView):
    serializer_class = MobileHouseSerializer
    pagination_class = MobilePagination

    @transaction.atomic
    def perform_create(self, serializer):
        house = serializer.save(proprietaire=self.request.user)
        record_audit("mobile.house.created", request=self.request, maison=house, target=house)

    def get_queryset(self):
        return Maison.objects.visible_to(self.request.user).select_related("proprietaire")


class HouseDetailAPIView(MobileAuthMixin, generics.RetrieveAPIView):
    serializer_class = MobileHouseSerializer

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        house = self.get_object()
        if house.proprietaire_id != request.user.pk:
            raise PermissionDenied("Seul le propriétaire peut modifier cette maison.")
        serializer = self.get_serializer(house, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record_audit("mobile.house.updated", request=request, maison=house, target=house)
        return Response(serializer.data)

    def get_queryset(self):
        return Maison.objects.visible_to(self.request.user).select_related("proprietaire")


class CameraListAPIView(MobileAuthMixin, generics.ListAPIView):
    serializer_class = MobileCameraSerializer
    pagination_class = MobilePagination

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        form = CameraForm(data=request.data, user=request.user)
        if not form.is_valid():
            raise serializers.ValidationError(dict(form.errors))
        camera = form.save()
        record_audit("camera.create", request=request, user=request.user,
                     camera=camera, target=camera)
        return Response(self.get_serializer(camera).data, status=201)

    def get_queryset(self):
        return Camera.objects.visible_to(self.request.user).select_related("maison")


class CameraDetailAPIView(MobileAuthMixin, generics.RetrieveAPIView):
    serializer_class = MobileCameraSerializer

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        camera = self.get_object()
        if camera.maison.proprietaire_id != request.user.pk:
            raise PermissionDenied("Seul le propriétaire peut modifier cette caméra.")
        if camera.statut_appairage == StatutAppairage.REVOQUEE:
            return Response({"detail": "Cette caméra est révoquée."}, status=409)
        # Renaming must never change pairing, source secrets or house ownership.
        camera.nom = serializers.CharField(max_length=120).run_validation(request.data.get("nom"))
        camera.save(update_fields=["nom"])
        record_audit("camera.rename", request=request, user=request.user,
                     camera=camera, target=camera)
        return Response(self.get_serializer(camera).data)

    def get_queryset(self):
        return Camera.objects.visible_to(self.request.user).select_related("maison")


class CameraPairingCodeAPIView(MobileAuthMixin, APIView):
    def post(self, request, pk):
        camera = get_object_or_404(Camera.objects.select_related("maison"),
                                  pk=pk, maison__proprietaire=request.user)
        rate = check_rate_limit("pairing_code", request,
                                identifier=f"{request.user.pk}:{camera.pk}")
        if not rate.allowed:
            record_audit("camera.pairing_code.rate_limited", ResultatAudit.REFUS,
                         request=request, user=request.user, camera=camera, target=camera,
                         metadata={"retry_after": rate.retry_after})
            response = Response({"detail": "Trop de codes demandés. Réessayez plus tard."}, status=429)
            response["Retry-After"] = str(rate.retry_after)
        else:
            try:
                pairing, code = create_pairing_code(camera)
            except PairingError as error:
                record_audit("camera.pairing_code.failure", ResultatAudit.REFUS,
                             request=request, user=request.user, camera=camera, target=camera)
                response = Response({"detail": str(error)}, status=409)
            else:
                record_audit("camera.pairing_code.created", request=request,
                             user=request.user, camera=camera, target=camera,
                             metadata={"expires_at": pairing.date_expiration.isoformat()})
                response = Response({"code": code, "expires_at": pairing.date_expiration}, status=201)
        patch_cache_control(response, no_store=True, private=True)
        return response


class EventListAPIView(MobileAuthMixin, generics.ListAPIView):
    serializer_class = MobileEventSerializer
    pagination_class = MobilePagination

    def get_queryset(self):
        queryset = (
            Evenement.objects.visible_to(self.request.user)
            .select_related("camera", "maison", "capture")
            .prefetch_related("objets")
        )
        camera_id = self.request.query_params.get("camera")
        if camera_id:
            camera_id = serializers.UUIDField().run_validation(camera_id)
            queryset = queryset.filter(camera_id=camera_id)
        return queryset.order_by("-horodatage")


class EventDetailAPIView(MobileAuthMixin, generics.RetrieveAPIView):
    serializer_class = MobileEventSerializer

    def get_queryset(self):
        return (
            Evenement.objects.visible_to(self.request.user)
            .select_related("camera", "maison")
            .prefetch_related("objets")
        )


class EventCaptureAPIView(MobileAuthMixin, APIView):
    def get(self, request, pk):
        capture = get_object_or_404(
            CaptureChiffree.objects.select_related("evenement"),
            evenement__in=Evenement.objects.visible_to(request.user), evenement_id=pk,
        )
        content = decrypt_capture(bytes(capture.contenu_chiffre), bytes(capture.nonce), capture.evenement_id)
        response = HttpResponse(content, content_type=capture.type_mime)
        response["X-Content-Type-Options"] = "nosniff"
        patch_cache_control(response, no_store=True, private=True)
        return response


class EventDecisionAPIView(MobileAuthMixin, APIView):
    def post(self, request, pk):
        decision = serializers.ChoiceField(choices=["confirmed", "false_alarm"]).run_validation(request.data.get("decision"))
        with transaction.atomic():
            event = get_object_or_404(Evenement.objects.controllable_by(request.user).select_for_update(), pk=pk)
            if event.statut != StatutEvenement.NOUVEAU:
                return Response({"detail": "Cette alerte a déjà été traitée."}, status=409)
            event.statut = decision
            event.save(update_fields=["statut"])
            record_audit("event.decision", request=request, user=request.user, camera=event.camera,
                         maison=event.maison, target=event, metadata={"decision": decision})
            transaction.on_commit(lambda: publish_event(event.pk, message_type="alert.updated"))
        return Response(MobileEventSerializer(event, context={"request": request}).data)


class CameraMonitoringAPIView(MobileAuthMixin, APIView):
    def post(self, request, pk):
        active = serializers.BooleanField().run_validation(request.data.get("active"))
        camera = get_object_or_404(Camera.objects.filter(maison__proprietaire=request.user).exclude(
            statut_appairage=StatutAppairage.REVOQUEE), pk=pk)
        camera.surveillance_active = active
        camera.save(update_fields=["surveillance_active"])
        record_audit("camera.monitoring.toggle", request=request, user=request.user, camera=camera,
                     target=camera, metadata={"monitoring_active": active})
        return Response(MobileCameraSerializer(camera, context={"request": request}).data)
