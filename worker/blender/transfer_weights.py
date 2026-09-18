"""Transfer the body's skin weights onto the fitted garment.

Using the body's own weights is what makes the garment move exactly like the
character: the same bones, the same falloffs, no hand-authored envelopes.
"""

from __future__ import annotations

import bpy


def transfer(garment, body, armature, *, vertex_group_limit: int = 4) -> dict:
    """Copy vertex-group weights from ``body`` to ``garment`` and bind it."""
    bpy.ops.object.select_all(action="DESELECT")
    garment.select_set(True)
    bpy.context.view_layer.objects.active = garment

    # Vertex groups must exist before the data transfer can fill them.
    existing = {group.name for group in garment.vertex_groups}
    for group in body.vertex_groups:
        if group.name not in existing:
            garment.vertex_groups.new(name=group.name)

    modifier = garment.modifiers.new(name="WardrobeWeights", type="DATA_TRANSFER")
    modifier.object = body
    modifier.use_vert_data = True
    modifier.data_types_verts = {"VGROUP_WEIGHTS"}
    modifier.vert_mapping = "POLYINTERP_NEAREST"
    modifier.layers_vgroup_select_src = "ALL"
    modifier.layers_vgroup_select_dst = "NAME"

    bpy.ops.object.datalayout_transfer(modifier=modifier.name)
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    # Keep within the 4 influences per vertex that glTF skinning allows.
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=vertex_group_limit)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)

    _bind_to_armature(garment, armature)

    return {
        "vertexGroups": len(garment.vertex_groups),
        "influenceLimit": vertex_group_limit,
        "bones": sorted(group.name for group in garment.vertex_groups),
    }


def _bind_to_armature(garment, armature) -> None:
    for modifier in list(garment.modifiers):
        if modifier.type == "ARMATURE":
            garment.modifiers.remove(modifier)

    modifier = garment.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature
    garment.parent = armature
    garment.matrix_parent_inverse = armature.matrix_world.inverted()


def validate(garment) -> dict:
    """Check every vertex actually carries weight."""
    unweighted = 0
    max_influences = 0

    for vertex in garment.data.vertices:
        total = sum(group.weight for group in vertex.groups)
        influences = sum(1 for group in vertex.groups if group.weight > 0.0)
        max_influences = max(max_influences, influences)
        if total <= 1e-6:
            unweighted += 1

    return {
        "valid": unweighted == 0 and max_influences > 0,
        "unweightedVertices": unweighted,
        "maxInfluences": max_influences,
        "vertexCount": len(garment.data.vertices),
    }


__all__ = ["transfer", "validate"]
