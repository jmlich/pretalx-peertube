import re
from urllib.parse import parse_qs, urlparse

# Peertube video ids only ever contain these characters. Enforcing the charset
# keeps HTML metacharacters out of the id, which is embedded into iframe markup.
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def extract_video_id(url):
    """Return the Peertube video id from a URL, or None if nothing usable is found.

    Accepts any URL and extracts the last path component if it's alphanumeric.
    """
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
        
    qs = parse_qs(parsed.query)
    if "v" in qs:
        video_id = qs["v"][0]
    elif parsed.path:
        path_parts = [p for p in parsed.path.split("/") if p]
        if not path_parts:
            return None
        video_id = path_parts[-1]
    else:
        return None
        
    if len(video_id) > 64:
        return None
        
    if not VIDEO_ID_RE.match(video_id):
        return None
        
    return video_id
