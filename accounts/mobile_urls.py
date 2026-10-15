from django.urls import path

from homes.mobile_api import (
    CameraDetailAPIView,
    CameraListAPIView,
    CameraMonitoringAPIView,
    CameraPairingCodeAPIView,
    EventCaptureAPIView,
    EventDecisionAPIView,
    EventDetailAPIView,
    EventListAPIView,
    HouseDetailAPIView,
    HouseListAPIView,
)

from .mobile_api import (
    MobileLoginAPIView,
    MobileMeAPIView,
    MobileMFAVerifyAPIView,
    MobileRefreshAPIView,
    MobileSessionListAPIView,
    MobileSessionRevokeAPIView,
)
from notifications.api import (
    MobilePushDeliveryReceiptAPIView,
    MobilePushInstallationAPIView,
)

app_name = "mobile-api"

from homes.mobile_management import (HouseScheduleAPIView, CameraPreferencesAPIView,
                                     HouseMembersAPIView, InvitationsAPIView)

urlpatterns = [
    path("houses/<int:pk>/schedule/", HouseScheduleAPIView.as_view(), name="house-schedule"),
    path("houses/<int:pk>/members/", HouseMembersAPIView.as_view(), name="house-members"),
    path("invitations/", InvitationsAPIView.as_view(), name="invitations"),
    path("cameras/<uuid:pk>/preferences/", CameraPreferencesAPIView.as_view(), name="camera-preferences"),
    path("auth/login/", MobileLoginAPIView.as_view(), name="login"),
    path("auth/mfa/verify/", MobileMFAVerifyAPIView.as_view(), name="mfa-verify"),
    path("auth/refresh/", MobileRefreshAPIView.as_view(), name="refresh"),
    path("auth/sessions/", MobileSessionListAPIView.as_view(), name="session-list"),
    path(
        "auth/sessions/<uuid:session_id>/revoke/",
        MobileSessionRevokeAPIView.as_view(),
        name="session-revoke",
    ),
    path("me/", MobileMeAPIView.as_view(), name="me"),
    path(
        "push/installation/",
        MobilePushInstallationAPIView.as_view(),
        name="push-installation",
    ),
    path(
        "push/deliveries/<uuid:delivery_id>/received/",
        MobilePushDeliveryReceiptAPIView.as_view(),
        name="push-delivery-received",
    ),
    path("houses/", HouseListAPIView.as_view(), name="house-list"),
    path("houses/<int:pk>/", HouseDetailAPIView.as_view(), name="house-detail"),
    path("cameras/", CameraListAPIView.as_view(), name="camera-list"),
    path("cameras/<uuid:pk>/", CameraDetailAPIView.as_view(), name="camera-detail"),
    path("cameras/<uuid:pk>/monitoring/", CameraMonitoringAPIView.as_view(), name="camera-monitoring"),
    path("cameras/<uuid:pk>/pairing-code/", CameraPairingCodeAPIView.as_view(), name="camera-pairing-code"),
    path("events/", EventListAPIView.as_view(), name="event-list"),
    path("events/<uuid:pk>/", EventDetailAPIView.as_view(), name="event-detail"),
    path("events/<uuid:pk>/capture/", EventCaptureAPIView.as_view(), name="event-capture"),
    path("events/<uuid:pk>/decision/", EventDecisionAPIView.as_view(), name="event-decision"),
]
