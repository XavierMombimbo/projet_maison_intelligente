from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import CameraPushPreference
from notifications.views import CameraPushPreferenceForm
from .audit import record_audit
from .forms import (PlanningQuotidienForm, PlageSurveillanceForm,
                    ExceptionSurveillanceForm, DerogationSurveillanceForm)
from .mobile_api import MobileAuthMixin
from .models import (Maison, Camera, PlageSurveillance, ExceptionSurveillance,
                     DerogationSurveillance, MembreMaison, AccesCamera,
                     RoleMaison, StatutInvitation)
from .scheduling import evaluate_surveillance


def valid_form(form):
    if not form.is_valid():
        raise serializers.ValidationError(dict(form.errors))
    return form.cleaned_data


def house_for(request, pk, *, owner=False):
    queryset = Maison.objects.filter(proprietaire=request.user) if owner else Maison.objects.visible_to(request.user)
    return get_object_or_404(queryset, pk=pk)


def schedule_data(house, user):
    decision = evaluate_surveillance(house)
    daily = house.plages_surveillance.filter(nom="Planning quotidien", active=True).first()
    override = DerogationSurveillance.objects.filter(maison=house, expire_le__gt=timezone.now()).first()
    tz = ZoneInfo(house.fuseau_horaire)
    return {
        "timezone": house.fuseau_horaire, "can_edit": house.proprietaire_id == user.pk,
        "active": decision.active, "reason": decision.libelle,
        "daily_start": daily.heure_debut.strftime("%H:%M") if daily else None,
        "daily_end": daily.heure_fin.strftime("%H:%M") if daily else None,
        "override": {"active": override.surveillance_active, "expires_at": override.expire_le} if override else None,
        "windows": list(house.plages_surveillance.exclude(nom="Planning quotidien").values(
            "id", "nom", "jour", "heure_debut", "heure_fin", "active")),
        "exceptions": [{"id": item.pk, "nom": item.nom,
            "date_debut": item.date_debut.astimezone(tz).strftime("%Y-%m-%dT%H:%M"),
            "date_fin": item.date_fin.astimezone(tz).strftime("%Y-%m-%dT%H:%M"),
            "surveillance_active": item.surveillance_active, "priorite": item.priorite}
            for item in house.exceptions_surveillance.all()],
    }


class HouseScheduleAPIView(MobileAuthMixin, APIView):
    def get(self, request, pk):
        return Response(schedule_data(house_for(request, pk), request.user))

    def post(self, request, pk):
        house = house_for(request, pk, owner=True)
        action = serializers.ChoiceField(choices=["daily", "daily_clear", "window", "window_delete",
            "exception", "exception_delete", "override", "override_clear"]).run_validation(request.data.get("action"))
        try:
            with transaction.atomic():
                house = Maison.objects.select_for_update().get(pk=house.pk)
                self.apply(request, house, action)
                record_audit(f"mobile.schedule.{action}", request=request, maison=house, target=house)
        except IntegrityError:
            raise serializers.ValidationError({"detail": "Cette plage existe déjà."})
        return Response(schedule_data(house, request.user))

    def apply(self, request, house, action):
        data = request.data
        if action == "daily":
            cleaned = valid_form(PlanningQuotidienForm(data))
            house.plages_surveillance.filter(nom="Planning quotidien").delete()
            PlageSurveillance.objects.bulk_create([PlageSurveillance(maison=house,
                nom="Planning quotidien", jour=day, heure_debut=cleaned["heure_activation"],
                heure_fin=cleaned["heure_arret"], active=True) for day in range(7)])
        elif action == "daily_clear":
            house.plages_surveillance.filter(nom="Planning quotidien").delete()
        elif action in ("window", "exception"):
            model = PlageSurveillance if action == "window" else ExceptionSurveillance
            instance = model(maison=house)
            if data.get("id") is not None:
                item_id = serializers.IntegerField(min_value=1).run_validation(data["id"])
                instance = get_object_or_404(model, pk=item_id, maison=house)
            if action == "window" and (data.get("nom") == "Planning quotidien" or instance.nom == "Planning quotidien"):
                raise serializers.ValidationError({"nom": "Nom réservé au planning quotidien."})
            form = (PlageSurveillanceForm(data, instance=instance) if action == "window" else
                    ExceptionSurveillanceForm(data, instance=instance, house_timezone=house.fuseau_horaire))
            valid_form(form)
            form.save()
        elif action in ("window_delete", "exception_delete"):
            model = PlageSurveillance if action == "window_delete" else ExceptionSurveillance
            item_id = serializers.IntegerField(min_value=1).run_validation(data.get("id"))
            item = get_object_or_404(model, pk=item_id, maison=house)
            if action == "window_delete" and item.nom == "Planning quotidien":
                raise serializers.ValidationError({"detail": "Utilisez la suppression du planning quotidien."})
            item.delete()
        elif action == "override":
            active = serializers.BooleanField().run_validation(data.get("surveillance_active"))
            cleaned = valid_form(DerogationSurveillanceForm({**data,
                "surveillance_active": "True" if active else "False"}))
            DerogationSurveillance.objects.update_or_create(maison=house, defaults={
                "surveillance_active": active, "creee_par": request.user,
                "expire_le": timezone.now() + timedelta(minutes=cleaned["duree_minutes"]),
            })
        else:
            DerogationSurveillance.objects.filter(maison=house).delete()


