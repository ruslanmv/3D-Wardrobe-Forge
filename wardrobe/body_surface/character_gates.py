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

What this never does: infer a character's age from anything — not from the person using the app
(a user's "I am an adult" is about the user), not from an operator's declaration, not from the
file's terms. Adulthood of a design is only ever a person's recorded finding about exact bytes.
"""

from __future__ import annotations

import hashlib
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


def status(path: Path, *, slug: str | None, depicts_adult: bool, pinned_sha256: str | None,
           settings, body: dict | None = None) -> dict:
    """Every answer for this exact file, the source of each, and what would change a "no".

    ``body`` is the geometry result when the caller measured it (``tools/audit/bare_visibility.py``);
    without it body completeness is reported as not measured, never as complete.
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
        need("independent reviewer", "review these exact bytes (tools/body_surface/review_packet.py, then "
                                     "tools/body_surface/gates.py record) and record the finding")
    if meta["modification"] in (None, "unknown", "prohibited"):
        said = _licence_url_says(url, "modification")
        if said != "allow":
            need("creator", "a licence that permits modification (the file's meta says "
                            f"{meta['modification']!r})")

    cleared = answers.checks["design-clearance"]["passed"]
    body_state = (body or {}).get("result")
    open_body = body_state is not None and not str(body_state).startswith("built")
    if open_body:
        need("licensed 3D artist", "a completed source file with the body closed under the clothes "
                                   "(docs/qa/body-state-specs/), or BR1's opt-in completion")
    if blocked:
        state = "blocked"
    elif not cleared or not depicts_adult or any(r["owner"] == "creator" for r in requirements):
        state = "needs-review"
    elif open_body:
        state = "incomplete"
    else:
        state = "eligible"
    return {
        "slug": slug, "file": str(path), "sha256": sha, "pinnedSha256": pinned_sha256,
        "vrm": str(info.spec), "title": info.title,
        "metadata": meta,
        "licenceUrlSays": {k: _licence_url_says(url, k) for k in ("sexual_expression", "modification")},
        "operatorDeclaration": depicts_adult,
        "review": review,
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
    content = json.loads(path.read_text(encoding="utf-8"))
    reviews = content.setdefault("reviews", {})
    if actual in reviews:
        raise ValueError("a finding is already recorded for these bytes; it is not replaced")
    entry = {"outcome": outcome, "reviewer": reviewer.strip(), "date": date.strip(),
             "evidence": evidence.strip()}
    if packet is not None:
        entry["packet"] = str(packet)
    reviews[actual] = entry
    path.write_text(json.dumps(content, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry


__all__ = ["CLEARED", "REVIEW_OUTCOMES", "record_review", "status"]
