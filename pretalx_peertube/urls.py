from django.urls import re_path
from rest_framework import routers

from pretalx.event.models.event import SLUG_REGEX

from .api import PeertubeLinkViewSet
from .views import C3VOCWebhookView, PeertubeSettings

router = routers.SimpleRouter()
router.register(
    f"api/events/(?P<event>{SLUG_REGEX})/p/peertube",
    PeertubeLinkViewSet,
    basename="peertube",
)

urlpatterns = [
    re_path(
        rf"^orga/event/(?P<event>{SLUG_REGEX})/settings/p/peertube/$",
        PeertubeSettings.as_view(),
        name="settings",
    ),
    re_path(
        rf"^(?P<event>{SLUG_REGEX})/p/peertube/c3voc/$",
        C3VOCWebhookView.as_view(),
        name="c3voc_webhook",
    ),
]
urlpatterns += router.urls
