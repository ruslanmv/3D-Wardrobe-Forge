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
from wardrobe.lingerie import LINGERIE_KINDS
from wardrobe.lingerie import assembly as lingerie_assembly
from wardrobe.lingerie.atelier import component_table
from wardrobe.materials import boots as boot_assembly
from wardrobe.materials.fabrics import gusset_material
from wardrobe.materials.textures import boning_shading, pleat_shading
from wardrobe.pipeline.context import BuiltLayer, PipelineContext
from wardrobe.vrm.garments import garment_material_name, garment_slot
from wardrobe.vrm.inspect import VrmSpec
from wardrobe.vrm.merge import GarmentMaterial, attach_garment, set_title, tag_derived
from wardrobe.vrm.skinning import bind_mesh, bones_for_coverage, build_bone_segments, weight_report

logger = logging.getLogger(__name__)

GENERATOR = "3D-Wardrobe-Forge (native engine)"



#: Stretch knits (leggings, a sports bra) shade softly under the toon shader: a matte knit's
#: shading toony (MToon), where the avatar's own cloth is near 1.0, a hard step.
STRETCH_KNIT_KINDS = frozenset({"leggings", "seamless-leggings", "sports-bra"})
KNIT_TOONY = 0.5

def fitted_short(template, plan) -> bool:
    """PS3. A dress or skirt cut close to her and ending above mid-thigh: bound like her skin.

    A bodycon mini was bound to her pelvis while the foundation under it, a second-skin
    garment, followed her thighs: seated, her thighs and the slip shorts rose through the
    dress's lap and sides. Cut this close (conform 0.9 and up) and this short, the dress is
    on her skin and has no hem to hang; a looser or longer skirt keeps the hanging binding.
    """
    if template is None or plan is None:
        return False
    hem = plan.hem or template.hem
    # A flared or pleated mini is excluded: its hem stands off her, and bound to her thighs the
    # pleats would part between her legs as she sat.
    return (template.category in ("dress", "skirt") and template.fit.conform >= 0.9
            and hem in ("mini", "crop") and template.silhouette in ("sheath", "pencil", "slim"))


