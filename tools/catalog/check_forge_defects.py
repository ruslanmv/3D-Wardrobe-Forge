"""Verify the Forge wardrobe defect plan.

    python tools/catalog/check_forge_defects.py
    python tools/catalog/check_forge_defects.py --pose-report /tmp/forge-qa/jeans-verdict.json

Exit 0 when every issue in docs/plans/forge-wardrobe-defects/issues.json satisfies its
verify block and its status is fixed (or not-forge, for the jeans issue only).
Exit 1 while any issue is still open or a status overclaims the files on disk.
Exit 2 when the issue file itself is unreadable.

The jeans verdict is written outside the repository. pose_contact refuses an
in-repo path, and a penetration of 0 mm is not treated as a closed garment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ISSUES = ROOT / "docs" / "plans" / "forge-wardrobe-defects" / "issues.json"
PASS_STATUS = {"fixed", "not-forge"}


def load_issues(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("issues"), list):
        raise ValueError("issues.json has no issues list")
    return data


def _record(report_path: Path, template_id: str) -> dict | None:
    if not report_path.is_file():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for record in report.get("records") or []:
        if record.get("id") == template_id:
            return record
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def check_preview(issue: dict, root: Path) -> list[str]:
    verify = issue["verify"]
    problems = []
    webp = root / verify["webp"]
    if not webp.is_file():
        problems.append(f"missing {verify['webp']}")
        return problems
    try:
        from PIL import Image, ImageStat
    except ImportError:
        problems.append("Pillow is not installed; preview size cannot be checked")
        return problems
    with Image.open(webp) as image:
        if image.size != (verify["width"], verify["height"]):
            problems.append(f"{verify['webp']} is {image.size[0]}x{image.size[1]}, expected {verify['width']}x{verify['height']}")
        if max(ImageStat.Stat(image.convert("RGB")).stddev) < 8:
            problems.append(f"{verify['webp']} is nearly uniform")
    other = verify.get("distinctFrom")
    if other:
        sibling = root / other
        if not sibling.is_file():
            problems.append(f"cannot compare with missing {other}")
        elif _sha256(webp) == _sha256(sibling):
            problems.append(f"{verify['webp']} is the same file as {other}")
    record = _record(root / verify["report"], verify["templateId"])
    if record is None:
        problems.append(f"build report has no record for {verify['templateId']}")
        return problems
    if record.get("status") not in set(verify["acceptedStatus"]):
        problems.append(f"build report status is {record.get('status')!r}")
    if verify.get("requireFitPassed") and record.get("fitPassed") is not True:
        problems.append("build report fitPassed is not true")
    return problems


def check_failure_detail(issue: dict, root: Path) -> list[str]:
    verify = issue["verify"]
    problems = []
    source = (root / verify["source"]).read_text(encoding="utf-8") if (root / verify["source"]).is_file() else ""
    inspector = (root / verify["inspector"]).read_text(encoding="utf-8") if (root / verify["inspector"]).is_file() else ""
    if verify["sourceMustContain"] not in source:
        problems.append(f"{verify['source']} does not record {verify['sourceMustContain']}")
    if verify["inspectorMustContain"] not in inspector:
        problems.append(f"{verify['inspector']} does not print {verify['inspectorMustContain']}")
    diagnosis = issue.get("diagnosis") or {}
    for template_id in verify["templates"]:
        found = diagnosis.get(template_id)
        if not isinstance(found, dict):
            problems.append(f"diagnosis for {template_id} is empty")
            continue
        for field in ("clippingCheck", "checks", "errors"):
            if field not in found:
                problems.append(f"diagnosis for {template_id} has no {field}")
    return problems


def check_pose(issue: dict, pose_report: Path | None) -> list[str]:
    verify = issue["verify"]
    if pose_report is None:
        return ["pass --pose-report with the Sitting (Desk) verdict"]
    if not pose_report.is_file():
        return [f"pose report not found: {pose_report}"]
    verdict = json.loads(pose_report.read_text(encoding="utf-8"))
    problems = []
    for field in ("templateId", "pose", "avatar"):
        if verdict.get(field) != verify[field]:
            problems.append(f"pose report {field} is {verdict.get(field)!r}")
    penetration = verdict.get("maxPenetrationMm")
    if not isinstance(penetration, (int, float)) or penetration > verify["maxPenetrationMmAtMost"]:
        problems.append(f"maxPenetrationMm is {penetration!r}")
    status = issue.get("status")
    visual = verdict.get("visual")
    if status == "not-forge":
        if visual != "closed-in-forge":
            problems.append("not-forge requires visual closed-in-forge")
    elif visual != verify["requireVisual"]:
        problems.append(f"visual is {visual!r}")
    frame = Path(str(verdict.get("frame") or ""))
    if not frame.is_file() or frame.stat().st_size < 10000:
        problems.append("frame is missing or smaller than 10 KB")
    contact = Path(str(verdict.get("contact") or ""))
    if not contact.is_file():
        problems.append("contact JSON is missing")
    return problems


def evaluate(issue: dict, root: Path, pose_report: Path | None) -> list[str]:
    kind = (issue.get("verify") or {}).get("kind")
    if kind == "catalog-preview":
        return check_preview(issue, root)
    if kind == "failure-detail":
        return check_failure_detail(issue, root)
    if kind == "pose-contact":
        return check_pose(issue, pose_report)
    return [f"unknown verify kind {kind!r}"]


def summarize(data: dict, root: Path, pose_report: Path | None) -> tuple[list[str], list[str]]:
    """Return (still open lines, false-claim lines)."""
    open_lines = []
    false_claims = []
    for issue in data["issues"]:
        problems = evaluate(issue, root, pose_report)
        status = issue.get("status")
        label = f"{issue.get('id')} [{status}]"
        if problems:
            open_lines.append(label + ": " + "; ".join(problems))
            if status in PASS_STATUS:
                false_claims.append(label)
        elif status not in PASS_STATUS:
            open_lines.append(f"{label}: verify passed but status is still {status!r}")
        elif status == "not-forge" and issue.get("id") != "WARDROBE-DEFORM-002":
            false_claims.append(label)
            open_lines.append(f"{label}: not-forge is only valid for WARDROBE-DEFORM-002")
    return open_lines, false_claims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--issues", type=Path, default=DEFAULT_ISSUES)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--pose-report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        data = load_issues(args.issues)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    open_lines, false_claims = summarize(data, args.root, args.pose_report)
    if not open_lines and not false_claims:
        print(f"All {len(data['issues'])} Forge defect issues verify.")
        return 0
    print(f"{len(open_lines)} issue(s) still open:")
    for line in open_lines:
        print(f"- {line}")
    if false_claims:
        print("Status overclaims the evidence: " + ", ".join(false_claims), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
