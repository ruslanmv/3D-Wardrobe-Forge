"""CG1. Where a character stands for the bare body state, and exactly why — for one exact file.

Forge's bare body state asks five questions of the exact source file (``eligibility.assess``) and
then whether the authored body is closed. A refusal used to say only the first "no". This module
answers all of them for one file, names the metadata or registry entry each answer came from, and
turns every "no" into a requirement with an owner, so a blocked character says what would unblock
it and who has to act:

* ``eligible``      — every answer is yes for this exact file; with the operator's switch on, bare
                       builds. The approval is the review keyed by this file's SHA-256: it holds for
                       these bytes, needs no repeating, and covers no other file.
* ``needs-review``  — the file allows it and nothing else is missing but a person's design review
                       of these bytes. Missing information is never read as a yes.
* ``blocked``       — something only a different file can fix: its own terms refuse sexual
                       expression, or a person reviewed it and did not find it clearly adult
                       (age-ambiguous, appears to be a minor). That finding is kept for these bytes.
* ``incomplete``    — the character is cleared but the authored body is not closed under her
                       clothes; a completed source file is needed (or BR1's opt-in completion).
* ``needs-body-state`` — CG4. The character is cleared and her body is closed, but her clothing is
                       painted onto her skin texture (CV1 ``painted-on``): there is no garment
                       mesh to take off, so she needs a separate bare body-state file, imported
                       through the operator's body-state import (which reviews that file too).

CG4. Two things this module used to fold into one status are now said apart, because they have
different owners and one is not a verdict at all:

* ``reviewState`` is ``pending`` when nobody has looked — work still to do, never a rejection —
  and otherwise the finding a person recorded. Only a recorded ``age-ambiguous``,
  ``appears-minor`` or ``not-assessable`` blocks a file; an empty registry never does.
* ``bodyState`` is the body question alone, from CV1's ``clothing_structure.analyze`` on the
  exact file: ``complete`` (separate garments over a closed body, or no clothing), ``painted-on``,
  ``body-missing`` (with the bands), or ``not-measured``. An accepted bare body-state import for
  the file answers ``painted-on`` and ``body-missing`` (``bodyStateFiles``).

And one source of the licence answer it used to miss: the library's own provenance record. A
pinned library file whose record grants modification (the CC0 samples: CC0 waives every right,
``LICENSE_CONDITIONS``) has the same answer here that the dressing pipeline already uses
(``LibraryAvatar.avatar_input``), so the audit no longer asks the creator for a licence the
library already holds. It holds only for the pinned bytes: a changed file is asked again.

What this never does: infer a character's age from anything — not from the person using the app
(a user's "I am an adult" is about the user), not from an operator's declaration, not from the
file's terms. Adulthood of a design is only ever a person's recorded finding about exact bytes.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path

from wardrobe.body_surface.eligibility import assess
from wardrobe.body_surface.gate import design_review, explicit_usage_disallowed
from wardrobe.policy.intimate import sexual_usage_disallowed

#: The findings a person may record about a design. Only the first opens anything.
REVIEW_OUTCOMES = ("clearly-adult", "age-ambiguous", "appears-minor", "not-assessable")
CLEARED = "clearly-adult"


def _terms_summary(terms) -> dict:
    raw = (terms.raw if terms is not None else None) or {}
    summary = terms.to_dict() if terms is not None else {}
    return {
        "sexualUssageName (VRM 0.x)": raw.get("sexualUssageName"),
        "allowExcessivelySexualUsage (VRM 1.0)": raw.get("allowExcessivelySexualUsage"),
        "modification": summary.get("modification"),
        "redistributionAllowed": summary.get("redistributionAllowed"),
        "licenseUrl": summary.get("licenseUrl"),
        "authors": summary.get("authors"),
    }


def _licence_url_says(url: str | None, key: str) -> str | None:
    """A VRoid Hub licence URL's own answer for ``key`` (``sexual_expression``, ``modification``)."""
    if not url or "?" not in url:
        return None
    from urllib.parse import parse_qs, urlparse

    return (parse_qs(urlparse(url).query).get(key) or [None])[0]


def measure_body_state(path: Path) -> dict:
    """CG4. The body question for one exact file: CV1's structure, and the old one-line result.

    Nothing is changed. Slow (it reads her skin texture), so callers cache it by SHA-256.
    """
    from wardrobe.body_surface.clothing_structure import analyze
    from wardrobe.vrm.document import GltfDocument
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body

    doc = GltfDocument.from_path(path)
    structure = analyze(doc, measure_body(doc, inspect_document(doc)))
    missing = structure.get("missingBands") or []
    result = "built" if structure.get("bodyComplete") else f"refused: body incomplete ({', '.join(missing)})"
    return {"result": result, "structure": structure}


