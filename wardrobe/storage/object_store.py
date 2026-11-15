"""Artifact storage: generated VRMs, previews, fit reports and manifests."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from wardrobe.config import Settings
from wardrobe.policy.file_safety import validate_storage_key

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    ".vrm": "model/gltf-binary",
    ".glb": "model/gltf-binary",
    ".json": "application/json",
    ".webp": "image/webp",
    ".png": "image/png",
}


def content_type_for(key: str) -> str:
    return CONTENT_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")


class ObjectStore(ABC):
    """Minimal async object storage interface."""

    @abstractmethod
    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    def url_for(self, key: str) -> str: ...

    async def get_shared(self, key: str) -> bytes | None:
        """RU2. The copy every Forge shares, when this store has one apart from its own (else None).

        Only the dataset store does: there a file this process wrote locally hides the
        dataset's newer copy from ``get``. Small index files read both and merge them.
        """
        return None

    async def put_path(self, key: str, path: str | Path, *, content_type: str | None = None) -> str:
        data = await asyncio.to_thread(Path(path).read_bytes)
        return await self.put(key, data, content_type=content_type)


class LocalObjectStore(ObjectStore):
    """Filesystem-backed store; the default for development and CLI runs."""

    def __init__(self, root: str | Path, settings: Settings | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._settings = settings

    def _path(self, key: str) -> Path:
        validate_storage_key(key)
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"storage key escapes the storage root: {key!r}")
        return path

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Unique per write: two jobs finishing together both write wardrobe.json, and a
            # shared "<name>.part" let one rename the other's temporary away (FileNotFoundError,
            # the look's job failed). The last complete write wins, never a half one.
            temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
            try:
                temporary.write_bytes(data)
                temporary.replace(path)  # atomic publish
            finally:
                temporary.unlink(missing_ok=True)

        await asyncio.to_thread(_write)
        return self.url_for(key)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> bool:
        path = self._path(key)

        def _delete() -> bool:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                return True
            if path.exists():
                path.unlink()
                return True
            return False

        return await asyncio.to_thread(_delete)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)

    def url_for(self, key: str) -> str:
        if self._settings is not None:
            return self._settings.artifact_url(key)
        return f"/v1/assets/{key}"

    def local_path(self, key: str) -> Path:
        """Escape hatch for the Blender worker, which needs real file paths."""
        return self._path(key)


class S3ObjectStore(ObjectStore):
    """S3-compatible store (AWS S3, MinIO, R2).

    ``boto3`` is an optional dependency: install the ``s3`` extra to use this.
    """

    def __init__(self, settings: Settings) -> None:
        try:
            import boto3  # noqa: PLC0415 - optional dependency, imported on use
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise RuntimeError(
                "S3 storage requires boto3; install with: pip install '3d-wardrobe-forge[s3]'"
            ) from exc

        if not settings.s3_bucket:
            raise RuntimeError("S3_BUCKET must be set when WARDROBE_STORAGE_BACKEND=s3")

        self.bucket = settings.s3_bucket
        self.settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        validate_storage_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type or content_type_for(key),
        )
        return self.url_for(key)

    async def get(self, key: str) -> bytes:
        validate_storage_key(key)
        response = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> bool:
        validate_storage_key(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)
        return True

    async def exists(self, key: str) -> bool:
        validate_storage_key(key)
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def url_for(self, key: str) -> str:
        """Pre-signed URL so generated avatars are never world-readable."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.settings.s3_signed_url_ttl_s,
        )


