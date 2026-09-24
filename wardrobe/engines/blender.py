"""Headless Blender engine.

The Python side does no geometry here: it writes a job spec, runs Blender with
``worker/blender/run_pipeline.py``, and reads back the exported VRM, the render
and a fit report. Blender is what can deform authored meshes, transfer weights
from the body and delete covered body polygons — the things the native engine
deliberately does not attempt.

The subprocess is bounded (timeout, captured output, no shell) because it is
parsing an untrusted model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from wardrobe.config import Settings
from wardrobe.domain.looks import ClippingCheck
from wardrobe.engines.base import FittingEngine
from wardrobe.engines.shell import build_fitted_shell, shell_coverage
from wardrobe.errors import FittingError
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.export import mesh_to_glb
from wardrobe.vrm.garments import garment_material_name
from wardrobe.vrm.merge import GarmentMaterial

logger = logging.getLogger(__name__)

GENERATOR = "3D-Wardrobe-Forge (blender engine)"
#: Tail of Blender's output kept when a run fails, for the job's error message.
LOG_TAIL_CHARS = 4000


class BlenderEngine(FittingEngine):
    name = "blender"
    supports_raw_mesh = True
    supports_body_masking = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._output_path: Path | None = None
        self._preview_path: Path | None = None

    @classmethod
    def available(cls, settings: Settings) -> bool:
        return shutil.which(settings.blender_bin) is not None

    # ------------------------------------------------------------------
    async def fit_garment(self, context: PipelineContext) -> None:
        if context.source_path is None:
            raise FittingError("the Blender engine needs the source VRM on disk")
        if context.plan is None or context.artifact is None:
            raise FittingError("outfit planning must run before fitting")

        workdir = context.workdir
        workdir.mkdir(parents=True, exist_ok=True)

        output_path = workdir / "look.vrm"
        preview_path = workdir / "preview.webp"
        report_path = workdir / "fit-report.json"
        spec_path = workdir / "job.json"

        # Build the same measured shell the native engine would, and let
        # Blender refine it against the real body surface.
        shell = build_fitted_shell(context)
        # The same slot marker the native engine writes, so a look built by either
        # engine can have its garment replaced by the next one in an outfit set.
        material_name = garment_material_name(
            context.plan.name, context.artifact.procedural_kind or context.plan.category
        )
        material = GarmentMaterial.from_plan(material_name, context.plan.material)
        garment_path = workdir / "garment.glb"
        garment_path.write_bytes(mesh_to_glb(shell.mesh, name=context.plan.name, material=material))

        template = context.catalog.get(context.artifact.template_id) if context.artifact.template_id else None
        spec = {
            "jobId": context.job_id,
            "lookId": context.look_id,
            "sourceVrm": str(context.source_path),
            "garmentGlb": str(garment_path),
            "generatedMeshUrl": context.artifact.mesh_path if context.artifact.metadata.get(
                "requiresCleanup"
            ) else None,
            "outputVrm": str(output_path),
            "previewImage": str(preview_path),
            "reportPath": str(report_path),
            "generator": GENERATOR,
            "materialName": material_name,
            # The material resolved once, here, so Blender renders what the native
            # engine renders: the same factor, alpha, rim and texture images.
            "material": self._material_spec(material, workdir),
            "options": {
                "outputVersion": context.record.request.options.output_version,
                "renderPreview": context.record.request.options.render_preview,
                "bodyClearanceMm": shell.clearance_m * 1000.0,
            },
            "plan": context.plan.model_dump(by_alias=True, mode="json"),
            "artifact": context.artifact.model_dump(by_alias=True, mode="json"),
            "template": template.model_dump(by_alias=True, mode="json") if template else None,
            "measurements": context.measurements.to_dict() if context.measurements else None,
            "humanoidBones": context.info.humanoid_bones if context.info else {},
            # Blender identifies bones by name, not by glTF node index.
            "humanoidBoneNames": self._bone_names(context),
        }
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        context.mesh = shell.mesh
        context.fit_report.clipping_check = shell.verdict
        context.fit_report.coverage = shell_coverage(shell, context.artifact.coverage)
        if context.measurements is not None:
            context.fit_report.measurements = context.measurements.to_dict()

        await self._run_blender(spec_path)

        if not output_path.exists():
            raise FittingError("Blender finished without writing an output VRM")

        self._output_path = output_path
        self._preview_path = preview_path if preview_path.exists() else None

        report = context.fit_report
        report.engine = self.name
        if report_path.exists():
            self._merge_report(context, json.loads(report_path.read_text(encoding="utf-8")))
        else:
            context.warn("Blender produced no fit report; output validation is the only evidence")

    @staticmethod
    def _material_spec(material: GarmentMaterial, workdir: Path) -> dict:
        textures: dict[str, str] = {}
        for slot, data in (("baseColor", material.texture), ("matcap", material.matcap)):
            if data is not None:
                path = workdir / f"{slot}.png"
                path.write_bytes(data)
                textures[slot] = str(path)
        return {
            "name": material.name,
            "finish": material.finish,
            "baseColorFactor": [float(c) for c in material.base_color],
            "metallic": float(material.metallic),
            "roughness": float(material.roughness),
            "alphaMode": material.alpha_mode,
            "alphaCutoff": float(material.alpha_cutoff),
            "rimColor": [float(c) for c in material.rim_color],
            "rimPower": float(material.rim_power),
            "rimLift": float(material.rim_lift),
            "textures": textures,
        }

    @staticmethod
    def _bone_names(context: PipelineContext) -> dict[str, str]:
        """Map humanoid bone -> glTF node name, which Blender imports as the bone name."""
        if context.info is None or context.document is None:
            return {}
        nodes = context.document.nodes
        names: dict[str, str] = {}
        for bone, node_index in context.info.humanoid_bones.items():
            if 0 <= node_index < len(nodes):
                name = nodes[node_index].get("name")
                if name:
                    names[bone] = str(name)
        return names

    async def _run_blender(self, spec_path: Path) -> None:
        command = [
            self.settings.blender_bin,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            self.settings.wardrobe_blender_script,
            "--",
            "--spec",
            str(spec_path),
        ]
        logger.info("running blender: %s", " ".join(command))

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise FittingError(f"Blender executable not found: {self.settings.blender_bin}") from exc

        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=self.settings.blender_timeout_s
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise FittingError(
                f"Blender exceeded the {self.settings.blender_timeout_s}s time limit"
            ) from exc

        output = (stdout or b"").decode("utf-8", errors="replace")
        if process.returncode != 0:
            raise FittingError(
                f"Blender exited with code {process.returncode}",
                detail={"log": output[-LOG_TAIL_CHARS:]},
            )
        logger.debug("blender output:\n%s", output[-LOG_TAIL_CHARS:])

    def _merge_report(self, context: PipelineContext, payload: dict) -> None:
        report = context.fit_report
        report.garment_vertices = int(payload.get("garmentVertices", 0))
        report.garment_triangles = int(payload.get("garmentTriangles", 0))
        report.weights_valid = bool(payload.get("weightsValid", False))
        report.bones_used = list(payload.get("bonesUsed", []))
        report.coverage = dict(payload.get("coverage", {}))
        report.pose_tests = dict(payload.get("poseTests", {}))
        if payload.get("measurements"):
            report.measurements = dict(payload["measurements"])

        try:
            report.clipping_check = ClippingCheck(str(payload.get("clippingCheck", "not-run")))
        except ValueError:
            report.clipping_check = ClippingCheck.NOT_RUN

        for warning in payload.get("warnings", []):
            context.warn(str(warning))

    # ------------------------------------------------------------------
    async def assemble(self, context: PipelineContext) -> None:
        if self._output_path is None:
            raise FittingError("Blender did not produce an output to assemble")
        context.output_bytes = await asyncio.to_thread(self._output_path.read_bytes)

    async def render_preview(self, context: PipelineContext) -> None:
        if self._preview_path is None:
            return
        try:
            context.preview_bytes = await asyncio.to_thread(self._preview_path.read_bytes)
        except OSError as exc:  # pragma: no cover - disk-level failure
            context.warn(f"could not read the rendered preview: {exc}")


__all__ = ["BlenderEngine", "GENERATOR"]
