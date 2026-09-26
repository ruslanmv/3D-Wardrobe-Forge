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
from wardrobe.domain.looks import ClippingCheck
from wardrobe.engines.base import FittingEngine
from wardrobe.engines.geometry_checks import pose_stress_test
from wardrobe.engines.shell import build_fitted_shell, on_axis_mask, shell_coverage
from wardrobe.errors import FittingError
from wardrobe.geometry.procedural import trim_triangles
from wardrobe.geometry.raster import RenderLayer, render
from wardrobe.geometry.waistband import WAISTBAND_SHADE, waistband_mask
from wardrobe.hosiery import assembly as hosiery_assembly
from wardrobe.hosiery import fit as hosiery_fit
from wardrobe.hosiery.materials import shade_material
from wardrobe.materials.textures import pleat_shading
from wardrobe.pipeline.context import BuiltLayer, PipelineContext
from wardrobe.vrm.garments import garment_material_name, garment_slot
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

        if hosiery_fit.role(context) == "connector":
            await self._fit_connector(context)
            return
        hosiery_fit.before_shell(context)
        shell = build_fitted_shell(context)
        mesh = hosiery_fit.after_shell(context, shell.mesh)

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
        # The garment's body binds to the torso; only pieces off the body's axis
        # (sleeves, stocking legs) may follow the limbs.
        bind_mesh(mesh, segments, torso=on_axis_mask(mesh, context.measurements))
        hosiery_fit.after_bind(context, mesh, segments)

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

    async def _fit_connector(self, context: PipelineContext) -> None:
        """Suspender straps and hardware: built from the fitted belt and stocking tops, not a shell."""
        mesh, segments = hosiery_fit.fit_connector(context)
        issues = mesh.validate()
        if issues:
            raise FittingError("; ".join(issues))
        context.mesh, context.segments = mesh, segments
        report = context.fit_report
        report.engine = self.name
        report.garment_vertices = mesh.vertex_count
        report.garment_triangles = mesh.triangle_count
        # Nothing to push out of the body: each strap was laid on it, a gap above what is under it.
        report.clipping_check = ClippingCheck.CLEARANCE_ONLY
        report.coverage = {"regions": ["hips", "upperLegs"]}
        report.pose_tests = pose_stress_test(
            mesh, segments, {k: np.array(v) for k, v in context.measurements.bone_positions.items()}
        )
        weights = weight_report(mesh, segments)
        report.weights_valid = bool(weights.get("valid"))
        report.bones_used = list(weights.get("bonesUsed", []))

    # ------------------------------------------------------------------
    async def assemble(self, context: PipelineContext) -> None:
        if context.document is None or context.info is None or context.mesh is None:
            raise FittingError("nothing to assemble; fitting did not complete")

        plan = context.plan
        if plan is None or context.artifact is None:
            raise FittingError("nothing to assemble; planning did not complete")
        layers = context.built or [BuiltLayer(plan, context.artifact, context.mesh, context.segments)]
        for layer in layers:
            kind = layer.artifact.procedural_kind or layer.plan.category
            material = layer.plan.material
            # A see-through garment's straps and elastic stay opaque: its own colour
            # and finish, no pattern, no alpha — a second material on the same mesh.
            trim_plan = material.model_copy(
                update={"opacity": 1.0, "alpha_mode": "opaque", "pattern": "none", "texture_scale": 0.0,
                        "lined": False}
            ) if material.exposes_body else None
            hosiery_parts = hosiery_assembly.primitives(layer, kind)
            if hosiery_parts is not None:
                fabric_material, trim_mask, trim_mat, extra = hosiery_parts
                attached = attach_garment(
                    context.document, context.info, layer.mesh, layer.segments,
                    material=fabric_material, name=layer.plan.name,
                    trim=trim_mask, trim_material=trim_mat, extra=extra,
                )
            else:
                fabric = GarmentMaterial.from_plan(garment_material_name(layer.plan.name, kind), material)
                if layer.mesh.metadata.get("pleatShading") and material.pattern == "none":
                    # Knife pleats read by their shadows (wardrobe.materials.textures.pleat_shading).
                    fabric.texture = pleat_shading()
                # A skirt's waistband is the same cloth a shade darker, opaque, unpatterned:
                # the line that says where the garment begins (wardrobe.geometry.waistband).
                band = waistband_mask(layer.mesh)
                extra = [(band, shade_material(garment_material_name(f"{layer.plan.name} Waistband", kind),
                                               material, WAISTBAND_SHADE))] if band.any() else None
                attached = attach_garment(
                    context.document,
                    context.info,
                    layer.mesh,
                    layer.segments,
                    material=fabric,
                    name=layer.plan.name,
                    trim=trim_triangles(layer.mesh) if trim_plan else None,
                    trim_material=GarmentMaterial.from_plan(
                        garment_material_name(f"{layer.plan.name} Trim", kind), trim_plan
                    ) if trim_plan else None,
                    extra=extra,
                )
            # What this garment is, for the next job that meets it: an outer layer
            # made later knows not to take this underwear off (garment_inventory).
            slot = garment_slot(kind)
            context.document.nodes[attached.node_index].setdefault("extras", {})["wardrobeForge"] = {
                "kind": "garment",
                "slot": slot.lower() if slot else None,
                "role": layer.plan.role,
                "layer": layer.plan.layer,
                "templateId": layer.plan.template_id,
                "lookId": context.look_id,
            }
            if layer.plan.hosiery is not None:  # its part in a hosiery design, for posed previews
                forge = context.document.nodes[attached.node_index]["extras"]["wardrobeForge"]
                forge["hosiery"] = layer.artifact.metadata.get("hosieryRole", layer.plan.role)
            if layer.plan.set_id:  # a coordinated set: only then, so no other garment's extras change
                forge = context.document.nodes[attached.node_index]["extras"]["wardrobeForge"]
                forge["setId"] = layer.plan.set_id

        title = f"{context.info.title or 'Avatar'} — {plan.name}" if plan else context.info.title
        if title:
            set_title(context.document, context.info, title[:100])
        tag_derived(
            context.document,
            source_hash=context.source_sha256,
            look_id=context.look_id,
            generator=GENERATOR,
            outfit={
                "baseBodyMode": context.fit_report.base_body.get("mode"),
                "removedSourceSlots": context.fit_report.base_body.get("removedSlots", []),
                "removedSourceMaterials": context.fit_report.base_body.get("removedMaterials", []),
                "layers": [
                    {"name": layer.plan.name, "role": layer.plan.role, "layer": layer.plan.layer,
                     "templateId": layer.plan.template_id}
                    for layer in layers
                ],
            },
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

        colours = {
            garment.name: tuple(float(c) for c in garment.material.base_color[:3])
            for garment in (context.plan.garments if context.plan else [])
        }

        for node_index in document.mesh_nodes():
            node = document.nodes[node_index]
            mesh = document.meshes[node["mesh"]]
            matrix = document.world_matrices()[node_index]
            skinned = "skin" in node
            colour_of_garment = colours.get(mesh.get("name"))

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

                colour = colour_of_garment or (0.76, 0.70, 0.66)
                layers.append(RenderLayer(positions=points, indices=indices, color=colour))

        return layers


__all__ = ["NativeEngine", "GENERATOR"]
