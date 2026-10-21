from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views import (
    AuditLogoutView,
    MFAChallengeView,
    MFAEmailCodeView,
    MFAQRCodeView,
    MFAReplaceQRCodeView,
    MFAReplaceView,
    MFARevokeSessionsView,
    MFASetupView,
    RateLimitedLoginView,
    SentinellePasswordResetCompleteView,
    SentinellePasswordResetConfirmView,
    SentinellePasswordResetDoneView,
    SentinellePasswordResetView,
    SignUpView,
)
from accounts.mobile_views import MobileAPITestView
from homes.api import (
    CameraBiometricEnrollmentAPIView,
    CameraBiometricProfilesAPIView,
    CameraBiometricPurgeAckAPIView,
    CameraHeartbeatAPIView,
    CameraDetectionAPIView,
    CameraStateAPIView,
    CameraSourceAPIView,
    CameraTokenAPIView,
    CameraViewSet,
    PairCameraAPIView,
)
from homes.views import CameraMonitorView, ConnectCameraView, DashboardView, HealthView, HomeView, MyProfileView
from homes import pwa
from homes.weapon_analysis import WeaponObservationAPIView

router = DefaultRouter()
router.register("cameras", CameraViewSet, basename="camera")

urlpatterns = [
    path("manifest.webmanifest", pwa.manifest, name="app-manifest"),
    path("service-worker.js", pwa.service_worker, name="app-service-worker"),
    path("hors-ligne/", pwa.offline, name="app-offline"),
    path("", HomeView.as_view(), name="home"),
    path("health/", HealthView.as_view(), name="health"),
    path("inscription/", SignUpView.as_view(), name="signup"),
    path("connexion/", RateLimitedLoginView.as_view(), name="login"),
    path(
        "mot-de-passe-oublie/",
        SentinellePasswordResetView.as_view(),
        name="password-reset",
    ),
    path(
        "mot-de-passe-oublie/message-envoye/",
        SentinellePasswordResetDoneView.as_view(),
        name="password-reset-done",
    ),
    path(
        "reinitialiser/<uidb64>/<token>/",
        SentinellePasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path(
        "reinitialiser/termine/",
        SentinellePasswordResetCompleteView.as_view(),
        name="password-reset-complete",
    ),
    path("connexion/mfa/", MFAChallengeView.as_view(), name="mfa-challenge"),
    path("connexion/mfa/email/", MFAEmailCodeView.as_view(), name="mfa-email-code"),
    path("deconnexion/", AuditLogoutView.as_view(), name="logout"),
    path("securite/mfa/", MFASetupView.as_view(), name="mfa-setup"),
    path("securite/mfa/qr.svg", MFAQRCodeView.as_view(), name="mfa-qr"),
    path("securite/mfa/remplacer/", MFAReplaceView.as_view(), name="mfa-replace"),
    path("securite/mfa/remplacer/qr.svg", MFAReplaceQRCodeView.as_view(), name="mfa-replace-qr"),
    path("securite/sessions/revoquer/", MFARevokeSessionsView.as_view(), name="mfa-revoke-sessions"),
    path("securite/api-mobile/test/", MobileAPITestView.as_view(), name="mobile-api-test"),
    path("tableau-de-bord/", DashboardView.as_view(), name="dashboard"),
    path("mon-profil/", MyProfileView.as_view(), name="my-profile"),
    path("connecter-camera/", ConnectCameraView.as_view(), name="connect-camera"),
    path("camera/surveillance/", CameraMonitorView.as_view(), name="camera-monitor"),
    path("maisons/", include("homes.urls")),
    path("api/v1/", include("accounts.mobile_urls")),
    path("api/camera/appairer/", PairCameraAPIView.as_view(), name="api-camera-pair"),
    path("api/camera/token/", CameraTokenAPIView.as_view(), name="api-camera-token"),
    path("api/camera/me/etat/", CameraStateAPIView.as_view(), name="api-camera-state"),
    path("api/camera/me/source/", CameraSourceAPIView.as_view(), name="api-camera-source"),
    path(
        "api/camera/me/profils-biometriques/",
        CameraBiometricProfilesAPIView.as_view(),
        name="api-camera-biometric-profiles",
    ),
    path(
        "api/camera/me/profils-biometriques/<uuid:profile_id>/enroler/",
        CameraBiometricEnrollmentAPIView.as_view(),
        name="api-camera-biometric-enroll",
    ),
    path(
        "api/camera/me/profils-biometriques/purges/",
        CameraBiometricPurgeAckAPIView.as_view(),
        name="api-camera-biometric-purge-ack",
    ),
    path("api/camera/me/presence/", CameraHeartbeatAPIView.as_view(), name="api-camera-heartbeat"),
    path("api/camera/me/detections/", CameraDetectionAPIView.as_view(), name="api-camera-detection"),
    path("api/camera/me/suspicion-arme/", WeaponObservationAPIView.as_view(), name="api-camera-weapon"),
    path("api/", include((router.urls, "api"), namespace="api")),
    path("admin/login/", RateLimitedLoginView.as_view(), name="admin-login-mfa"),
    path("admin/", admin.site.urls),
]

handler403 = "homes.views.error_403"
handler404 = "homes.views.error_404"
handler500 = "homes.views.error_500"
