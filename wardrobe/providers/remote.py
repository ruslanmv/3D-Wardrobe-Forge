"""Shared plumbing for remote AI mesh providers.

Every provider in this family follows the same shape: submit a task, poll until
it succeeds, download a GLB. Response payloads differ, so each adapter supplies
its own small extraction functions and the polling/retry/limit logic lives here.

These adapters are the *experimental* path. Their request and response shapes
are pinned by the nightly provider smoke workflow rather than assumed to be
stable, and every field lookup below tolerates several spellings.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from wardrobe.errors import ProviderError

logger = logging.getLogger(__name__)

#: Terminal task states, lower-cased, across the providers we support.
SUCCESS_STATES = {"succeeded", "success", "completed", "done", "finished"}
FAILURE_STATES = {"failed", "error", "cancelled", "canceled", "banned", "expired", "unknown"}


@dataclass(slots=True)
class RemoteTask:
    task_id: str
    status: str = "pending"
    progress: float = 0.0
    model_url: str | None = None
    raw: dict[str, Any] | None = None


def dig(payload: Any, *paths: tuple[str, ...], default: Any = None) -> Any:
    """Return the first value found at any of the given key paths."""
    for path in paths:
        cursor: Any = payload
        for key in path:
            if isinstance(cursor, dict) and key in cursor:
                cursor = cursor[key]
            else:
                cursor = None
                break
        if cursor is not None:
            return cursor
    return default


class RemoteMeshClient:
    """Submit-and-poll HTTP client shared by the AI mesh providers."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        provider: str,
        timeout_s: float = 600.0,
        poll_interval_s: float = 5.0,
        max_download_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        if not api_key:
            raise ProviderError(f"{provider} is enabled but no API key is configured")
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.max_download_bytes = max_download_bytes
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(60.0),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def post_json(self, path: str, payload: dict) -> dict:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.provider}: request failed: {exc}") from exc
        return self._json_or_raise(response, path)

    async def get_json(self, path: str) -> dict:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.provider}: request failed: {exc}") from exc
        return self._json_or_raise(response, path)

    def _json_or_raise(self, response: httpx.Response, path: str) -> dict:
        if response.status_code >= 400:
            # Provider error bodies can be large and may echo the prompt back.
            raise ProviderError(
                f"{self.provider}: {path} returned HTTP {response.status_code}",
                detail={"body": response.text[:500]},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.provider}: {path} returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise ProviderError(
                f"{self.provider}: {path} returned {type(payload).__name__}, expected an object"
            )
        return payload

    async def poll(
        self,
        status_path: Callable[[], str],
        parse: Callable[[dict], RemoteTask],
        *,
        on_progress: Callable[[RemoteTask], None] | None = None,
    ) -> RemoteTask:
        """Poll until the task reaches a terminal state or the deadline passes."""
        deadline = asyncio.get_running_loop().time() + self.timeout_s
        interval = self.poll_interval_s

        while True:
            task = parse(await self.get_json(status_path()))
            status = (task.status or "").lower()

            if on_progress is not None:
                on_progress(task)

            if status in SUCCESS_STATES:
                return task
            if status in FAILURE_STATES:
                raise ProviderError(
                    f"{self.provider}: task {task.task_id} ended in state {task.status!r}",
                    detail={"task": task.raw or {}},
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise ProviderError(
                    f"{self.provider}: task {task.task_id} did not finish within {self.timeout_s:.0f}s"
                )

            await asyncio.sleep(interval)
            interval = min(interval * 1.25, 20.0)  # back off on long generations

    async def download(self, url: str) -> bytes:
        """Fetch the produced GLB, refusing anything oversized."""
        chunks: list[bytes] = []
        total = 0
        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise ProviderError(
                        f"{self.provider}: model download returned HTTP {response.status_code}"
                    )
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.max_download_bytes:
                        raise ProviderError(
                            f"{self.provider}: generated model exceeds {self.max_download_bytes} bytes"
                        )
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.provider}: model download failed: {exc}") from exc
        return b"".join(chunks)


__all__ = ["RemoteMeshClient", "RemoteTask", "dig", "SUCCESS_STATES", "FAILURE_STATES"]
