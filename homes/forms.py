from django import forms

from .models import Camera, Maison


class MaisonForm(forms.ModelForm):
    class Meta:
        model = Maison
        fields = ("nom",)


class CameraForm(forms.ModelForm):
    class Meta:
        model = Camera
        fields = ("maison", "nom")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["maison"].queryset = Maison.objects.filter(proprietaire=user)


class ConnectCameraForm(forms.Form):
    code = forms.RegexField(
        regex=r"^\d{6}$",
        min_length=6,
        max_length=6,
        label="Code d’appairage",
        error_messages={"invalid": "Saisissez exactement six chiffres."},
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
                "class": "pairing-input",
            }
        ),
    )
