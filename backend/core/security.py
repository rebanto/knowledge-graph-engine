"""Input hardening for user-supplied sources.

Two attack surfaces are covered here:

1. URL-based sources (rss / web_url). The ingestion worker fetches whatever URL
   the user saved, so without validation a source can be pointed at internal
   services (SSRF): cloud metadata endpoints, the Docker network, localhost
   admin ports. `validate_public_http_url` rejects non-HTTP schemes and any
   host that resolves to a private / loopback / link-local / reserved address.
   Set ALLOW_PRIVATE_SOURCE_URLS=true to opt out in local development (e.g.
   to ingest a page served from localhost).

2. PDF uploads. The filename is attacker-controlled and used to build the
   on-disk path; the bytes are parsed by pypdf. `sanitize_upload_filename`
   strips path components and shell-hostile characters, and
   `validate_pdf_upload` enforces the size cap and the PDF magic bytes so
   arbitrary files can't be smuggled into the pipeline.
"""
import ipaddress
import os
import re
import socket
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """The URL is not a safe, public HTTP(S) endpoint."""


class InvalidUploadError(ValueError):
    """The uploaded file failed validation (not a PDF / too large / bad name)."""


_MAX_PDF_UPLOAD_MB = float(os.environ.get("MAX_PDF_UPLOAD_MB", 50))


def _allow_private() -> bool:
    return os.environ.get("ALLOW_PRIVATE_SOURCE_URLS", "").lower() == "true"


def _is_public_address(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_http_url(url: str) -> str:
    """Validate that `url` is an http(s) URL pointing at a public address.

    Returns the URL unchanged on success; raises UnsafeURLError otherwise.
    Resolution uses getaddrinfo (blocking) — call via asyncio.to_thread from
    async code. Note this checks the URL as given; it does not follow
    redirects, which is an accepted limitation for a local-first tool.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(
            f"Only http:// and https:// URLs are supported (got {parsed.scheme or 'no scheme'!r})."
        )
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no hostname.")

    if _allow_private():
        return url

    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host {host!r}: {exc}") from exc

    for info in infos:
        addr = info[4][0]
        if not _is_public_address(addr):
            raise UnsafeURLError(
                f"Host {host!r} resolves to a private or internal address ({addr}). "
                "Set ALLOW_PRIVATE_SOURCE_URLS=true to allow internal URLs in local dev."
            )
    return url


# ── PDF upload validation ──────────────────────────────────────────────────────

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")


def sanitize_upload_filename(filename: str | None) -> str:
    """Reduce an attacker-controlled filename to a safe basename.

    Strips directory components (both / and \\ conventions), collapses anything
    outside [A-Za-z0-9._ -], and guarantees a .pdf suffix. Never returns an
    empty or dot-only name.
    """
    # Take the basename under both path conventions — a Windows client may send
    # backslashes that PurePosixPath would treat as ordinary characters.
    name = PureWindowsPath(PurePosixPath(filename or "").name).name
    name = _UNSAFE_NAME_CHARS.sub("_", name).strip(" .")
    if not name:
        name = "upload.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def validate_pdf_upload(contents: bytes, filename: str | None) -> str:
    """Validate uploaded PDF bytes; return the sanitized filename to store under.

    Raises InvalidUploadError when the file is empty, oversized, or does not
    start with the PDF magic bytes.
    """
    if not contents:
        raise InvalidUploadError("Uploaded file is empty.")
    max_bytes = int(_MAX_PDF_UPLOAD_MB * 1024 * 1024)
    if len(contents) > max_bytes:
        raise InvalidUploadError(
            f"File is {len(contents) / (1024 * 1024):.1f} MB — the limit is "
            f"{_MAX_PDF_UPLOAD_MB:g} MB (set MAX_PDF_UPLOAD_MB to change it)."
        )
    if not contents.startswith(b"%PDF-"):
        raise InvalidUploadError("File does not look like a PDF (missing %PDF header).")
    return sanitize_upload_filename(filename)
