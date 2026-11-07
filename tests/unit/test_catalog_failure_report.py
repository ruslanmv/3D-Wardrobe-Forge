"""A failed catalog fit keeps the check that rejected it.

The renderer used to store only "fit not verified" when a completed job had an
empty error. This test builds that record without downloading an avatar.
"""

from __future__ import annotations

from wardrobe.domain.looks import ClippingCheck, FitReport, fit_failure_detail


def test_a_completed_job_with_a_failed_fit_names_the_check():
    report = FitReport(
        vrmValid=True,
        humanoidValid=True,
        weightsValid=False,
        skeletonPreserved=True,
        sourceRecoverable=True,
        clippingCheck=ClippingCheck.WARNINGS,
    )
    detail = fit_failure_detail(report)
    assert detail["clippingCheck"] == "warnings"
    assert detail["checks"]["structure"] == "failed"
    assert detail["checks"]["clearance"] == "warnings"
    assert detail["errors"] == []
    assert detail["unplanned"] == []
    assert report.passed is False


def test_a_missing_report_is_explicit():
    assert fit_failure_detail(None) == {
        "clippingCheck": None,
        "checks": None,
        "errors": [],
        "unplanned": [],
    }
