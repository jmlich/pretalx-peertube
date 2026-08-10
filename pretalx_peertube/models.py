import secrets
from urllib.parse import urlparse

from django.db import models
from django.utils.html import format_html
from rules.contrib.models import RulesModelBase, RulesModelMixin

from pretalx.agenda.rules import can_view_schedule
from pretalx.event.rules import can_change_event_settings

from .utils import extract_video_id


class PeertubeLink(RulesModelMixin, models.Model, metaclass=RulesModelBase):
    submission = models.OneToOneField(
        to="submission.Submission",
        on_delete=models.CASCADE,
        related_name="peertube_link",
    )
    link = models.URLField(max_length=255)

    class Meta:
        rules_permissions = {
            "list": can_view_schedule,
            "view": can_view_schedule,
            "create": can_change_event_settings,
            "update": can_change_event_settings,
        }

    def __str__(self):
        return f"PeertubeLink({self.link})"

    @property
    def event(self):
        return self.submission.event

    @property
    def domain(self):
        parsed = urlparse(self.link)
        return parsed.netloc

    @property
    def video_id(self):
        return extract_video_id(self.link)

    @property
    def player_link(self):
        return f"https://{self.domain}/videos/embed/{self.video_id}"

    @property
    def peertube_link(self):
        return f"https://{self.domain}/w/{self.video_id}"

    @property
    def iframe(self):
        return format_html(
            '<div class="embed-responsive embed-responsive-16by9"><iframe title="{}" width="560" height="315" src="{}" style="border: 0px;" allow="fullscreen" sandbox="allow-same-origin allow-scripts allow-popups allow-forms"></iframe></div>',
            self.submission.title,
            self.player_link,
        )


def generate_webhook_token():
    return secrets.token_urlsafe(32)


class PeertubeWebhookSettings(models.Model):
    event = models.OneToOneField(
        to="event.Event",
        on_delete=models.CASCADE,
        related_name="peertube_webhook_settings",
    )
    token = models.CharField(max_length=128, default=generate_webhook_token)

    def __str__(self):
        return f"PeertubeWebhookSettings(event={self.event.slug})"
