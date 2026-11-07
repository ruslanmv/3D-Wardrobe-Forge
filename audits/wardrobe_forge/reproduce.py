"""Forge adaptation of the HomePilot wardrobe audit.

The chatbot runner opens Try-On in a browser. This one stays in Forge: it
reads the catalog build report, fits the templates that report names, and
writes a front diagnostic of each fitted file. A diagnostic is not a catalog
preview. A preview still has to come from tools/catalog/render_templates.py
after FitReport.passed is true.

    python audits/wardrobe_forge/reproduce.py
    python audits/wardrobe_forge/reproduce.py --fit trousers-leggings-v1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "assets" / "catalog" / "build-report.json"
ISSUES = ROOT / "docs" / "plans" / "forge-wardrobe-defects" / "issues.json"
OUT = Path("/tmp/forge-qa")

# The public templates whose catalog preview is missing because the fit did not pass.
BAD_FITS = (
    ("trousers-leggings-v1", "black Leggings"),
    ("trousers-leggings-highwaist-v1", "black High-Waist Leggings"),
    ("trousers-leggings-seamless-v1", "black Seamless Scrunch Leggings"),
)


def bad_records() -> list[dict]:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    return [
        record for record in report.get("records") or []
        if record.get("status") == "failed-or-ineligible"
    ]


def fit_one(template: str, prompt: str, avatar: str, out: Path) -> dict:
    destination = out / f"{template}.vrm"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "inspect" / "fit_look.py"),
            "--avatar",
            avatar,
            "--prompt",
            prompt,
            "--template",
            template,
            "--base-body",
            "replace-outer",
            "--out",
            str(destination),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    text = completed.stdout.strip()
    payload = json.loads(text[text.find("{") : text.rfind("}") + 1]) if "{" in text else {}
    payload["returncode"] = completed.returncode
    payload["stderr"] = completed.stderr[-500:]
    payload["vrm"] = str(destination) if destination.is_file() else ""
    if destination.is_file():
        sys.path.insert(0, str(ROOT))
        from audits.wardrobe_forge.snapshot import front_png

        frame = out / f"{template}-front.png"
        front_png(destination, frame, f"{template} fitPassed={payload.get('fitPassed')}")
        payload["frame"] = str(frame)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", default="avatar-sample-a")
    parser.add_argument(
        "--fit", nargs="*", default=None,
        help="Template ids to fit. Default: the three bad leggings.",
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    print("Build report failures:")
    for record in bad_records():
        print(f"  {record.get('id')}: fitPassed={record.get('fitPassed')} reason={record.get('reason')}")
    wanted = args.fit if args.fit is not None else [item[0] for item in BAD_FITS]
    prompts = dict(BAD_FITS)
    results = []
    for template in wanted:
        print(f"Fitting {template}...", flush=True)
        fitted = fit_one(template, prompts.get(template, template), args.avatar, args.out)
        results.append({"template": template, **fitted})
        shown = {
            key: results[-1][key]
            for key in ("template", "fitPassed", "clippingCheck", "checks", "errors", "frame")
            if key in results[-1]
        }
        print(json.dumps(shown, indent=1))
    (args.out / "audit.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"Wrote {args.out / 'audit.json'}")
    if ISSUES.is_file():
        print(f"Issue plan: {ISSUES}")
    return 0 if all(item.get("fitPassed") for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