def _body_state(body: dict | None) -> dict:
    """CG4. ``complete``, ``painted-on``, ``body-missing`` or ``not-measured``, with what answers it."""
    structure = (body or {}).get("structure")
    files = int((body or {}).get("bodyStateFiles") or 0)
    if not structure:
        result = (body or {}).get("result")
        if result is None:
            state = "not-measured"
        else:
            state = "complete" if str(result).startswith("built") else "body-missing"
        return {"state": state, "verdict": None, "missingBands": [], "paintedShare": None,
                "bodyStateFiles": files, "satisfied": state == "complete" or files > 0}
    verdict = structure.get("verdict")
    if verdict == "separable-body-missing" or not structure.get("bodyComplete", True):
        state = "body-missing"
    elif verdict == "painted-on":
        state = "painted-on"
    else:
        state = "complete"
    return {"state": state, "verdict": verdict, "missingBands": structure.get("missingBands") or [],
            "paintedShare": structure.get("paintedShare"), "bodyStateFiles": files,
            "satisfied": state == "complete" or files > 0}


def status(path: Path, *, slug: str | None, depicts_adult: bool, pinned_sha256: str | None,
           settings, body: dict | None = None, library_conditions: dict | None = None) -> dict:
    """Every answer for this exact file, the source of each, and what would change a "no".

    ``body`` is the geometry result when the caller measured it (``measure_body_state``, and
    ``bodyStateFiles`` when it counted accepted body-state imports); without it body completeness
    is reported as not measured, never as complete. ``library_conditions`` is the library record's
    grant for the pinned file (``LibraryAvatar.granted_conditions``); it is ignored for any other
    bytes.
    """
    from wardrobe.vrm.document import GltfDocument
    from wardrobe.vrm.inspect import inspect_document

    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    info = inspect_document(GltfDocument.from_bytes(data))
    terms = info.license
    answers = assess(terms=terms, operator_enabled=True, depicts_adult=depicts_adult, private=True,
                     source_sha256=sha, review_root=settings.body_surface_root_path,
                     reference_root=settings.wardrobe_calibration_root)
    review = design_review(settings.body_surface_root_path, sha)
    meta = _terms_summary(terms)
    url = meta["licenseUrl"]
    requirements: list[dict] = []

    def need(owner: str, what: str) -> None:
        requirements.append({"owner": owner, "what": what})

    blocked: list[str] = []
    if pinned_sha256 and pinned_sha256 != sha:
        blocked.append("file differs from the library pin")
        need("operator", f"restore the pinned file ({pinned_sha256[:12]}…) or pin this one")
    if sexual_usage_disallowed(terms) or explicit_usage_disallowed(terms):
        blocked.append("the file's own terms refuse sexual expression")
        need("creator", "a version of the model whose terms allow sexual expression "
                        "(VRM 1.0 allowExcessivelySexualUsage: true; VRM 0.x sexualUssageName: Allow)")
    if not depicts_adult:
        need("operator", "declare the character adult in assets/library/policy.json "
                         "(a declaration only: it opens nothing without a review)")
    if review is not None and review.get("outcome") != CLEARED:
        blocked.append(f"reviewed: {review.get('outcome')} ({review.get('reviewer')}, {review.get('date')})")
        need("creator", "a different character, adult by design; this file's finding stands for these bytes")
    elif review is None:
        need("independent reviewer", "review these exact bytes (Studio ▸ Character review, or "
                                     "tools/body_surface/gates.py record) and record the finding")
    # CG4. Where the modification answer came from: the file, its licence URL, or the library's
    # provenance record for exactly these pinned bytes.
    modification_source = None
    if meta["modification"] not in (None, "unknown", "prohibited"):
        modification_source = "file"
    elif _licence_url_says(url, "modification") == "allow":
        modification_source = "licence URL"
    elif (meta["modification"] != "prohibited" and library_conditions
          and str(library_conditions.get("modification", "")).lower() == "allow"
          and pinned_sha256 and pinned_sha256 == sha):
        modification_source = "library record"
    if modification_source is None:
        need("creator", "a licence that permits modification (the file's meta says "
                        f"{meta['modification']!r})")

    cleared = answers.checks["design-clearance"]["passed"]
    body_state = (body or {}).get("result")
    body_answer = _body_state(body)
    open_body = body_answer["state"] == "body-missing" and not body_answer["satisfied"]
    painted = body_answer["state"] == "painted-on" and not body_answer["satisfied"]
    if open_body:
        need("licensed 3D artist", "a completed source file with the body closed under the clothes "
                                   "(docs/qa/body-state-specs/), or BR1's opt-in completion")
    if painted:
        need("licensed 3D artist", "a bare body-state file for this character (the clothing is painted on "
                                   "the skin: no garment mesh to take off), imported through the Studio's "
                                   "body-state import, where that file is reviewed too")
    if blocked:
        state = "blocked"
    elif not cleared or not depicts_adult or any(r["owner"] == "creator" for r in requirements):
        state = "needs-review"
    elif open_body:
        state = "incomplete"
    elif painted:
        state = "needs-body-state"
    else:
        state = "eligible"
    return {
        "slug": slug, "file": str(path), "sha256": sha, "pinnedSha256": pinned_sha256,
        "vrm": str(info.spec), "title": info.title,
        "metadata": meta,
        "licenceUrlSays": {k: _licence_url_says(url, k) for k in ("sexual_expression", "modification")},
        "operatorDeclaration": depicts_adult,
        "review": review,
        "reviewState": "pending" if review is None else review.get("outcome"),
        "licence": {"sexualUse": not (sexual_usage_disallowed(terms) or explicit_usage_disallowed(terms)),
                    "modification": modification_source is not None,
                    "modificationSource": modification_source},
        "bodyState": body_answer,
        "answers": {k: {"passed": v["passed"], "why": v.get("why", "")} for k, v in answers.checks.items()
                    if k != "operator-switch"},
        "body": body_state or "not measured",
        "status": state,
        "blockedBecause": blocked,
        "requirements": requirements,
    }


