"""Which imported mesh is her body. Pure Python: no ``bpy``, so it is unit-tested.

The worker used to take the mesh with the most vertices. That is the body on
the avatars it was written against and nothing guarantees it: a VRoid girl
whose hair reaches her thighs can carry more hair vertices than skin, and a
heavily dressed avatar more clothing. Taking the wrong mesh is not a crash — it
is a garment shrinkwrapped onto her hair and weights transferred from it.

The body is the mesh whose vertices are driven by her torso and legs: for each
candidate, count the vertices whose strongest vertex group is a torso or leg
bone of the humanoid map. Hair is driven by hair bones under the head, a face
by the head, shoes by the feet. Vertex count only breaks a tie, and a mesh
nothing drives by the torso falls back to the old rule.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Humanoid bones whose vertices are her body, not her head, hands or feet.
TORSO_BONES = frozenset(
    {
        "hips", "spine", "chest", "upperChest",
        "leftUpperLeg", "rightUpperLeg", "leftLowerLeg", "rightLowerLeg",
    }
)


@dataclass(frozen=True)
class Candidate:
    """One mesh: its name, vertex count, and each vertex's strongest group name (None if unweighted)."""

    name: str
    vertex_count: int
    dominant_groups: list[str | None]


def torso_score(candidate: Candidate, torso_groups: set[str]) -> int:
    """How many of the mesh's vertices her torso and legs drive."""
    return sum(1 for group in candidate.dominant_groups if group in torso_groups)


def choose_body(candidates: list[Candidate], humanoid: dict[str, str]) -> Candidate:
    """The body among ``candidates``; ``humanoid`` maps humanoid bone names to the rig's bone names."""
    if not candidates:
        raise ValueError("no meshes to choose a body from")
    torso_groups = {humanoid[bone] for bone in TORSO_BONES if bone in humanoid}
    return max(candidates, key=lambda c: (torso_score(c, torso_groups), c.vertex_count))


__all__ = ["TORSO_BONES", "Candidate", "choose_body", "torso_score"]
