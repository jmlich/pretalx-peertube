import base64
import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django_scopes import scope

from pretalx.agenda.signals import register_recording_provider

from pretalx_peertube.api import (
    PeertubeLinkSerializer,
    PeertubeLinkViewSet,
    PeertubeLinkWriteSerializer,
)
from pretalx_peertube.forms import PeertubeUrlForm
from pretalx_peertube.models import PeertubeLink, PeertubeWebhookSettings
from pretalx_peertube.recording import PeertubeProvider
from pretalx_peertube.utils import extract_video_id
from pretalx_peertube.views import PeertubeSettings, _find_submission

SETTINGS_URL_NAME = "plugins:pretalx_peertube:settings"
WEBHOOK_URL_NAME = "plugins:pretalx_peertube:c3voc_webhook"


@pytest.mark.django_db
def test_orga_can_access_settings(orga_client, event):
    response = orga_client.get(
        reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug}), follow=True
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_reviewer_cannot_access_settings(review_client, event):
    response = review_client.get(
        reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    )
    assert response.status_code == 404


# -- Model tests --


@pytest.mark.django_db
def test_peertube_link_properties(peertube_link):
    assert (
        peertube_link.player_link == "https://peertube.com/videos/embed/dQw4w9WgXcQ"
    )
    assert peertube_link.peertube_link == "https://peertube.com/w/dQw4w9WgXcQ"
    assert "iframe" in peertube_link.iframe
    assert peertube_link.player_link in peertube_link.iframe


@pytest.mark.django_db
def test_peertube_link_iframe_escapes_video_id(confirmed_submission):
    # The iframe is rendered with |safe on the public talk page; even though the
    # video_id is short and charset-validated on write, the markup itself must
    # escape it as defence in depth.
    with scope(event=confirmed_submission.event):
        link = PeertubeLink.objects.create(
            submission=confirmed_submission, link='https://peertube.com/watch?v="><b>x'
        )
    iframe = link.iframe
    assert "<b>" not in iframe
    


@pytest.mark.parametrize(
    "url",
    (
        'https://www.peertube.com/watch?v="><b>',
        "https://www.peertube.com/watch?v=ab cd",
        "https://www.peertube.com/embed/<script>",
    ),
)
def test_extract_video_id_rejects_non_charset(url):
    assert extract_video_id(url) is None


# -- Recording provider tests --


@pytest.mark.django_db
def test_recording_provider_with_link(event, confirmed_submission, peertube_link):
    provider = PeertubeProvider(event)
    result = provider.get_recording(confirmed_submission)
    assert result is not None
    assert "iframe" in result
    assert result["csp_header"] == "https://peertube.com/"


@pytest.mark.django_db
def test_recording_provider_without_link(event, confirmed_submission):
    provider = PeertubeProvider(event)
    result = provider.get_recording(confirmed_submission)
    assert result is None


# -- Form tests --


@pytest.mark.django_db
def test_url_form_no_schedule(event):
    with scope(event=event):
        form = PeertubeUrlForm(event=event)
    assert len(form.fields) == 0


@pytest.mark.django_db
def test_url_form_with_schedule(event, slot):
    with scope(event=event):
        form = PeertubeUrlForm(event=event)
    assert len(form.fields) == 1


@pytest.mark.django_db
def test_url_form_with_existing_link(event, slot, peertube_link):
    with scope(event=event):
        form = PeertubeUrlForm(event=event)
    field = next(iter(form.fields.values()))
    assert field.initial == peertube_link.peertube_link


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "expected_link"),
    (
        ("https://www.peertube.com/watch?v=dQw4w9WgXcQ", "https://www.peertube.com/watch?v=dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
        (
            "https://youtu.be/dQw4w9WgXcQ?list=PLmfWO7gH1WEvXcXh0KOA3tDmG13Kn10fO",
            "dQw4w9WgXcQ",
        ),
        (
            "https://www.peertube.com/watch?v=dQw4w9WgXcQ&list=PLmfWO7gH1WEvXcXh0KOA",
            "dQw4w9WgXcQ",
        ),
        ("https://www.peertube.com/embed/dQw4w9WgXcQ", "https://www.peertube.com/embed/dQw4w9WgXcQ"),
        ("https://www.peertube.com/shorts/dQw4w9WgXcQ", "https://www.peertube.com/shorts/dQw4w9WgXcQ"),
    ),
)
def test_url_form_clean_valid(event, slot, url, expected_link):
    code = slot.submission.code
    with scope(event=event):
        form = PeertubeUrlForm(data={f"link_{code}": url}, event=event)
        assert form.is_valid(), form.errors
        assert form.cleaned_data[f"link_{code}"] == url


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    ("https://www.peertube.com/", "https://youtu.be/"),
)
def test_url_form_clean_invalid_url(event, slot, url):
    code = slot.submission.code
    with scope(event=event):
        form = PeertubeUrlForm(data={f"link_{code}": url}, event=event)
        assert not form.is_valid()


