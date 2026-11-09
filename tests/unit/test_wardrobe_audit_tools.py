"""Run the wardrobe audit's own unit tests with the Forge suite.

The audit lives in ``tools/audit/`` with ``unittest`` tests beside it (they
came from 3D-Avatar-Chatbot that way, and ``python -m unittest discover -s
tools/audit`` still works). pytest only collects ``tests/``, so without this
file a broken audit tool would pass CI unnoticed.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

import pytest

AUDIT = Path(__file__).resolve().parents[2] / "tools" / "audit"


def test_the_audit_tools_pass_their_own_tests():
    pytest.importorskip("PIL")
    sys.path.insert(0, str(AUDIT))
    try:
        suite = unittest.defaultTestLoader.discover(str(AUDIT), pattern="test_*.py", top_level_dir=str(AUDIT))
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    finally:
        sys.path.remove(str(AUDIT))
    failures = [f"{case.id()}: {trace.splitlines()[-1]}" for case, trace in result.failures + result.errors]
    assert result.testsRun >= 35, f"only {result.testsRun} audit tests were found"
    assert not failures, "\n".join(failures)
