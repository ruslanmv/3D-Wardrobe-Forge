"""Input safety for untrusted avatar files and URLs.

User-uploaded VRMs are untrusted binaries that a Blender worker will parse, so
everything is bounded and checked before it reaches the pipeline: URL scheme
and host, private-network egress, download size, content sniffing and hash
verification.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from wardrobe.config import Settings
from wardrobe.domain.jobs import FailureReason
from wardrobe.errors import SourceRejected
from wardrobe.vrm.glb import is_glb

#: Storage keys are built from these characters only — no traversal, no shells.
SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(slots=True)
class UrlVerdict:
    allowed: bool
    message: str = ""
    host: str | None = None


def sanitize_component(value: str, *, fallback: str = "asset") -> str:
    """Make ``value`` safe to use as one path segment of a storage key."""
    cleaned = _UNSAFE_CHARS.sub("-", (value or "").strip()).strip("-.")
    cleaned = cleaned[:80]
    return cleaned or fallback


def validate_storage_key(key: str) -> str:
    if not SAFE_KEY.match(key or "") or ".." in key:
        raise SourceRejected(f"unsafe storage key: {key!r}", reason=FailureReason.UNSUPPORTED_ASSET)
    return key


def _is_private_address(host: str) -> bool:
    """True when the host resolves to a private, loopback or link-local IP."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Unresolvable: treat as unsafe rather than letting the fetch try.
        return True

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def check_source_url(url: str, settings: Settings) -> UrlVerdict:
    """Validate a source URL before any network request is made."""
    parsed = urlparse(str(url))
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    if scheme not in {s.lower() for s in settings.allowed_source_schemes}:
        return UrlVerdict(
            False, f"scheme {scheme!r} is not allowed (allowed: {settings.allowed_source_schemes})"
        )
    if not host:
        return UrlVerdict(False, "URL has no host")

    if settings.allowed_source_hosts:
        allowed = {h.lower() for h in settings.allowed_source_hosts}
        if host not in allowed and not any(host.endswith(f".{a}") for a in allowed):
            return UrlVerdict(False, f"host {host!r} is not in the configured allowlist", host)

    if settings.block_private_networks and _is_private_address(host):
        return UrlVerdict(False, f"host {host!r} resolves to a non-public address", host)

    return UrlVerdict(True, host=host)


def require_source_url(url: str, settings: Settings) -> str:
    verdict = check_source_url(url, settings)
    if not verdict.allowed:
        raise SourceRejected(verdict.message, reason=FailureReason.SOURCE_UNREACHABLE)
    return str(url)


def check_size(size: int, settings: Settings, *, what: str = "source avatar") -> None:
    limit = settings.max_avatar_bytes
    if size > limit:
        raise SourceRejected(
            f"{what} is {size} bytes, over the {limit} byte limit",
            reason=FailureReason.SOURCE_TOO_LARGE,
        )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_hash(data: bytes, expected: str | None) -> str:
    """Return the digest, raising when it does not match ``expected``."""
    digest = sha256_hex(data)
    if expected and digest.lower() != expected.lower():
        raise SourceRejected(
            "source avatar does not match the supplied sha256",
            reason=FailureReason.HASH_MISMATCH,
            detail={"expected": expected, "actual": digest},
        )
    return digest


def sniff_vrm(data: bytes) -> None:
    """Reject anything that is not a GLB container before parsing it."""
    if not is_glb(data):
        raise SourceRejected(
            "source file is not a GLB/VRM container",
            reason=FailureReason.SOURCE_NOT_A_VRM,
        )


__all__ = [
    "UrlVerdict",
    "sanitize_component",
    "validate_storage_key",
    "check_source_url",
    "require_source_url",
    "check_size",
    "sha256_hex",
    "verify_hash",
    "sniff_vrm",
]