def record_review(registry: Path, *, file: Path, sha256: str, outcome: str, reviewer: str, evidence: str,
                  date: str, packet: Path | None = None) -> dict:
    """Write a person's finding about these exact bytes into the review registry.

    Run by the person who reviewed the file, under their own name. It refuses: a SHA-256 that is not
    the file's, an outcome outside ``REVIEW_OUTCOMES``, an empty reviewer or evidence, a packet that
    is not for this file, and replacing an earlier finding (a new finding is for a new file). A
    ``clearly-adult`` finding for a file whose own terms refuse sexual expression is refused too:
    the creator's terms are not the reviewer's to overrule.
    """
    import json

    data = Path(file).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if sha256 != actual:
        raise ValueError(f"SHA-256 {sha256[:12]}… is not this file's ({actual[:12]}…)")
    if outcome not in REVIEW_OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(REVIEW_OUTCOMES)}")
    if not reviewer.strip() or not evidence.strip() or not date.strip():
        raise ValueError("reviewer, date and evidence are required: a review with an empty field is none")
    if packet is not None:
        recorded = json.loads(Path(packet).read_text(encoding="utf-8"))
        if (recorded.get("file") or {}).get("sha256") != actual:
            raise ValueError("the review packet is for a different file")
    if outcome == CLEARED:
        from wardrobe.vrm.document import GltfDocument
        from wardrobe.vrm.inspect import inspect_document

        terms = inspect_document(GltfDocument.from_bytes(data)).license
        if sexual_usage_disallowed(terms) or explicit_usage_disallowed(terms):
            raise ValueError("the file's own terms refuse sexual expression; no review changes that")
    path = Path(registry)
    entry = {"outcome": outcome, "reviewer": reviewer.strip(), "date": date.strip(),
             "evidence": evidence.strip()}
    if packet is not None:
        entry["packet"] = str(packet)
    # Read, check and write as one step: two findings recorded at once (two Studio requests on
    # worker threads) both read the old registry, and the later write dropped the earlier finding
    # or replaced one for the same bytes, against the write-once rule. The file is replaced
    # atomically, so a reader never sees half a registry.
    with _REGISTRY_LOCK:
        content = json.loads(path.read_text(encoding="utf-8"))
        reviews = content.setdefault("reviews", {})
        if actual in reviews:
            raise ValueError("a finding is already recorded for these bytes; it is not replaced")
        reviews[actual] = entry
        # Off the "waiting for a review" list: it has one now.
        pending = content.get("pending")
        if isinstance(pending, dict):
            pending.pop(actual, None)
        fd, tmp = tempfile.mkstemp(prefix=".reviews-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(content, indent=1, ensure_ascii=False) + "\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return entry


#: One writer of a review registry at a time within this process (the API's worker threads).
_REGISTRY_LOCK = threading.Lock()


__all__ = ["CLEARED", "REVIEW_OUTCOMES", "measure_body_state", "record_review", "status"]
