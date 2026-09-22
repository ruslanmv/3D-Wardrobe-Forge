"""``wardrobe-forge`` command line interface.

    wardrobe-forge create --avatar mira.vrm --prompt "elegant dark red evening dress"

produces::

    output/
    ├── mira-red-evening.vrm
    ├── preview.webp
    ├── wardrobe.json
    └── fit-report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

from wardrobe import __version__
from wardrobe.config import Settings, get_settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest, JobRecord, JobState
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.policy.file_safety import sanitize_component
from wardrobe.queue.jobs import AsyncioJobQueue
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
from wardrobe.storage.object_store import LocalObjectStore
from wardrobe.targets import TargetName, package_yourfriend_bundle
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document, validate_humanoid
from wardrobe.vrm.measure import measure_body

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REJECTED = 2


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-") or "look"


def _build_orchestrator(root: Path, settings: Settings) -> Orchestrator:
    store = LocalObjectStore(root, settings)
    return Orchestrator(
        settings=settings,
        store=store,
        jobs=InMemoryJobRepository(),
        wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(settings.template_root_path),
    )


# ----------------------------------------------------------------------
# create
# ----------------------------------------------------------------------
async def _create(args: argparse.Namespace) -> int:
    avatar_path = Path(args.avatar).expanduser().resolve()
    if not avatar_path.is_file():
        print(f"error: avatar not found: {avatar_path}", file=sys.stderr)
        return EXIT_FAILED

    settings = get_settings().model_copy(
        update={
            "wardrobe_engine": args.engine,
            "strict_licensing": not args.skip_license_check,
        }
    )

    target = TargetName(args.target or settings.wardrobe_target)
    default_out = "dist/yourfriend-online" if target is TargetName.YOURFRIEND else "output"
    output_dir = Path(args.out or default_out).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="wardrobe-cli-") as scratch:
        orchestrator = _build_orchestrator(Path(scratch), settings)

        source_key = f"sources/{sanitize_component(avatar_path.name, fallback='avatar.vrm')}"
        await orchestrator.store.put(source_key, avatar_path.read_bytes())

        avatar_id = args.avatar_id or avatar_path.stem
        request = CreateJobRequest.model_validate(
            {
                "avatar": {
                    "storageKey": source_key,
                    "avatarId": avatar_id,
                    "name": avatar_path.stem,
                    "license": {"userAttestsModificationAllowed": bool(args.attest)},
                },
                "outfit": {
                    "prompt": args.prompt,
                    "mode": args.mode,
                    "templateId": args.template,
                },
                "options": {
                    "renderPreview": not args.no_preview,
                    "engine": args.engine,
                    "wardrobeId": avatar_id,
                },
            }
        )

        record = await orchestrator.run_now(request)
        _report(record)

        if record.state is not JobState.COMPLETED or record.look is None:
            return EXIT_REJECTED if record.state is JobState.REJECTED else EXIT_FAILED

        written = await _write_outputs(
            orchestrator,
            record,
            output_dir,
            avatar_path,
            avatar_id,
            target=target,
            settings=settings,
        )

    print(f"\noutput/ ({output_dir})")
    for path in written:
        print(f"├── {path.name}  ({path.stat().st_size} bytes)")
    return EXIT_OK


async def _write_outputs(
    orchestrator: Orchestrator,
    record: JobRecord,
    output_dir: Path,
    avatar_path: Path,
    avatar_id: str,
    *,
    target: TargetName,
    settings: Settings,
) -> list[Path]:
    look = record.look
    assert look is not None

    if target is TargetName.GENERIC:
        return await _write_generic_outputs(
            orchestrator, record, output_dir, avatar_path, avatar_id
        )

    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise RuntimeError(f"pipeline completed without wardrobe manifest for {avatar_id!r}")

    look_key = f"looks/{look.id}"
    vrm_bytes = await orchestrator.store.get(f"{look_key}/look.vrm")
    preview_bytes = None
    if look.preview_url:
        preview_bytes = await orchestrator.store.get(f"{look_key}/preview.webp")

    return package_yourfriend_bundle(
        output_dir,
        look=look,
        manifest=manifest,
        record=record,
        vrm_bytes=vrm_bytes,
        preview_bytes=preview_bytes,
        avatar_id=avatar_id,
        forge_version=__version__,
        engine=record.fit_report.engine if record.fit_report is not None else settings.wardrobe_engine,
        provider=settings.wardrobe_provider,
    )


async def _write_generic_outputs(
    orchestrator: Orchestrator,
    record: JobRecord,
    output_dir: Path,
    avatar_path: Path,
    avatar_id: str,
) -> list[Path]:
    look = record.look
    assert look is not None
    written: list[Path] = []

    look_key = f"looks/{look.id}"
    vrm_name = f"{_slug(avatar_path.stem)}-{_slug(look.name)}.vrm"

    vrm_path = output_dir / vrm_name
    vrm_path.write_bytes(await orchestrator.store.get(f"{look_key}/look.vrm"))
    written.append(vrm_path)

    if look.preview_url:
        preview_path = output_dir / "preview.webp"
        preview_path.write_bytes(await orchestrator.store.get(f"{look_key}/preview.webp"))
        written.append(preview_path)

    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is not None:
        # Point the manifest at the file we just wrote, not at scratch storage.
        stored = manifest.get(look.id)
        if stored is not None:
            stored.vrm_url = vrm_name
            stored.preview_url = "preview.webp" if look.preview_url else None
        manifest_path = output_dir / "wardrobe.json"
        manifest_path.write_text(manifest.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        written.append(manifest_path)

    if record.fit_report is not None:
        report_path = output_dir / "fit-report.json"
        report_path.write_text(
            record.fit_report.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
        )
        written.append(report_path)

    return written


def _report(record: JobRecord) -> None:
    print(f"job {record.id}: {record.state}")
    if record.plan is not None:
        plan = record.plan
        print(
            f"  plan: {plan.name}  [{plan.category}/{plan.silhouette}/{plan.hem}]  "
            f"template={plan.template_id}  confidence={plan.confidence}"
        )
    if record.error:
        print(f"  error: {record.error}", file=sys.stderr)
        if record.reason:
            print(f"  reason: {record.reason}", file=sys.stderr)

    report = record.fit_report
    if report is None:
        return
    checks = [
        ("vrm valid", report.vrm_valid),
        ("humanoid valid", report.humanoid_valid),
        ("weights valid", report.weights_valid),
        ("skeleton preserved", report.skeleton_preserved),
        ("expressions preserved", report.expressions_preserved),
        ("source recoverable", report.source_recoverable),
        ("preview rendered", report.preview_rendered),
    ]
    print(f"  fit report (engine={report.engine}):")
    for label, value in checks:
        print(f"    {'PASS' if value else 'FAIL'}  {label}")
    print(f"    ----  clipping: {report.clipping_check}")
    print(f"    ----  garment: {report.garment_vertices} verts / {report.garment_triangles} tris")
    for warning in report.warnings:
        print(f"    warn: {warning}")


# ----------------------------------------------------------------------
# other commands
# ----------------------------------------------------------------------
def _inspect(args: argparse.Namespace) -> int:
    path = Path(args.avatar).expanduser().resolve()
    document = GltfDocument.from_bytes(path.read_bytes())
    info = inspect_document(document)
    issues = validate_humanoid(document, info)
    measurements = measure_body(document, info)

    print(
        json.dumps(
            {
                "file": str(path),
                "vrm": info.to_dict(),
                "measurements": measurements.to_dict(),
                "issues": issues,
            },
            indent=2,
        )
    )
    return EXIT_OK if not issues else EXIT_FAILED


def _templates(args: argparse.Namespace) -> int:
    catalog = TemplateCatalog.from_directory(get_settings().template_root_path)
    for template in sorted(catalog.all(), key=lambda t: (t.category, t.id)):
        print(f"{template.category:10s} {template.id:28s} {template.name:24s} tags={','.join(template.tags)}")
    issues = catalog.validate_all()
    for issue in issues:
        print(f"invalid: {issue}", file=sys.stderr)
    return EXIT_OK if not issues else EXIT_FAILED


def _fixtures(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    for body in CALIBRATION_BODIES:
        for spec in ("VRM0", "VRM1"):
            path = out / f"{body.name}-{spec.lower()}.vrm"
            path.write_bytes(build_vrm(body, spec=spec))
            print(f"wrote {path} ({path.stat().st_size} bytes)")
    return EXIT_OK


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wardrobe-forge", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="generate a new look for an avatar")
    create.add_argument("--avatar", required=True, help="path to the source .vrm")
    create.add_argument("--prompt", required=True, help="the outfit to generate")
    create.add_argument("--out", default=None, help="output directory (target-specific default)")
    create.add_argument(
        "--target",
        default=None,
        choices=[item.value for item in TargetName],
        help="delivery target (default: WARDROBE_TARGET, normally yourfriend)",
    )
    create.add_argument("--mode", default="auto", choices=["auto", "template", "generated"])
    create.add_argument("--engine", default="auto", choices=["auto", "native", "blender"])
    create.add_argument("--template", default=None, help="force a specific template id")
    create.add_argument("--avatar-id", default=None, help="wardrobe id (default: the file stem)")
    create.add_argument("--no-preview", action="store_true", help="skip preview rendering")
    create.add_argument(
        "--attest",
        action="store_true",
        help="attest that the source model's terms permit modification",
    )
    create.add_argument(
        "--skip-license-check",
        action="store_true",
        help="allow sources with unknown terms (disables strict licensing)",
    )
    create.set_defaults(handler=lambda args: asyncio.run(_create(args)))

    inspect_cmd = sub.add_parser("inspect", help="report what a VRM contains")
    inspect_cmd.add_argument("--avatar", required=True)
    inspect_cmd.set_defaults(handler=_inspect)

    templates = sub.add_parser("templates", help="list the garment library")
    templates.set_defaults(handler=_templates)

    fixtures = sub.add_parser("fixtures", help="generate the calibration avatars")
    fixtures.add_argument("--out", default="assets/fixtures")
    fixtures.set_defaults(handler=_fixtures)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
