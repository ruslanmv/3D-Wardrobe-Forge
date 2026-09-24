"""The native, Blender-free fitting engine.

Rather than deforming a donor mesh onto an unknown body, it *builds* the
garment shell at the avatar's own measurements, binds it to that avatar's own
humanoid bones, pushes any intersecting vertices outside the body, and writes
the result straight into the VRM. Deterministic, dependency-light, and the
engine CI runs on every commit.
"""

from __future__ import annotations

import logging

import numpy as np

from wardrobe.config import Settings
from wardrobe.engines.base import FittingEngine
from wardrobe.engines.geometry_checks import pose_stress_test
from wardrobe.engines.shell import build_fitted_shell, shell_coverage
from wardrobe.errors import FittingError
from wardrobe.geometry.raster import RenderLayer, render
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.garments import garment_material_name
from wardrobe.vrm.merge import GarmentMaterial, attach_garment, set_title, tag_derived
from wardrobe.vrm.skinning import bind_mesh, bones_for_coverage, build_bone_segments, weight_report

logger = logging.getLogger(__name__)

GENERATOR = "3D-Wardrobe-Forge (native engine)"


class NativeEngine(FittingEngine):
    name = "native"
    supports_raw_mesh = False
    supports_body_masking = False

    @classmethod
    def available(cls, settings: Settings) -> bool:
        return True

    # ------------------------------------------------------------------
    async def fit_garment(self, context: PipelineContext) -> None:
        if context.info is None or context.measurements is None or context.document is None:
            raise FittingError("avatar analysis must run before fitting")
        if context.plan is None or context.artifact is None:
            raise FittingError("outfit planning must run before fitting")

        artifact = context.artifact
        if artifact.metadata.get("requiresBlender"):
            raise FittingError(
                "this garment was produced by an AI mesh provider and needs the Blender "
                "engine to be cleaned and fitted; set WARDROBE_ENGINE=blender or use "
                "outfit.mode='auto'"
            )

        shell = build_fitted_shell(context)
        mesh = shell.mesh

        # ---- skin binding ----------------------------------------------
        regions = artifact.anchors or artifact.coverage
        candidates = bones_for_coverage(regions)
        if not candidates:
            raise FittingError(f"template declares no usable anchor regions: {regions}")

        segments = build_bone_segments(context.info.humanoid_bones, context.measurements, candidates)
        if not segments:
            raise FittingError(
                "none of the garment's anchor bones exist on this avatar: " + ", ".join(candidates)
            )
        bind_mesh(mesh, segments)

        issues = mesh.validate()
        if issues:
            raise FittingError("; ".join(issues))

        context.mesh = mesh
        context.segments = segments

        report = context.fit_report
        report.engine = self.name
        report.garment_vertices = mesh.vertex_count
        report.garment_triangles = mesh.triangle_count
        report.clipping_check = shell.verdict
        report.coverage = shell_coverage(shell, artifact.coverage)
        report.measurements = context.measurements.to_dict()
        report.pose_tests = pose_stress_test(
            mesh, segments, {k: np.array(v) for k, v in context.measurements.bone_positions.items()}
        )

        weights = weight_report(mesh, segments)
        report.weights_valid = bool(weights.get("valid"))
        report.bones_used = list(weights.get("bonesUsed", []))
        if not report.weights_valid:
            context.warn(f"skin weights failed validation: {weights}")

    # ------------------------------------------------------------------
    async def assemble(self, context: PipelineContext) -> None:
        if context.document is None or context.info is None or context.mesh is None:
            raise FittingError("nothing to assemble; fitting did not complete")

        plan = context.plan
        artifact_kind = context.artifact.procedural_kind if context.artifact else None
        kind = artifact_kind or (plan.category if plan else "")
        material = GarmentMaterial(
            name=garment_material_name(plan.name, kind) if plan else "Garment",
            base_color=tuple(plan.material.base_color) if plan else (0.6, 0.6, 0.6, 1.0),
            metallic=plan.material.metallic if plan else 0.0,
            roughness=plan.material.roughness if plan else 0.7,
        )

        attach_garment(
            context.document,
            context.info,
            context.mesh,
            context.segments,
            material=material,
            name=plan.name if plan else "Garment",
        )

        title = f"{context.info.title or 'Avatar'} — {plan.name}" if plan else context.info.title
        if title:
            set_title(context.document, context.info, title[:100])
        tag_derived(
            context.document,
            source_hash=context.source_sha256,
            look_id=context.look_id,
            generator=GENERATOR,
        )

        context.output_bytes = context.document.to_bytes()

    # ------------------------------------------------------------------
    async def render_preview(self, context: PipelineContext) -> None:
        if context.output_bytes is None:
            return
        try:
            layers = self._render_layers(context)
            context.preview_bytes = render(layers)
        except Exception as exc:  # a preview is never worth failing a job over
            logger.warning("preview rendering failed: %s", exc)
            context.warn(f"preview rendering failed: {exc}")

    def _render_layers(self, context: PipelineContext) -> list[RenderLayer]:
        document = context.document
        assert document is not None
        accessors = document.gltf.get("accessors") or []
        layers: list[RenderLayer] = []

        garment_mesh_names = {context.plan.name} if context.plan else set()

        for node_index in document.mesh_nodes():
            node = document.nodes[node_index]
            mesh = document.meshes[node["mesh"]]
            matrix = document.world_matrices()[node_index]
            skinned = "skin" in node
            is_garment = mesh.get("name") in garment_mesh_names

            for primitive in mesh.get("primitives", []):
                attributes = primitive.get("attributes", {})
                position = attributes.get("POSITION")
                index_accessor = primitive.get("indices")
                if position is None or index_accessor is None or position >= len(accessors):
                    continue

                points = document.read_accessor(position).astype(np.float64)[:, :3]
                if not skinned:
                    homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
                    points = (homogeneous @ matrix.T)[:, :3]
                indices = document.read_accessor(index_accessor).reshape(-1).astype(np.int64)

                if is_garment and context.plan is not None:
                    colour = tuple(float(c) for c in context.plan.material.base_color[:3])
                else:
                    colour = (0.76, 0.70, 0.66)
                layers.append(RenderLayer(positions=points, indices=indices, color=colour))

        return layers


__all__ = ["NativeEngine", "GENERATOR"]
