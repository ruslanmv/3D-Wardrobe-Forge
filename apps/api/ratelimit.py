"""F1. A per-client limit and a queue cap on job creation, and nothing else.

F5 lets yourfriend.online call a keyed Space without the key, because a public page
cannot hold one. That keeps other *websites* out; it does not stop one visitor — or
a script sending yourfriend.online's ``Origin`` — from queueing a hundred fits and
holding the Space's two workers for an hour. A fit costs seconds of CPU; reading a
template list costs nothing. So the limit sits on the routes that create a job
(``POST /v1/jobs``, ``/v1/generate``, ``/v1/library/{slug}/jobs``) and never on a
read: a Try-On haul polling its job must not be refused for polling.

Two independent checks, each off at 0:

- ``WARDROBE_RATE_LIMIT_PER_MINUTE``: jobs one client may create in any 60 s. A
  client is its address — the connecting peer, or, behind a proxy that appends to
  ``X-Forwarded-For`` (a Hugging Face Space does), the hop that proxy added, chosen
  with ``WARDROBE_FORWARDED_HOPS``. Never the leftmost entry: the caller writes that.
- ``WARDROBE_QUEUE_CAP``: jobs waiting or running at once, all clients together.
  Past it, a new job would only wait behind the others until its page gave up.

Both answer 429 with ``Retry-After``, so a client can say "try again in a minute"
instead of showing a failure. The window lives in this process's memory: one Space
is one process, and a restart forgetting who asked recently costs nothing.
"""

from __future__ import annotations

import math
import time
from collections import deque
from threading import Lock

from fastapi import HTTPException, Request

from apps.api.dependencies import OrchestratorDep, SettingsDep
from wardrobe.config import Settings

WINDOW_S = 60.0
#: How far back the queue cap looks for unfinished jobs. The queue is first in,
#: first out, so waiting jobs are the newest; one still unfinished behind this
#: many newer jobs has stalled, and counting it would block the Space for good.
QUEUE_SCAN = 200
#: When the queue is full: long enough for a fit to finish, short enough to retry.
QUEUE_RETRY_S = 30


class SlidingWindow:
    """Request times per client over the last ``WINDOW_S`` seconds."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def take(self, client: str, limit: int) -> float:
        """Record one request and answer 0, or refuse and answer seconds until one is allowed."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] >= WINDOW_S:
                hits.popleft()
            if len(hits) >= limit:
                return max(WINDOW_S - (now - hits[0]), 1.0)
            hits.append(now)
            if len(self._hits) > 10_000:
                # A long-lived process sees many addresses once; drop the idle ones.
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= WINDOW_S]:
                    del self._hits[key]
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


window = SlidingWindow()


def client_address(request: Request, settings: Settings) -> str:
    """Who is asking: the peer, or the address a trusted proxy appended for it."""
    hops = settings.wardrobe_forwarded_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.client.host if request.client else "unknown"


def _too_many(detail: str, retry_after: float) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={"reason": "rate_limited", "message": detail},
        headers={"Retry-After": str(math.ceil(retry_after))},
    )


async def limit_job_creation(request: Request, settings: SettingsDep, orchestrator: OrchestratorDep) -> None:
    """The dependency the job-creating routes take. Does nothing unless configured."""
    per_minute = settings.wardrobe_rate_limit_per_minute
    if per_minute > 0:
        wait = window.take(client_address(request, settings), per_minute)
        if wait:
            raise _too_many(f"at most {per_minute} new looks a minute; try again shortly", wait)
    cap = settings.wardrobe_queue_cap
    if cap > 0:
        recent = await orchestrator.list(limit=QUEUE_SCAN)
        if sum(not record.is_terminal for record in recent) >= cap:
            raise _too_many("the wardrobe is busy with other looks; try again shortly", QUEUE_RETRY_S)


__all__ = ["QUEUE_SCAN", "SlidingWindow", "client_address", "limit_job_creation", "window"]
