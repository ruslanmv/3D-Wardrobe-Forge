#!/usr/bin/env python3
"""Read-only, format-neutral VRM readiness report for arbitrary local VRM 0.x/1.0 files.

Normal clothing is not an adult-content operation. This report separates the ordinary
wardrobe path from restricted wardrobe and bare-body paths so an unreviewed character
is never mistakenly described as unusable for *all* clothing.

It is a preflight, not an authorization token: existing server-side gates, operator
declarations, exact-file design reviews, and renderer/import checks remain authoritative.

Usage:
    python -m tools.vrm_compatibility /path/to/character.vrm
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from wardrobe.body_surface.gate import explicit_usage_disallowed
from wardrobe.policy.intimate import evaluate as intimate_evaluate
from wardrobe.policy.licensing import evaluate as licensing_evaluate
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document, validate_humanoid

MAX_BYTES = 64 * 1024 * 1024


def _decision(status: str, reason: str) -> dict:
    return {"status": status, "reason": reason}


def assess(info, rig_issues: list[str]) -> dict:
    """Preview capabilities, without accepting a user-supplied age or review claim."""
    rights = licensing_evaluate(info.license, strict=True)
    valid_rig = not rig_issues
    base = {
        "spec": str(info.spec),
        "title": info.title,
        "rigValid": valid_rig,
        "rigIssues": list(rig_issues),
        "license": info.license.to_dict(),
        "modificationRights": rights.to_dict(),
    }

    if not valid_rig:
        common = _decision("blocked-invalid-rig", "Fix the required humanoid bones before wardrobe fitting.")
        return {**base, "ordinaryClothing": common, "privateClothing": common,
                "bareBody": common}

    if not rights.allowed:
        status = "needs-license-evidence" if rights.requires_attestation else "blocked-source-terms"
        common = _decision(status, rights.message)
        return {**base, "ordinaryClothing": common, "privateClothing": common,
                "bareBody": common}

    ordinary = _decision(
        "ready-for-wardrobe",
        "Ordinary opaque clothing needs no adult-design review; normal fitting and renderer checks still apply.",
    )

    # The real operator declaration, private session, and consent cannot be asserted by
    # a local CLI. Ask the existing policy whether creator metadata could permit this.
    intimate_author = intimate_evaluate("underwear", info.license, depicts_adult=True)
    if not intimate_author.allowed:
        private = _decision("blocked-source-terms", intimate_author.message)
    else:
        private = _decision(
            "needs-session-and-operator-check",
            "A server-side adult declaration, eligible outfit, and authorized private session "
            "must be verified by the existing Forge and NEXUS controls.",
        )

    if (not intimate_author.allowed or explicit_usage_disallowed(info.license)):
        bare = _decision(
            "blocked-source-terms",
            "The VRM's embedded sexual-usage terms do not permit bare-body output.",
        )
    else:
        bare = _decision(
            "needs-reviewed-adult-body-assets",
            "The existing body-state workflow additionally requires genuine exact-file "
            "adult-design review, rights, operator enablement, a private session, "
            "complete geometry, reviewed output, and an accepted import. "
            "A local preflight never grants these.",
        )

    return {**base, "ordinaryClothing": ordinary, "privateClothing": private,
            "bareBody": bare}


def inspect_file(path: Path) -> dict:
    """Inspect one VRM without importing, modifying, or registering its bytes."""
    length = path.stat().st_size
    if length > MAX_BYTES:
        raise ValueError(f"VRM exceeds the {MAX_BYTES} byte input limit")
    if not length:
        raise ValueError("VRM file is empty")
    data = path.read_bytes()
    document = GltfDocument.from_bytes(data)
    info = inspect_document(document)
    result = assess(info, validate_humanoid(document, info))
    result["sourceSha256"] = hashlib.sha256(data).hexdigest()
    result["sourceBytes"] = length
    result["file"] = str(path)
    result["advisoryOnly"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local, read-only VRM compatibility and capability preflight")
    parser.add_argument("file", type=Path, help="Any local VRM 0.x or VRM 1.0 file")
    args = parser.parse_args(argv)
    try:
        result = inspect_file(args.file)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({"file": str(args.file), "valid": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