#: PS1. Shapes with a separate tube round each leg (see the skin binding below).
LEG_TUBE_KINDS = frozenset({"trousers", "leggings", "seamless-leggings", "shorts", "slip-shorts",
                            "catsuit", "jumpsuit"})


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
        kind = artifact.procedural_kind or context.plan.category
        if kind in LEG_TUBE_KINDS:
            # PS1. A garment with a tube round each leg bends at her knee as she does. Its
            # anchors name where it hangs from (jeans: waist and hips), which gives her thigh
            # bones but no shin: every vertex below the knee followed the thigh, so seated or
            # kneeling the trouser leg stayed straight out while her shin went down through it.
            # The leg bones of what it covers are added for these kinds only; a skirt or dress is
            # one tube across both legs, and a hem split between them is worse than a stiff one.
            leg_regions = [r for r in artifact.coverage if r in ("upperLegs", "lowerLegs")]
            candidates += [b for b in bones_for_coverage(leg_regions) if b not in candidates]
        if not candidates:
            raise FittingError(f"template declares no usable anchor regions: {regions}")

        segments = build_bone_segments(context.info.humanoid_bones, context.measurements, candidates)
        if not segments:
            raise FittingError(
                "none of the garment's anchor bones exist on this avatar: " + ", ".join(candidates)
            )
        # The garment's body binds to the torso; only pieces off the body's axis
        # (sleeves, stocking legs) may follow the limbs.
        torso = on_axis_mask(mesh, context.measurements)
        sleeve = mesh.metadata.get("sleeve")
        if sleeve is not None and np.asarray(sleeve).shape[0] == mesh.vertex_count:
            # G6. A panel garment is one piece, sleeves sewn into its armholes, so connected
            # components cannot tell sleeve from body: the builder says which is which.
            torso = ~np.asarray(sleeve, dtype=bool)
        bind_mesh(mesh, segments, torso=torso)
        template = context.catalog.get(artifact.template_id) if artifact.template_id else None
        second_skin = bool(artifact.metadata.get("secondSkin")) or fitted_short(template, context.plan)
        if mesh.metadata.get("panelBuilt") or second_skin:
            # G5. A garment cut on her (wardrobe.geometry.panels) takes her own skin weights
            # above her hips, so its set-in sleeves bend at her shoulder as she does.
            # AN-A5. A second-skin garment takes them everywhere. Bound to her pelvis by the
            # torso mask, briefs and swimsuits stayed where they were when she strode, sat or
            # stood wide while her thighs moved through them: 18-40 mm inside her at the leg
            # openings on every reference body. With her skin's weights they stay 1 mm clear
            # striding and standing wide. Where she has no skin to read, the binding above stays.
            from wardrobe.vrm.weight_transfer import transfer_weights

            hip = context.measurements.bone_positions.get("hips")
            transfer_weights(mesh, segments, context.document, context.info.humanoid_bones,
                             hip_y=float(hip[1]) if hip is not None else float(mesh.positions[:, 1].min()),
                             forward=-1.0 if context.info.spec is VrmSpec.VRM0 else 1.0,
                             axis_z=float(hip[2]) if hip is not None else 0.0,
                             whole=second_skin)
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
            # LC3. A collection piece's fabrics are routed like hosiery's: one primitive each.
            hosiery_parts = (hosiery_assembly.primitives(layer, kind)
                             or lingerie_assembly.primitives(layer, kind)
                             or boot_assembly.primitives(layer, kind))  # DC2: sole, laces, metal
            if hosiery_parts is not None:
                fabric_material, trim_mask, trim_mat, extra = hosiery_parts
                attached = attach_garment(
                    context.document, context.info, layer.mesh, layer.segments,
                    material=fabric_material, name=layer.plan.name,
                    trim=trim_mask, trim_material=trim_mat, extra=extra,
                )
            else:
                fabric = GarmentMaterial.from_plan(garment_material_name(layer.plan.name, kind), material)
                if kind in STRETCH_KNIT_KINDS and material.finish == "matte":
                    fabric.toony = KNIT_TOONY
                if layer.mesh.metadata.get("pleatShading") and material.pattern == "none":
                    # Knife pleats read by their shadows (wardrobe.materials.textures.pleat_shading).
                    fabric.texture = pleat_shading()
                pitch = layer.mesh.metadata.get("boningPitchM")
                if pitch and material.pattern == "none" and layer.mesh.uvs is not None:
                    # P1. A corset's boning channels, one texture tile per panel. The loft's u is
                    # metres round her body, so dividing by the pitch puts a channel every pitch.
                    layer.mesh.uvs = layer.mesh.uvs.copy()
                    layer.mesh.uvs[:, 0] /= float(pitch)
                    fabric.texture = boning_shading()
                # A skirt's waistband is the same cloth a shade darker, opaque, unpatterned:
                # the line that says where the garment begins (wardrobe.geometry.waistband).
                band = waistband_mask(layer.mesh)
                extra = [(band, shade_material(garment_material_name(f"{layer.plan.name} Waistband", kind),
                                               material, WAISTBAND_SHADE))] if band.any() else None
                if extra and fabric.toony is not None:
                    extra[0][1].toony = fabric.toony
                gusset = (_gusset_triangles(layer.mesh) if kind in LINGERIE_KINDS and material.exposes_body
                          else None)
                if gusset is not None and gusset.any():
                    # L7. Every brief's gusset is lined and opaque, whatever its panels are: a
                    # sheer or lace brief was see-through there too.
                    extra = [*(extra or []), (gusset, GarmentMaterial.from_plan(
                        garment_material_name(f"{layer.plan.name} Gusset", kind), gusset_material(material)))]
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
            components = component_table(layer.mesh)
            if components:  # LC2: a collection piece names its parts (bra_left_cup, bow_L, …)
                forge = context.document.nodes[attached.node_index]["extras"]["wardrobeForge"]
                collection = layer.plan.style.collection or {}
                forge["collection"] = {k: collection.get(k) for k in ("id", "piece", "bottomStyle")}
                forge["components"] = components

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
        # PV1. Her arms at her sides, as the shelf's other previews show her: drawn in the
        # bind pose (a T-pose) a look read as a grey cross next to the built-in looks.
        info = getattr(context, "info", None)
        arms = _arms_down(document, info.humanoid_bones if info is not None else {})

        for node_index in document.mesh_nodes():
            node = document.nodes[node_index]
            mesh = document.meshes[node["mesh"]]
            matrix = document.world_matrices()[node_index]
            skinned = "skin" in node
            colour_of_garment = colours.get(mesh.get("name"))
            # OC3. A Forge garment carried from the look this job was built on (baseLookId) is
            # not in this job's plan; without its own colour it was drawn the skin's, so a navy
            # blouse put on a black pencil skirt showed on the shelf over a white one.
            tag = (node.get("extras") or {}).get("wardrobeForge") or {}
            if colour_of_garment is None and tag.get("kind") == "garment":
                colour_of_garment = _material_colour(document, mesh)

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
                if skinned and arms:
                    points = _posed(document, node, attributes, points, arms)

                colour = colour_of_garment or (0.76, 0.70, 0.66)
                layers.append(RenderLayer(positions=points, indices=indices, color=colour))

        return layers


