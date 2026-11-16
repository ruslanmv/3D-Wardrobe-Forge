"""AC1. Who is asking: the interface an identity provider plugs into, and nothing that pretends to be one.

A read grant (``wardrobe.policy.grants``) says which avatars' private looks a token reads. Before
AC1 only the operator minted one, in an admin session, for whoever would end up holding it: a
deployment of the companion app, for up to thirty days. Put in a web page's configuration that is
one shared credential in every visitor's browser. What a person signed in to the app should hold
is a token made for *them*, for the avatars *they* may see, for minutes.

Forge has no user accounts and this module does not invent any. It defines the seam:

* ``IdentityVerifier`` — given the credential a request carries, answer who it is (an
  ``Identity``) or None. The deployment supplies the implementation
  (``WARDROBE_IDENTITY_VERIFIER``): its identity provider's token check, or the built-in
  ``AssertionVerifier`` for a backend that already knows its signed-in users.
* ``Identity`` — the account, the avatars it is entitled to, and whether the provider vouches
  that the person is an adult. All three come from the verifier; none from the request body.
* ``authorize`` — the rule that turns a verified identity and a requested avatar into yes or no.

**Deny by default, at every step.** No verifier configured: no capabilities at all (the operator
grants of BI2 keep working). A verifier that cannot be loaded, or raises, or answers anything but
an ``Identity``: nobody. An identity without the avatar, or not vouched adult: refused, and the
whole request with it; a capability is never issued for a subset of what was asked.

``AssertionVerifier`` is the one implementation shipped, because it is the integration most
deployments have: the app's own server authenticates the person (however it does) and signs a
short statement about them with a secret that server and Forge share and no browser ever sees.
It is HMAC-SHA256 over a compact JWS, one algorithm, no negotiation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import inspect
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

HEADER = "X-Wardrobe-Identity"
MIN_SECRET_LENGTH = 32
#: An assertion is a statement about a request being made now, not a session.
ASSERTION_MAX_TTL_S = 5 * 60
#: Clocks on two servers disagree a little; an assertion from slightly in the future is not forged.
CLOCK_SKEW_S = 30
MAX_AVATARS = 32
MAX_CREDENTIAL_CHARS = 8192
_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@|+=/-]{0,127}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class Identity:
    """A verified account, as its identity provider described it."""

    #: The provider's stable id for the account. Opaque here; never an email typed by a user.
    subject: str
    #: Library avatars whose private looks this account may read.
    avatars: frozenset[str] = frozenset()
    #: The provider vouches that this person is an adult. Private looks are adult material;
    #: without this no capability is issued, whatever else the identity says.
    adult: bool = False
    issuer: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not _SUBJECT.match(self.subject):
            raise ValueError("an identity names one account by a stable, printable id")
        object.__setattr__(self, "avatars", frozenset(str(a) for a in self.avatars))
        object.__setattr__(self, "adult", self.adult is True)


@runtime_checkable
class IdentityVerifier(Protocol):
    """What a deployment implements. ``verify`` answers an ``Identity`` or None, and may be async.

    It is handed only the credential (the ``X-Wardrobe-Identity`` header). It must not trust
    anything else the browser says, must not raise for a bad credential (None is the answer),
    and must never return an identity for a credential it could not fully check.
    """

    #: Whether this verifier can verify anyone. False: capabilities are unavailable (503).
    configured: bool

    def verify(self, credential: str | None) -> Identity | None: ...


class DenyAll:
    """No identity provider: nobody is anybody. The default, and what every failure falls back to."""

    configured = False

    def __init__(self, reason: str = "no identity verifier is configured") -> None:
        self.reason = reason

    def verify(self, credential: str | None) -> Identity | None:
        return None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class AssertionVerifier:
    """A trusted backend's signed statement about its signed-in user (HS256 compact JWS).

    Claims, all required unless noted:

        iss   the backend, one of ``issuers``            aud   ``audience`` (this Forge)
        sub   the account id                             iat, exp   at most ASSERTION_MAX_TTL_S apart
        avatars   list of library slugs the account may read private looks of
        adult     true when the backend has verified the person is an adult (default false)

    Refused (None), never an error: a missing or oversized credential, anything but three
    segments, a header that names another algorithm (``none`` included), a signature that does
    not match, an expired or not-yet-valid or over-long assertion, a wrong audience or issuer,
    or claims of the wrong shape. The secret is the backend's and Forge's; it is not the grant
    secret (``load_verifier`` refuses to start with the two equal) and it is never sent anywhere.
    """

    configured = True

    def __init__(self, secret: str, *, audience: str, issuers=()) -> None:
        if not secret or len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"the identity secret must be at least {MIN_SECRET_LENGTH} characters")
        if not audience:
            raise ValueError("an audience is required: an assertion for another service is not for this one")
        self._secret = secret.encode("utf-8")
        self.audience = audience
        self.issuers = frozenset(issuers)

    def _signature(self, signed: str) -> str:
        return _b64(hmac.new(self._secret, signed.encode("ascii"), hashlib.sha256).digest())

    def verify(self, credential: str | None, *, now: float | None = None) -> Identity | None:
        if not credential or len(credential) > MAX_CREDENTIAL_CHARS or credential.count(".") != 2:
            return None
        head, body, signature = credential.split(".")
        try:
            header = json.loads(_unb64(head))
            if not isinstance(header, dict) or header.get("alg") != "HS256":
                return None
            if not hmac.compare_digest(signature, self._signature(f"{head}.{body}")):
                return None
            claims = json.loads(_unb64(body))
        except (ValueError, UnicodeError):
            return None
        if not isinstance(claims, dict):
            return None
        current = now if now is not None else time.time()
        try:
            issued, expires = int(claims["iat"]), int(claims["exp"])
            subject, avatars = claims["sub"], claims["avatars"]
        except (KeyError, TypeError, ValueError):
            return None
        if expires <= current or issued > current + CLOCK_SKEW_S:
            return None
        if not 0 < expires - issued <= ASSERTION_MAX_TTL_S:
            return None
        if claims.get("aud") != self.audience:
            return None
        issuer = claims.get("iss")
        if not isinstance(issuer, str) or (self.issuers and issuer not in self.issuers):
            return None
        if not isinstance(avatars, list) or len(avatars) > MAX_AVATARS:
            return None
        if not all(isinstance(a, str) and _SLUG.match(a) for a in avatars):
            return None
        try:
            return Identity(subject=subject, avatars=frozenset(avatars), adult=claims.get("adult") is True,
                            issuer=issuer)
        except ValueError:
            return None

    @staticmethod
    def sign(secret: str, claims: dict) -> str:
        """What the trusted backend does, in one place so its tests and Forge's agree on the format.

        Never called by Forge's request path: Forge only verifies.
        """
        head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
        body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        mac = hmac.new(secret.encode("utf-8"), f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
        return f"{head}.{body}.{_b64(mac)}"


def load_verifier(settings) -> IdentityVerifier:
    """The verifier ``WARDROBE_IDENTITY_VERIFIER`` names. Anything wrong with it: ``DenyAll``, logged.

    ``""`` (default): none. ``"assertion"``: ``AssertionVerifier`` from the identity settings.
    ``"package.module:factory"``: ``factory(settings)`` must return an object with ``verify`` and a
    true ``configured``. A deployment that misspells its verifier gets no capabilities, not open ones.
    """
    spec = (getattr(settings, "wardrobe_identity_verifier", "") or "").strip()
    if not spec:
        return DenyAll()
    try:
        if spec == "assertion":
            secret = settings.wardrobe_identity_secret
            if secret and secret == getattr(settings, "wardrobe_grant_secret", ""):
                raise ValueError("WARDROBE_IDENTITY_SECRET must differ from WARDROBE_GRANT_SECRET: whoever "
                                 "can state identities must not be able to sign grants directly")
            issuers = frozenset(i.strip() for i in settings.wardrobe_identity_issuers.split(",") if i.strip())
            return AssertionVerifier(secret, audience=settings.wardrobe_identity_audience, issuers=issuers)
        module_name, _, attribute = spec.partition(":")
        if not module_name or not attribute:
            raise ValueError("expected 'assertion' or 'package.module:factory'")
        verifier = getattr(importlib.import_module(module_name), attribute)(settings)
        configured = getattr(verifier, "configured", False) is True
        if not configured or not callable(getattr(verifier, "verify", None)):
            raise ValueError("the factory must return a verifier with verify() and configured = True")
        return verifier
    except Exception as exc:  # noqa: BLE001 - whatever is wrong, the answer is nobody
        logger.error("identity verifier %r could not be loaded (%s); account capabilities are off", spec, exc)
        return DenyAll(f"the configured identity verifier could not be loaded: {exc}")


async def identify(verifier: IdentityVerifier, credential: str | None) -> Identity | None:
    """Ask the verifier, sync or async, and accept only an ``Identity``. A verifier that raises is a no."""
    try:
        answer = verifier.verify(credential)
        if inspect.isawaitable(answer):
            answer = await answer
    except Exception as exc:  # noqa: BLE001
        logger.warning("the identity verifier failed (%s); the request is unverified", type(exc).__name__)
        return None
    return answer if isinstance(answer, Identity) else None


def authorize(identity: Identity, slug: str) -> tuple[bool, str]:
    """May this verified account read ``slug``'s private looks? (allowed, reason when not)."""
    if not identity.adult:
        return False, "adult_verification_required"
    if slug not in identity.avatars:
        return False, "not_entitled"
    return True, ""


__all__ = ["ASSERTION_MAX_TTL_S", "HEADER", "AssertionVerifier", "DenyAll", "Identity", "IdentityVerifier",
           "authorize", "identify", "load_verifier"]
