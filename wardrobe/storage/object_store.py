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
    disk after that. Writes stay local — a look made on demand is there until the Space
    restarts, and the next prebuild makes it permanent. Committing every file from the Space
    would be thousands of commits for one build.

    ``exists`` answers from a listing of the dataset, refreshed every ``LIST_TTL_S`` seconds,
    so a miss costs no request per key. The token is ``HF_TOKEN``; a private dataset needs it.
    """

    LIST_TTL_S = 600.0

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
        self._lock = asyncio.Lock()

    async def _remote_files(self) -> set[str]:
        import time

        async with self._lock:
            if self._remote is None or time.monotonic() - self._listed_at > self.LIST_TTL_S:
                from huggingface_hub import HfApi

                def _list() -> set[str]:
                    return set(HfApi().list_repo_files(self.repo_id, repo_type="dataset"))

                try:
                    self._remote = await asyncio.to_thread(_list)
                except Exception as exc:  # an unreachable dataset is an empty one, not a dead Forge
                    logger.warning("dataset %s could not be listed: %s", self.repo_id, exc)
                    self._remote = self._remote or set()
                self._listed_at = time.monotonic()
            return self._remote

    async def _fetch(self, key: str) -> bool:
        if key not in await self._remote_files():
            return False
        from huggingface_hub import hf_hub_download

        def _download() -> None:
            hf_hub_download(self.repo_id, filename=key, repo_type="dataset", local_dir=str(self.root))

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