class HfDatasetObjectStore(LocalObjectStore):
    """PB4. Local storage that falls back to a Hugging Face dataset for what it does not have.

    The prebuilt wardrobe (docs/PREBUILT_WARDROBE.md) is ~11.5 GB of looks: too big for git,
    comfortable in a private dataset repository. CI uploads the whole build in one batch; the
    Space reads a file from the dataset the first time it is asked for and keeps it on local
    disk after that. Writes land locally; with ``wardrobe_hf_publish`` (RU3, on by default) each
    look the Space makes — its prebuilt entry, files and wardrobe list — is also committed to
    the dataset in batches (every ``wardrobe_hf_publish_every`` looks or
    ``wardrobe_hf_publish_seconds``, and on shutdown), so it survives a restart and every other
    Forge finds it. Committing every file as it is written would be thousands of commits.

    ``exists`` answers from a listing of the dataset, refreshed every ``LIST_TTL_S`` seconds,
    so a miss costs no request per key. The token is ``HF_TOKEN``; a private dataset needs it.
    """

    LIST_TTL_S = 600.0
    #: After a failed listing, ask again this soon instead of waiting out LIST_TTL_S.
    RETRY_S = 30.0

    def __init__(self, root: str | Path, settings: Settings) -> None:
        super().__init__(root, settings)
        try:
            from huggingface_hub import HfApi  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise RuntimeError(
                "Hugging Face storage requires huggingface_hub; "
                "install with: pip install '3d-wardrobe-forge[hf]'"
            ) from exc
        if not settings.wardrobe_hf_dataset:
            raise RuntimeError("WARDROBE_HF_DATASET must be set when WARDROBE_STORAGE_BACKEND=hf")
        self.repo_id = settings.wardrobe_hf_dataset
        self._remote: set[str] | None = None
        self._listed_at = 0.0
        self._ttl = self.LIST_TTL_S
        self._lock = asyncio.Lock()
        #: RU2. key -> (read at, bytes) for get_shared.
        self._shared: dict[str, tuple[float, bytes]] = {}
        #: RU3. Entries and wardrobe lists written here and not yet in the dataset.
        self.publishing = bool(settings.wardrobe_hf_publish)
        self._publish_every = max(1, int(settings.wardrobe_hf_publish_every))
        self._publish_seconds = max(1.0, float(settings.wardrobe_hf_publish_seconds))
        self._pending_entries: set[str] = set()
        self._pending_lists: set[str] = set()
        self._publish_lock = asyncio.Lock()
        self._timer: asyncio.Task | None = None
        self.published = {"commits": 0, "looks": 0, "failures": 0}

    async def _remote_files(self) -> set[str]:
        import time

        async with self._lock:
            if self._remote is None or time.monotonic() - self._listed_at > self._ttl:
                from huggingface_hub import HfApi

                def _list() -> set[str]:
                    return set(HfApi().list_repo_files(self.repo_id, repo_type="dataset"))

                try:
                    self._remote = await asyncio.to_thread(_list)
                    self._ttl = self.LIST_TTL_S
                except Exception as exc:  # an unreachable dataset is an empty one, not a dead Forge
                    # A blip must not hide the whole dataset for LIST_TTL_S: keep the last good
                    # listing, and ask again after RETRY_S instead of ten minutes.
                    logger.warning("dataset %s could not be listed: %s", self.repo_id, exc)
                    self._remote = self._remote if self._remote is not None else set()
                    self._ttl = self.RETRY_S
                self._listed_at = time.monotonic()
            return self._remote

    async def _fetch(self, key: str) -> bool:
        if key not in await self._remote_files():
            return False
        from huggingface_hub import hf_hub_download

        final = self._path(key)

        def _download() -> None:
            # Into a private folder first, then one rename onto the real path: a download cut off
            # half way can never be served as a 12 MB look that ends early, and a crash leaves
            # nothing under the key — the next request simply downloads again.
            scratch = self.root / ".hf-download" / uuid.uuid4().hex
            try:
                got = hf_hub_download(self.repo_id, filename=key, repo_type="dataset", local_dir=str(scratch))
                final.parent.mkdir(parents=True, exist_ok=True)
                Path(got).replace(final)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)

        try:
            await asyncio.to_thread(_download)
        except Exception as exc:
            logger.warning("dataset file %s could not be downloaded: %s", key, exc)
            return False
        return await super().exists(key)

    async def get(self, key: str) -> bytes:
        if not await super().exists(key):
            await self._fetch(key)
        return await super().get(key)

    async def exists(self, key: str) -> bool:
        if await super().exists(key):
            return True
        return key in await self._remote_files()

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        url = await super().put(key, data, content_type=content_type)
        if self.publishing:
            from wardrobe.storage.dataset_publish import ENTRY, LIST

            if ENTRY.match(key):
                self._pending_entries.add(key)
            elif LIST.match(key):
                self._pending_lists.add(key)
            else:
                return url
            self._schedule()
        return url

    def _schedule(self) -> None:
        """A batch goes up at ``publish_every`` looks, or ``publish_seconds`` after the first."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - put is always awaited inside a loop
            return
        if len(self._pending_entries) >= self._publish_every:
            loop.create_task(self.flush())
        elif self._timer is None or self._timer.done():
            async def _later() -> None:
                await asyncio.sleep(self._publish_seconds)
                await self.flush()

            self._timer = loop.create_task(_later())

    async def flush(self) -> dict | None:
        """RU3. Publish what is pending in one commit. Never raises; a failure stays pending."""
        async with self._publish_lock:
            entries, lists = sorted(self._pending_entries), sorted(self._pending_lists)
            if not entries and not lists:
                return None
            self._pending_entries -= set(entries)
            self._pending_lists -= set(lists)
            from huggingface_hub import HfApi

            from wardrobe.storage.dataset_publish import hub_download, publish

            def _go() -> dict:
                return publish(HfApi(), self.repo_id, self.root, entries=entries, lists=lists,
                               keep_existing=False,
                               message=f"forge: {len(entries)} looks made on demand", download=hub_download())

            try:
                result = await asyncio.to_thread(_go)
            except Exception as exc:
                logger.warning("could not publish %d looks to %s (kept for the next batch): %s",
                               len(entries), self.repo_id, exc)
                self._pending_entries |= set(entries)
                self._pending_lists |= set(lists)
                self.published["failures"] += 1
                return None
            self._pending_lists |= set(result["heldBack"])
            self.published["commits"] += 1 if result["files"] else 0
            self.published["looks"] += len(result["looks"])
            # What just went up exists in the dataset now: no listing round trip to know it.
            if self._remote is not None:
                self._remote |= set(entries) | set(lists)
            for key in lists:
                self._shared.pop(key, None)
            logger.info("published %d looks (%d files) to %s",
                        len(result["looks"]), result["files"], self.repo_id)
            return result

    async def close(self) -> None:
        """RU3. On shutdown: cancel the timer and publish whatever is still pending."""
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        if self.publishing:
            await self.flush()

    async def get_shared(self, key: str) -> bytes | None:
        """RU2. The dataset's own copy of a small file, re-read at most every ``LIST_TTL_S``.

        Downloaded into a private folder and never onto the local path: the local file may be
        newer (a look this Space just made) and the merge, not the download, decides.
        """
        import time

        cached = self._shared.get(key)
        if cached is not None and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        if key not in await self._remote_files():
            return None
        from huggingface_hub import hf_hub_download

        def _download() -> bytes:
            scratch = self.root / ".hf-download" / uuid.uuid4().hex
            try:
                got = hf_hub_download(self.repo_id, filename=key, repo_type="dataset", local_dir=str(scratch))
                return Path(got).read_bytes()
            finally:
                shutil.rmtree(scratch, ignore_errors=True)

        try:
            data = await asyncio.to_thread(_download)
        except Exception as exc:
            logger.warning("dataset copy of %s could not be read: %s", key, exc)
            return cached[1] if cached is not None else None
        self._shared[key] = (time.monotonic(), data)
        return data


def create_object_store(settings: Settings) -> ObjectStore:
    backend = settings.wardrobe_storage_backend.lower()
    if backend == "local":
        return LocalObjectStore(settings.storage_root_path, settings)
    if backend == "s3":
        return S3ObjectStore(settings)
    if backend == "hf":
        return HfDatasetObjectStore(settings.storage_root_path, settings)
    raise ValueError(f"unknown storage backend: {backend!r}")


__all__ = [
    "ObjectStore",
    "LocalObjectStore",
    "S3ObjectStore",
    "HfDatasetObjectStore",
    "create_object_store",
    "content_type_for",
]
