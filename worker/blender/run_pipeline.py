"""Blender entrypoint for Wardrobe Forge.

Invoked by :class:`wardrobe.engines.blender.BlenderEngine` as::

    blender --background --factory-startup --python-exit-code 1 \
            --python worker/blender/run_pipeline.py -- --spec /path/to/job.json

Everything it needs is in that spec file; it writes the exported VRM, the
preview image and a fit report, then exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

# Blender does not put the project on sys.path, so locate it from this file.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from worker.blender import (  # noqa: E402 - must follow the sys.path fix
    analyze_humanoid,
    export_vrm,
    fit_generated_mesh,
    fit_template,
    generate_body_mask,
    import_garment,
    import_vrm,
    measure_body,
    normalize_pose,
    render_turntable,
    resolve_clipping,
    setup_materials,
    transfer_weights,
    validate_scene,
)


def log(message: str) -> None:
    print(f"[WardrobeForge] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="wardrobe-forge-blender")
    parser.add_argument("--spec", required=True, help="path to the job spec JSON")
    return parser.parse_args(argv)


def run(spec: dict) -> dict:
    report: dict = {"warnings": [], "engine": "blender"}
    options = spec.get("options", {}) or {}
    clearance_m = float(options.get("bodyClearanceMm", 6.0)) / 1000.0

    # ---- 1-2. import and identify the humanoid -------------------------
    import_vrm.clear_scene()
    log(f"importing {spec['sourceVrm']}")
    scene = import_vrm.import_vrm(spec["sourceVrm"])
    armature = scene["armature"]
    if not scene["usedVrmAddon"]:
        report["warnings"].append(
            "the VRM add-on was unavailable on import; VRM metadata may be incomplete"
        )

    humanoid = analyze_humanoid.analyze_humanoid(armature, spec.get("humanoidBoneNames"))
    if humanoid["missing"]:
        raise RuntimeError("missing required humanoid bones: " + ", ".join(humanoid["missing"]))
    bones = humanoid["bones"]
    # Chosen by what drives it, now that the humanoid is known: the largest mesh
    # can be her hair (see worker/blender/body_select.py).
    body = import_vrm.body_mesh(scene["meshes"], bones)
    log(f"resolved {len(bones)} humanoid bones")

    # ---- 3-4. normalise and measure ------------------------------------
    report["normalize"] = normalize_pose.normalize(armature, scene["objects"])
    measurements = measure_body.measure(armature, scene["meshes"], bones)
    report["measurements"] = measurements
    log(f"measured height {measurements['heightM']}m")

    # ---- 5. load the garment -------------------------------------------
    generated_url = spec.get("generatedMeshUrl")
    if generated_url:
        log(f"importing generated mesh {generated_url}")
        garment = import_garment.import_glb(generated_url, name=spec["plan"]["name"])
        import_garment.strip_rig(garment)
        report["cleanup"] = fit_generated_mesh.prepare(garment, measurements)
    else:
        log(f"importing shell {spec['garmentGlb']}")
        garment = import_garment.import_glb(spec["garmentGlb"], name=spec["plan"]["name"])
        import_garment.strip_rig(garment)

    # ---- 6-7. fit to the body ------------------------------------------
    template = spec.get("template") or {}
    fit_policy = template.get("fit", {}) or {}
    fit_template.apply_scale_limits(
        garment,
        min_scale=float(fit_policy.get("minLengthScale", 0.7)),
        max_scale=float(fit_policy.get("maxLengthScale", 1.3)),
    )
    report["fit"] = fit_template.shrinkwrap_to_body(garment, body, offset_m=clearance_m)

    # ---- 8. skin weights ------------------------------------------------
    report["weights"] = transfer_weights.transfer(garment, body, armature)
    weight_check = transfer_weights.validate(garment)
    report["weightsValid"] = bool(weight_check["valid"])
    report["bonesUsed"] = report["weights"]["bones"]
    if not weight_check["valid"]:
        report["warnings"].append(f"weight transfer left gaps: {weight_check}")

    # ---- 9-10. clipping and body masking --------------------------------
    detection = resolve_clipping.detect(garment, body, clearance_m=clearance_m)
    if detection["violationRatio"] > 0.0:
        report["repair"] = resolve_clipping.repair(garment, body, clearance_m=clearance_m)
        detection = resolve_clipping.detect(garment, body, clearance_m=clearance_m)
    report["clipping"] = detection
    report["clippingCheck"] = resolve_clipping.verdict(detection)

    # Masking hides the body under the garment so it cannot poke through. Under a
    # see-through garment that would hide exactly what the fabric is meant to
    # show — the body between fishnet threads, through sheer chiffon — so the
    # engine sends "none" there and clearance alone keeps the body inside.
    if spec.get("maskPolicy", "body-only") == "none":
        coverage = {"masked": False, "reason": "see-through garment: the body under it stays visible"}
        log("body masking skipped: see-through garment")
    else:
        coverage = generate_body_mask.apply_mask(body, garment, margin_m=max(clearance_m * 2.5, 0.015))
        log(f"masked {coverage.get('coveredVertices', 0)} body vertices")
    report["coverage"] = coverage

    # ---- 11. materials ---------------------------------------------------
    report["materials"] = setup_materials.setup(
        garment, spec["plan"], name=spec.get("materialName"), resolved=spec.get("material")
    )

    # ---- 12. validate before exporting -----------------------------------
    issues = validate_scene.check_scene(armature, body, garment)
    if issues:
        raise RuntimeError("scene validation failed: " + "; ".join(issues))
    report["poseTests"] = validate_scene.run_pose_tests(armature, garment, bones)

    report["garmentVertices"] = len(garment.data.vertices)
    report["garmentTriangles"] = len(garment.data.polygons)

    # ---- 13. export ------------------------------------------------------
    report["export"] = export_vrm.export_vrm(
        spec["outputVrm"],
        armature=armature,
        output_version=options.get("outputVersion", "source"),
    )
    log(f"exported {report['export']['sizeBytes']} bytes")

    # ---- 14. preview -----------------------------------------------------
    if options.get("renderPreview", True):
        try:
            report["preview"] = render_turntable.render(spec["previewImage"], [body, garment])
        except Exception as exc:  # noqa: BLE001 - a preview is never fatal
            report["warnings"].append(f"preview rendering failed: {exc}")

    return report


def main() -> int:
    args = parse_args()
    with open(args.spec, encoding="utf-8") as handle:
        spec = json.load(handle)

    report_path = spec.get("reportPath")
    try:
        report = run(spec)
        report["ok"] = True
    except Exception as exc:  # noqa: BLE001 - report it, then fail the process
        traceback.print_exc()
        report = {"ok": False, "error": str(exc), "warnings": [], "engine": "blender"}
        if report_path:
            _write(report_path, report)
        return 1

    if report_path:
        _write(report_path, report)
    return 0


def _write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
