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


def dataset_is_private(api, repo: str) -> bool:
    """BI4. Whether the hub says this dataset is private. Anything else (an error, no answer, an
    API without ``repo_info``) is *not private*: a private look is never sent on a guess."""
    try:
        return bool(api.repo_info(repo_id=repo, repo_type="dataset").private)
    except Exception:  # noqa: BLE001
        return False


def _is_private_look(root: Path, look_id: str | None, entry: bytes) -> bool:
    if look_id and (root / "looks" / look_id / "private.json").is_file():
        return True
    try:
        record = json.loads(entry).get("record") or {}
        return bool(((record.get("request") or {}).get("options") or {}).get("private"))
    except (ValueError, AttributeError):
        return False


def publish(api, repo: str, root: Path, *, entries: Iterable[str] | None = None,
            lists: Iterable[str] | None = None, keep_existing: bool = True,
            message: str = "publish prebuilt looks", download=None,
            include_private: bool | None = None) -> dict:
    """Upload ``entries`` (default: every entry under root), the looks they name, and ``lists``
    (default: every list under root), merged. One commit. Returns what went up and what did not.

    ``api`` is an ``HfApi``; ``download(repo, key) -> bytes`` reads the dataset's copy of a list
    (raising ``FileNotFoundError`` when it has none). Both are injected so tests run offline.
    """
    from huggingface_hub import CommitOperationAdd

    # BI4. A private look (a bare prebuild, an operator's imported body state, anything an admin
    # session's declaration made) is served only to an admin session or a read grant. Before,
    # publishing sent its VRM and its list entry to the dataset with everything else, so a public
    # dataset made it public; and then `include_private=True` (CLI `--include-private`) could
    # still send it to one. Now the only thing that lets a private file go up is the hub itself
    # answering that this dataset is private. The caller can ask for less (False), never more:
    # True against a dataset not confirmed private is refused and reported, not honoured.
    # Unverifiable (an error, no answer) is not private. Fail closed.
    verified_private = dataset_is_private(api, repo)
    allow_private = verified_private and include_private is not False
    refused_private = bool(include_private) and not verified_private
    private_held: list[str] = []
    unavailable: list[str] = []
    entries = sorted(set(entries if entries is not None else entries_under(root)))
    lists = sorted(set(lists if lists is not None else lists_under(root)))
    files: list[str] = []
    looks: list[str] = []
    for key in entries:
        path = root / key
        if not path.is_file():
            continue
        raw = path.read_bytes()
        look = look_of_entry(raw)
        if not allow_private and _is_private_look(root, look, raw):
            private_held.append(look or key)
            continue
        found = look_files(root, look) if look else []
        if not any(name.endswith("/look.vrm") for name in found):
            continue  # an entry whose look is not here (freed locally, already up) goes alone
        files.append(key)
        files += found
        looks.append(look)
    # An entry already up with its look freed locally: the entry alone is harmless and current.
    files += [key for key in entries if key not in files and (root / key).is_file()
              and (allow_private or not _is_private_look(root, look_of_entry((root / key).read_bytes()),
                                                           (root / key).read_bytes()))]

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
        remote_ids = {item.get("lookId") for item in remote.get("looks", []) if isinstance(item, dict)}
        kept_local = []
        for item in local.get("looks", []):
            if not isinstance(item, dict):
                continue
            if item.get("private") and not allow_private:
                private_held.append(item.get("lookId") or "?")
                continue
            if item.get("origin") == "operator-import":
                # BI5. An imported body state has no prebuilt entry, so the entry loop above never
                # sent its files: the list went up alone and, after a restart, named a VRM the
                # dataset did not have. Its folder (VRM, private marker, import receipt) goes in
                # this same commit, or the item does not go at all — unless the dataset already
                # lists it, which means it went up with its files before.
                found = look_files(root, item.get("lookId") or "")
                complete = (any(n.endswith("/look.vrm") for n in found)
                            and any(n.endswith("/private.json") for n in found))
                if complete:
                    files += found
                    looks.append(item["lookId"])
                elif item.get("lookId") not in remote_ids:
                    unavailable.append(item.get("lookId") or "?")
                    continue
            kept_local.append(item)
        local["looks"] = kept_local
        out = merge_list(local, remote, keep_existing=keep_existing)
        # The dataset's own copy is filtered too: a private item it holds from before (or from
        # when it was private) is not re-sent to a dataset that is not confirmed private now.
        if not allow_private:
            hidden = [item for item in out.get("looks", []) if isinstance(item, dict) and item.get("private")]
            private_held += [item.get("lookId") or "?" for item in hidden]
            out["looks"] = [item for item in out.get("looks", []) if item not in hidden]
        merged[key] = json.dumps(out).encode("utf-8")

    uploaded = list(dict.fromkeys(files))
    operations = [CommitOperationAdd(path_in_repo=key, path_or_fileobj=str(root / key)) for key in uploaded]
    operations += [CommitOperationAdd(path_in_repo=key, path_or_fileobj=data) for key, data in merged.items()]
    if operations:
        api.create_commit(repo_id=repo, repo_type="dataset", operations=operations, commit_message=message)
    return {"files": len(operations), "looks": looks, "lists": sorted(merged), "heldBack": held_back,
            "uploaded": uploaded + sorted(merged),
            "privateHeldBack": sorted(set(private_held)), "includePrivate": allow_private,
            "verifiedPrivate": verified_private, "refusedPrivate": refused_private,
            "unavailable": sorted(set(unavailable))}


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
