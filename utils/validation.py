"""Small input validators."""

from __future__ import annotations

from urllib.parse import urlparse


def is_http_url(url: str | None) -> bool:
    """True for non-empty http(s) URLs (used to validate embed image URLs)."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)
