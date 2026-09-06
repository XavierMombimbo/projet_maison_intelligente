from django.urls import path

from .views import (
    CameraCreateView,
    CameraDetailView,
    CameraListView,
    CameraToggleView,
    MaisonCreateView,
    MaisonDetailView,
    MaisonListView,
    PairingCodeCreateView,
    CameraRevokeView,
    CaptureView,
    EvenementDetailView,
    EvenementDecisionView,
    EvenementListView,
)

urlpatterns = [
    path("", MaisonListView.as_view(), name="maison-list"),
    path("nouvelle/", MaisonCreateView.as_view(), name="maison-create"),
    path("<int:pk>/", MaisonDetailView.as_view(), name="maison-detail"),
    path("cameras/", CameraListView.as_view(), name="camera-list"),
    path("cameras/nouvelle/", CameraCreateView.as_view(), name="camera-create"),
    path("cameras/<uuid:pk>/", CameraDetailView.as_view(), name="camera-detail"),
    path("cameras/<uuid:pk>/surveillance/", CameraToggleView.as_view(), name="camera-toggle"),
    path("cameras/<uuid:pk>/appairage/", PairingCodeCreateView.as_view(), name="pairing-code-create"),
    path("cameras/<uuid:pk>/revoquer/", CameraRevokeView.as_view(), name="camera-revoke"),
    path("evenements/", EvenementListView.as_view(), name="event-list"),
    path("evenements/<uuid:pk>/", EvenementDetailView.as_view(), name="event-detail"),
    path(
        "evenements/<uuid:pk>/decision/",
        EvenementDecisionView.as_view(),
        name="event-decision",
    ),
    path("evenements/<uuid:pk>/capture/", CaptureView.as_view(), name="event-capture"),
]
