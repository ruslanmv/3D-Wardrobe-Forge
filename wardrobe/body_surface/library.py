"""BS1. The server's allowlist: body-surface profiles and the templates they may use.

``assets/body_surface/`` holds two folders:

* ``profiles/<id>.json`` — ``wardrobe.bodySurface.v1``: which regions, which template for each,
  how strongly, how the collision body is made;
* ``templates/<name>.json`` — ``wardrobe.bodySurfaceTemplate.v1``: a displacement field in a
  local surface chart, with its provenance beside it in the same file.

**Provenance is checked, not trusted.** A template loads only when its provenance names a
licence on :data:`LICENSES` and the SHA-256 of its field data matches the one recorded when it
was installed (``tools/body_surface/install_template.py``). A template edited by hand, or
dropped in without provenance, is not loaded — and a profile that needs it is unavailable,
with the reason. The same rule as the wardrobe pack's hashes and the tattoo catalogue's PNGs.

**The capability is computed, not declared.** A profile's gate is the strictest of what it
says and what its regions are: one region in :data:`INTIMATE_REGIONS` makes it an
``adult_body_surface`` profile whatever its file claims. A typo in a profile cannot open the
adult path without the adult gate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from wardrobe.body_surface.contract import ID_PATTERN, Capability

logger = logging.getLogger(__name__)

PROFILE_SCHEMA = "wardrobe.bodySurface.v1"
TEMPLATE_SCHEMA = "wardrobe.bodySurfaceTemplate.v1"

#: Licences a template may carry (SPDX ids), plus a commissioned asset whose agreement is on
#: file with the operator. SMPL / SMPL-X / STAR model data are research-only and are not here.
LICENSES = frozenset({"CC0-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "LicenseRef-Commissioned"})

#: Regions whose visible geometry is intimate anatomy: any of them makes a profile adult-only.
INTIMATE_REGIONS = frozenset({"nipples", "chestDetail", "externalAnatomy", "pubic"})

#: Body landmarks a region may anchor to (wardrobe.body_surface.anchors computes them).
ANCHORS = frozenset({"navel", "sternum", "bust-left", "bust-right", "centre-front-crotch"})

#: Measurements the morph check can take (wardrobe.body_surface.regions).
MEASUREMENTS = frozenset({"underbust", "waist", "high-hip", "full-hip", "thigh"})


class LibraryError(ValueError):
    """A profile or template file that cannot be used, and why."""


@dataclass(frozen=True)
class Template:
    id: str
    region: str
    anchor: str
    radius_m: float
    #: Reference waist width the template was authored at; it is scaled to hers.
    reference_waist_m: float
    #: Displacement field over the chart [-radius, radius]²: (rows, cols, 3) of (dn, du, dv) metres.
    field: np.ndarray
    #: Chart landmarks: name -> (u, v) metres, optionally bound to a body landmark.
    landmarks: dict
    provenance: dict

    def sample(self, uv: np.ndarray) -> np.ndarray:
        """Bilinear (dn, du, dv) at chart points (metres); zero outside the chart."""
        rows, cols, _ = self.field.shape
        r = self.radius_m
        x = (np.asarray(uv)[:, 0] + r) / (2 * r) * (cols - 1)
        y = (np.asarray(uv)[:, 1] + r) / (2 * r) * (rows - 1)
        inside = (x >= 0) & (x <= cols - 1) & (y >= 0) & (y <= rows - 1)
        x0 = np.clip(np.floor(x).astype(int), 0, cols - 2)
        y0 = np.clip(np.floor(y).astype(int), 0, rows - 2)
        fx = np.clip(x - x0, 0, 1)[:, None]
        fy = np.clip(y - y0, 0, 1)[:, None]
        f = self.field
        top = f[y0, x0] * (1 - fx) + f[y0, x0 + 1] * fx
        bottom = f[y0 + 1, x0] * (1 - fx) + f[y0 + 1, x0 + 1] * fx
        out = top * (1 - fy) + bottom * fy
        out[~inside] = 0.0
        return out


@dataclass(frozen=True)
class Region:
    key: str
    template_id: str
    strength: float
    #: Share of the region's displacement the collision body keeps (0: none, 1: all of it).
    collision_detail: float
    #: Laplacian smoothness of the blend into her surface.
    smoothness: float
    #: Morph weight in the exported VRM (detailLevel "render").
    default_weight: float
    #: Measurements the region may not change by more than MAX_MEASUREMENT_CHANGE.
    preserve: tuple[str, ...]


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    capability: Capability
    regions: tuple[Region, ...]
    outward_margin_m: float
    detail_cutoff_m: float
    #: Close-fit cloth: the shell's body clearance is replaced by this (metres), or None to keep it.
    close_fit_clearance_m: float | None
    provenance: dict
    templates: dict = field(default_factory=dict)  # template id -> Template


def _sha256_field(data: dict) -> str:
    """The hash recorded at install: of the field values exactly as stored."""
    canonical = json.dumps(data["field"], separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_template(path: Path) -> Template:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != TEMPLATE_SCHEMA:
        raise LibraryError(f"{path.name}: schema must be {TEMPLATE_SCHEMA}")
    if not re.match(ID_PATTERN, str(data.get("id", ""))):
        raise LibraryError(f"{path.name}: bad id")
    provenance = data.get("provenance") or {}
    if provenance.get("license") not in LICENSES:
        raise LibraryError(f"{data['id']}: licence {provenance.get('license')!r} is not on the allowlist")
    if provenance.get("containsRealPersonScan") is not False:
        raise LibraryError(f"{data['id']}: provenance must state containsRealPersonScan: false")
    recorded = str(provenance.get("sha256", ""))
    if recorded != _sha256_field(data):
        raise LibraryError(f"{data['id']}: field data does not match its recorded sha256 "
                           "(edited after install?)")
    if data.get("anchor") not in ANCHORS:
        raise LibraryError(f"{data['id']}: unknown anchor {data.get('anchor')!r}")
    grid = np.asarray(data["field"], dtype=np.float64)
    if grid.ndim != 3 or grid.shape[2] != 3 or min(grid.shape[:2]) < 3:
        raise LibraryError(f"{data['id']}: field must be rows × cols × 3 (dn, du, dv)")
    radius = float(data["radiusM"])
    if not 0.002 <= radius <= 0.2:
        raise LibraryError(f"{data['id']}: radiusM out of range")
    if np.abs(grid).max() > radius:
        raise LibraryError(f"{data['id']}: displacement larger than the template itself")
    if np.abs(np.concatenate([grid[0], grid[-1], grid[:, 0], grid[:, -1]])).max() > 1e-6:
        raise LibraryError(f"{data['id']}: field must be zero on the chart's edge")
    return Template(
        id=data["id"], region=str(data["region"]), anchor=data["anchor"], radius_m=radius,
        reference_waist_m=float(data.get("referenceWaistM", 0.26)), field=grid,
        landmarks=dict(data.get("landmarks") or {}), provenance=provenance,
    )


def load_profile(path: Path, templates: dict[str, Template]) -> Profile:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != PROFILE_SCHEMA:
        raise LibraryError(f"{path.name}: schema must be {PROFILE_SCHEMA}")
    profile_id = str(data.get("profileId", ""))
    if not re.match(ID_PATTERN, profile_id) or path.stem != profile_id.replace("/", "-"):
        raise LibraryError(f"{path.name}: profileId must match the file name")
    authorization = data.get("authorization") or {}
    if authorization.get("allowPromptOverride", False):
        raise LibraryError(f"{profile_id}: allowPromptOverride is never allowed")
    regions, used = [], {}
    for key, spec in (data.get("regions") or {}).items():
        template_id = str(spec.get("templateId", ""))
        if template_id not in templates:
            raise LibraryError(f"{profile_id}: region {key} needs template {template_id!r}, "
                               "which is not installed")
        preserve = tuple(spec.get("preserveMeasurements") or ())
        if set(preserve) - MEASUREMENTS:
            raise LibraryError(f"{profile_id}: unknown measurement in {key}.preserveMeasurements")
        regions.append(Region(
            key=key, template_id=template_id,
            strength=float(np.clip(spec.get("strength", 1.0), 0.0, 1.0)),
            collision_detail=float(np.clip(spec.get("collisionDetail", 0.0), 0.0, 1.0)),
            smoothness=float(np.clip(spec.get("smoothness", 1.0), 0.0, 20.0)),
            default_weight=float(np.clip(spec.get("defaultWeight", 1.0), 0.0, 1.0)),
            preserve=preserve,
        ))
        used[template_id] = templates[template_id]
    declared = Capability(data.get("capability", Capability.BODY_COLLISION))
    intimate = any(r.key in INTIMATE_REGIONS or used[r.template_id].region in INTIMATE_REGIONS
                   for r in regions)
    order = [Capability.BODY_COLLISION, Capability.BODY_SURFACE, Capability.ADULT_BODY_SURFACE]
    computed = (Capability.ADULT_BODY_SURFACE if intimate
                else Capability.BODY_SURFACE if regions else Capability.BODY_COLLISION)
    capability = max(declared, computed, key=order.index)
    collision = data.get("collision") or {}
    close = collision.get("closeFitClearanceMm")
    return Profile(
        id=profile_id, title=str(data.get("title", profile_id)), capability=capability,
        regions=tuple(regions),
        outward_margin_m=float(np.clip(collision.get("outwardMarginMm", 1.0), 0.0, 5.0)) / 1000.0,
        detail_cutoff_m=float(np.clip(collision.get("detailCutoffMm", 3.0), 0.0, 20.0)) / 1000.0,
        close_fit_clearance_m=None if close is None else float(np.clip(close, 0.5, 6.0)) / 1000.0,
        provenance=dict(data.get("provenance") or {}), templates=used,
    )


@dataclass
class BodySurfaceLibrary:
    profiles: dict[str, Profile]
    #: What could not be loaded, and why: for the operator, never for a caller.
    rejected: dict[str, str]

    @classmethod
    def from_directory(cls, root: Path) -> BodySurfaceLibrary:
        templates: dict[str, Template] = {}
        rejected: dict[str, str] = {}
        for path in sorted((root / "templates").glob("*.json")):
            try:
                template = load_template(path)
                templates[template.id] = template
            except (LibraryError, KeyError, ValueError, TypeError) as exc:
                rejected[f"templates/{path.name}"] = str(exc)
                logger.warning("body-surface template %s rejected: %s", path.name, exc)
        profiles: dict[str, Profile] = {}
        for path in sorted((root / "profiles").glob("*.json")):
            try:
                profile = load_profile(path, templates)
                profiles[profile.id] = profile
            except (LibraryError, KeyError, ValueError, TypeError) as exc:
                rejected[f"profiles/{path.name}"] = str(exc)
                logger.warning("body-surface profile %s rejected: %s", path.name, exc)
        return cls(profiles=profiles, rejected=rejected)

    def public(self) -> list[dict]:
        """What a client may see: ids, titles, capabilities. Never templates or provenance."""
        return [{"id": p.id, "title": p.title, "capability": str(p.capability),
                 "regions": [r.key for r in p.regions]} for p in self.profiles.values()]


@lru_cache(maxsize=4)
def library_at(root: str) -> BodySurfaceLibrary:
    return BodySurfaceLibrary.from_directory(Path(root))


__all__ = [
    "ANCHORS", "BodySurfaceLibrary", "INTIMATE_REGIONS", "LICENSES", "LibraryError", "MEASUREMENTS",
    "PROFILE_SCHEMA", "Profile", "Region", "TEMPLATE_SCHEMA", "Template", "library_at", "load_profile",
    "load_template",
]
