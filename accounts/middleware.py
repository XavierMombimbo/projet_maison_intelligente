from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django.utils.cache import patch_vary_headers

from .mfa import VERIFIED_USER_KEY, establish_preauth


class MobileAPICORSMiddleware:
    allowed_methods = "GET, POST, OPTIONS"
    allowed_headers = "Authorization, Content-Type"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin", "")
        allowed = (
            request.path_info.startswith("/api/v1/")
            and origin in settings.MOBILE_WEB_ALLOWED_ORIGINS
        )
        if allowed and request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = self.allowed_methods
            response["Access-Control-Allow-Headers"] = self.allowed_headers
            response["Access-Control-Max-Age"] = "86400"
            patch_vary_headers(response, ("Origin",))
        return response


class MFAEnforcementMiddleware:
    exempt_names = {
        "login",
        "logout",
        "signup",
        "password-reset",
        "password-reset-done",
        "password-reset-confirm",
        "password-reset-complete",
        "mfa-challenge",
        "mfa-setup",
        "mfa-qr",
        "health",
        "app-manifest",
        "app-service-worker",
        "app-offline",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        try:
            url_name = resolve(request.path_info).url_name
        except Resolver404:
            url_name = None
        if (
            user.is_authenticated
            and url_name not in self.exempt_names
            and hasattr(user, "mfa_device")
            and user.mfa_device.is_confirmed
            and request.session.get(VERIFIED_USER_KEY) != user.pk
        ):
            user_id = user.pk
            backend = request.session.get("_auth_user_backend", "django.contrib.auth.backends.ModelBackend")
            next_url = request.get_full_path()
            logout(request)
            establish_preauth(request, user, backend=backend, next_url=next_url)
            return redirect("mfa-challenge")
        return self.get_response(request)