@pytest.mark.django_db
def test_url_form_clean_empty(event, slot):
    code = slot.submission.code
    with scope(event=event):
        form = PeertubeUrlForm(data={f"link_{code}": ""}, event=event)
        assert form.is_valid()
        assert form.cleaned_data[f"link_{code}"] is None


@pytest.mark.django_db
def test_url_form_save_creates_link(event, slot):
    code = slot.submission.code
    with scope(event=event):
        form = PeertubeUrlForm(
            data={f"link_{code}": "https://www.peertube.com/watch?v=abc123"},
            event=event,
        )
        assert form.is_valid()
        form.save()
    assert PeertubeLink.objects.filter(submission=slot.submission).exists()
    assert PeertubeLink.objects.get(submission=slot.submission).link == "https://www.peertube.com/watch?v=abc123"


@pytest.mark.django_db
def test_url_form_save_deletes_link(event, slot, peertube_link):
    code = slot.submission.code
    with scope(event=event):
        form = PeertubeUrlForm(data={f"link_{code}": ""}, event=event)
        assert form.is_valid()
        form.save()
    assert not PeertubeLink.objects.filter(submission=slot.submission).exists()


# -- View tests --


@pytest.mark.django_db
def test_settings_shows_no_schedule_message(orga_client, event):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    response = orga_client.get(url, follow=True)
    assert response.status_code == 200


@pytest.mark.django_db
def test_post_no_schedule_shows_error(orga_client, event):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    response = orga_client.post(url, data={}, follow=True)
    assert response.status_code == 200


@pytest.mark.django_db
def test_post_manual_url(orga_client, event, slot):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    code = slot.submission.code
    response = orga_client.post(
        url,
        data={f"link_{code}": "https://www.peertube.com/watch?v=test123"},
        follow=True,
    )
    assert response.status_code == 200
    assert PeertubeLink.objects.filter(submission__code=code).exists()


@pytest.mark.django_db
def test_post_invalid_manual_url(orga_client, event, slot):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    code = slot.submission.code
    response = orga_client.post(
        url, data={f"link_{code}": "https://example.com/"}, follow=True
    )
    assert response.status_code == 200
    assert not PeertubeLink.objects.filter(submission__code=code).exists()


@pytest.mark.django_db
def test_upload_json_file(orga_client, event, slot):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    code = slot.submission.code
    data = json.dumps([{"submission": code, "link": "https://peertube.com/watch?v=jsonvid1"}])
    upload = SimpleUploadedFile(
        "data.json", data.encode(), content_type="application/json"
    )
    response = orga_client.post(
        url, data={"action": "upload", "file": upload}, follow=True
    )
    assert response.status_code == 200
    assert PeertubeLink.objects.filter(
        submission__code=code, link="https://peertube.com/watch?v=jsonvid1"
    ).exists()


@pytest.mark.django_db
def test_upload_csv_file(orga_client, event, slot):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    code = slot.submission.code
    csv_content = f"submission,link\n{code},https://peertube.com/watch?v=csvvid1\n"
    upload = SimpleUploadedFile(
        "data.csv", csv_content.encode(), content_type="text/csv"
    )
    response = orga_client.post(
        url, data={"action": "upload", "file": upload}, follow=True
    )
    assert response.status_code == 200
    assert PeertubeLink.objects.filter(
        submission__code=code, link="https://peertube.com/watch?v=csvvid1"
    ).exists()


