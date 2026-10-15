from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from homes.audit import record_audit
from homes.models import Camera

from .models import CameraPushPreference


class CameraPushPreferenceForm(forms.ModelForm):
    class Meta:
        model = CameraPushPreference
        fields = ("enabled", "people", "objects_enabled", "quiet_start", "quiet_end", "urgent_during_quiet", "lock_screen")
        labels = {
            "lock_screen": "Écran verrouillé Android",
            "enabled": "Recevoir les notifications de cette caméra",
            "people": "Personnes détectées",
            "objects_enabled": "Objets détectés (y compris animaux)",
            "quiet_start": "Silence à partir de",
            "quiet_end": "Reprise des notifications à",
            "urgent_during_quiet": "Recevoir les alertes urgentes pendant la plage silencieuse",
        }
        widgets = {
            "quiet_start": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "quiet_end": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Older clients omit this field; preserve the user's privacy choice.
        if self.is_bound and "lock_screen" not in self.data:
            self.data = self.data.copy()
            self.data["lock_screen"] = self.instance.lock_screen or "private"

    def clean(self):
        data = super().clean()
        start, end = data.get("quiet_start"), data.get("quiet_end")
        if (start is None) != (end is None):
            raise forms.ValidationError("Renseignez les deux heures ou laissez-les toutes les deux vides.")
        if start is not None and start == end:
            raise forms.ValidationError("Les heures de début et de fin doivent être différentes.")
        return data


class CameraPushPreferenceView(LoginRequiredMixin, View):
    def get(self, request, pk):
        return self._render(request, pk)

    def post(self, request, pk):
        return self._render(request, pk)

    def _render(self, request, pk):
        camera = get_object_or_404(Camera.objects.visible_to(request.user), pk=pk)
        preference = CameraPushPreference.objects.filter(user=request.user, camera=camera).first()
        form = CameraPushPreferenceForm(
            request.POST if request.method == "POST" else None,
            instance=preference or CameraPushPreference(user=request.user, camera=camera),
        )
        if request.method == "POST" and form.is_valid():
            preference, _ = CameraPushPreference.objects.update_or_create(
                user=request.user, camera=camera, defaults=form.cleaned_data,
            )
            record_audit(
                "push.preferences.updated", request=request, camera=camera,
                target=preference, metadata=form.cleaned_data,
            )
            messages.success(request, "Vos préférences de notifications sont enregistrées.")
            return redirect("camera-push-preferences", pk=camera.pk)
        return render(request, "notifications/camera_preferences.html", {"camera": camera, "form": form})
