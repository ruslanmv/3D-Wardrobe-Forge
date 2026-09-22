"""Standalone worker process.

The API can run jobs in-process (the default for a single container). For a
split deployment — a light API and one or more heavy Blender workers — run this
against a shared Redis queue and shared storage::

    WARDROBE_JOB_BACKEND=redis://redis:6379/0 python -m worker.runner
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from wardrobe.config import get_settings
from wardrobe.engines import BlenderEngine
from wardrobe.pipeline.orchestrator import Orchestrator

logger = logging.getLogger("wardrobe.worker")


async def serve() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.app_log_level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )

    orchestrator = Orchestrator(settings=settings)
    await orchestrator.start()

    logger.info(
        "worker ready: engine=%s blender=%s provider=%s templates=%d storage=%s",
        settings.wardrobe_engine,
        BlenderEngine.available(settings),
        settings.wardrobe_provider,
        len(orchestrator.catalog),
        settings.wardrobe_storage_backend,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        # Signal handlers are unavailable on Windows; the worker still runs.
        with contextlib.suppress(AttributeError, NotImplementedError):
            loop.add_signal_handler(getattr(signal, signal_name), stop.set)

    try:
        await stop.wait()
    finally:
        logger.info("shutting down; waiting for in-flight jobs")
        await orchestrator.stop()


def main() -> int:
    with contextlib.suppress(KeyboardInterrupt):  # pragma: no cover - interactive use
        asyncio.run(serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
