"""RX2. The review registries on disk, in either shape a person may leave them.

Forge keeps a person's design findings in ``adult-design-reviews.json`` and detail reviews in
``adult-detail-reviews.json`` (with packets under ``packets/``). The Studio's **Export reviews**
(RX1) downloads them as one file, ``wardrobe.reviews.export.v1``, meant for
``tools/body_surface/import_reviews.py``. On 2026-11-21 that file was committed straight over
``adult-design-reviews.json``: a natural thing to do from a phone, and every reader then found no
``reviews`` in it, so every character fell back to "needs review".

So the readers here accept both: the registry itself, or an export standing in its place (in
either file). Nothing is relaxed — a review is read exactly as written, with the same fields
required by the callers (``gate.design_review``, ``eligibility.detail_review``) — only the
envelope differs. Before anything new is written, ``normalize`` turns an export back into the two
registries and their packets, so a write never mixes a finding into an export, and a finding
already there is never replaced (write-once, as everywhere).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

EXPORT_SCHEMA = "wardrobe.reviews.export.v1"
DESIGN_FILE = "adult-design-reviews.json"
DETAIL_FILE = "adult-detail-reviews.json"
DESIGN_SCHEMA = "wardrobe.bodySurface.adultDesignReviews.v1"
DETAIL_SCHEMA = "wardrobe.bodySurface.detailReviews.v1"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _part(data: dict | None, key: str) -> dict | None:
    """The registry inside an export, or the registry itself; None when it is neither."""
    if not data:
        return None
    if data.get("schema") == EXPORT_SCHEMA:
        part = data.get(key)
        return part if isinstance(part, dict) else None
    return data


def _merged(root, key: str, schema: str, own_file: str) -> dict | None:
    """One registry from every place it may be: its own file first, then any export in either file.

    Codex (#104). Each source used to hide the others: a detail file with one review hid the
    detail reviews an export carried, and an export over the detail file had its design findings
    unread. Now all are read; for the same bytes the registry's own entry wins (write-once).
    """
    root = Path(root)
    own = _read(root / own_file)
    merged = None
    if own and own.get("schema") == schema:
        merged = dict(own)
        merged["reviews"] = dict(own.get("reviews") or {})
    for name in (DESIGN_FILE, DETAIL_FILE):
        data = _read(root / name)
        if not data or data.get("schema") != EXPORT_SCHEMA:
            continue
        part = data.get(key) or {}
        if merged is None:
            merged = {"schema": part.get("schema") or schema, "reviews": {}}
        for sha, entry in (part.get("reviews") or {}).items():
            merged["reviews"].setdefault(sha, entry)
    return merged


def design_registry(root) -> dict | None:
    """The design findings (``wardrobe.bodySurface.adultDesignReviews.v1``) from every source, or None."""
    return _merged(root, "designReviews", DESIGN_SCHEMA, DESIGN_FILE)


def detail_registry(root) -> dict | None:
    """The detail reviews from their own file and any export in either file, or None."""
    return _merged(root, "detailReviews", DETAIL_SCHEMA, DETAIL_FILE)


def packets(root) -> dict:
    """Every review packet known here: ``packets/<sha>.json`` files, then any an export carries."""
    root = Path(root)
    out = {}
    folder = root / "packets"
    if folder.is_dir():
        for path in folder.glob("*.json"):
            data = _read(path)
            if data:
                out[path.stem] = data
    for name in (DESIGN_FILE, DETAIL_FILE):
        data = _read(root / name)
        if data and data.get("schema") == EXPORT_SCHEMA:
            for sha, packet in (data.get("packets") or {}).items():
                out.setdefault(sha, packet)
    return out


def _write(path: Path, content: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".reviews-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(content, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def normalize(root) -> bool:
    """Turn an export standing in either file back into the registries and packets. True if done.

    Findings are copied as written; a packet an export carries is written to ``packets/<sha>.json``
    (unless one is there) and the detail review then names that file. A finding already in a
    registry for the same bytes is kept, never replaced.
    """
    root = Path(root)
    exports = [d for d in (_read(root / DESIGN_FILE), _read(root / DETAIL_FILE))
               if d and d.get("schema") == EXPORT_SCHEMA]
    if not exports:
        return False
    design = _read(root / DESIGN_FILE)
    if not (design and design.get("schema") == DESIGN_SCHEMA):
        design = {"schema": DESIGN_SCHEMA, "reviews": {}}
    detail = _read(root / DETAIL_FILE)
    if not (detail and detail.get("schema") == DETAIL_SCHEMA):
        detail = {"schema": DETAIL_SCHEMA, "reviews": {}}
    for export in exports:
        for sha, entry in ((export.get("designReviews") or {}).get("reviews") or {}).items():
            design.setdefault("reviews", {}).setdefault(sha, entry)
        packets = export.get("packets") or {}
        for sha, entry in ((export.get("detailReviews") or {}).get("reviews") or {}).items():
            entry = dict(entry)
            if sha in packets:
                path = root / "packets" / f"{sha}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    text = json.dumps(packets[sha], indent=1, ensure_ascii=False) + "\n"
                    path.write_text(text, encoding="utf-8")
                entry["packet"] = f"packets/{sha}.json"
            detail.setdefault("reviews", {}).setdefault(sha, entry)
    _write(root / DESIGN_FILE, design)
    if detail.get("reviews"):
        _write(root / DETAIL_FILE, detail)
    elif (root / DETAIL_FILE).exists() and _read(root / DETAIL_FILE).get("schema") == EXPORT_SCHEMA:
        (root / DETAIL_FILE).unlink()
    return True


__all__ = ["DESIGN_FILE", "DETAIL_FILE", "EXPORT_SCHEMA", "design_registry", "detail_registry", "normalize",
           "packets"]
