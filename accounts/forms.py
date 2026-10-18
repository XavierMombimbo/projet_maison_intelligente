from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class SignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class MFACodeForm(forms.Form):
    code = forms.RegexField(
        r"^\d{6}$",
        label="Code à six chiffres",
        error_messages={"invalid": "Saisissez un code à six chiffres."},
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "maxlength": "6"}),
    )


class MFAChallengeForm(forms.Form):
    code = forms.RegexField(
        r"^(?:\d{6}|[A-Za-z0-9]{4}-?[A-Za-z0-9]{4})$",
        label="Code e-mail, TOTP ou code de récupération",
        error_messages={"invalid": "Saisissez un code e-mail, TOTP ou de récupération valide."},
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )


class MFAReauthenticationForm(MFAChallengeForm):
    password = forms.CharField(
        label="Mot de passe actuel",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
