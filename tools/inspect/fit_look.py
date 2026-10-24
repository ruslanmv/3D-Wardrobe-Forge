"""Fit one look on a library avatar through the real pipeline and save the VRM: research input.

    python tools/inspect/fit_look.py --avatar fem-vroid --prompt "red bodycon mini dress" \\
        --template dress-mini-bodycon-v1 --out /tmp/qa/bodycon.vrm

The job is exactly what the API runs for a library avatar: the avatar's own licence and adult
declaration (assets/library/policy.json), native engine, strict licensing, ``replace-outer``
and Auto Foundation, as HomePilot's Try-On sends. Its fit report is printed; the look is
written to ``--out``. Nothing is stored in the repository and no server is needed.

A look that needs an adult declaration is refused on an avatar without one, as it is in the
product: this tool has no way round the gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402


async def fit(avatar: str, prompt: str, template: str | None, out: Path, base_body: str) -> int:
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    entry = library.get(avatar)
    if entry is None or entry.path is None:
        raise SystemExit(f"no library avatar {avatar!r} with its file present (make library)")
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            _env_file=None,
            wardrobe_storage_root=str(Path(tmp) / "store"),
            wardrobe_engine="native",
            strict_licensing=True,
        )
        store = LocalObjectStore(settings.storage_root_path, settings)
        orch = Orchestrator(
            settings=settings,
            store=store,
            jobs=InMemoryJobRepository(),
            wardrobes=InMemoryWardrobeRepository(),
            queue=AsyncioJobQueue(concurrency=1),
            catalog=catalog,
        )
        await library.seed(store)
        outfit = {"prompt": prompt, "mode": "template" if template else "auto"}
        if template:
            outfit["templateId"] = template
        record = await orch.run_now(
            CreateJobRequest.model_validate(
                {
                    "avatar": entry.avatar_input(),
                    "outfit": outfit,
                    "options": {
                        "renderPreview": False,
                        "engine": "native",
                        "baseBody": base_body,
                        "ensureFoundation": True,
                    },
                }
            )
        )
        report = record.fit_report
        print(
            json.dumps(
                {
                    "state": str(record.state),
                    "error": record.error,
                    "garments": [g.name for g in record.plan.garments] if record.plan else None,
                    "fitPassed": bool(report and report.passed),
                    "poseTests": report.pose_tests if report else None,
                    "warnings": list(report.warnings)[:8] if report else [],
                },
                indent=1,
                default=str,
            )
        )
        if record.look is None:
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
        print(f"look → {out}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--avatar", default="fem-vroid")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--template", default=None)
    parser.add_argument("--base-body", default="replace-outer")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(fit(args.avatar, args.prompt, args.template, args.out, args.base_body))


if __name__ == "__main__":
    raise SystemExit(main())
