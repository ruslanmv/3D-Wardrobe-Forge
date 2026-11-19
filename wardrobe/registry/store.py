"""WS1. The admin's wardrobe decisions, kept on disk: overrides, custom collections, favourites.

Forge has no SQL database (``wardrobe_database_url`` is declared and unused); jobs and wardrobes
are JSON files under ``<storage_root>/state``. This follows that pattern: one JSON document,
written whole through a temporary file and a rename, so a crash mid-write leaves the previous
version, never half of one.

What lives here is only what a person decided — a garment's type, tags, visibility or reviewed
mark; collections they made, renamed or archived, and what they put in or took out; favourites.
Everything a rule can work out (wardrobe.registry.classify) is computed fresh from the templates
each time and never copied in, so a rule improved later reaches every garment no one overrode.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from wardrobe.registry.classify import BY_ID, CATEGORY_IDS

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
VISIBILITY = ("public", "private")
_LOCK = threading.Lock()


def _empty() -> dict:
    return {"version": 1, "garments": {}, "collections": {}, "favourites": [], "updatedAt": None}


class RegistryStore:
    """One JSON document of admin decisions. Thread-safe within a process."""

    def __init__(self, root: Path):
        self.path = Path(root) / "state" / "wardrobe-registry.json"

    # ------------------------------------------------------------------ read / write
    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty()
        except (OSError, ValueError):
            # A damaged file must not take the wardrobe down: no decisions, and say so.
            return {**_empty(), "damaged": True}
        base = _empty()
        base.update({k: data.get(k, base[k]) for k in base})
        return base

    def _write(self, data: dict) -> dict:
        data["updatedAt"] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)
        return data

    def _update(self, change) -> dict:
        with _LOCK:
            data = self.read()
            data.pop("damaged", None)
            change(data)
            return self._write(data)

    # ------------------------------------------------------------------ garments
    def set_garment(
        self, garment_id: str, *, category=None, tags=None, visibility=None, reviewed=None
    ) -> dict:
        """An admin's classification of one garment. Only the fields given change."""
        if category is not None and category not in CATEGORY_IDS:
            raise ValueError("unknown category")
        if visibility is not None and visibility not in VISIBILITY:
            raise ValueError("visibility is public or private")
        if tags is not None:
            tags = sorted({str(t).strip().lower()[:40] for t in tags if str(t).strip()})[:40]

        def change(data):
            entry = data["garments"].setdefault(garment_id, {})
            for key, value in (
                ("category", category),
                ("tags", tags),
                ("visibility", visibility),
                ("reviewed", reviewed),
            ):
                if value is not None:
                    entry[key] = value
            entry["at"] = time.time()

        return self._update(change)["garments"][garment_id]

    # ------------------------------------------------------------------ collections
    def create_collection(
        self, *, title: str, description: str = "", private: bool = True, items=(), cover: str | None = None
    ) -> dict:
        title = str(title).strip()[:80]
        if not title:
            raise ValueError("a collection needs a title")
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "collection"

        def change(data):
            cid, n = base, 2
            while cid in data["collections"] or cid in BY_ID:
                cid, n = f"{base}-{n}", n + 1
            data["collections"][cid] = {
                "id": cid,
                "title": title,
                "description": str(description)[:200],
                "private": bool(private),
                "archived": False,
                "cover": cover,
                "add": sorted(set(items)),
                "remove": [],
                "custom": True,
                "createdAt": time.time(),
            }
            data["_new"] = cid

        data = self._update(change)
        return data["collections"][data.pop("_new")]

    def edit_collection(self, cid: str, **fields) -> dict:
        """Rename, describe, archive, cover or (custom only) change privacy. Built-in collections
        keep their id and privacy; their title, description, cover and archived mark can change."""
        allowed = {"title", "description", "archived", "cover", "private"}

        def change(data):
            entry = data["collections"].setdefault(cid, {"id": cid, "add": [], "remove": []})
            for key, value in fields.items():
                if key not in allowed or value is None:
                    continue
                if key == "private" and not entry.get("custom"):
                    continue  # a built-in collection's privacy is part of the product, not a setting
                entry[key] = str(value)[:200] if key in ("title", "description") else value
            entry["at"] = time.time()

        return self._update(change)["collections"][cid]

    def assign(self, cid: str, *, add=(), remove=()) -> dict:
        """Bulk membership: what a person put in or took out wins over the rules."""

        def change(data):
            entry = data["collections"].setdefault(cid, {"id": cid, "add": [], "remove": []})
            add_set = set(entry.get("add", [])) | set(add)
            remove_set = set(entry.get("remove", [])) | set(remove)
            add_set -= set(remove)
            remove_set -= set(add)
            entry["add"], entry["remove"] = sorted(add_set), sorted(remove_set)
            entry["at"] = time.time()

        return self._update(change)["collections"][cid]

    # ------------------------------------------------------------------ favourites
    def favourite(self, item_id: str, on: bool) -> list[str]:
        def change(data):
            fav = [f for f in data["favourites"] if f != item_id]
            if on:
                fav.insert(0, item_id)
            data["favourites"] = fav[:500]

        return self._update(change)["favourites"]


__all__ = ["RegistryStore", "SLUG", "VISIBILITY"]
