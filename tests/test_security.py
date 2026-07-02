"""Unit tests for backend/core/security.py — source URL + upload validation.

Pure unit: private/loopback checks use literal IPs (no DNS), and the one
hostname case uses 'localhost', which resolves without a network.
"""
import pytest

from backend.core.security import (
    InvalidUploadError,
    UnsafeURLError,
    sanitize_upload_filename,
    validate_pdf_upload,
    validate_public_http_url,
)
from tests.conftest import make_pdf_bytes


# ── URL guard ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "ftp://example.com/feed.xml",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "not a url at all",
    "",
])
def test_non_http_schemes_rejected(url):
    with pytest.raises(UnsafeURLError):
        validate_public_http_url(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/admin",          # loopback
    "http://localhost/secret",              # loopback via hostname
    "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
    "http://192.168.1.10/router",           # RFC1918
    "http://10.0.0.5/internal",             # RFC1918
    "http://[::1]/",                        # IPv6 loopback
    "http://0.0.0.0/",                      # unspecified
])
def test_private_and_internal_addresses_rejected(url):
    with pytest.raises(UnsafeURLError):
        validate_public_http_url(url)


def test_private_urls_allowed_with_env_override(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_SOURCE_URLS", "true")
    assert validate_public_http_url("http://localhost:8080/feed") is not None


def test_public_literal_ip_accepted():
    # A literal public IP needs no DNS, so this stays offline-safe.
    assert validate_public_http_url("https://8.8.8.8/feed.xml")


def test_unresolvable_host_rejected():
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://this-host-does-not-exist-xyz.invalid/")


# ── Upload filename sanitization ───────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_suffix", [
    ("paper.pdf", "paper.pdf"),
    ("..\\..\\..\\evil.pdf", "evil.pdf"),
    ("../../etc/passwd", "passwd.pdf"),
    ("C:\\Windows\\system32\\x.pdf", "x.pdf"),
    ("nul<>|;&.pdf", "nul____;_.pdf".replace(";", "_")),  # unsafe chars collapsed
    ("", "upload.pdf"),
    (None, "upload.pdf"),
    ("...", "upload.pdf"),
])
def test_sanitize_upload_filename(raw, expected_suffix):
    name = sanitize_upload_filename(raw)
    assert name.lower().endswith(".pdf")
    assert "/" not in name and "\\" not in name and ".." not in name
    if raw in ("paper.pdf",):
        assert name == expected_suffix


def test_sanitize_strips_all_directory_components():
    # Enough .. components previously escaped the uploads dir after lexical
    # normalization on Windows — the sanitized name must be a pure basename.
    name = sanitize_upload_filename("..\\..\\..\\..\\outside.pdf")
    assert name == "outside.pdf"


# ── PDF upload validation ──────────────────────────────────────────────────────

def test_valid_pdf_accepted():
    pdf = make_pdf_bytes(["hello world"])
    assert validate_pdf_upload(pdf, "doc.pdf") == "doc.pdf"


def test_empty_upload_rejected():
    with pytest.raises(InvalidUploadError):
        validate_pdf_upload(b"", "doc.pdf")


def test_non_pdf_bytes_rejected():
    with pytest.raises(InvalidUploadError):
        validate_pdf_upload(b"MZ\x90\x00 definitely-not-a-pdf", "doc.pdf")


def test_oversized_upload_rejected(monkeypatch):
    import backend.core.security as sec
    monkeypatch.setattr(sec, "_MAX_PDF_UPLOAD_MB", 0.0001)  # ~100 bytes
    pdf = make_pdf_bytes(["x" * 500])
    with pytest.raises(InvalidUploadError):
        validate_pdf_upload(pdf, "doc.pdf")
