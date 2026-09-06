from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views import AuditLogoutView, RateLimitedLoginView, SignUpView
from homes.api import (
    CameraHeartbeatAPIView,
    CameraDetectionAPIView,
    CameraStateAPIView,
    CameraTokenAPIView,
    CameraViewSet,
    PairCameraAPIView,
)
from homes.views import CameraMonitorView, ConnectCameraView, DashboardView, HealthView, HomeView

router = DefaultRouter()
router.register("cameras", CameraViewSet, basename="camera")

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("health/", HealthView.as_view(), name="health"),
    path("inscription/", SignUpView.as_view(), name="signup"),
    path("connexion/", RateLimitedLoginView.as_view(), name="login"),
    path("deconnexion/", AuditLogoutView.as_view(), name="logout"),
    path("tableau-de-bord/", DashboardView.as_view(), name="dashboard"),
    path("connecter-camera/", ConnectCameraView.as_view(), name="connect-camera"),
    path("camera/surveillance/", CameraMonitorView.as_view(), name="camera-monitor"),
    path("maisons/", include("homes.urls")),
    path("api/camera/appairer/", PairCameraAPIView.as_view(), name="api-camera-pair"),
    path("api/camera/token/", CameraTokenAPIView.as_view(), name="api-camera-token"),
    path("api/camera/me/etat/", CameraStateAPIView.as_view(), name="api-camera-state"),
    path("api/camera/me/presence/", CameraHeartbeatAPIView.as_view(), name="api-camera-heartbeat"),
    path("api/camera/me/detections/", CameraDetectionAPIView.as_view(), name="api-camera-detection"),
    path("api/", include((router.urls, "api"), namespace="api")),
    path("admin/", admin.site.urls),
]

handler403 = "homes.views.error_403"
handler404 = "homes.views.error_404"
handler500 = "homes.views.error_500"
