"""Build a pinned avatar library on disk for tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def write_library(root: Path, files: dict[str, bytes], *, license: str = "CC0", overrides=None) -> Path:
    """A library directory whose manifest pins the given files."""
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for name, data in files.items():
        (root / name).write_bytes(data)
        item = {
            "slug": Path(name).stem.lower().replace("_", "-"),
            "name": Path(name).stem,
            "file": name,
            "license": license,
            "source": f"https://example.test/{name}",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        item.update((overrides or {}).get(name, {}))
        items.append(item)
    (root / "models.json").write_text(json.dumps({"license_note": "test set", "items": items}))
    return root
