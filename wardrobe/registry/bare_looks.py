"""AB1. After Dark · Bare: named bare looks for the admin's (and a grant's) most explicit collection.

Why a file of its own. After Dark is an occasion, and an occasion lists outfit dictionary ids only
(a test refuses anything else): a body state is not an outfit. Asked for "a collection made only
of pure bare body variants" inside After Dark, the honest place is the registry's private side,
where body items already live (``preset:``, ``state:``, ``extra:``). A single state is a raw
ingredient; what an admin browses for is a finished look — this skin, this state, these marks —
so each entry here is one, with its own name and thumbnail, listed as ``look:<id>``.

Every look is checked against the painter's own catalogue (``presets.json``, ``states.json``,
``extras.json``) when loaded, so a look here is exactly what a bare job accepts
(``bareDetail`` + ``bareStates`` + ``bareExtras``). An entry naming anything Forge cannot paint is
dropped with a warning, never guessed at — and ``tests/unit/test_bare_looks.py`` fails on it.
Nothing here grants anything: listing is private (admin or grant), building still needs the
character declared adult and detail clearance for her exact file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2] / "assets" / "body_detail"
PATH = ROOT / "bare_looks.json"
#: Forge's limit on one job (wardrobe/domain/jobs.py).
MAX_EXTRAS = 4


def _names(name: str, key: str, root: Path) -> set[str]:
    try:
        return set(json.loads((root / f"{name}.json").read_text(encoding="utf-8")).get(key, {}))
    except (OSError, ValueError):
        return set()


def load(root: Path = ROOT) -> dict:
    """``{"chapters": [...], "looks": {id: {...}}}``, each look checked; an invalid one is dropped."""
    try:
        data = json.loads((root / "bare_looks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOG.warning("bare looks unavailable: %s", exc)
        return {"chapters": [], "looks": {}}
    presets = _names("presets", "presets", root)
    states = _names("states", "states", root)
    extras = _names("extras", "extras", root)
    chapters = [c for c in data.get("chapters", []) if c.get("id")]
    chapter_ids = {c["id"] for c in chapters}
    looks = {}
    for look_id, spec in data.get("looks", {}).items():
        problems = problems_of(spec, presets, states, extras, chapter_ids)
        if problems:
            LOG.warning("bare look %s dropped: %s", look_id, "; ".join(problems))
            continue
        looks[look_id] = spec
    return {"chapters": chapters, "looks": looks}


def problems_of(spec: dict, presets: set, states: set, extras: set, chapters: set) -> list[str]:
    out = []
    if spec.get("preset") not in presets:
        out.append(f"unknown preset {spec.get('preset')!r}")
    if spec.get("state") not in states:
        out.append(f"unknown state {spec.get('state')!r}")
    unknown = [e for e in spec.get("extras", []) if e not in extras]
    if unknown:
        out.append(f"unknown extras {unknown}")
    if len(spec.get("extras", [])) > MAX_EXTRAS:
        out.append(f"more than {MAX_EXTRAS} extras")
    if spec.get("chapter") not in chapters:
        out.append(f"unknown chapter {spec.get('chapter')!r}")
    if not spec.get("label"):
        out.append("no label")
    return out


def describe(spec: dict, states_body: dict) -> str:
    """The look in words: the state's own ``body`` line (second person), then what is painted on."""
    line = states_body.get(spec["state"], "")
    extras = ", ".join(e.replace("-", " ") for e in spec.get("extras", []))
    return f"{line}{' · ' if line and extras else ''}{extras}"


def job_options(spec: dict) -> dict:
    """What a bare job takes for this look (the Studio's and prebuild_private.py's request)."""
    options = {"baseBody": "bare", "bareDetail": spec["preset"], "bareStates": ["closed", spec["state"]]}
    if spec.get("extras"):
        options["bareExtras"] = list(spec["extras"])
    return options