class CameraPreferencesAPIView(MobileAuthMixin, APIView):
    def camera(self, request, pk):
        return get_object_or_404(Camera.objects.visible_to(request.user).select_related("maison"), pk=pk)

    def response(self, camera, preference):
        return Response({"timezone": camera.maison.fuseau_horaire,
            **{field: getattr(preference, field) for field in CameraPushPreferenceForm.Meta.fields}})

    def get(self, request, pk):
        camera = self.camera(request, pk)
        preference = CameraPushPreference.objects.filter(user=request.user, camera=camera).first()
        return self.response(camera, preference or CameraPushPreference(user=request.user, camera=camera))

    @transaction.atomic
    def post(self, request, pk):
        camera = self.camera(request, pk)
        data = dict(request.data)
        for key in ("enabled", "people", "objects_enabled", "urgent_during_quiet"):
            data[key] = serializers.BooleanField().run_validation(data.get(key))
        existing = CameraPushPreference.objects.filter(user=request.user, camera=camera).first()
        cleaned = valid_form(CameraPushPreferenceForm(data, instance=existing))
        preference, _ = CameraPushPreference.objects.update_or_create(user=request.user,
            camera=camera, defaults=cleaned)
        record_audit("push.preferences.updated", request=request, camera=camera,
                     target=preference, metadata=cleaned)
        return self.response(camera, preference)


def members_data(house):
    return {"members": [{"id": member.pk, "username": member.utilisateur.username,
        "role": member.role, "status": member.statut,
        "is_owner": member.utilisateur_id == house.proprietaire_id,
        "access": list(member.acces_cameras.filter(camera__maison=house).values(
            "camera_id", "peut_voir", "peut_controler"))}
        for member in house.membres.select_related("utilisateur").prefetch_related("acces_cameras")],
        "cameras": list(house.cameras.values("id", "nom"))}


class CameraAccessSerializer(serializers.Serializer):
    camera_id = serializers.UUIDField()
    peut_voir = serializers.BooleanField()
    peut_controler = serializers.BooleanField()

    def validate(self, data):
        if data["peut_controler"] and not data["peut_voir"]:
            raise serializers.ValidationError("Le contrôle nécessite un accès en lecture.")
        return data


class HouseMembersAPIView(MobileAuthMixin, APIView):
    def get(self, request, pk):
        return Response(members_data(house_for(request, pk, owner=True)))

    @transaction.atomic
    def post(self, request, pk):
        house = house_for(request, pk, owner=True)
        # Serialize membership mutations for this house, including concurrent invitations.
        house = Maison.objects.select_for_update().get(pk=house.pk)
        action = serializers.ChoiceField(choices=["invite", "update", "remove"]).run_validation(request.data.get("action"))
        if action == "invite":
            username = serializers.CharField(max_length=150).run_validation(request.data.get("username"))
            user = get_user_model().objects.filter(username=username, is_active=True).first()
            if user is None:
                raise serializers.ValidationError({"username": "Compte introuvable."})
            if user.pk == house.proprietaire_id or house.membres.filter(utilisateur=user).exists():
                return Response({"detail": "Ce compte est déjà associé à la maison."}, status=409)
            member = MembreMaison(maison=house, utilisateur=user, statut=StatutInvitation.EN_ATTENTE)
        else:
            member_id = serializers.IntegerField(min_value=1).run_validation(request.data.get("id"))
            member = get_object_or_404(MembreMaison, pk=member_id, maison=house)
            if member.utilisateur_id == house.proprietaire_id:
                raise serializers.ValidationError({"detail": "Le propriétaire ne peut pas être modifié ou retiré."})
        if action == "remove":
            record_audit("mobile.member.remove", request=request, maison=house, target=member)
            member.delete()
        else:
            role = serializers.ChoiceField(choices=[RoleMaison.FAMILLE, RoleMaison.INVITE]).run_validation(request.data.get("role"))
            access = CameraAccessSerializer(data=request.data.get("access", []), many=True)
            access.is_valid(raise_exception=True)
            ids = [item["camera_id"] for item in access.validated_data]
            if len(ids) != len(set(ids)) or house.cameras.filter(pk__in=ids).count() != len(ids):
                raise serializers.ValidationError({"access": "Caméras invalides pour cette maison."})
            member.role = role
            member.save()
            member.acces_cameras.all().delete()
            AccesCamera.objects.bulk_create([AccesCamera(membre=member, **item) for item in access.validated_data])
            record_audit(f"mobile.member.{action}", request=request, maison=house, target=member)
        return Response(members_data(house))


class InvitationsAPIView(MobileAuthMixin, APIView):
    def get(self, request):
        return Response({"invitations": list(MembreMaison.objects.filter(utilisateur=request.user,
            statut=StatutInvitation.EN_ATTENTE).values("id", "role", "maison__nom", "maison__proprietaire__username"))})

    @transaction.atomic
    def post(self, request):
        member_id = serializers.IntegerField(min_value=1).run_validation(request.data.get("id"))
        action = serializers.ChoiceField(choices=["accept", "refuse"]).run_validation(request.data.get("action"))
        member = get_object_or_404(MembreMaison.objects.select_for_update(), pk=member_id,
                                  utilisateur=request.user, statut=StatutInvitation.EN_ATTENTE)
        member.statut = StatutInvitation.ACCEPTEE if action == "accept" else StatutInvitation.REFUSEE
        member.save(update_fields=["statut"])
        record_audit(f"mobile.invitation.{action}", request=request, maison=member.maison, target=member)
        return self.get(request)
