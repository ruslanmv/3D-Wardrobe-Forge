"""VRM 0.x / 1.0 introspection: spec detection, humanoid rig, license terms.

Everything here is normalised into a single shape so that no other module has
to branch on the VRM version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from wardrobe.vrm.document import GltfDocument

VRM0_EXTENSION = "VRM"
VRM1_EXTENSION = "VRMC_vrm"


class VrmSpec(StrEnum):
    VRM0 = "VRM0"
    VRM1 = "VRM1"


class ModificationPermission(StrEnum):
    """Normalised answer to 'may we derive a new model from this one?'"""

    ALLOWED = "allowed"
    ALLOWED_WITH_REDISTRIBUTION = "allowed_with_redistribution"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class CommercialUsage(StrEnum):
    ALLOWED = "allowed"
    PERSONAL_ONLY = "personal_only"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


#: The bones VRM 1.0 marks as required. VRM 0.x uses the same names, and the
#: same set is what the fitting stage needs in order to place a garment.
REQUIRED_HUMANOID_BONES: frozenset[str] = frozenset(
    {
        "hips",
        "spine",
        "head",
        "leftUpperArm",
        "leftLowerArm",
        "leftHand",
        "rightUpperArm",
        "rightLowerArm",
        "rightHand",
        "leftUpperLeg",
        "leftLowerLeg",
        "leftFoot",
        "rightUpperLeg",
        "rightLowerLeg",
        "rightFoot",
    }
)

#: Bones that improve fit quality when present but are not fatal when absent.
OPTIONAL_HUMANOID_BONES: frozenset[str] = frozenset({"chest", "upperChest", "neck", "leftToes", "rightToes"})

# VRM 0.x encodes modification rights inside the license name.
_VRM0_NO_DERIVATIVES = {"CC_BY_ND", "CC_BY_NC_ND"}
_VRM0_PERMISSIVE = {"CC0", "CC_BY", "CC_BY_NC", "CC_BY_SA", "CC_BY_NC_SA"}


@dataclass(slots=True)
class LicenseTerms:
    """Usage terms normalised across VRM 0.x and VRM 1.0."""

    modification: ModificationPermission = ModificationPermission.UNKNOWN
    commercial_usage: CommercialUsage = CommercialUsage.UNKNOWN
    redistribution_allowed: bool | None = None
    credit_notation: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    authors: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "modification": str(self.modification),
            "commercialUsage": str(self.commercial_usage),
            "redistributionAllowed": self.redistribution_allowed,
            "creditNotation": self.credit_notation,
            "licenseName": self.license_name,
            "licenseUrl": self.license_url,
            "authors": list(self.authors),
        }


@dataclass(slots=True)
class VrmInfo:
    spec: VrmSpec
    title: str | None
    version: str | None
    humanoid_bones: dict[str, int]
    license: LicenseTerms
    expressions: list[str] = field(default_factory=list)
    has_first_person: bool = False
    mesh_count: int = 0
    material_count: int = 0

    @property
    def missing_required_bones(self) -> list[str]:
        return sorted(REQUIRED_HUMANOID_BONES - set(self.humanoid_bones))

    def to_dict(self) -> dict:
        return {
            "spec": str(self.spec),
            "title": self.title,
            "version": self.version,
            "humanoidBones": dict(sorted(self.humanoid_bones.items())),
            "license": self.license.to_dict(),
            "expressions": list(self.expressions),
            "hasFirstPerson": self.has_first_person,
            "meshCount": self.mesh_count,
            "materialCount": self.material_count,
        }


class NotAVrm(ValueError):
    """The GLB parses, but carries no VRM extension."""


def inspect_document(document: GltfDocument) -> VrmInfo:
    if document.extension(VRM1_EXTENSION) is not None:
        return _inspect_vrm1(document)
    if document.extension(VRM0_EXTENSION) is not None:
        return _inspect_vrm0(document)
    raise NotAVrm("file is a GLB but declares neither the VRM nor VRMC_vrm extension")


def _inspect_vrm1(document: GltfDocument) -> VrmInfo:
    block = document.extension(VRM1_EXTENSION) or {}
    meta = block.get("meta") or {}

    bones: dict[str, int] = {}
    human_bones = (block.get("humanoid") or {}).get("humanBones") or {}
    for name, entry in human_bones.items():
        if isinstance(entry, dict) and isinstance(entry.get("node"), int):
            bones[name] = entry["node"]

    modification = {
        "prohibited": ModificationPermission.PROHIBITED,
        "allowModification": ModificationPermission.ALLOWED,
        "allowModificationRedistribution": ModificationPermission.ALLOWED_WITH_REDISTRIBUTION,
    }.get(meta.get("modification"), ModificationPermission.UNKNOWN)

    commercial = {
        "personalNonProfit": CommercialUsage.PERSONAL_ONLY,
        "personalProfit": CommercialUsage.PERSONAL_ONLY,
        "corporation": CommercialUsage.ALLOWED,
    }.get(meta.get("commercialUsage"), CommercialUsage.UNKNOWN)

    license_terms = LicenseTerms(
        modification=modification,
        commercial_usage=commercial,
        redistribution_allowed=meta.get("allowRedistribution"),
        credit_notation=meta.get("creditNotation"),
        license_name=meta.get("licenseUrl"),
        license_url=meta.get("licenseUrl"),
        authors=[str(a) for a in (meta.get("authors") or [])],
        raw=dict(meta),
    )

    expressions = sorted((block.get("expressions") or {}).get("preset", {}).keys())
    return VrmInfo(
        spec=VrmSpec.VRM1,
        title=meta.get("name"),
        version=meta.get("version"),
        humanoid_bones=bones,
        license=license_terms,
        expressions=expressions,
        has_first_person="firstPerson" in block,
        mesh_count=len(document.gltf.get("meshes") or []),
        material_count=len(document.gltf.get("materials") or []),
    )


def _inspect_vrm0(document: GltfDocument) -> VrmInfo:
    block = document.extension(VRM0_EXTENSION) or {}
    meta = block.get("meta") or {}

    bones: dict[str, int] = {}
    for entry in (block.get("humanoid") or {}).get("humanBones") or []:
        if isinstance(entry, dict) and isinstance(entry.get("node"), int) and entry.get("bone"):
            bones[str(entry["bone"])] = entry["node"]

    license_name = meta.get("licenseName")
    if license_name in _VRM0_NO_DERIVATIVES:
        modification = ModificationPermission.PROHIBITED
    elif license_name in _VRM0_PERMISSIVE:
        modification = ModificationPermission.ALLOWED
    elif license_name == "Redistribution_Prohibited":
        # VRoid's default: derive freely for yourself, do not redistribute.
        modification = ModificationPermission.ALLOWED
    else:
        modification = ModificationPermission.UNKNOWN

    commercial = {
        "Allow": CommercialUsage.ALLOWED,
        "Disallow": CommercialUsage.PROHIBITED,
    }.get(meta.get("commercialUssageName"), CommercialUsage.UNKNOWN)

    redistribution: bool | None
    if license_name == "Redistribution_Prohibited":
        redistribution = False
    elif license_name in _VRM0_PERMISSIVE:
        redistribution = True
    else:
        redistribution = None

    license_terms = LicenseTerms(
        modification=modification,
        commercial_usage=commercial,
        redistribution_allowed=redistribution,
        credit_notation=meta.get("author"),
        license_name=license_name,
        license_url=meta.get("otherLicenseUrl") or meta.get("otherPermissionUrl"),
        authors=[meta["author"]] if meta.get("author") else [],
        raw=dict(meta),
    )

    expressions = sorted(
        str(group.get("presetName"))
        for group in (block.get("blendShapeMaster") or {}).get("blendShapeGroups") or []
        if group.get("presetName")
    )
    return VrmInfo(
        spec=VrmSpec.VRM0,
        title=meta.get("title"),
        version=meta.get("version"),
        humanoid_bones=bones,
        license=license_terms,
        expressions=expressions,
        has_first_person="firstPerson" in block,
        mesh_count=len(document.gltf.get("meshes") or []),
        material_count=len(document.gltf.get("materials") or []),
    )


def validate_humanoid(document: GltfDocument, info: VrmInfo) -> list[str]:
    """Return a list of human-readable problems; empty means the rig is usable."""
    issues: list[str] = []

    missing = info.missing_required_bones
    if missing:
        issues.append(f"missing required humanoid bones: {', '.join(missing)}")

    node_count = len(document.gltf.get("nodes") or [])
    for bone, node in sorted(info.humanoid_bones.items()):
        if node < 0 or node >= node_count:
            issues.append(f"humanoid bone '{bone}' points at node {node}, which does not exist")

    if not document.mesh_nodes():
        issues.append("model contains no mesh nodes")

    if not (document.gltf.get("skins") or []):
        issues.append("model has no skins; a garment cannot inherit body deformation")

    return issues


__all__ = [
    "VrmSpec",
    "VrmInfo",
    "LicenseTerms",
    "ModificationPermission",
    "CommercialUsage",
    "REQUIRED_HUMANOID_BONES",
    "OPTIONAL_HUMANOID_BONES",
    "NotAVrm",
    "inspect_document",
    "validate_humanoid",
    "VRM0_EXTENSION",
    "VRM1_EXTENSION",
]
