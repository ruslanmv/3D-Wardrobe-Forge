"""Job queue abstraction.

The default is an in-process asyncio worker pool, which is all a single
container needs. Redis is available for multi-worker deployments where the API
and the Blender workers are separate processes.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from wardrobe.config import Settings

logger = logging.getLogger(__name__)

JobHandler = Callable[[str], Awaitable[None]]


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(self, job_id: str) -> None: ...

    @abstractmethod
    async def start(self, handler: JobHandler) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @property
    @abstractmethod
    def depth(self) -> int: ...


class AsyncioJobQueue(JobQueue):
    """Bounded in-process queue with a fixed number of worker tasks."""

    def __init__(self, concurrency: int = 2, max_depth: int = 1000) -> None:
        self.concurrency = max(1, concurrency)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_depth)
        self._workers: list[asyncio.Task] = []
        self._handler: JobHandler | None = None
        self._stopping = False

    async def enqueue(self, job_id: str) -> None:
        if self._handler is None:
            raise RuntimeError("queue has not been started")
        await self._queue.put(job_id)

    async def start(self, handler: JobHandler) -> None:
        if self._workers:
            return
        self._handler = handler
        self._stopping = False
        self._workers = [
            asyncio.create_task(self._run(index), name=f"wardrobe-worker-{index}")
            for index in range(self.concurrency)
        ]
        logger.info("started %d wardrobe worker(s)", self.concurrency)

    async def _run(self, index: int) -> None:
        while not self._stopping:
            try:
                job_id = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                assert self._handler is not None
                await self._handler(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The handler records the failure on the job itself; a worker
                # must never die because one job blew up.
                logger.exception("worker %d failed while processing %s", index, job_id)
            finally:
                self._queue.task_done()

    async def drain(self, timeout: float | None = None) -> None:
        """Wait for the queue to empty — used by tests and the CLI."""
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    async def stop(self) -> None:
        self._stopping = True
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        logger.info("stopped wardrobe workers")

    @property
    def depth(self) -> int:
        return self._queue.qsize()


class RedisJobQueue(JobQueue):
    """Redis list-backed queue for multi-process deployments.

    ``redis`` is an optional dependency: install the ``redis`` extra to use it.
    """

    def __init__(self, url: str, *, key: str = "wardrobe:jobs", concurrency: int = 2) -> None:
        try:
            from redis import asyncio as redis_asyncio  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise RuntimeError(
                "Redis queue requires the redis package; install with: "
                "pip install '3d-wardrobe-forge[redis]'"
            ) from exc

        self._redis = redis_asyncio.from_url(url)
        self._key = key
        self.concurrency = max(1, concurrency)
        self._workers: list[asyncio.Task] = []
        self._handler: JobHandler | None = None
        self._stopping = False

    async def enqueue(self, job_id: str) -> None:
        await self._redis.lpush(self._key, job_id)

    async def start(self, handler: JobHandler) -> None:
        if self._workers:
            return
        self._handler = handler
        self._stopping = False
        self._workers = [asyncio.create_task(self._run()) for _ in range(self.concurrency)]

    async def _run(self) -> None:
        while not self._stopping:
            try:
                item = await self._redis.brpop(self._key, timeout=5)
            except asyncio.CancelledError:
                return
            except Exception:  # pragma: no cover - transient redis outage
                logger.exception("redis queue read failed; retrying")
                await asyncio.sleep(1.0)
                continue
            if not item:
                continue
            job_id = item[1].decode("utf-8") if isinstance(item[1], bytes) else str(item[1])
            try:
                assert self._handler is not None
                await self._handler(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker failed while processing %s", job_id)

    async def stop(self) -> None:
        self._stopping = True
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        await self._redis.aclose()

    @property
    def depth(self) -> int:  # pragma: no cover - requires a live redis
        return -1


def create_job_queue(settings: Settings) -> JobQueue:
    backend = settings.wardrobe_job_backend.lower()
    if backend in {"memory", "asyncio"}:
        return AsyncioJobQueue(concurrency=settings.wardrobe_job_concurrency)
    if backend.startswith("redis"):
        url = backend if backend.startswith("redis://") else "redis://localhost:6379/0"
        return RedisJobQueue(url, concurrency=settings.wardrobe_job_concurrency)
    raise ValueError(f"unknown job backend: {backend!r}")


__all__ = ["JobQueue", "AsyncioJobQueue", "RedisJobQueue", "create_job_queue", "JobHandler"]
