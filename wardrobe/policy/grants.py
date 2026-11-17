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
* **Expiring, or until revoked.** At most ``MAX_TTL_S``, or, when the operator asks for it in so
  many words, ``NO_EXPIRY_TTL_S`` (CG8: a grant pasted into the operator's own devices that should
  not need renewing). That one is still revocable by its id or by rotating the secret.
* **Revocable.** By its id (``WARDROBE_GRANT_REVOKED``), or all at once by rotating the secret.
* **Stateless.** An HMAC-SHA256 over its own claims with ``WARDROBE_GRANT_SECRET``. Unset (the
  default), or shorter than ``MIN_SECRET_LENGTH``, there are no grants at all and every private
  look stays admin-only, exactly as before.

The operator mints one per deployment of the app (or per device) in an admin session
(``POST /v1/admin/grants``). Who may *use* the app's Private mode is the app's question — its own
consent flow and age gate — and a grant does not answer it; it only stops the Forge secret from
being the thing the app holds.

AC1. **Account capabilities.** An operator grant answers "which avatars", for whoever holds it,
for up to thirty days: handed to a browser it is a shared long-lived credential. A capability is
the same signed token with one more claim, ``sub``: the signed-in account it was issued to by
``POST /v1/access/capabilities`` (``wardrobe.policy.identity``), after that account was verified
and found entitled to each avatar it names. It lasts at most ``ACCOUNT_MAX_TTL_S`` (a token with
``sub`` and a longer life does not verify, whoever signed it), is revocable by its id or by its
account (``wardrobe.policy.revocations``), and reads a look whose marker names an account only
when it is that account's. Tokens minted before AC1 carry no ``sub`` and verify as they did.
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
#: CG8. "No expiry": a hundred years, asked for explicitly; never a capability, always revocable.
NO_EXPIRY_TTL_S = 100 * 365 * 24 * 3600
#: AC1. The longest an account capability lives. Short enough that a copied one is soon
#: nothing, long enough for a wardrobe to be listed and a 15 MB look downloaded on a phone.
ACCOUNT_MAX_TTL_S = 15 * 60
ACCOUNT_MIN_TTL_S = 30
MAX_SLUGS = 32
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
#: An account id as an identity provider states it: opaque, printable, bounded.
_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@|+=/-]{0,127}$")


class GrantError(ValueError):
    pass


@dataclass(frozen=True)
class Grant:
    id: str
    slugs: frozenset[str]
    expires: int
    issued: int
    label: str
    #: AC1. The account this capability was issued to; None for an operator grant.
    subject: str | None = None

    def covers(self, slug: str | None, account: str | None = None) -> bool:
        """Whether this grant reads private looks of ``slug``.

        ``account`` is the account a look's own marker names, when it names one: such a look
        is that account's alone, so an operator grant (no subject) and another account's
        capability do not read it, even for the right avatar.
        """
        if not slug or slug not in self.slugs:
            return False
        return account is None or (self.subject is not None and self.subject == account)

    def to_dict(self) -> dict:
        out = {"id": self.id, "scope": SCOPE, "slugs": sorted(self.slugs), "expires": self.expires,
               "issued": self.issued, "label": self.label}
        if self.subject is not None:
            out["subject"] = self.subject
        return out


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def usable(secret: str | None) -> bool:
    return bool(secret) and len(secret) >= MIN_SECRET_LENGTH


def _sign(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def mint(secret: str, *, slugs, ttl_s: int, label: str = "", now: float | None = None,
         subject: str | None = None) -> tuple[str, Grant]:
    """Sign a grant. With ``subject`` it is an account capability (AC1): shorter-lived, and bound."""
    if not usable(secret):
        raise GrantError(f"grants need WARDROBE_GRANT_SECRET of at least {MIN_SECRET_LENGTH} characters")
    names = sorted({str(s) for s in slugs or []})
    if not names or len(names) > MAX_SLUGS or not all(_SLUG.match(s) for s in names):
        raise GrantError(f"a grant names 1-{MAX_SLUGS} library avatars by slug")
    if subject is None:
        if not (60 <= int(ttl_s) <= MAX_TTL_S or int(ttl_s) == NO_EXPIRY_TTL_S):
            raise GrantError(f"a grant lasts between 60 s and {MAX_TTL_S // 86400} days, or has no expiry")
    else:
        if not isinstance(subject, str) or not _SUBJECT.match(subject):
            raise GrantError("a capability is issued to one account, named by its identity provider")
        if not ACCOUNT_MIN_TTL_S <= int(ttl_s) <= ACCOUNT_MAX_TTL_S:
            raise GrantError(
                f"a capability lasts between {ACCOUNT_MIN_TTL_S} s and {ACCOUNT_MAX_TTL_S // 60} minutes")
    issued = int(now if now is not None else time.time())
    grant = Grant(secrets.token_hex(8), frozenset(names), issued + int(ttl_s), issued, str(label)[:80],
                  subject)
    claims = {"v": VERSION, "scope": SCOPE, "jti": grant.id, "slugs": names, "iat": issued,
              "exp": grant.expires, "label": grant.label}
    if subject is not None:
        claims["sub"] = subject
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
    life = expires - issued
    allowed_life = life <= MAX_TTL_S or life == NO_EXPIRY_TTL_S
    if expires <= current or not allowed_life or grant_id in set(revoked or ()):
        return None
    subject = claims.get("sub")
    if subject is not None:
        # AC1. A token that names an account is a capability, and a capability is short-lived
        # by definition: one with a longer life is refused here even though it is signed, so a
        # misconfigured issuer cannot hand out a month-long token with someone's name on it.
        if not isinstance(subject, str) or not _SUBJECT.match(subject):
            return None
        if expires - issued > ACCOUNT_MAX_TTL_S:
            return None
    return Grant(grant_id, slugs, expires, issued, str(claims.get("label", "")), subject)


__all__ = ["ACCOUNT_MAX_TTL_S", "ACCOUNT_MIN_TTL_S", "HEADER", "MAX_TTL_S", "MIN_SECRET_LENGTH",
           "NO_EXPIRY_TTL_S", "SCOPE",
           "Grant", "GrantError", "mint", "usable", "verify"]
