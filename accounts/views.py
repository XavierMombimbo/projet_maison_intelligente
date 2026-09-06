from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.views.generic import CreateView

from homes.audit import fingerprint, record_audit
from homes.models import ResultatAudit
from homes.throttling import check_rate_limit

from .forms import SignUpForm


class RateLimitedLoginView(LoginView):
    template_name = "registration/login.html"

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
        response = super().form_valid(form)
        record_audit("auth.login.success", request=self.request, user=form.get_user())
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


class SignUpView(CreateView):
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
        response = super().form_valid(form)
        login(self.request, self.object)
        record_audit("auth.signup.success", request=self.request, user=self.object)
        return response
