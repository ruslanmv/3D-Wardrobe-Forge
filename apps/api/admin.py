"""The Studio's admin session: the operator signs in and makes adult declarations for that session.

Swimwear, underwear, see-through fabric and suspender hosiery need the avatar
declared as depicting an adult (``wardrobe.policy.intimate``). For a library
avatar the declaration was only ever ``assets/library/policy.json``: an edit, a
commit and a redeploy, and then it held for every visitor of a public Space. The
operator of a public demo wants neither — the declaration for themselves, now,
and nobody else shown what it unlocked.

A session is that, and deliberately no more:

* **It is a declaration, per avatar, made by a person.** Signing in unlocks
  nothing. The operator turns on "this avatar depicts an adult" for a specific
  avatar, and each one is logged. There is no switch that turns the gate off:
  the gate still runs on every garment, the model's own terms (a VRM that says
  ``sexualUssageName: Disallow``) are still checked first and still win, and an
  avatar nobody declared is refused exactly as before.
* **It lasts as long as the session.** Nothing is written to ``policy.json``.
  Signing out, expiry or a restart drops every declaration made in it.
* **What it makes is private.** A job that relied on a session's declaration is
  ``JobOptions.private``: its record, its look, its files and its place in the
  wardrobe and the export are shown to an admin session and to no one else
  (the routes check ``current_admin``; ``/v1/assets`` checks a marker stored
  beside the look's files, so it outlives a restart on persistent storage).

The password is ``WARDROBE_ADMIN_PASSWORD``, a secret. Unset — the default — there
is no admin at all and the Studio offers no sign-in; shorter than
``MIN_PASSWORD_LENGTH`` it is refused with a warning rather than guarding a public
Space with something guessable. Tokens are random, held only as their SHA-256,
and failed sign-ins are throttled per client.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header

from wardrobe.config import get_settings

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 12
#: Failed sign-ins allowed per client within the window before it must wait.
MAX_FAILURES = 5
FAILURE_WINDOW_S = 15 * 60
#: The request header a Studio in an admin session sends its token in. Not
#: ``Authorization``: that is the API key's, and a keyed Space needs both.
HEADER = "X-Wardrobe-Admin"


class AdminError(Exception):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message


@dataclass
class AdminSession:
    token_hash: str
    expires_at: float
    #: Library slugs this session has declared as depicting an adult.
    declared: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "expiresAt": datetime.fromtimestamp(self.expires_at, UTC).isoformat(),
            "declared": sorted(self.declared),
        }


class AdminSessions:
    def __init__(
        self,
        password: str,
        ttl_hours: float = 8.0,
        clock: Callable[[], float] = time.time,
        username: str = "admin",
    ):
        self.problem: str | None = None
        #: Why log-in is off, as a code the Studio can explain: not_configured | password_too_short.
        self.reason: str | None = None
        if not password:
            self.problem, self.reason = "WARDROBE_ADMIN_PASSWORD is not set", "not_configured"
        elif len(password) < MIN_PASSWORD_LENGTH:
            self.problem = f"WARDROBE_ADMIN_PASSWORD is shorter than {MIN_PASSWORD_LENGTH} characters"
            self.reason = "password_too_short"
            logger.warning("admin sign-in disabled: %s", self.problem)
        self._password = password.encode("utf-8") if self.problem is None else b""
        self.username = (username or "admin").strip()
        self._ttl_s = max(ttl_hours, 0.05) * 3600
        self._clock = clock
        self._sessions: dict[str, AdminSession] = {}
        self._failures: dict[str, list[float]] = {}

    @property
    def enabled(self) -> bool:
        return self.problem is None

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def sign_in(
        self, password: str, client: str = "?", username: str | None = None
    ) -> tuple[str, AdminSession]:
        if not self.enabled:
            raise AdminError(404, "admin_disabled", "this deployment has no admin")
        now = self._clock()
        recent = [t for t in self._failures.get(client, []) if now - t < FAILURE_WINDOW_S]
        self._failures[client] = recent
        if len(recent) >= MAX_FAILURES:
            raise AdminError(429, "too_many_attempts", "too many failed sign-ins; wait and try again")
        # Both compared in constant time, and both always compared, so neither the
        # answer nor its timing says which one was wrong. None (an API caller that
        # sends only a password) is taken as the configured name.
        name = self.username if username is None else username.strip()
        name_ok = secrets.compare_digest(name.encode("utf-8"), self.username.encode("utf-8"))
        password_ok = secrets.compare_digest(password.encode("utf-8"), self._password)
        if not (name_ok and password_ok):
            recent.append(now)
            logger.warning("admin sign-in failed from %s", client)
            raise AdminError(401, "wrong_credentials", "Wrong username or password")
        self._failures.pop(client, None)
        token = secrets.token_urlsafe(32)
        session = AdminSession(token_hash=self._hash(token), expires_at=now + self._ttl_s)
        self._sessions[session.token_hash] = session
        logger.info("admin signed in from %s", client)
        return token, session

    def session(self, token: str | None) -> AdminSession | None:
        if not token or not self.enabled:
            return None
        now = self._clock()
        for key in [k for k, s in self._sessions.items() if s.expires_at <= now]:
            del self._sessions[key]
        return self._sessions.get(self._hash(token))

    def sign_out(self, token: str | None) -> None:
        if token:
            self._sessions.pop(self._hash(token), None)

    def declare(self, session: AdminSession, slug: str, depicts_adult: bool) -> None:
        if depicts_adult:
            session.declared.add(slug)
        else:
            session.declared.discard(slug)
        logger.info("admin session %s: %s %s as depicting an adult",
                    session.token_hash[:8], "declared" if depicts_adult else "withdrew", slug)


@lru_cache(maxsize=1)
def get_admin_sessions() -> AdminSessions:
    settings = get_settings()
    return AdminSessions(
        settings.wardrobe_admin_password,
        settings.wardrobe_admin_session_hours,
        username=settings.wardrobe_admin_username,
    )


def admin_sessions_dependency() -> AdminSessions:
    return get_admin_sessions()


AdminSessionsDep = Annotated[AdminSessions, Depends(admin_sessions_dependency)]


def current_admin(
    admins: AdminSessionsDep,
    x_wardrobe_admin: Annotated[str | None, Header()] = None,
) -> AdminSession | None:
    """The request's admin session, or None. Routes decide what None costs."""
    return admins.session(x_wardrobe_admin)


AdminDep = Annotated[AdminSession | None, Depends(current_admin)]


__all__ = [
    "HEADER",
    "MIN_PASSWORD_LENGTH",
    "AdminError",
    "AdminSession",
    "AdminSessions",
    "AdminSessionsDep",
    "AdminDep",
    "get_admin_sessions",
    "admin_sessions_dependency",
    "current_admin",
]
