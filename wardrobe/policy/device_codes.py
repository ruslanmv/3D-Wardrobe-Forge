"""DC1. A short one-time code that carries a read grant to a device where pasting one is impossible.

A read grant (``wardrobe.policy.grants``) is a signed token of well over a hundred characters.
The operator mints it in the Studio and pastes it into the companion app's Settings — which works
on a desktop and does not on a Quest, where the only keyboard is a laser pointer on a floating
panel and a single mistyped character is a token that does not verify. The token itself must not
get shorter: it is short-lived or revocable *because* it is signed, and a short signed token is a
guessable one.

So the token stays as it is and only its delivery changes. The operator asks for a **device code**
instead: six characters such as ``K7P-4QX``, which the person types once on the headset. The app
trades it here (``POST /v1/device-codes/redeem``) for the grant the operator minted, and keeps the
grant exactly as if it had been pasted. The code is:

* **One use.** Redeemed once, it is gone; a second attempt with the same code is refused.
* **Ten minutes.** An unused code is forgotten after ``CODE_TTL_S``; the grant it held was never
  handed to anyone.
* **Hard to guess.** Thirty-one unambiguous symbols (no 0/O, no 1/I/L) to the sixth power is
  about 887 million codes, against a handful pending at once, behind a per-client limit on
  attempts in the route.
* **Never stored as itself.** The store keys on the code's SHA-256, so a dump of this process's
  memory or a log line does not hold a live code.

What a code is not: a new permission. It carries exactly the grant the operator minted, with that
grant's avatars, lifetime and revocability; the grant is still read-only, and none of the other
gates (the operator's switch, the avatar's declaration, a design review, the viewer's own adult
confirmation in the app) moves. The pending codes live in this process's memory: a Space is one
process, and a restart losing an unredeemed code costs one more click in the Studio.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from threading import Lock

#: No 0/O and no 1/I/L: a code read off one screen and typed on another must not be ambiguous.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 6
CODE_TTL_S = 10 * 60
#: More pending codes than any operator issues by hand; a bound so a loop cannot fill memory.
MAX_PENDING = 200


@dataclass
class _Pending:
    token: str
    grant: dict
    expires: float


def normalize(code: str | None) -> str:
    """What the person typed, as the store keys it: upper case, separators and spaces dropped."""
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def formatted(code: str) -> str:
    """``K7P4QX`` → ``K7P-4QX``: the shape shown to the operator, easier to read aloud."""
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}"


def _key(code: str) -> str:
    return hashlib.sha256(normalize(code).encode("ascii", "ignore")).hexdigest()


class DeviceCodes:
    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._pending: dict[str, _Pending] = {}
        self._lock = Lock()

    def _sweep(self, now: float) -> None:
        for key in [k for k, p in self._pending.items() if p.expires <= now]:
            del self._pending[key]

    def issue(self, token: str, grant: dict, ttl_s: int = CODE_TTL_S) -> tuple[str, float]:
        """Hold ``token`` behind a new code; answer the code (unformatted) and when it expires."""
        if not token:
            raise ValueError("a device code needs a grant to carry")
        now = self._clock()
        with self._lock:
            self._sweep(now)
            if len(self._pending) >= MAX_PENDING:
                raise ValueError("too many device codes waiting; let some expire first")
            while True:
                code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
                if _key(code) not in self._pending:
                    break
            expires = now + max(1, min(int(ttl_s), CODE_TTL_S))
            self._pending[_key(code)] = _Pending(token=token, grant=dict(grant), expires=expires)
        return code, expires

    def redeem(self, code: str | None) -> dict | None:
        """The grant this code holds, once; None for an unknown, used or expired code."""
        if len(normalize(code)) != CODE_LENGTH:
            return None
        now = self._clock()
        with self._lock:
            self._sweep(now)
            pending = self._pending.pop(_key(code), None)
        if pending is None:
            return None
        return {"token": pending.token, **pending.grant}

    def pending(self) -> int:
        with self._lock:
            self._sweep(self._clock())
            return len(self._pending)

    def reset(self) -> None:
        with self._lock:
            self._pending.clear()


codes = DeviceCodes()

__all__ = ["ALPHABET", "CODE_LENGTH", "CODE_TTL_S", "DeviceCodes", "codes", "formatted", "normalize"]
