from pretalx.agenda.recording import BaseRecordingProvider

from .models import PeertubeLink


class PeertubeProvider(BaseRecordingProvider):
    def get_recording(self, submission):
        peertube = PeertubeLink.objects.filter(submission=submission).first()
        if peertube:
            return {
                "iframe": peertube.iframe,
                "csp_header": f"https://{peertube.domain}/",
            }