#: PV1. Where the preview lowers her upper arms to: this far below horizontal.
PREVIEW_ARM_DROP = np.radians(65.0)


def _arms_down(document, bones: dict[str, int]) -> dict[int, np.ndarray]:
    """Per node, the world transform that lowers her arms for the preview: each upper arm and
    everything below it turned about the shoulder joint, in her frontal plane, to
    ``PREVIEW_ARM_DROP`` below horizontal (from the angle it is bound at, so an A-posed model is
    lowered by less). Empty when the rig names no arms; the preview is then drawn as bound."""
    world = document.world_matrices()
    out: dict[int, np.ndarray] = {}
    for upper, lower in (("leftUpperArm", "leftLowerArm"), ("rightUpperArm", "rightLowerArm")):
        if upper not in bones or lower not in bones:
            continue
        shoulder = world[bones[upper]][:3, 3]
        elbow = world[bones[lower]][:3, 3]
        arm = elbow - shoulder
        if abs(arm[0]) < 1e-6:
            continue
        side = np.sign(arm[0])
        now = np.arctan2(arm[1], abs(arm[0]))
        # About +z: negative turns the +x arm down, positive the -x arm (mirrored).
        angle = side * (-PREVIEW_ARM_DROP - now)
        c, s = np.cos(angle), np.sin(angle)
        turn = np.eye(4)
        turn[:2, :2] = [[c, -s], [s, c]]
        about = np.eye(4)
        about[:3, 3] = shoulder
        back = np.eye(4)
        back[:3, 3] = -shoulder
        delta = about @ turn @ back
        stack = [bones[upper]]
        while stack:
            index = stack.pop()
            out[index] = delta
            stack.extend(document.nodes[index].get("children") or [])
    return out


def _posed(document, node: dict, attributes: dict, points: np.ndarray,
           arms: dict[int, np.ndarray]) -> np.ndarray:
    """``points`` skinned to ``arms`` (node -> world transform) by their own joints and weights."""
    skins = document.gltf.get("skins") or []
    if node.get("skin") is None or node["skin"] >= len(skins):
        return points
    joint_nodes = skins[node["skin"]].get("joints") or []
    if "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
        return points
    joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
    weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
    if joints.shape[0] != points.shape[0]:
        return points
    transforms = np.stack([arms.get(n, np.eye(4)) for n in joint_nodes] or [np.eye(4)])
    homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
    posed = np.zeros_like(points)
    total = np.zeros(points.shape[0])
    for slot in range(joints.shape[1]):
        joint = np.clip(joints[:, slot], 0, transforms.shape[0] - 1)
        weight = weights[:, slot]
        posed += np.einsum("nij,nj->ni", transforms[joint], homogeneous)[:, :3] * weight[:, None]
        total += weight
    unweighted = total < 1e-6
    posed[unweighted] = points[unweighted]
    posed[~unweighted] /= total[~unweighted, None]
    return posed


def _material_colour(document, mesh: dict) -> tuple[float, float, float] | None:
    """The base colour of a mesh's first material, or None when it names none."""
    materials = document.gltf.get("materials") or []
    for primitive in mesh.get("primitives", []):
        index = primitive.get("material")
        if index is None or index >= len(materials):
            continue
        factor = (materials[index].get("pbrMetallicRoughness") or {}).get("baseColorFactor")
        if factor and len(factor) >= 3:
            return tuple(float(c) for c in factor[:3])
    return None


__all__ = ["NativeEngine", "GENERATOR"]


def _gusset_triangles(mesh) -> np.ndarray:
    """One bool per triangle: those of a lingerie block's gusset section."""
    from wardrobe.geometry.mesh import section_ranges

    mask = np.zeros(mesh.triangle_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if name == "gusset":
            mask[first:first + count] = True
    return mask
