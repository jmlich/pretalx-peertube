from django.dispatch import receiver
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from pretalx.agenda.signals import register_recording_provider
from pretalx.common.signals import activitylog_display
from pretalx.orga.signals import nav_event_settings


@receiver(register_recording_provider)
def peertube_provider(sender, **kwargs):
    from .recording import PeertubeProvider  # noqa: PLC0415

    return PeertubeProvider(sender)


@receiver(nav_event_settings)
def peertube_settings(sender, request, **kwargs):
    return [
        {
            "label": "Peertube",
            "url": reverse(
                "plugins:pretalx_peertube:settings", kwargs={"event": request.event.slug}
            ),
            "active": request.resolver_match.url_name
            == "plugins:pretalx_peertube:settings",
        }
    ]


@receiver(activitylog_display)
def peertube_activitylog_display(sender, activitylog, **kwargs):
    if activitylog.action_type == "pretalx_peertube.link.update":
        return _("The Peertube link was changed.")
