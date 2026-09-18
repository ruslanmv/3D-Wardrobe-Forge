"""In-process publish/subscribe for job progress events.

The API turns these into a Server-Sent Events stream so the chatbot can show
'fitting', 'resolving-clipping', 'rendering-preview' instead of a spinner.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict

from wardrobe.domain.jobs import JobEvent

#: Bound per-subscriber buffers so a stalled browser cannot grow memory forever.
SUBSCRIBER_BUFFER = 64


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = defaultdict(set)
        self._history: dict[str, list[JobEvent]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, job_id: str, event: JobEvent) -> None:
        async with self._lock:
            self._history[job_id].append(event)
            subscribers = list(self._subscribers.get(job_id, ()))

        for queue in subscribers:
            # A slow consumer loses intermediate ticks, never the pipeline.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    async def subscribe(self, job_id: str) -> asyncio.Queue[JobEvent]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=SUBSCRIBER_BUFFER)
        async with self._lock:
            # Replay what already happened so a late subscriber sees the whole run.
            for event in self._history.get(job_id, []):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    break
            self._subscribers[job_id].add(queue)
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEvent]) -> None:
        async with self._lock:
            self._subscribers.get(job_id, set()).discard(queue)
            if not self._subscribers.get(job_id):
                self._subscribers.pop(job_id, None)

    async def forget(self, job_id: str) -> None:
        async with self._lock:
            self._history.pop(job_id, None)
            self._subscribers.pop(job_id, None)

    def history(self, job_id: str) -> list[JobEvent]:
        return list(self._history.get(job_id, []))


broker = EventBroker()

__all__ = ["EventBroker", "broker", "SUBSCRIBER_BUFFER"]
