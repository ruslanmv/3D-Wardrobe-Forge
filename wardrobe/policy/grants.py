"""BI2. A read grant: what a companion app holds instead of the operator's admin token.

Before this, a private look (every bare look, every look an admin session's declaration made) was
listed and served to an admin session and to no one else. The companion app's Private wardrobe
reads Forge as an ordinary client, so the only way it could ever be shown a private body state was
to be handed the admin token — the one secret that also signs declarations, uploads tattoo artwork,
imports body states and deletes looks, for every avatar, for eight hours, to whoever opens the
browser's network panel. A consumer must never hold that.

A grant is the smallest thing that is enough:

* **Read only.** It lists private looks and fetches their files. It cannot declare, import, build,
  delete or mint, and no route that changes anything accepts it.
* **Scoped to named library avatars.** A grant for ``vroid-model-girl`` does not list or serve
  Rinna's private looks. ``/v1/assets`` checks the grant against the wardrobe named in the look's
  own private marker, a stored object, so the check holds after a restart.
* **Expiring.** At most ``MAX_TTL_S``; there is no "forever".
* **Revocable.** By its id (``WARDROBE_GRANT_REVOKED``), or all at once by rotating the secret.
* **Stateless.** An HMAC-SHA256 over its own claims with ``WARDROBE_GRANT_SECRET``. Unset (the
  default), or shorter than ``MIN_SECRET_LENGTH``, there are no grants at all and every private
  look stays admin-only, exactly as before.

The operator mints one per deployment of the app (or per device) in an admin session
(``POST /v1/admin/grants``). Who may *use* the app's Private mode is the app's question — its own
consent flow and age gate — and a grant does not answer it; it only stops the Forge secret from
being the thing the app holds.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass

HEADER = "X-Wardrobe-Grant"
SCOPE = "private-read"
VERSION = 1
MIN_SECRET_LENGTH = 32
MAX_TTL_S = 30 * 24 * 3600
MAX_SLUGS = 32
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class GrantError(ValueError):
    pass


@dataclass(frozen=True)
class Grant:
    id: str
    slugs: frozenset[str]
    expires: int
    issued: int
    label: str

    def covers(self, slug: str | None) -> bool:
        return bool(slug) and slug in self.slugs

    def to_dict(self) -> dict:
        return {"id": self.id, "scope": SCOPE, "slugs": sorted(self.slugs), "expires": self.expires,
                "issued": self.issued, "label": self.label}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def usable(secret: str | None) -> bool:
    return bool(secret) and len(secret) >= MIN_SECRET_LENGTH


def _sign(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def mint(secret: str, *, slugs, ttl_s: int, label: str = "", now: float | None = None) -> tuple[str, Grant]:
    if not usable(secret):
        raise GrantError(f"grants need WARDROBE_GRANT_SECRET of at least {MIN_SECRET_LENGTH} characters")
    names = sorted({str(s) for s in slugs or []})
    if not names or len(names) > MAX_SLUGS or not all(_SLUG.match(s) for s in names):
        raise GrantError(f"a grant names 1-{MAX_SLUGS} library avatars by slug")
    if not 60 <= int(ttl_s) <= MAX_TTL_S:
        raise GrantError(f"a grant lasts between 60 s and {MAX_TTL_S // 86400} days")
    issued = int(now if now is not None else time.time())
    grant = Grant(secrets.token_hex(8), frozenset(names), issued + int(ttl_s), issued, str(label)[:80])
    claims = {"v": VERSION, "scope": SCOPE, "jti": grant.id, "slugs": names, "iat": issued,
              "exp": grant.expires, "label": grant.label}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_sign(secret, body)}", grant


def verify(secret: str | None, token: str | None, *, revoked=(), now: float | None = None) -> Grant | None:
    """The grant this token is, or None: unsigned, tampered, expired, revoked, or grants are off."""
    if not usable(secret) or not token or token.count(".") != 1 or len(token) > 4096:
        return None
    body, signature = token.split(".")
    if not hmac.compare_digest(signature, _sign(secret, body)):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict) or claims.get("v") != VERSION or claims.get("scope") != SCOPE:
        return None
    current = int(now if now is not None else time.time())
    try:
        expires, issued = int(claims["exp"]), int(claims["iat"])
        slugs = frozenset(str(s) for s in claims["slugs"])
        grant_id = str(claims["jti"])
    except (KeyError, TypeError, ValueError):
        return None
    if expires <= current or expires - issued > MAX_TTL_S or grant_id in set(revoked or ()):
        return None
    return Grant(grant_id, slugs, expires, issued, str(claims.get("label", "")))


__all__ = ["HEADER", "MAX_TTL_S", "MIN_SECRET_LENGTH", "SCOPE", "Grant", "GrantError", "mint", "usable",
           "verify"]
