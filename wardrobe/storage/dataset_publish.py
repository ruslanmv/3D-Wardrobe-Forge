"""RU3/RU4. What goes up to the prebuilt dataset, and how — one rule for the Space and for CI.

Before this, two things were wrong with the dataset (``docs/PREBUILT_WARDROBE.md``):

* **A look made on demand never reached it.** The Space wrote new looks locally, "and the next
  prebuild makes it permanent" — but a prebuild only makes catalogue garments, so a look the
  app asked for (an outfit of two garments, a described one) was lost at the Space's next
  restart and made again the next time. ``HfDatasetObjectStore`` now hands every finished
  look to ``publish`` in batches (RU3).
* **Looks went up that nothing could find.** CI uploaded every ``looks/<id>/`` folder in its
  storage root, including looks with no prebuilt entry (body art, layers, a free prompt):
  nothing points at them, so they cost space and are never served. Only a look a prebuilt
  entry names is published now (RU4); ``tools/dataset_orphans.py`` removes the ones already
  there.

A publish is one commit: the entries, the files of the looks they name, and every wardrobe
list touched, each list merged with the dataset's own copy first so a publish never drops a
look (PB7). A list whose dataset copy cannot be read right now is held back, not uploaded
over it; the looks still go up and the next publish lists them.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

#: A prebuilt entry (``prebuilt/<key>.json``): not a wardrobe list, which lives one level down.
ENTRY = re.compile(r"^prebuilt/[^/]+\.json$")
LIST = re.compile(r"^prebuilt/wardrobes/[^/]+\.json$")


def look_of_entry(data: bytes | str) -> str | None:
    """The look a prebuilt entry answers with, or None when the entry is not a usable one."""
    try:
        entry = json.loads(data)
    except (ValueError, TypeError):
        return None
    look = entry.get("lookId") or ((entry.get("record") or {}).get("look") or {}).get("id")
    return look if isinstance(look, str) and look.startswith("look_") else None


def look_files(root: Path, look_id: str) -> list[str]:
    """Every finished file of a look under ``root`` (a ``.part`` is still being written)."""
    folder = root / "looks" / look_id
    if not folder.is_dir():
        return []
    done = [p for p in folder.rglob("*") if p.is_file() and not p.name.endswith(".part")]
    return sorted(str(p.relative_to(root)) for p in done)


def entries_under(root: Path) -> list[str]:
    folder = root / "prebuilt"
    if not folder.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in folder.glob("*.json"))


def lists_under(root: Path) -> list[str]:
    folder = root / "prebuilt" / "wardrobes"
    if not folder.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in folder.glob("*.json"))


def merge_list(local: dict, remote: dict, *, keep_existing: bool) -> dict:
    """PB7 with RU1's identity. ``keep_existing``: a look the dataset already lists stays (CI's
    default); otherwise the one built last wins (a look rebuilt because its files were lost)."""
    from wardrobe.pipeline.prebuilt import LIST_FIELDS, merge_lists

    if not keep_existing:
        return {**local, **merge_lists(remote, local)}
    ident = lambda item: tuple(item.get(f) for f in LIST_FIELDS)  # noqa: E731
    kept = [item for item in remote.get("looks", []) if isinstance(item, dict)]
    have = {ident(item) for item in kept}
    added = [item for item in local.get("looks", []) if isinstance(item, dict) and ident(item) not in have]
    return {**local, "looks": kept + added}


def publish(api, repo: str, root: Path, *, entries: Iterable[str] | None = None,
            lists: Iterable[str] | None = None, keep_existing: bool = True,
            message: str = "publish prebuilt looks", download=None) -> dict:
    """Upload ``entries`` (default: every entry under root), the looks they name, and ``lists``
    (default: every list under root), merged. One commit. Returns what went up and what did not.

    ``api`` is an ``HfApi``; ``download(repo, key) -> bytes`` reads the dataset's copy of a list
    (raising ``FileNotFoundError`` when it has none). Both are injected so tests run offline.
    """
    from huggingface_hub import CommitOperationAdd

    entries = sorted(set(entries if entries is not None else entries_under(root)))
    lists = sorted(set(lists if lists is not None else lists_under(root)))
    files: list[str] = []
    looks: list[str] = []
    for key in entries:
        path = root / key
        if not path.is_file():
            continue
        look = look_of_entry(path.read_bytes())
        found = look_files(root, look) if look else []
        if not any(name.endswith("/look.vrm") for name in found):
            continue  # an entry whose look is not here (freed locally, already up) goes alone
        files.append(key)
        files += found
        looks.append(look)
    # An entry already up with its look freed locally: the entry alone is harmless and current.
    files += [key for key in entries if key not in files and (root / key).is_file()]

    held_back: list[str] = []
    merged: dict[str, bytes] = {}
    for key in lists:
        path = root / key
        if not path.is_file():
            continue
        try:
            remote = json.loads(download(repo, key))
        except FileNotFoundError:
            remote = {"looks": []}
        except Exception as exc:
            logger.warning("%s: the dataset copy could not be read (%s); not uploading it", key, exc)
            held_back.append(key)
            continue
        local = json.loads(path.read_text())
        merged[key] = json.dumps(merge_list(local, remote, keep_existing=keep_existing)).encode("utf-8")

    operations = [CommitOperationAdd(path_in_repo=key, path_or_fileobj=str(root / key))
                  for key in dict.fromkeys(files)]
    operations += [CommitOperationAdd(path_in_repo=key, path_or_fileobj=data) for key, data in merged.items()]
    if operations:
        api.create_commit(repo_id=repo, repo_type="dataset", operations=operations, commit_message=message)
    return {"files": len(operations), "looks": looks, "lists": sorted(merged), "heldBack": held_back}


def hub_download(token: str | None = None):
    """The ``download`` ``publish`` takes, reading the dataset with huggingface_hub."""

    def _download(repo: str, key: str) -> bytes:
        import shutil
        import tempfile

        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError

        scratch = tempfile.mkdtemp(prefix="hf-list-")
        try:
            try:
                got = hf_hub_download(repo, key, repo_type="dataset", local_dir=scratch, token=token)
            except EntryNotFoundError as exc:
                raise FileNotFoundError(key) from exc
            return Path(got).read_bytes()
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    return _download


def orphans(remote_files: Iterable[str], entry_looks: Iterable[str],
            listed_looks: Iterable[str]) -> list[str]:
    """RU4. Look folders in the dataset that no prebuilt entry and no wardrobe list names."""
    used = set(entry_looks) | set(listed_looks)
    folders = {name.split("/")[1] for name in remote_files
               if name.startswith("looks/") and name.count("/") >= 2}
    return sorted(look for look in folders if look not in used)


__all__ = ["ENTRY", "LIST", "entries_under", "hub_download", "lists_under", "look_files", "look_of_entry",
           "merge_list", "orphans", "publish"]
