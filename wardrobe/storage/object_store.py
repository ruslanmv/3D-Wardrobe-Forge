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

    async def read_shared(self, key: str) -> bytes | None:
        """WD1. ``get_shared`` for a file that decides whether something is served.

        ``get_shared`` answers None both when there is no shared copy and when there is one
        that could not be read, which is right for a list (the local one is merged alone) and
        wrong for a withdrawal receipt: "could not ask" must not read as "not withdrawn".
        This raises when the shared copy exists and no reading of it is to be had.
        """
        return None

    async def read_versioned(self, key: str) -> tuple[bytes | None, str | None] | None:
        """AC1. ``(bytes, version)`` for a store that can write on condition, else None.

        A store shared by several processes with no disk between them (S3) cannot take a
        lock file. What it can do is refuse a write when the object changed since it was
        read: ``put_if_unchanged`` with the version returned here. ``(None, None)`` is "no
        such object". None means this store has no such thing (it has a disk: lock that).
        """
        return None

    async def put_if_unchanged(self, key: str, data: bytes, version: str | None, *,
                               content_type: str | None = None) -> bool:
        """Write ``data`` only if the object is still the ``version`` read. False: it changed."""
        raise NotImplementedError

    async def put_path(self, key: str, path: str | Path, *, content_type: str | None = None) -> str:
        data = await asyncio.to_thread(Path(path).read_bytes)
        return await self.put(key, data, content_type=content_type)

    async def list_keys(self, prefix: str) -> list[str]:
        """WD1. Every key under ``prefix`` (a folder, no trailing slash needed), sorted.

        Only what a withdrawal needs: the receipts under ``withdrawn/``. A store that cannot
        list answers with nothing, which costs the startup sweep its work and nothing else.
        """
        return []

    async def _remove(self, keys: list[str]) -> list[str]:
        """Delete each of ``keys`` here and return the ones that are still stored afterwards.

        ``delete`` returning is not the file being gone: each key is checked, and a check that
        fails counts as still there.
        """
        remaining = []
        for key in keys:
            try:
                if await self.exists(key):
                    await self.delete(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not delete %s: %s", key, exc)
            try:
                still = await self.exists(key)
            except Exception:  # noqa: BLE001 - cannot confirm it is gone: treat it as there
                still = True
            if still:
                remaining.append(key)
        return remaining

    async def purge(self, keys: list[str], *, then: list[str] | None = None,
                    replace: dict[str, bytes] | None = None,
                    unlist: dict[str, str] | None = None) -> list[str]:
        """WD1. Delete ``keys`` from every place this store keeps them, then ``then``, then write ``replace``.

        Returns what is **not done**: the ``keys`` that could not be confirmed gone; or, when
        those are all gone, the ``then`` keys that remain; or, when everything is gone, the
        replacement keys that could not be written. Empty means the whole step happened.
        Three rules a withdrawal stands on:

        * **Guards go last.** ``then`` (the private marker) is touched only once every one of
          ``keys`` is confirmed gone, so a file that will not delete keeps what protects it.
        * **Confirmed, not assumed.** Each key is checked after its deletion.
        * **Replacements only after.** ``replace`` (the final receipt) is written only when
          nothing remains, so a receipt never says "withdrawn" over files still stored.

        ``unlist`` (list key -> look id) names the shared lists the look must leave. A store
        with one copy of everything has nothing to do with it: its list is the caller's to
        rewrite. The dataset store rewrites the dataset's copy in the same commit.

        Safe to repeat: deleting what is gone and rewriting the same bytes change nothing.
        """
        remaining = await self._remove(list(keys)) or await self._remove(list(then or []))
        if remaining:
            return remaining
        unwritten = []
        for key, data in (replace or {}).items():
            try:
                await self.put(key, data, content_type=content_type_for(key))
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not write %s: %s", key, exc)
                unwritten.append(key)
        return unwritten


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

    async def list_keys(self, prefix: str) -> list[str]:
        folder = self._path(prefix.rstrip("/"))

        def _list() -> list[str]:
            if not folder.is_dir():
                return []
            root = self.root.resolve()
            done = [p for p in folder.rglob("*") if p.is_file() and not p.name.endswith(".part")]
            return sorted(p.resolve().relative_to(root).as_posix() for p in done)

        return await asyncio.to_thread(_list)

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

    @staticmethod
    def _refusal(exc: Exception) -> tuple[str, int]:
        """The error code and HTTP status of a botocore ``ClientError``, without importing it."""
        response = getattr(exc, "response", None) or {}
        code = str((response.get("Error") or {}).get("Code") or "")
        return code, int((response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)

    async def read_versioned(self, key: str) -> tuple[bytes | None, str | None] | None:
        validate_storage_key(key)
        try:
            response = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        except Exception as exc:
            code, http = self._refusal(exc)
            if code in ("NoSuchKey", "404") or http == 404:
                return None, None
            raise
        return await asyncio.to_thread(response["Body"].read), response.get("ETag")

    async def put_if_unchanged(self, key: str, data: bytes, version: str | None, *,
                               content_type: str | None = None) -> bool:
        """AC1. S3's conditional write: ``If-Match`` the ETag read, or ``If-None-Match: *`` for
        an object that was not there. AWS S3, R2 and current MinIO honour both; a service that
        ignores them accepts the write, which is what an unconditional ``put`` did before."""
        validate_storage_key(key)
        condition = {"IfMatch": version} if version else {"IfNoneMatch": "*"}
        try:
            await asyncio.to_thread(
                self._client.put_object, Bucket=self.bucket, Key=key, Body=data,
                ContentType=content_type or content_type_for(key), **condition)
        except Exception as exc:
            code, http = self._refusal(exc)
            if code in ("PreconditionFailed", "ConditionalRequestConflict") or http in (409, 412):
                return False
            raise
        return True

    async def list_keys(self, prefix: str) -> list[str]:
        validate_storage_key(prefix.rstrip("/"))

        def _list() -> list[str]:
            pages = self._client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix.rstrip("/") + "/")
            return sorted(item["Key"] for page in pages for item in page.get("Contents", []))

        return await asyncio.to_thread(_list)

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
        #: WD1. The last attempt to list the dataset failed: ``_remote`` is the listing before it.
        self._list_stale = False
        self._lock = asyncio.Lock()
        #: RU2. key -> (read at, bytes) for get_shared.
        self._shared: dict[str, tuple[float, bytes]] = {}
        #: WD1. key -> when its shared copy last could not be read (asked again after RETRY_S).
        self._shared_failed: dict[str, float] = {}
        #: RU3. Entries and wardrobe lists written here and not yet in the dataset.
        self.publishing = bool(settings.wardrobe_hf_publish)
        self._publish_every = max(1, int(settings.wardrobe_hf_publish_every))
        self._publish_seconds = max(1.0, float(settings.wardrobe_hf_publish_seconds))
        self._pending_entries: set[str] = set()
        self._pending_lists: set[str] = set()
        #: WD1. Withdrawal receipts written here and not yet in the dataset.
        self._pending_receipts: set[str] = set()
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
                    self._list_stale = False
                except Exception as exc:  # an unreachable dataset is an empty one, not a dead Forge
                    self._list_stale = True
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
            from wardrobe.storage.withdrawals import RECEIPT

            if ENTRY.match(key):
                self._pending_entries.add(key)
            elif LIST.match(key):
                self._pending_lists.add(key)
            elif RECEIPT.match(key):
                # WD1. A receipt is the only thing that keeps a withdrawn look withdrawn after
                # this disk is gone, so it goes up with the next batch like a list does.
                self._pending_receipts.add(key)
            elif key == "access/revocations.json":
                # CG8. A revoked grant must stay revoked after a restart wipes this disk: the
                # list goes up at once, on its own (rare, small, and a no-expiry grant depends
                # on it). load() reads it back from the dataset when the disk has none.
                await self._upload_now(key)
                return url
            else:
                return url
            self._schedule()
        return url

    async def _upload_now(self, key: str) -> None:
        """CG8. Commit one small local file to the dataset now. Never raises: a failure is logged
        loudly, and the next change to the file uploads it again."""
        from huggingface_hub import HfApi

        path = self._path(key)

        def _go() -> None:
            HfApi().upload_file(path_or_fileobj=str(path), path_in_repo=key, repo_id=self.repo_id,
                                repo_type="dataset", commit_message=f"forge: {key}")

        try:
            await asyncio.to_thread(_go)
            if self._remote is not None:
                self._remote.add(key)
            self._shared.pop(key, None)
        except Exception as exc:  # noqa: BLE001
            logger.error("could not upload %s to %s: it is lost at the next restart unless "
                         "changed again (%s)", key, self.repo_id, exc)

    async def list_keys(self, prefix: str) -> list[str]:
        """Local keys and the dataset's: after a restart with empty storage, only the dataset has them."""
        local = set(await super().list_keys(prefix))
        folder = prefix.rstrip("/") + "/"
        remote = {key for key in await self._remote_files() if key.startswith(folder)}
        return sorted(local | remote)

    async def _list_remote_now(self) -> set[str]:
        """The dataset's files as they are this moment. Raises when it cannot be asked.

        ``_remote_files`` answers from a listing up to ``LIST_TTL_S`` old and turns a failure
        into the last good answer: right for serving, wrong for deciding that a file is gone.
        """
        import time

        from huggingface_hub import HfApi

        def _list() -> set[str]:
            return set(HfApi().list_repo_files(self.repo_id, repo_type="dataset"))

        listed = await asyncio.to_thread(_list)
        async with self._lock:
            self._remote, self._listed_at, self._ttl = listed, time.monotonic(), self.LIST_TTL_S
            self._list_stale = False
        return listed

    async def _remove_local(self, keys: list[str]) -> list[str]:
        remaining = []
        for key in keys:
            try:
                await LocalObjectStore.delete(self, key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not delete the local copy of %s: %s", key, exc)
            try:
                still = await LocalObjectStore.exists(self, key)
            except Exception:  # noqa: BLE001 - cannot confirm it is gone: treat it as there
                still = True
            if still:
                remaining.append(key)
        return remaining

    async def purge(self, keys: list[str], *, then: list[str] | None = None,
                    replace: dict[str, bytes] | None = None,
                    unlist: dict[str, str] | None = None) -> list[str]:
        """WD1. ``ObjectStore.purge`` for a store with two copies: this disk and the dataset.

        Before this, ``delete`` removed the local copy and nothing else. ``exists`` then
        answered from the dataset's listing and ``get`` downloaded the file again, so on a
        Space a withdrawn look's files "remained" for ever and were served the whole time.

        The local copies go first (``keys``, and only then ``then``: the marker). Then **one
        commit** to the dataset: every one of those keys it holds deleted, each list in
        ``unlist`` (list key -> look id) rewritten from the dataset's own copy without that
        look, and ``replace`` (the final receipt) added. One commit is all or nothing, so the
        dataset never holds a receipt saying "withdrawn" beside the files, nor the files
        without the receipt that blocks them. Only then is ``replace`` written locally.

        A dataset this Forge does not publish to (``wardrobe_hf_publish`` off) cannot be
        changed from here: files it holds are reported as remaining, honestly, and the look
        stays blocked by the local receipt for as long as this storage lives.
        """
        replace = dict(replace or {})
        remaining = await self._remove_local(list(keys)) or await self._remove_local(list(then or []))
        if remaining:
            return remaining
        keys = [*keys, *(then or [])]
        try:
            remote = await self._list_remote_now()
        except Exception as exc:  # noqa: BLE001
            logger.warning("dataset %s could not be listed, so nothing is confirmed gone: %s",
                           self.repo_id, exc)
            return list(keys)
        doomed = [key for key in keys if key in remote]
        if not self.publishing:
            if doomed:
                logger.warning("%s still holds %s and this Forge does not publish to it",
                               self.repo_id, doomed)
                return doomed
        elif doomed or replace or any(key in remote for key in (unlist or {})):
            from wardrobe.storage.dataset_publish import hub_download, withdraw_commit

            def _go() -> dict:
                from huggingface_hub import HfApi

                return withdraw_commit(HfApi(), self.repo_id, deletes=doomed, replace=replace,
                                       unlist={k: v for k, v in (unlist or {}).items() if k in remote},
                                       download=hub_download())

            try:
                result = await asyncio.to_thread(_go)
            except Exception as exc:  # noqa: BLE001
                logger.warning("the withdrawal commit to %s failed (nothing changed there): %s",
                               self.repo_id, exc)
                self.published["failures"] += 1
                return doomed or sorted(replace)
            async with self._lock:
                if self._remote is not None:
                    self._remote = (self._remote - set(doomed)) | set(replace)
            for key in [*result["lists"], *result["listsHeldBack"], *doomed, *replace]:
                self._shared.pop(key, None)
                self._shared_failed.pop(key, None)
            # A list whose dataset copy could not be read goes up with the next batch instead,
            # where publish() filters it by the receipt that is in the dataset now.
            self._pending_lists |= set(result["listsHeldBack"])
            self._pending_receipts -= set(replace)
            self.published["commits"] += 1
        unwritten = []
        for key, data in replace.items():
            try:
                await LocalObjectStore.put(self, key, data, content_type=content_type_for(key))
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not write %s locally: %s", key, exc)
                unwritten.append(key)
        return unwritten

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
            receipts = sorted(self._pending_receipts)
            if not entries and not lists and not receipts:
                return None
            self._pending_entries -= set(entries)
            self._pending_lists -= set(lists)
            self._pending_receipts -= set(receipts)
            from huggingface_hub import HfApi

            from wardrobe.storage.dataset_publish import hub_download, publish

            def _go() -> dict:
                return publish(HfApi(), self.repo_id, self.root, entries=entries, lists=lists,
                               receipts=receipts, keep_existing=False,
                               message=f"forge: {len(entries)} looks made on demand", download=hub_download())

            try:
                result = await asyncio.to_thread(_go)
            except Exception as exc:
                logger.warning("could not publish %d looks to %s (kept for the next batch): %s",
                               len(entries), self.repo_id, exc)
                self._pending_entries |= set(entries)
                self._pending_lists |= set(lists)
                self._pending_receipts |= set(receipts)
                self.published["failures"] += 1
                return None
            self._pending_lists |= set(result["heldBack"])
            self._pending_receipts |= set(result.get("receiptsHeldBack") or [])
            self.published["commits"] += 1 if result["files"] else 0
            self.published["looks"] += len(result["looks"])
            # What just went up exists in the dataset now: no listing round trip to know it.
            if self._remote is not None:
                self._remote |= set(entries) | set(lists) | set(result.get("uploaded") or [])
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
        return await self._shared_copy(key, strict=False)

    async def read_shared(self, key: str) -> bytes | None:
        """WD1. The dataset's copy, no older than ``LIST_TTL_S``, or an error. Never a guess.

        ``get_shared`` falls back: an old listing when the dataset cannot be listed, the last
        reading when the file cannot be downloaded, None when there is neither. For a list
        that is the right kindness. For a withdrawal receipt each of those is a way to serve
        a look another Forge has withdrawn, so here each raises: the answer is the dataset's
        copy as it was at most ``LIST_TTL_S`` ago, or it is "cannot tell" and the caller
        refuses. A failure is remembered for ``RETRY_S`` so an outage costs one request per
        receipt per half minute, not one per download asked for.
        """
        return await self._shared_copy(key, strict=True)

    async def _shared_copy(self, key: str, *, strict: bool) -> bytes | None:
        import time

        cached = self._shared.get(key)
        if cached is not None and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        remote = await self._remote_files()
        if strict and self._list_stale:
            raise RuntimeError(f"dataset {self.repo_id} could not be listed: is {key} there? unknown")
        if key not in remote:
            return None
        failed = self._shared_failed.get(key)
        if strict and failed is not None and time.monotonic() - failed < self.RETRY_S:
            raise RuntimeError(f"the dataset copy of {key} could not be read a moment ago")
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
            self._shared_failed[key] = time.monotonic()
            if strict:
                raise
            return cached[1] if cached is not None else None
        self._shared_failed.pop(key, None)
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
