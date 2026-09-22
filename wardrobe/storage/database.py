"""Job and wardrobe repositories.

Two implementations ship today: in-memory (tests, single-process dev) and
JSON-on-disk (durable across restarts, good enough for a single worker host).
PostgreSQL slots in behind the same two interfaces — see docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path

from wardrobe.config import Settings
from wardrobe.domain.jobs import JobRecord
from wardrobe.domain.manifests import WardrobeManifest
from wardrobe.policy.file_safety import sanitize_component


class JobRepository(ABC):
    @abstractmethod
    async def save(self, record: JobRecord) -> None: ...

    @abstractmethod
    async def get(self, job_id: str) -> JobRecord | None: ...

    @abstractmethod
    async def list(self, *, limit: int = 50) -> list[JobRecord]: ...


class WardrobeRepository(ABC):
    @abstractmethod
    async def save(self, manifest: WardrobeManifest) -> None: ...

    @abstractmethod
    async def get(self, avatar_id: str) -> WardrobeManifest | None: ...

    @abstractmethod
    async def list(self) -> list[str]: ...


# ----------------------------------------------------------------------
# in-memory
# ----------------------------------------------------------------------
class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()

    async def save(self, record: JobRecord) -> None:
        async with self._lock:
            self._jobs[record.id] = record

    async def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def list(self, *, limit: int = 50) -> list[JobRecord]:
        records = sorted(self._jobs.values(), key=lambda r: r.created_at, reverse=True)
        return records[:limit]


class InMemoryWardrobeRepository(WardrobeRepository):
    def __init__(self) -> None:
        self._wardrobes: dict[str, WardrobeManifest] = {}
        self._lock = asyncio.Lock()

    async def save(self, manifest: WardrobeManifest) -> None:
        async with self._lock:
            self._wardrobes[manifest.avatar_id] = manifest

    async def get(self, avatar_id: str) -> WardrobeManifest | None:
        return self._wardrobes.get(avatar_id)

    async def list(self) -> list[str]:
        return sorted(self._wardrobes)


# ----------------------------------------------------------------------
# JSON on disk
# ----------------------------------------------------------------------
class JsonFileJobRepository(JobRepository):
    """Durable job records, one file per job."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()

    def _path(self, job_id: str) -> Path:
        return self.root / f"{sanitize_component(job_id, fallback='job')}.json"

    async def save(self, record: JobRecord) -> None:
        async with self._lock:
            self._cache[record.id] = record
            payload = record.model_dump_json(by_alias=True, indent=2)
            path = self._path(record.id)

            def _write() -> None:
                temporary = path.with_suffix(".json.part")
                temporary.write_text(payload, encoding="utf-8")
                temporary.replace(path)

            await asyncio.to_thread(_write)

    async def get(self, job_id: str) -> JobRecord | None:
        if job_id in self._cache:
            return self._cache[job_id]
        path = self._path(job_id)
        if not path.exists():
            return None
        payload = await asyncio.to_thread(path.read_text, "utf-8")
        record = JobRecord.model_validate_json(payload)
        self._cache[job_id] = record
        return record

    async def list(self, *, limit: int = 50) -> list[JobRecord]:
        paths = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        records: list[JobRecord] = []
        for path in paths[:limit]:
            try:
                records.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue  # a partially written record must not break listing
        return records


class JsonFileWardrobeRepository(WardrobeRepository):
    """Durable wardrobe manifests, one file per avatar."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _path(self, avatar_id: str) -> Path:
        return self.root / f"{sanitize_component(avatar_id, fallback='avatar')}.json"

    async def save(self, manifest: WardrobeManifest) -> None:
        async with self._lock:
            payload = manifest.model_dump_json(by_alias=True, indent=2)
            path = self._path(manifest.avatar_id)

            def _write() -> None:
                temporary = path.with_suffix(".json.part")
                temporary.write_text(payload, encoding="utf-8")
                temporary.replace(path)

            await asyncio.to_thread(_write)

    async def get(self, avatar_id: str) -> WardrobeManifest | None:
        path = self._path(avatar_id)
        if not path.exists():
            return None
        payload = await asyncio.to_thread(path.read_text, "utf-8")
        try:
            return WardrobeManifest.model_validate_json(payload)
        except ValueError:
            return None

    async def list(self) -> list[str]:
        manifests: list[str] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(data, dict) and data.get("avatarId"):
                manifests.append(str(data["avatarId"]))
        return manifests


def create_repositories(settings: Settings) -> tuple[JobRepository, WardrobeRepository]:
    """Pick repositories to match the configured job backend."""
    if settings.wardrobe_job_backend.lower() == "memory":
        return InMemoryJobRepository(), InMemoryWardrobeRepository()

    root = settings.storage_root_path / "state"
    return JsonFileJobRepository(root / "jobs"), JsonFileWardrobeRepository(root / "wardrobes")


__all__ = [
    "JobRepository",
    "WardrobeRepository",
    "InMemoryJobRepository",
    "InMemoryWardrobeRepository",
    "JsonFileJobRepository",
    "JsonFileWardrobeRepository",
    "create_repositories",
]