@pytest.mark.django_db
def test_upload_invalid_file_type(orga_client, event, slot):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    upload = SimpleUploadedFile("data.txt", b"hello", content_type="text/plain")
    response = orga_client.post(
        url, data={"action": "upload", "file": upload}, follow=True
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_upload_no_file(orga_client, event, slot):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    response = orga_client.post(url, data={"action": "upload"}, follow=True)
    assert response.status_code == 200


@pytest.mark.django_db
def test_upload_invalid_json_content(orga_client, event, slot):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    data = json.dumps([{"submission": "NONEXIST", "video_id": "vid1"}])
    upload = SimpleUploadedFile(
        "data.json", data.encode(), content_type="application/json"
    )
    response = orga_client.post(
        url, data={"action": "upload", "file": upload}, follow=True
    )
    assert response.status_code == 200


# -- API tests --


@pytest.mark.django_db
def test_api_list(api_client, event, peertube_link):
    response = api_client.get(f"/api/events/{event.slug}/p/peertube/")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["link"] == "https://peertube.com/watch?v=dQw4w9WgXcQ"
    assert (
        data["results"][0]["peertube_link"] == "https://peertube.com/w/dQw4w9WgXcQ"
    )


@pytest.mark.django_db
def test_api_detail(api_client, event, peertube_link):
    code = peertube_link.submission.code
    response = api_client.get(f"/api/events/{event.slug}/p/peertube/{code}/")
    assert response.status_code == 200
    data = response.json()
    assert data["link"] == "https://peertube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.django_db
def test_api_create(api_client, event, confirmed_submission):
    response = api_client.post(
        f"/api/events/{event.slug}/p/peertube/",
        data={"submission": confirmed_submission.code, "link": "https://peertube.com/watch?v=newvid123"},
        format="json",
    )
    assert response.status_code == 201
    assert PeertubeLink.objects.filter(
        submission=confirmed_submission, link="https://peertube.com/watch?v=newvid123"
    ).exists()


@pytest.mark.django_db
def test_api_update(api_client, event, peertube_link):
    code = peertube_link.submission.code
    response = api_client.patch(
        f"/api/events/{event.slug}/p/peertube/{code}/",
        data={"link": "https://peertube.com/watch?v=updated123"},
        format="json",
    )
    assert response.status_code == 200
    peertube_link.refresh_from_db()
    assert peertube_link.link == "https://peertube.com/watch?v=updated123"


@pytest.mark.django_db
def test_api_create_duplicate_updates(api_client, event, peertube_link):
    code = peertube_link.submission.code
    response = api_client.post(
        f"/api/events/{event.slug}/p/peertube/",
        data={"submission": code, "link": "https://peertube.com/watch?v=replaced"},
        format="json",
    )
    assert response.status_code == 201
    assert PeertubeLink.objects.filter(submission__code=code).count() == 1
    assert PeertubeLink.objects.get(submission__code=code).link == "https://peertube.com/watch?v=replaced"


@pytest.mark.django_db
def test_api_create_strips_url_from_video_id(api_client, event, confirmed_submission):
    response = api_client.post(
        f"/api/events/{event.slug}/p/peertube/",
        data={"submission": confirmed_submission.code, "link": "https://peertube.com/watch?v=abc123"},
        format="json",
    )
    assert response.status_code == 201
    assert PeertubeLink.objects.get(submission=confirmed_submission).link == "https://peertube.com/watch?v=abc123"


@pytest.mark.django_db
def test_api_create_rejects_invalid_video_id(api_client, event, confirmed_submission):
    response = api_client.post(
        f"/api/events/{event.slug}/p/peertube/",
        data={"submission": confirmed_submission.code, "link": "not a valid url!"},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["link"] == ["Enter a valid URL."]
    assert not PeertubeLink.objects.filter(submission=confirmed_submission).exists()


@pytest.mark.django_db
def test_api_bulk_import_json(api_client, event, confirmed_submission):
    data = [{"submission": confirmed_submission.code, "link": "https://peertube.com/watch?v=bulkvid1"}]
    response = api_client.post(
        f"/api/events/{event.slug}/p/peertube/import/", data=data, format="json"
    )
    assert response.status_code == 201
    assert PeertubeLink.objects.filter(
        submission=confirmed_submission, link="https://peertube.com/watch?v=bulkvid1"
    ).exists()


@pytest.mark.django_db
def test_api_bulk_import_parser_returns_none(api_client, event):
    with patch("pretalx_peertube.api.parsers.FileUploadParser") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.parse.return_value = None
        mock_cls.return_value = mock_instance
        response = api_client.post(
            f"/api/events/{event.slug}/p/peertube/import/",
            data=b"x",
            content_type="text/csv",
        )
    assert response.status_code == 400


@pytest.mark.django_db
def test_api_bulk_import_too_many_files(api_client, event):
    with patch("pretalx_peertube.api.parsers.FileUploadParser") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.parse.return_value = {"a": "1", "b": "2"}
        mock_cls.return_value = mock_instance
        response = api_client.post(
            f"/api/events/{event.slug}/p/peertube/import/",
            data=b"x",
            content_type="text/csv",
        )
    assert response.status_code == 400


@pytest.mark.django_db
def test_api_bulk_import_csv_file(api_client, event, confirmed_submission):
    csv_content = f"submission,link\n{confirmed_submission.code},https://peertube.com/watch?v=csvvid1\n"
    with patch("pretalx_peertube.api.parsers.FileUploadParser") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.parse.return_value = {"file": csv_content}
        mock_cls.return_value = mock_instance
        response = api_client.post(
            f"/api/events/{event.slug}/p/peertube/import/",
            data=b"x",
            content_type="text/csv",
        )
    assert response.status_code == 201
    assert PeertubeLink.objects.filter(
        submission=confirmed_submission, link="https://peertube.com/watch?v=csvvid1"
    ).exists()


@pytest.mark.django_db
def test_api_serializer_without_context():
    serializer = PeertubeLinkSerializer()
    assert not hasattr(serializer, "event")


@pytest.mark.django_db
def test_api_write_serializer_without_context():
    serializer = PeertubeLinkWriteSerializer()
    assert not hasattr(serializer, "event")


@pytest.mark.django_db
def test_api_viewset_queryset_no_event():
    viewset = PeertubeLinkViewSet()
    viewset.request = MagicMock(event=None)
    assert list(viewset.get_queryset()) == []


@pytest.mark.django_db
def test_api_viewset_permission_object(event):
    viewset = PeertubeLinkViewSet()
    viewset.request = MagicMock(event=event)
    assert viewset.get_permission_object() == event


# -- Signal tests --


@pytest.mark.django_db
def test_nav_event_settings_signal(orga_client, event):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    response = orga_client.get(url, follow=True)
    assert response.status_code == 200


@pytest.mark.django_db
def test_register_recording_provider_signal(event):
    responses = register_recording_provider.send(sender=event)
    providers = [r for _, r in responses]
    assert any(isinstance(p, PeertubeProvider) for p in providers)


# -- Misc view/form coverage --


def test_get_success_url_returns_request_path():
    view = PeertubeSettings()
    view.request = MagicMock(path="/some/settings/path")
    assert view.get_success_url() == "/some/settings/path"


@pytest.mark.django_db
def test_url_form_rejects_overly_long_id(event, slot):
    code = slot.submission.code
    long_url = "https://www.peertube.com/embed/" + "a" * 70
    with scope(event=event):
        form = PeertubeUrlForm(data={f"link_{code}": long_url}, event=event)
        assert not form.is_valid()


# -- c3voc webhook tests --


VALID_VIDEO_URL = "https://www.peertube.com/watch?v=abcDEF12345"
VALID_VIDEO_ID = "abcDEF12345"


@pytest.fixture
def webhook_settings(event):
    return PeertubeWebhookSettings.objects.create(event=event, token="secret-token-xyz")


def _payload(event, submission, *, enabled=True, urls=None, conference=None):
    return {
        "announcement": None,
        "is_master": True,
        "fahrplan": {
            "conference": conference or event.slug,
            "guid": None,
            "id": submission.pk,
            "language": "eng",
            "slug": f"{event.slug}-{submission.pk}-test-talk",
            "title": submission.title,
        },
        "voctoweb": {"enabled": False},
        "peertube": {
            "enabled": enabled,
            "privacy": "public",
            "publish_at": None,
            "urls": urls if urls is not None else [VALID_VIDEO_URL],
        },
        "rclone": {"enabled": False},
    }


def _post_webhook(client, event, payload, *, token=None, header=None):
    url = reverse(WEBHOOK_URL_NAME, kwargs={"event": event.slug})
    extra = {}
    if header is not None:
        extra["HTTP_AUTHORIZATION"] = header
    elif token is not None:
        extra["HTTP_AUTHORIZATION"] = token
    return client.post(
        url, data=json.dumps(payload), content_type="application/json", **extra
    )


@pytest.mark.django_db
def test_webhook_requires_auth(client, event, webhook_settings, confirmed_submission):
    response = _post_webhook(client, event, _payload(event, confirmed_submission))
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_rejects_wrong_token(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client, event, _payload(event, confirmed_submission), token="nope"
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_rejects_bearer_scheme(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        header=f"Bearer {webhook_settings.token}",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_accepts_plain_token(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        token=webhook_settings.token,
    )
    assert response.status_code == 204
    with scope(event=event):
        link = PeertubeLink.objects.get(submission=confirmed_submission)
    assert link.link == VALID_VIDEO_URL


@pytest.mark.django_db
def test_webhook_accepts_basic_auth(
    client, event, webhook_settings, confirmed_submission
):
    credentials = base64.b64encode(
        f"voctopublish:{webhook_settings.token}".encode()
    ).decode()
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        header=f"Basic {credentials}",
    )
    assert response.status_code == 204
    with scope(event=event):
        assert PeertubeLink.objects.filter(submission=confirmed_submission).exists()


@pytest.mark.django_db
def test_webhook_rejects_basic_auth_with_wrong_password(
    client, event, webhook_settings, confirmed_submission
):
    credentials = base64.b64encode(b"voctopublish:wrong").decode()
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        header=f"Basic {credentials}",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_rejects_basic_auth_without_colon(
    client, event, webhook_settings, confirmed_submission
):
    credentials = base64.b64encode(b"nocolon").decode()
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        header=f"Basic {credentials}",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_rejects_malformed_basic_auth(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        header="Basic !!!not-base64!!!",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_rejects_empty_basic_password(
    client, event, webhook_settings, confirmed_submission
):
    credentials = base64.b64encode(b"user:").decode()
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        header=f"Basic {credentials}",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_unknown_event_is_rejected(client, webhook_settings, event):
    url = reverse(WEBHOOK_URL_NAME, kwargs={"event": event.slug}).replace(
        event.slug, "doesnotexist"
    )
    response = client.post(
        url,
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=webhook_settings.token,
    )
    assert response.status_code in (403, 404)


@pytest.mark.django_db
def test_webhook_plugin_disabled_is_rejected(
    client, event, webhook_settings, confirmed_submission
):
    event.plugins = ""
    event.save()
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        token=webhook_settings.token,
    )
    assert response.status_code in (403, 404)


@pytest.mark.django_db
def test_webhook_without_settings_returns_403(client, event, confirmed_submission):
    response = _post_webhook(
        client, event, _payload(event, confirmed_submission), token="anything"
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_rejects_non_json(client, event, webhook_settings):
    url = reverse(WEBHOOK_URL_NAME, kwargs={"event": event.slug})
    response = client.post(
        url,
        data="not json",
        content_type="application/json",
        HTTP_AUTHORIZATION=webhook_settings.token,
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_rejects_non_object_payload(client, event, webhook_settings):
    url = reverse(WEBHOOK_URL_NAME, kwargs={"event": event.slug})
    response = client.post(
        url,
        data=json.dumps([1, 2, 3]),
        content_type="application/json",
        HTTP_AUTHORIZATION=webhook_settings.token,
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_disabled_peertube_is_noop(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission, enabled=False),
        token=webhook_settings.token,
    )
    assert response.status_code == 204
    with scope(event=event):
        assert not PeertubeLink.objects.filter(submission=confirmed_submission).exists()


@pytest.mark.django_db
def test_webhook_empty_urls_returns_400(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission, urls=[]),
        token=webhook_settings.token,
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_urls_wrong_type_returns_400(
    client, event, webhook_settings, confirmed_submission
):
    payload = _payload(event, confirmed_submission)
    payload["peertube"]["urls"] = "https://youtu.be/abc"
    response = _post_webhook(client, event, payload, token=webhook_settings.token)
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_no_valid_url_returns_400(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission, urls=["https://example.com/foo bar"]),
        token=webhook_settings.token,
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_skips_non_string_url_entries(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission, urls=[123, VALID_VIDEO_URL]),
        token=webhook_settings.token,
    )
    assert response.status_code == 204


@pytest.mark.django_db
def test_webhook_wrong_conference_returns_404(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission, conference="otherconference"),
        token=webhook_settings.token,
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_webhook_unknown_submission_returns_404(
    client, event, webhook_settings, confirmed_submission
):
    payload = _payload(event, confirmed_submission)
    payload["fahrplan"]["id"] = 9999999
    payload["fahrplan"]["slug"] = f"{event.slug}-9999999-nope"
    response = _post_webhook(client, event, payload, token=webhook_settings.token)
    assert response.status_code == 404


@pytest.mark.django_db
def test_webhook_matches_by_slug_when_id_missing(
    client, event, webhook_settings, confirmed_submission
):
    payload = _payload(event, confirmed_submission)
    payload["fahrplan"]["id"] = None
    response = _post_webhook(client, event, payload, token=webhook_settings.token)
    assert response.status_code == 204
    with scope(event=event):
        assert PeertubeLink.objects.filter(submission=confirmed_submission).exists()


@pytest.mark.django_db
def test_webhook_updates_existing_link(
    client, event, webhook_settings, confirmed_submission, peertube_link
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission),
        token=webhook_settings.token,
    )
    assert response.status_code == 204
    with scope(event=event):
        peertube_link.refresh_from_db()
    assert peertube_link.link == VALID_VIDEO_URL


@pytest.mark.django_db
def test_webhook_only_get_rejected(client, event, webhook_settings):
    url = reverse(WEBHOOK_URL_NAME, kwargs={"event": event.slug})
    response = client.get(url, HTTP_AUTHORIZATION=webhook_settings.token)
    assert response.status_code == 405


@pytest.mark.django_db
def test_settings_page_shows_webhook_config(orga_client, event):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    response = orga_client.get(url)
    assert response.status_code == 200
    # Webhook settings should be auto-created
    settings = PeertubeWebhookSettings.objects.get(event=event)
    assert settings.token
    assert settings.token.encode() in response.content


@pytest.mark.django_db
def test_settings_rotate_token(orga_client, event):
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    orga_client.get(url)  # auto-create
    original = PeertubeWebhookSettings.objects.get(event=event).token
    response = orga_client.post(url, data={"action": "rotate_token"}, follow=True)
    assert response.status_code == 200
    new_token = PeertubeWebhookSettings.objects.get(event=event).token
    assert new_token != original


@pytest.mark.django_db
def test_settings_rotate_creates_settings_if_missing(orga_client, event):
    PeertubeWebhookSettings.objects.filter(event=event).delete()
    url = reverse(SETTINGS_URL_NAME, kwargs={"event": event.slug})
    response = orga_client.post(url, data={"action": "rotate_token"}, follow=True)
    assert response.status_code == 200
    assert PeertubeWebhookSettings.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_webhook_peertube_nocookie_url(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(
            event,
            confirmed_submission,
            urls=["https://www.peertube-nocookie.com/embed/abcDEF12345"],
        ),
        token=webhook_settings.token,
    )
    assert response.status_code == 204
    with scope(event=event):
        link = PeertubeLink.objects.get(submission=confirmed_submission)
    assert link.link == "https://www.peertube-nocookie.com/embed/abcDEF12345"


@pytest.mark.django_db
def test_webhook_peertube_shorts_url(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission, urls=["https://youtu.be/abcDEF12345"]),
        token=webhook_settings.token,
    )
    assert response.status_code == 204


@pytest.mark.django_db
def test_webhook_model_str(webhook_settings):
    assert "PeertubeWebhookSettings" in str(webhook_settings)


@pytest.mark.django_db
def test_webhook_rejects_peertube_com_without_video_id(
    client, event, webhook_settings, confirmed_submission
):
    response = _post_webhook(
        client,
        event,
        _payload(event, confirmed_submission, urls=["https://www.peertube.com/"]),
        token=webhook_settings.token,
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_find_submission_slug_wrong_prefix(event, confirmed_submission):
    with scope(event=event):
        payload = {
            "fahrplan": {
                "conference": event.slug,
                "id": None,
                "slug": "other-event-42-foo",
            }
        }
        assert _find_submission(event, payload) is None


@pytest.mark.django_db
def test_find_submission_slug_non_numeric_pk(event, confirmed_submission):
    with scope(event=event):
        payload = {
            "fahrplan": {
                "conference": event.slug,
                "id": None,
                "slug": f"{event.slug}-notanumber-foo",
            }
        }
        assert _find_submission(event, payload) is None
