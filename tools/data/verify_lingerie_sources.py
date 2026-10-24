"""RL3. Check the lingerie reference library offline: what CI and a reviewer run.

    python tools/data/verify_lingerie_sources.py

Network-free. It checks that every source record says what a reviewer needs (licence,
redistribution, commercial use, contents and what is *not* in it, use class, verification
date), that every file kept in this repository is the pinned file (SHA-256), sits under a
licence that lets this MIT repository keep it, and has that licence beside it, that nothing
else has crept into the library, and that the normalized JSON is what the converter makes of
the vendored files now. tests/unit/test_lingerie_sources.py runs the same checks.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "assets" / "reference" / "lingerie"
LOCK = BASE / "sources.lock.json"
USES = {"directly-usable", "indirectly-useful", "research-only", "unsuitable"}
REDISTRIBUTABLE = {"MIT", "Apache-2.0", "CC0-1.0", "CC-BY-4.0"}
REQUIRED = (
    "id",
    "title",
    "authors",
    "url",
    "version",
    "license",
    "redistribution",
    "commercialUse",
    "format",
    "units",
    "contents",
    "notContained",
    "garmentCategories",
    "measurementFields",
    "use",
    "storage",
    "conversion",
    "files",
)
#: Files in the library that no lock entry names but that belong there.
OWN = {"sources.lock.json", "README.md"}


def _converter():
    spec = importlib.util.spec_from_file_location("convert", ROOT / "tools/data/convert_lingerie_patterns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATUSES = {"measured", "designer-convention", "class-typical", "unmeasured"}


def _values(node, where: str):
    """Every ``{value, unit, status}`` leaf of the fabric file, with where it is."""
    if isinstance(node, dict) and "status" in node and "unit" in node:
        yield where, node
    elif isinstance(node, dict):
        for key, child in node.items():
            yield from _values(child, f"{where}.{key}")


def _fabric_problems(path: Path, sources: set[str]) -> list[str]:
    """A value is a number only with a source; an unmeasured one is null and says how to measure it."""
    problems = []
    doc = json.loads(path.read_text(encoding="utf-8"))
    for fabric in doc["classes"]:
        for where, value in _values(fabric, fabric["id"]):
            status = value["status"]
            if status not in STATUSES:
                problems.append(f"fabrics.json {where}: status {status!r}")
            elif status == "unmeasured" and (value["value"] is not None or not value.get("calibrate")):
                problems.append(f"fabrics.json {where}: unmeasured must be null with a calibration procedure")
            elif status in {"measured", "designer-convention"} and (
                value["value"] is None or not value.get("source")
            ):
                problems.append(f"fabrics.json {where}: {status} needs a value and a source")
            elif value.get("source") and value["source"] not in sources:
                problems.append(
                    f"fabrics.json {where}: source {value['source']!r} is not in sources.lock.json"
                )
    return problems


def verify() -> list[str]:
    problems: list[str] = []
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if not lock.get("verifiedOn"):
        problems.append("sources.lock.json: no verifiedOn date")
    ids = [s.get("id") for s in lock["sources"]]
    if len(ids) != len(set(ids)):
        problems.append("sources.lock.json: duplicate source ids")
    named: set[Path] = set()
    for source in lock["sources"]:
        sid = source.get("id", "?")
        problems += [f"{sid}: no {key}" for key in REQUIRED if key not in source]
        if source.get("use") not in USES:
            problems.append(f"{sid}: use {source.get('use')!r} not one of {sorted(USES)}")
        files = source.get("files") or []
        if files and source.get("license") not in REDISTRIBUTABLE:
            problems.append(f"{sid}: {source.get('license')} files may not be kept in this repository")
        if files and not any(f["role"] == "licence" for f in files):
            problems.append(f"{sid}: files kept without their licence")
        if source.get("use") in {"research-only", "unsuitable"} and files:
            problems.append(f"{sid}: a {source['use']} source keeps files")
        for entry in files:
            path = ROOT / entry["path"]
            named.add(path)
            if BASE not in path.parents:
                problems.append(f"{sid}: {entry['path']} is outside the library")
            if (
                not entry.get("url", "").startswith("https://")
                or "/main/" in entry["url"]
                or "/master/" in entry["url"]
            ):
                problems.append(f"{sid}: {entry['path']} is not fetched from a pinned https URL")
            if not path.is_file():
                problems.append(f"{sid}: {entry['path']} missing (tools/data/fetch_lingerie_sources.py)")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
                problems.append(f"{sid}: {entry['path']} is not the pinned file")
    for authored in lock.get("authored", []):
        named.add(ROOT / authored["path"])
        problems += _fabric_problems(ROOT / authored["path"], set(ids))
    converter = _converter()
    outputs = {BASE / relative for relative in converter.OUTPUTS}
    for path in sorted(p for p in BASE.rglob("*") if p.is_file()):
        if path.name in OWN or path in named or path in outputs:
            continue
        problems.append(f"{path.relative_to(ROOT)}: in the library but in no source record")
    for relative, build in converter.OUTPUTS.items():
        target = BASE / relative
        fresh = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
        if not target.is_file() or target.read_text(encoding="utf-8") != fresh:
            problems.append(f"{relative}: stale (tools/data/convert_lingerie_patterns.py)")
    return problems


def main() -> int:
    problems = verify()
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if not problems:
        print("lingerie reference library: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
