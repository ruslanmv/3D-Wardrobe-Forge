"""Pure-Python VRM/glTF tooling.

VRM files are GLB containers, so a large part of Wardrobe Forge's work
(validating a source model, reading its humanoid rig, measuring the body,
attaching a skinned garment, re-validating the result) can be done without
Blender. Blender is reserved for the operations that genuinely need a mesh
kernel: cage/shrinkwrap fitting of arbitrary meshes, polygon-level body
masking and offline rendering.
"""

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.glb import Glb, GlbError
from wardrobe.vrm.inspect import (
    REQUIRED_HUMANOID_BONES,
    LicenseTerms,
    ModificationPermission,
    VrmInfo,
    VrmSpec,
    inspect_document,
    validate_humanoid,
)
from wardrobe.vrm.measure import BodyMeasurements, measure_body

__all__ = [
    "Glb",
    "GlbError",
    "GltfDocument",
    "VrmInfo",
    "VrmSpec",
    "LicenseTerms",
    "ModificationPermission",
    "REQUIRED_HUMANOID_BONES",
    "inspect_document",
    "validate_humanoid",
    "BodyMeasurements",
    "measure_body",
]
