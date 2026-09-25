"""The operator's declaration for the calibration mannequins, from ``assets/calibration/policy.json``.

The library's avatars get theirs from ``assets/library/policy.json``, shipped
empty. The calibration bodies are generated, faceless and built to adult
proportions, and the repository declares them adult in its own policy file so
the verification gallery and the hosiery golden previews go through the same
gate as everything else, with the declaration coming from policy metadata and
not from a tool's source. Nothing in a request reads this file.
"""

from __future__ import annotations

import json
from pathlib import Path

POLICY = Path(__file__).resolve().parents[2] / "assets" / "calibration" / "policy.json"


def declared_adult(body: str, path: Path = POLICY) -> bool:
    """Whether the calibration body named ``body`` is declared adult. Unknown or unreadable: no."""
    try:
        bodies = json.loads(path.read_text(encoding="utf-8")).get("bodies") or {}
    except (OSError, ValueError):
        return False
    return bool((bodies.get(body) or {}).get("depictsAdult") is True)


__all__ = ["POLICY", "declared_adult"]
