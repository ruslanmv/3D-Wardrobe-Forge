"""Input safety: URL policy, size limits, hashes and storage keys."""

from __future__ import annotations

import pytest

from wardrobe.config import Settings
from wardrobe.domain.jobs import FailureReason
from wardrobe.errors import SourceRejected
from wardrobe.policy.file_safety import (
    check_size,
    check_source_url,
    sanitize_component,
    sha256_hex,
    sniff_vrm,
    validate_storage_key,
    verify_hash,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(block_private_networks=True, allowed_source_schemes=["https"])


# ----------------------------------------------------------------------
# URLs
# ----------------------------------------------------------------------
def test_http_is_rejected_by_default(settings: Settings):
    verdict = check_source_url("http://example.com/a.vrm", settings)
    assert not verdict.allowed
    assert "scheme" in verdict.message


def test_loopback_is_rejected(settings: Settings):
    verdict = check_source_url("https://127.0.0.1/a.vrm", settings)
    assert not verdict.allowed
    assert "non-public" in verdict.message


def test_private_range_is_rejected(settings: Settings):
    assert not check_source_url("https://10.0.0.5/a.vrm", settings).allowed


def test_link_local_metadata_endpoint_is_rejected(settings: Settings):
    """169.254.169.254 is the cloud metadata service; it must never be fetched."""
    assert not check_source_url("https://169.254.169.254/latest/meta-data/", settings).allowed


def test_host_allowlist_is_enforced():
    settings = Settings(allowed_source_hosts=["cdn.example.com"], block_private_networks=False)
    assert check_source_url("https://cdn.example.com/a.vrm", settings).allowed
    assert check_source_url("https://assets.cdn.example.com/a.vrm", settings).allowed
    assert not check_source_url("https://evil.example.org/a.vrm", settings).allowed


def test_url_without_a_host_is_rejected(settings: Settings):
    assert not check_source_url("https:///a.vrm", settings).allowed


# ----------------------------------------------------------------------
# storage keys
# ----------------------------------------------------------------------
@pytest.mark.parametrize("key", ["../../etc/passwd", "looks/../../secret", "/absolute", "a b", ""])
def test_unsafe_storage_keys_are_rejected(key: str):
    with pytest.raises(SourceRejected):
        validate_storage_key(key)


def test_safe_storage_key_is_accepted():
    assert validate_storage_key("looks/look_abc/look.vrm")


def test_sanitize_component_strips_separators():
    assert "/" not in sanitize_component("../../evil/name.vrm")
    assert sanitize_component("") == "asset"
    assert sanitize_component("Mira Avatar!") == "Mira-Avatar"


# ----------------------------------------------------------------------
# content
# ----------------------------------------------------------------------
def test_size_limit(settings: Settings):
    with pytest.raises(SourceRejected) as error:
        check_size(settings.max_avatar_bytes + 1, settings)
    assert error.value.reason is FailureReason.SOURCE_TOO_LARGE


def test_hash_mismatch_is_rejected():
    with pytest.raises(SourceRejected) as error:
        verify_hash(b"payload", "0" * 64)
    assert error.value.reason is FailureReason.HASH_MISMATCH


def test_hash_match_returns_the_digest():
    assert verify_hash(b"payload", sha256_hex(b"payload")) == sha256_hex(b"payload")


def test_missing_expected_hash_is_allowed():
    assert verify_hash(b"payload", None) == sha256_hex(b"payload")


def test_sniff_rejects_non_glb():
    with pytest.raises(SourceRejected) as error:
        sniff_vrm(b"<html>not a model</html>")
    assert error.value.reason is FailureReason.SOURCE_NOT_A_VRM


def test_sniff_accepts_a_real_vrm(vrm_bytes: bytes):
    sniff_vrm(vrm_bytes)
