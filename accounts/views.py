import logging

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView
from django.contrib.auth.mixins import LoginRequiredMixin

from homes.audit import fingerprint, record_audit
from homes.models import ResultatAudit
from homes.throttling import check_rate_limit

from .forms import MFAChallengeForm, MFACodeForm, MFAReauthenticationForm, SignUpForm
from .mfa import (
    PREAUTH_BACKEND_KEY,
    PREAUTH_EMAIL_SENT_KEY,
    PREAUTH_NEXT_KEY,
    PREAUTH_USER_KEY,
    VERIFIED_USER_KEY,
    SETUP_EMAIL_USER_KEY,
    clear_preauth,
    consume_mfa_factor,
    consume_email_code,
    establish_preauth,
    email_delivery_configured,
    generate_recovery_codes,
    generate_secret,
    issue_email_code,
    mask_email,
    preauth_is_valid,
    provisioning_uri,
    qr_svg,
    revoke_other_sessions,
    verify_totp,
)
from .models import MFADevice


logger = logging.getLogger(__name__)


def _consume_factor(device, user, code):
    return consume_mfa_factor(device, user, code)


class AnonymousOnlyMixin:
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


class RateLimitedLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")
        rate = check_rate_limit("login", request, identifier=fingerprint(username))
        if not rate.allowed:
            form = self.get_form()
            form.add_error(None, "Trop de tentatives. Réessayez dans quelques minutes.")
            record_audit(
                "auth.login.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                metadata={"retry_after": rate.retry_after, "username_hash": fingerprint(username)},
            )
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        device = MFADevice.objects.filter(user=user, confirmed_at__isnull=False).first()
        if device:
            establish_preauth(
                self.request,
                user,
                backend=user.backend,
                next_url=self.get_success_url(),
            )
            record_audit("auth.login.password_verified", request=self.request, user=user)
            try:
                issue_email_code(user)
                record_audit("auth.mfa.email.sent", request=self.request, user=user)
            except Exception:
                logger.exception("Échec d'envoi du code MFA par e-mail.")
                messages.warning(
                    self.request,
                    "Le code e-mail n’a pas pu être envoyé. Utilisez votre application ou un code de récupération.",
                )
                record_audit(
                    "auth.mfa.email.failure",
                    ResultatAudit.ECHEC,
                    request=self.request,
                    user=user,
                )
                self.request.session[PREAUTH_EMAIL_SENT_KEY] = False
            else:
                delivered = email_delivery_configured()
                self.request.session[PREAUTH_EMAIL_SENT_KEY] = delivered
                if not delivered:
                    messages.info(
                        self.request,
                        "Le SMTP local n’est pas configuré; utilisez votre application MFA pour ce test.",
                    )
            return redirect("mfa-challenge")
        response = super().form_valid(form)
        record_audit("auth.login.success", request=self.request, user=user)
        return response

    def form_invalid(self, form):
        record_audit(
            "auth.login.failure",
            ResultatAudit.REFUS,
            request=self.request,
            metadata={"username_hash": fingerprint(self.request.POST.get("username", ""))},
        )
        return super().form_invalid(form)


class AuditLogoutView(LogoutView):
    def post(self, request, *args, **kwargs):
        record_audit("auth.logout", request=request)
        return super().post(request, *args, **kwargs)


class SignUpView(AnonymousOnlyMixin, CreateView):
    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("dashboard")

    def post(self, request, *args, **kwargs):
        rate = check_rate_limit("signup", request)
        if not rate.allowed:
            form = self.get_form()
            form.add_error(None, "Trop de créations de compte. Réessayez plus tard.")
            record_audit(
                "auth.signup.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                metadata={"retry_after": rate.retry_after},
            )
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except DatabaseError:
            logger.exception("Échec de l'écriture en base pendant l'inscription.")
            self.object = None
            form.add_error(
                None,
                "Le service d’inscription est temporairement indisponible. "
                "Veuillez réessayer dans quelques instants.",
            )
            return self.render_to_response(self.get_context_data(form=form), status=503)
        login(self.request, self.object)
        record_audit("auth.signup.success", request=self.request, user=self.object)
        return response


