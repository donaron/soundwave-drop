"""URL validation, request allowlists, and safe Content-Disposition helpers."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from typing import Callable

ALLOWED_QUALITIES: dict[str, set[str]] = {
    "mp3": {"320", "192", "128"},
    "mp4": {"2160", "1440", "1080", "720", "480", "360", "best"},
}

_ILLEGAL_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_FILENAME_LEN = 120


class ValidationError(ValueError):
    """Raised when a user-supplied URL or download parameter fails validation."""


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_forbidden_ip(ip.ipv4_mapped)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_url(
    url: str,
    resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
) -> str:
    """Validate an http/https URL and guard against loopback/private SSRF targets."""
    cleaned = url.strip()
    if not cleaned:
        raise ValidationError("Please enter a media URL.")

    parsed = urllib.parse.urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValidationError("Only http:// and https:// URLs are supported.")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValidationError("URL must include a valid hostname.")

    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValidationError("Local and private network URLs are not allowed.")

    try:
        ip_literal = ipaddress.ip_address(host)
    except ValueError:
        ip_literal = None

    if ip_literal is not None:
        if _is_forbidden_ip(ip_literal):
            raise ValidationError("Local and private IP addresses are not allowed.")
        return cleaned

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        addr_infos = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValidationError("Could not resolve URL hostname.") from exc

    if not addr_infos:
        raise ValidationError("Could not resolve URL hostname.")

    for info in addr_infos:
        raw_ip = str(info[4][0]).split("%", 1)[0]
        try:
            resolved_ip = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise ValidationError("URL resolved to an invalid IP address.") from exc
        if _is_forbidden_ip(resolved_ip):
            raise ValidationError("URL resolves to a private or local network address.")

    return cleaned


def has_playlist_context(url: str) -> bool:
    """Return True when the URL carries playlist query parameters or path segments."""
    parsed = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qs(parsed.query)
    if "list" in query:
        return True
    return parsed.path.rstrip("/").lower().endswith("/playlist")


def validate_download_request(fmt: str, quality: str) -> tuple[str, str]:
    """Validate format and quality against strict allowlists."""
    normalized_fmt = fmt.strip().lower()
    normalized_quality = quality.strip().lower()
    allowed = ALLOWED_QUALITIES.get(normalized_fmt)
    if allowed is None:
        raise ValidationError("Format must be 'mp3' or 'mp4'.")
    if normalized_quality not in allowed:
        raise ValidationError(f"Unsupported quality '{quality}' for {normalized_fmt}.")
    return normalized_fmt, normalized_quality


def _sanitize_stem(raw_stem: str, max_len: int) -> str:
    cleaned = _ILLEGAL_FILENAME_CHARS_RE.sub(" ", raw_stem)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" .")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
    return cleaned or "download"


def build_content_disposition(filename: str) -> str:
    """Build a safe RFC 5987 Content-Disposition attachment header."""
    raw = filename.strip()
    if "." in raw:
        raw_stem, raw_ext = raw.rsplit(".", 1)
        clean_ext = _ILLEGAL_FILENAME_CHARS_RE.sub("", raw_ext).strip(" .")
        ext = f".{clean_ext[:12]}" if clean_ext else ""
    else:
        raw_stem = raw
        ext = ""

    max_stem_len = max(1, _MAX_FILENAME_LEN - len(ext))
    utf8_stem = _sanitize_stem(raw_stem, max_stem_len)
    utf8_name = f"{utf8_stem}{ext}"

    ascii_raw = utf8_stem.encode("ascii", "ignore").decode("ascii")
    ascii_stem = _sanitize_stem(ascii_raw, max_stem_len)
    ascii_name = f"{ascii_stem}{ext}"

    quoted_utf8 = urllib.parse.quote(utf8_name, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted_utf8}'
