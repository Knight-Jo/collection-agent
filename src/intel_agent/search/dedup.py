"""Conservative URL dedup keys (spec §6.2)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def dedup_key(url: str, tracking_params: tuple[str, ...] = ()) -> str:
    """Conservative normalization that never merges distinct sources.

    Lowercases scheme and host and drops default ports, but keeps path case,
    trailing slashes, and the scheme (http vs https) distinct. Tracking
    parameters are stripped via a configurable whitelist; fragments are
    dropped except for hash routes (``#/...``) where they identify content.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    query = parts.query
    if query and tracking_params:
        pairs = [
            (k, v)
            for k, v in parse_qsl(query, keep_blank_values=True)
            if k not in tracking_params
        ]
        query = urlencode(pairs)
    fragment = parts.fragment
    if fragment and not fragment.startswith("/"):
        fragment = ""
    return urlunsplit((scheme, netloc, parts.path, query, fragment))
