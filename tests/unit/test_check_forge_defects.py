"""The defect checker accepts a real preview and rejects a copied or unfitted one."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "check_forge_defects",
    Path(__file__).resolve().parents[2] / "tools" / "catalog" / "check_forge_defects.py",
)
assert _SPEC and _SPEC.loader
_CHECK = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CHECK)
check_failure_detail = _CHECK.check_failure_detail
check_pose = _CHECK.check_pose
check_preview = _CHECK.check_preview
summarize = _CHECK.summarize


def _webp(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (480, 640), color)
    ImageDraw.Draw(image).rectangle((0, 0, 240, 640), fill=(255, 40, 40))
    image.save(path, "WEBP", quality=80)


def _issue(template: str, webp: str, distinct: str | None = None) -> dict:
    verify = {
        "kind": "catalog-preview",
        "templateId": template,
        "webp": webp,
        "width": 480,
        "height": 640,
        "report": "build-report.json",
        "acceptedStatus": ["generated", "cached"],
        "requireFitPassed": True,
    }
    if distinct:
        verify["distinctFrom"] = distinct
    return {"id": "WARDROBE-UI-F181", "status": "fixed", "verify": verify}


def test_a_missing_preview_stays_open(tmp_path: Path):
    problems = check_preview(_issue("trousers-leggings-v1", "leggings.webp"), tmp_path)
    assert any("missing" in problem for problem in problems)


def test_a_fitted_preview_passes_and_a_copy_does_not(tmp_path: Path):
    _webp(tmp_path / "a.webp", (20, 20, 20))
    _webp(tmp_path / "b.webp", (20, 20, 80))
    report = {
        "records": [
            {"id": "trousers-leggings-v1", "status": "generated", "fitPassed": True},
            {"id": "trousers-leggings-highwaist-v1", "status": "generated", "fitPassed": True},
        ]
    }
    (tmp_path / "build-report.json").write_text(json.dumps(report), encoding="utf-8")
    plain = _issue("trousers-leggings-v1", "a.webp")
    assert check_preview(plain, tmp_path) == []
    high = _issue("trousers-leggings-highwaist-v1", "b.webp", distinct="a.webp")
    assert check_preview(high, tmp_path) == []
    (tmp_path / "b.webp").write_bytes((tmp_path / "a.webp").read_bytes())
    assert any("same file" in problem for problem in check_preview(high, tmp_path))


def test_unfitted_report_is_not_a_ready_preview(tmp_path: Path):
    _webp(tmp_path / "a.webp", (30, 30, 30))
    (tmp_path / "build-report.json").write_text(
        json.dumps({"records": [{"id": "trousers-leggings-v1", "status": "failed-or-ineligible", "fitPassed": False}]}),
        encoding="utf-8",
    )
    problems = check_preview(_issue("trousers-leggings-v1", "a.webp"), tmp_path)
    assert any("fitPassed" in problem for problem in problems)
    assert any("status" in problem for problem in problems)


def test_failure_detail_requires_the_source_and_a_copied_diagnosis(tmp_path: Path):
    (tmp_path / "render.py").write_text("reason = 'fit not verified'\n", encoding="utf-8")
    (tmp_path / "fit_look.py").write_text("print(state)\n", encoding="utf-8")
    issue = {
        "diagnosis": {"trousers-leggings-v1": None},
        "verify": {
            "kind": "failure-detail",
            "source": "render.py",
            "sourceMustContain": "fit_report.checks",
            "inspector": "fit_look.py",
            "inspectorMustContain": "clippingCheck",
            "templates": ["trousers-leggings-v1"],
        },
    }
    problems = check_failure_detail(issue, tmp_path)
    assert any("fit_report.checks" in problem for problem in problems)
    assert any("clippingCheck" in problem for problem in problems)
    assert any("diagnosis" in problem for problem in problems)
    (tmp_path / "render.py").write_text("record['checks'] = result.fit_report.checks\n", encoding="utf-8")
    (tmp_path / "fit_look.py").write_text('payload["clippingCheck"] = str(report.clipping_check)\n', encoding="utf-8")
    issue["diagnosis"] = {"trousers-leggings-v1": {"clippingCheck": "warnings", "checks": {"structure": "passed"}, "errors": []}}
    assert check_failure_detail(issue, tmp_path) == []


def test_pose_verdict_needs_a_frame_and_not_forge_is_its_own_visual(tmp_path: Path):
    frame = tmp_path / "front.png"
    frame.write_bytes(b"x" * 12000)
    contact = tmp_path / "contact.json"
    contact.write_text("{}", encoding="utf-8")
    issue = {
        "id": "WARDROBE-DEFORM-002",
        "status": "fixed",
        "verify": {
            "kind": "pose-contact",
            "templateId": "jeans-straight-v1",
            "pose": "sittingDesk",
            "avatar": "fem-vroid",
            "maxPenetrationMmAtMost": 1.0,
            "requireVisual": "closed",
        },
    }
    assert check_pose(issue, None)  # a missing report is not a pass
    verdict = tmp_path / "verdict.json"
    verdict.write_text(
        json.dumps(
            {
                "templateId": "jeans-straight-v1",
                "pose": "sittingDesk",
                "avatar": "fem-vroid",
                "maxPenetrationMm": 0.4,
                "visual": "closed",
                "frame": str(frame),
                "contact": str(contact),
            }
        ),
        encoding="utf-8",
    )
    assert check_pose(issue, verdict) == []
    issue["status"] = "not-forge"
    assert any("closed-in-forge" in problem for problem in check_pose(issue, verdict))


def test_summarize_keeps_a_passing_verify_open_until_status_moves(tmp_path: Path):
    _webp(tmp_path / "a.webp", (12, 12, 12))
    (tmp_path / "build-report.json").write_text(
        json.dumps({"records": [{"id": "trousers-leggings-v1", "status": "generated", "fitPassed": True}]}),
        encoding="utf-8",
    )
    issue = _issue("trousers-leggings-v1", "a.webp")
    issue["status"] = "open"
    open_lines, false_claims = summarize({"issues": [issue]}, tmp_path, None)
    assert open_lines and not false_claims
    issue["status"] = "fixed"
    assert summarize({"issues": [issue]}, tmp_path, None) == ([], [])