class SentinellePasswordResetView(AnonymousOnlyMixin, PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("password-reset-done")

    def post(self, request, *args, **kwargs):
        email = request.POST.get("email", "")
        rate = check_rate_limit(
            "password_reset",
            request,
            identifier=fingerprint(email),
        )
        if not rate.allowed:
            form = self.get_form()
            form.add_error(
                None,
                "Trop de demandes. Réessayez dans quelques minutes.",
            )
            record_audit(
                "auth.password_reset.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                metadata={"retry_after": rate.retry_after},
            )
            response = self.render_to_response(
                self.get_context_data(form=form),
                status=429,
            )
            response["Retry-After"] = str(rate.retry_after)
            return response
        return super().post(request, *args, **kwargs)


class SentinellePasswordResetDoneView(AnonymousOnlyMixin, PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


class SentinellePasswordResetConfirmView(AnonymousOnlyMixin, PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("password-reset-complete")


class SentinellePasswordResetCompleteView(AnonymousOnlyMixin, PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"


def _pending_device(user):
    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        device = MFADevice.objects.filter(user=locked_user).first()
        if device is None:
            device = MFADevice(user=locked_user)
            device.set_secret(generate_secret())
            device.save()
        return device


class MFASetupView(LoginRequiredMixin, View):
    template_name = "registration/mfa_setup.html"

    def get(self, request):
        device = _pending_device(request.user)
        return self._render(request, device)

    def _render(self, request, device, form=None, *, method="email", status=200, recovery_codes=None):
        form = form if form is not None else MFACodeForm()
        if method == "email":
            form.fields["code"].label = "Code reçu par e-mail"
        email_form = form if method == "email" else MFACodeForm()
        totp_form = form if method == "totp" else MFACodeForm()
        email_form.fields["code"].label = "Code reçu par e-mail"
        email_form.fields["code"].widget.attrs["id"] = "id_email_code"
        totp_form.fields["code"].widget.attrs["id"] = "id_totp_code"
        response = render(
            request,
            self.template_name,
            {
                "device": device,
                "form": form,
                "email_form": email_form,
                "totp_form": totp_form,
                "setup_method": method,
                "masked_email": mask_email(request.user.email),
                "email_sent": request.session.get(SETUP_EMAIL_USER_KEY) == request.user.pk,
                "email_ttl_minutes": settings.EMAIL_OTP_TTL_SECONDS // 60,
                "recovery_codes": recovery_codes,
            },
            status=status,
        )
        response["Cache-Control"] = "no-store, private"
        return response

    def _send_email(self, request, device):
        rate = check_rate_limit("mfa_email", request, identifier=fingerprint(str(request.user.pk)))
        if not rate.allowed:
            messages.error(request, "Trop d’envois. Réessayez dans quelques minutes.")
            response = self._render(request, device, status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        try:
            if not email_delivery_configured():
                raise RuntimeError("Envoi e-mail indisponible.")
            with transaction.atomic():
                locked = MFADevice.objects.select_for_update().get(user=request.user)
                if locked.is_confirmed:
                    return redirect("mfa-setup")
                issue_email_code(request.user, purpose="setup")
        except Exception:
            logger.exception("Echec d'envoi du code d'activation MFA.")
            record_audit("auth.mfa.setup_email.failure", ResultatAudit.ECHEC, request=request, user=request.user)
            messages.error(request, "Le code n’a pas pu être envoyé. Réessayez dans un instant.")
            return self._render(request, device, status=503)
        request.session[SETUP_EMAIL_USER_KEY] = request.user.pk
        record_audit("auth.mfa.setup_email.sent", request=request, user=request.user)
        messages.success(request, f"Code envoyé à {mask_email(request.user.email)}. Consultez aussi les indésirables.")
        return redirect("mfa-setup")

    def post(self, request):
        pending = _pending_device(request.user)
        if pending.is_confirmed:
            return redirect("mfa-setup")
        if request.POST.get("action") == "send_email":
            return self._send_email(request, pending)
        # Old, already-open QR forms remain usable after this update.
        method = request.POST.get("method", "totp")
        if method not in ("email", "totp"):
            raise Http404
        form = MFACodeForm(request.POST)
        rate = check_rate_limit("mfa", request, identifier=fingerprint(str(request.user.pk)))
        if not rate.allowed:
            form.is_valid()
            form.add_error(None, "Trop de tentatives. Réessayez dans quelques minutes.")
            response = self._render(request, pending, form, method=method, status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        with transaction.atomic():
            device = MFADevice.objects.select_for_update().filter(user=request.user).first()
            if device is None:
                device = _pending_device(request.user)
            if device.is_confirmed:
                return redirect("mfa-setup")
            if form.is_valid():
                code = form.cleaned_data["code"]
                counter = None
                if method == "email":
                    accepted = (request.session.get(SETUP_EMAIL_USER_KEY) == request.user.pk
                                and consume_email_code(request.user, code))
                else:
                    counter = verify_totp(device.get_secret(), code, last_counter=device.last_counter)
                    accepted = counter is not None
                if accepted:
                    if method == "email":
                        # An abandoned (or shared) setup QR must not become an
                        # extra factor after activation through the e-mail path.
                        device.set_secret(generate_secret())
                        device.last_counter = -1
                    else:
                        device.last_counter = counter
                    device.confirmed_at = timezone.now()
                    device.save()
                    recovery_codes = generate_recovery_codes(request.user)
                    request.session[VERIFIED_USER_KEY] = request.user.pk
                    request.session.pop(SETUP_EMAIL_USER_KEY, None)
                    record_audit("auth.mfa.enabled", request=request, user=request.user, target=device,
                                 metadata={"method": method})
                    messages.success(request, "L’authentification multifacteur est activée.")
                    return self._render(request, device, recovery_codes=recovery_codes)
                error = ("Code e-mail incorrect ou expiré. Utilisez le dernier code reçu."
                         if method == "email" else
                         "Code de l’application incorrect. Attendez un nouveau code et vérifiez l’heure automatique du téléphone.")
                form.add_error("code", error)
        record_audit("auth.mfa.setup.failure", ResultatAudit.REFUS, request=request, user=request.user,
                     metadata={"method": method})
        return self._render(request, device, form, method=method, status=400)


class MFAQRCodeView(LoginRequiredMixin, View):
    def get(self, request):
        device = _pending_device(request.user)
        if device.is_confirmed:
            raise Http404
        response = HttpResponse(
            qr_svg(provisioning_uri(device.get_secret(), request.user)),
            content_type="image/svg+xml",
        )
        response["Cache-Control"] = "no-store, private"
        return response


class MFAChallengeView(View):
    template_name = "registration/mfa_challenge.html"

    def _user(self, request):
        if not preauth_is_valid(request.session):
            clear_preauth(request.session)
            return None
        return get_user_model().objects.filter(
            pk=request.session[PREAUTH_USER_KEY], is_active=True
        ).first()

    def get(self, request):
        user = self._user(request)
        if user is None:
            return redirect("login")
        return render(
            request,
            self.template_name,
            {
                "form": MFAChallengeForm(),
                "masked_email": mask_email(user.email),
                "email_sent": request.session.get(PREAUTH_EMAIL_SENT_KEY, False),
                "email_delivery_configured": email_delivery_configured(),
            },
        )

    def post(self, request):
        user = self._user(request)
        if user is None:
            return redirect("login")
        rate = check_rate_limit("mfa", request, identifier=fingerprint(str(user.pk)))
        if not rate.allowed:
            form = MFAChallengeForm(request.POST)
            form.is_valid()
            form.add_error(None, "Trop de tentatives. Réessayez dans quelques minutes.")
            response = render(
                request,
                self.template_name,
                {
                    "form": form,
                    "masked_email": mask_email(user.email),
                    "email_sent": request.session.get(PREAUTH_EMAIL_SENT_KEY, False),
                    "email_delivery_configured": email_delivery_configured(),
                },
                status=429,
            )
            response["Retry-After"] = str(rate.retry_after)
            record_audit("auth.mfa.rate_limited", ResultatAudit.REFUS, request=request, user=user)
            return response
        form = MFAChallengeForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                device = MFADevice.objects.select_for_update().filter(
                    user=user, confirmed_at__isnull=False
                ).first()
                method = (
                    _consume_factor(device, user, form.cleaned_data["code"]) if device else None
                )
                if method:
                    backend = request.session[PREAUTH_BACKEND_KEY]
                    next_url = request.session.get(PREAUTH_NEXT_KEY, reverse("dashboard"))
                    clear_preauth(request.session)
                    login(request, user, backend=backend)
                    request.session[VERIFIED_USER_KEY] = user.pk
                    record_audit(
                        "auth.mfa.success",
                        request=request,
                        user=user,
                        target=device,
                        metadata={"method": method},
                    )
                    if not url_has_allowed_host_and_scheme(
                        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
                    ):
                        next_url = reverse("dashboard")
                    return redirect(next_url)
            form.add_error("code", "Code incorrect ou déjà utilisé.")
        record_audit("auth.mfa.failure", ResultatAudit.REFUS, request=request, user=user)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "masked_email": mask_email(user.email),
                "email_sent": request.session.get(PREAUTH_EMAIL_SENT_KEY, False),
                "email_delivery_configured": email_delivery_configured(),
            },
            status=400,
        )


class MFAEmailCodeView(View):
    def post(self, request):
        challenge_view = MFAChallengeView()
        user = challenge_view._user(request)
        if user is None:
            return redirect("login")
        rate = check_rate_limit("mfa_email", request, identifier=fingerprint(str(user.pk)))
        if not rate.allowed:
            form = MFAChallengeForm({})
            form.is_valid()
            form.add_error(None, "Trop d’envois. Réessayez dans quelques minutes.")
            response = render(
                request,
                MFAChallengeView.template_name,
                {
                    "form": form,
                    "masked_email": mask_email(user.email),
                    "email_sent": request.session.get(PREAUTH_EMAIL_SENT_KEY, False),
                    "email_delivery_configured": email_delivery_configured(),
                },
                status=429,
            )
            response["Retry-After"] = str(rate.retry_after)
            record_audit(
                "auth.mfa.email.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                user=user,
            )
            return response
        try:
            issue_email_code(user)
        except Exception:
            logger.exception("Échec de renvoi du code MFA par e-mail.")
            messages.error(request, "Le code e-mail n’a pas pu être envoyé.")
            record_audit(
                "auth.mfa.email.failure",
                ResultatAudit.ECHEC,
                request=request,
                user=user,
            )
            request.session[PREAUTH_EMAIL_SENT_KEY] = False
        else:
            delivered = email_delivery_configured()
            request.session[PREAUTH_EMAIL_SENT_KEY] = delivered
            if delivered:
                messages.success(request, f"Un nouveau code a été envoyé à {mask_email(user.email)}.")
            else:
                messages.info(request, "Le SMTP local n’est pas configuré.")
            record_audit("auth.mfa.email.sent", request=request, user=user)
        return redirect("mfa-challenge")


class MFAReplaceView(LoginRequiredMixin, View):
    template_name = "registration/mfa_replace.html"

    def _device(self, request, *, lock=False):
        queryset = MFADevice.objects.select_for_update() if lock else MFADevice.objects
        device = queryset.filter(user=request.user, confirmed_at__isnull=False).first()
        if device is None:
            raise Http404
        return device

    def get(self, request):
        device = self._device(request)
        form = MFACodeForm() if device.pending_encrypted_secret else MFAReauthenticationForm()
        return render(request, self.template_name, {"device": device, "form": form})

    def post(self, request):
        rate = check_rate_limit("mfa", request, identifier=fingerprint(str(request.user.pk)))
        stage = request.POST.get("stage", "start")
        form = MFACodeForm(request.POST) if stage == "confirm" else MFAReauthenticationForm(request.POST)
        if not rate.allowed:
            form.is_valid()
            form.add_error(None, "Trop de tentatives. Réessayez dans quelques minutes.")
            response = render(
                request,
                self.template_name,
                {"device": self._device(request), "form": form},
                status=429,
            )
            response["Retry-After"] = str(rate.retry_after)
            return response
        with transaction.atomic():
            device = self._device(request, lock=True)
            if stage == "confirm":
                pending_secret = device.get_pending_secret()
                form_valid = form.is_valid()
                if pending_secret and form_valid:
                    counter = verify_totp(pending_secret, form.cleaned_data["code"])
                    if counter is not None:
                        device.encrypted_secret = device.pending_encrypted_secret
                        device.nonce = device.pending_nonce
                        device.pending_encrypted_secret = None
                        device.pending_nonce = None
                        device.last_counter = counter
                        device.confirmed_at = timezone.now()
                        device.save()
                        recovery_codes = generate_recovery_codes(request.user)
                        revoked = revoke_other_sessions(request.user, request.session.session_key)
                        record_audit(
                            "auth.mfa.replaced",
                            request=request,
                            user=request.user,
                            target=device,
                            metadata={"revoked_sessions": revoked},
                        )
                        messages.success(request, "Le facteur MFA a été remplacé.")
                        return render(
                            request,
                            MFASetupView.template_name,
                            {
                                "device": device,
                                "form": MFACodeForm(),
                                "recovery_codes": recovery_codes,
                            },
                        )
                form.add_error("code", "Code incorrect.")
            elif form.is_valid():
                method = None
                if request.user.check_password(form.cleaned_data["password"]):
                    method = _consume_factor(device, request.user, form.cleaned_data["code"])
                if method:
                    device.set_pending_secret(generate_secret())
                    device.save(update_fields=("pending_encrypted_secret", "pending_nonce", "updated_at"))
                    record_audit(
                        "auth.mfa.replacement_started",
                        request=request,
                        user=request.user,
                        target=device,
                        metadata={"method": method},
                    )
                    return redirect("mfa-replace")
                form.add_error(None, "Mot de passe ou second facteur incorrect.")
        return render(request, self.template_name, {"device": device, "form": form}, status=400)


class MFAReplaceQRCodeView(LoginRequiredMixin, View):
    def get(self, request):
        device = MFADevice.objects.filter(user=request.user, confirmed_at__isnull=False).first()
        secret = device.get_pending_secret() if device else None
        if secret is None:
            raise Http404
        response = HttpResponse(
            qr_svg(provisioning_uri(secret, request.user)), content_type="image/svg+xml"
        )
        response["Cache-Control"] = "no-store, private"
        return response


class MFARevokeSessionsView(LoginRequiredMixin, View):
    template_name = "registration/mfa_reauthenticate.html"

    def get(self, request):
        return render(request, self.template_name, {"form": MFAReauthenticationForm()})

    def post(self, request):
        form = MFAReauthenticationForm(request.POST)
        rate = check_rate_limit("mfa", request, identifier=fingerprint(str(request.user.pk)))
        if not rate.allowed:
            form.is_valid()
            form.add_error(None, "Trop de tentatives. Réessayez dans quelques minutes.")
            response = render(request, self.template_name, {"form": form}, status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        if form.is_valid():
            with transaction.atomic():
                device = MFADevice.objects.select_for_update().filter(
                    user=request.user, confirmed_at__isnull=False
                ).first()
                method = None
                if device and request.user.check_password(form.cleaned_data["password"]):
                    method = _consume_factor(device, request.user, form.cleaned_data["code"])
                if method:
                    revoked = revoke_other_sessions(request.user, request.session.session_key)
                    record_audit(
                        "auth.sessions.revoked",
                        request=request,
                        user=request.user,
                        metadata={"revoked_sessions": revoked, "method": method},
                    )
                    messages.success(request, f"{revoked} autre(s) session(s) révoquée(s).")
                    return redirect("mfa-setup")
            form.add_error(None, "Mot de passe ou second facteur incorrect.")
        return render(request, self.template_name, {"form": form}, status=400)
