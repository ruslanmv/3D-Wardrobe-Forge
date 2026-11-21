"""BE1. Who may have a bare (authored-only, unclothed) look built: one contract, five questions.

Before this module, ``bare_body.prepare`` asked ``gate.evaluate`` three of the questions (the
model's terms, the operator's switch, the adult declaration) and never the fourth: it called the
gate without ``intimate`` and without a design review, while ``prepare_body_surface`` passed both
for an intimate region. A bare body shows everything a garment covered, so it is at least as
intimate as a region profile; the omission meant a library character with an empty review
registry could be built bare on a declaration alone, which the eligibility matrix
(``docs/qa`` in the chatbot) says it must not be. This contract closes that gap, in one place,
and reports every answer — not only the first no — so a refusal says everything that is
missing, not one thing per attempt.

The five questions, each with its own owner, in the order the first refusal is reported:

1. ``author-permission``  — the VRM's own licence (its author). Read strictly, as the gate does.
2. ``operator-switch``    — ``WARDROBE_ADULT_BODY_SURFACE`` (the deployment). Off by default.
3. ``adult-declaration``  — ``avatar.depictsAdult`` (the operator, server-side for the library).
4. ``design-clearance``   — the exact source file, by SHA-256, has either
   * a recorded person's review with ``outcome: "clearly-adult"`` (``adult-design-reviews.json``), or
   * a **synthetic-reference** record (``assets/calibration/synthetic-references.json``): a body
     Forge generated itself, from a declared adult template, whose bytes the registering tool
     reproduced. That is not a review and is never reported as one: it says there is no
     character design to review because the body was built here, to adult survey sizes, faceless
     and without hair. A changed generator produces different bytes, which no record covers.
   A changed file has a different hash, so any edit invalidates either kind of clearance.
5. ``private-session``    — the job is private (``options.private``).

Body integrity is the sixth condition, but it is measured on the document after removal, so
``bare_body`` checks it later and adds it to the same report.

Nothing here reads a caller-supplied review or reference claim: both registries are files on the
server. Nothing here writes to either registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from wardrobe.body_surface.contract import Capability
from wardrobe.body_surface.gate import design_review, evaluate

SYNTHETIC_SCHEMA = "wardrobe.calibration.syntheticReferences.v1"
SYNTHETIC_FILE = "synthetic-references.json"
SYNTHETIC_FIELDS = ("bodyId", "generator", "template", "sizes")


def synthetic_reference(root, source_sha256: str | None) -> dict | None:
    """The synthetic-reference record for these exact bytes, or None (unreadable counts as none)."""
    if not source_sha256:
        return None
    try:
        data = json.loads((Path(root) / SYNTHETIC_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("schema") != SYNTHETIC_SCHEMA:
        return None
    record = (data.get("references") or {}).get(source_sha256)
    if not isinstance(record, dict) or any(not record.get(k) for k in SYNTHETIC_FIELDS):
        return None
    return record


def design_clearance(review_root, reference_root, source_sha256: str | None) -> dict | None:
    """``{"kind": "review"|"synthetic-reference", ...}`` for this exact file, or None."""
    review = design_review(review_root, source_sha256)
    if review and review.get("outcome") == "clearly-adult":
        return {"kind": "review", "reviewer": review["reviewer"], "date": review["date"]}
    reference = synthetic_reference(reference_root, source_sha256)
    if reference:
        return {"kind": "synthetic-reference", "bodyId": reference["bodyId"],
                "generator": reference["generator"]}
    return None


#: BD1. Written evidence a full review gives, at least: the placeholder entries of 2026-11-17
#: ("Its okay is adult", no character, no packet) are not one.
DETAIL_EVIDENCE_CHARS = 40
#: CG10. The detail reviews: a person's second look at a file already found clearly adult, made
#: from Forge's review packet for those exact bytes, with written evidence. Separate from
#: ``adult-design-reviews.json`` because a finding there is write-once: a design reviewed in the
#: Studio before packets existed could otherwise never reach detail without a new file.
DETAIL_REVIEWS_FILE = "adult-detail-reviews.json"
DETAIL_REVIEWS_SCHEMA = "wardrobe.bodySurface.detailReviews.v1"


def detail_review(review_root, source_sha256: str | None) -> dict | None:
    """CG10. The recorded detail review of these exact bytes, or None (incomplete counts as none)."""
    if not source_sha256:
        return None
    from wardrobe.body_surface.review_files import detail_registry

    data = detail_registry(review_root)  # RX2. its own file, or an export committed in its place
    if not data or data.get("schema") != DETAIL_REVIEWS_SCHEMA:
        return None
    entry = (data.get("reviews") or {}).get(source_sha256)
    fields = ("reviewer", "date", "packet", "evidence")
    if not isinstance(entry, dict) or not all(entry.get(k) for k in fields):
        return None
    if entry.get("examined") is not True or len(str(entry["evidence"]).strip()) < DETAIL_EVIDENCE_CHARS:
        return None
    return entry


def detail_clearance(review_root, reference_root, source_sha256: str | None) -> dict | None:
    """BD1. Clearance for painted anatomical detail on these exact bytes, or None.

    Detail is more explicit than the bare body itself, so it asks for more than ``design_clearance``:
    a person's ``clearly-adult`` finding that carries its review packet (the front/back/side
    evidence ``tools/body_surface/review_packet.py`` writes, which ``record_review`` checks is for
    this file) and written evidence of at least ``DETAIL_EVIDENCE_CHARS`` characters — or Forge's
    own synthetic adult reference, which has no character design to review. A finding recorded
    without looking at the packet does not paint detail on anyone.
    """
    review = design_review(review_root, source_sha256)
    if (review and review.get("outcome") == "clearly-adult" and review.get("packet")
            and len(str(review.get("evidence", "")).strip()) >= DETAIL_EVIDENCE_CHARS):
        return {"kind": "review", "reviewer": review["reviewer"], "date": review["date"],
                "packet": review["packet"]}
    # CG10. The same requirements in two records: the design finding (clearly-adult, by a person)
    # and that person's or another's detail review of the same bytes (the packet, written evidence,
    # their statement that they looked). Neither alone is enough.
    if review and review.get("outcome") == "clearly-adult":
        detail = detail_review(review_root, source_sha256)
        if detail:
            return {"kind": "review", "reviewer": detail["reviewer"], "date": detail["date"],
                    "packet": detail["packet"]}
    reference = synthetic_reference(reference_root, source_sha256)
    if reference:
        return {"kind": "synthetic-reference", "bodyId": reference["bodyId"]}
    return None


def detail_status(review_root, reference_root, source_sha256: str | None) -> dict:
    """CG10. For the review page: is detail cleared for these bytes, and if not, what is missing."""
    cleared = detail_clearance(review_root, reference_root, source_sha256)
    review = design_review(review_root, source_sha256)
    detail = detail_review(review_root, source_sha256)
    missing = []
    if not review:
        missing.append("a design review (clearly-adult)")
    elif review.get("outcome") != "clearly-adult":
        missing.append(f"a clearly-adult finding (recorded: {review.get('outcome')})")
    elif not cleared:
        missing.append(f"a detail review: Forge's review packet and at least {DETAIL_EVIDENCE_CHARS} "
                       "characters of written evidence")
    return {
        "cleared": bool(cleared),
        "kind": cleared["kind"] if cleared else None,
        "reviewer": (cleared or {}).get("reviewer"),
        "date": (cleared or {}).get("date"),
        "designEvidenceChars": len(str((review or {}).get("evidence", "")).strip()),
        "detailRecorded": bool(detail),
        "needed": DETAIL_EVIDENCE_CHARS,
        "missing": [] if cleared else missing,
    }


@dataclass
class Eligibility:
    allowed: bool
    refused_by: str | None
    message: str
    checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "refusedBy": self.refused_by, "checks": self.checks}


def assess(*, terms, operator_enabled: bool, depicts_adult: bool, private: bool,
           source_sha256: str | None, review_root, reference_root) -> Eligibility:
    """Every answer for a bare job on this exact source. Pure: reads only the two registries."""
    checks: dict[str, dict] = {}
    # 1-3 are the gate's own questions; asked one at a time so each gets its own answer.
    author = evaluate(Capability.ADULT_BODY_SURFACE, terms, operator_enabled=True, depicts_adult=True)
    checks["author-permission"] = {"passed": author.allowed, "why": "" if author.allowed else author.message}
    checks["operator-switch"] = {"passed": bool(operator_enabled),
                                 "why": "" if operator_enabled else "WARDROBE_ADULT_BODY_SURFACE is off"}
    checks["adult-declaration"] = {"passed": bool(depicts_adult),
                                   "why": "" if depicts_adult else "avatar.depictsAdult is not true"}
    clearance = design_clearance(review_root, reference_root, source_sha256)
    checks["design-clearance"] = {
        "passed": clearance is not None, "sourceSha256": source_sha256, "clearance": clearance,
        "why": "" if clearance else ("no clearly-adult review and no synthetic-reference record for this "
                                     "exact file (adult-design-reviews.json / synthetic-references.json)"),
    }
    checks["private-session"] = {"passed": bool(private),
                                 "why": "" if private else "bare output must be private"}
    first = next((name for name, c in checks.items() if not c["passed"]), None)
    if first is None:
        return Eligibility(True, None, f"bare permitted ({clearance['kind']})", checks)
    return Eligibility(False, first, checks[first]["why"], checks)


__all__ = ["DETAIL_EVIDENCE_CHARS", "DETAIL_REVIEWS_FILE", "DETAIL_REVIEWS_SCHEMA", "Eligibility",
           "detail_review", "detail_status", "SYNTHETIC_FILE", "SYNTHETIC_SCHEMA", "assess",
           "design_clearance", "detail_clearance", "synthetic_reference"]
