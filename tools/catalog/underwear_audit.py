"""UA1. The underwear audit: does each fitted piece measure what its pattern says it is?

    python tools/catalog/underwear_audit.py --out /tmp/ua            # all 36, ~10 min
    python tools/catalog/underwear_audit.py --out /tmp/ua --only under-thong-v2 under-g-string-v2
    python tools/catalog/underwear_audit.py --out /tmp/ua2 --before /tmp/ua/audit.json

A preview proves a mesh was made and drawn; it does not prove a thong came out a thong. Each
piece is fitted exactly as its preview is (tools/catalog/render_templates.py's own profile,
reference base and colour, on the operator-declared adult avatar), and then measured on the
**fitted** mesh, not on the pattern the solver planned:

* **silhouette** — measured on the drafted pattern and on the fitted piece alike: coverage as
  the pattern block defines it (``wardrobe.lingerie.blocks.brief``: the share of each column
  round her pelvis, from the garment's own waistline down to the gusset seam, that it
  covers, averaged over the front or back half), the side height, and the back's width just
  above the gusset seam;
* **spec → pattern → fitted** — the template's own figures against the pattern the builder
  drafted, and the fitted piece against that pattern (see ``compare``), split into **hard**
  failures (the piece is not its design) and **soft** ones (calibration ranges);
* **rules** — the lingerie rows of the fit report (gusset midline, elastic strain and
  pressure, underband level, cup symmetry, straps) and the report's warnings;
* **contact** — clearance, depth inside, share inside and edge stretch against her posed
  skin in Standing, Sitting and Sitting (Wide) (tools/inspect/pose_contact.py);
* **geometry** — a hash of the fitted piece's rest geometry, for regression.

Coverage is the pattern's own figure for that garment: a G-string's 0.03 at the back is
correct for a G-string, and a full brief's 0.85 for a brief. Nothing here compares a piece
with any other piece's coverage, or with a general target.

Pieces built without a pattern block (the legacy procedural kinds) have no spec to compare
against: they are measured and reported as ``no pattern spec``, never passed by default.

``--out`` must be outside the repository: each fitted VRM is kept there (``vrm/{id}.vrm``), so
a later run's ``--before`` can be compared look for look. ``audit.json`` is written there too;
``--publish`` also writes the numbers (no meshes, no images) to
assets/catalog/adult/underwear-audit.json and docs/UNDERWEAR_AUDIT.md. With ``--only``,
``--publish`` replaces those pieces' records and keeps every other published record as it is.

UA2. Three things a new template found. A body mode (``body-bare-v1``) is filed under
underwear and is not a garment: it is left out, where the full run used to stop on it before
fitting anything. A template the planner builds as another template of its own kind (the
Leather Garter Belt is the classic suspender belt in leather, ``wardrobe.hosiery.planning``)
is measured on that piece, not on the stockings and straps planned with it. And a partial
``--publish`` used to write only its own pieces over the whole published file.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load("render_templates", ROOT / "tools/catalog/render_templates.py")
pose_contact = _load("pose_contact", ROOT / "tools/inspect/pose_contact.py")

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.lingerie.blocks.brief import SEAM_ABOVE_CROTCH_M  # noqa: E402
from wardrobe.lingerie.landmarks import landmarks_for_document  # noqa: E402
from wardrobe.lingerie.specs import parse_block  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import VrmSpec, inspect_document  # noqa: E402

AVATAR = "fem-vroid"
POSES = ("standing", "sitting", "sittingWide")
#: Tolerances on the fitted piece. The pattern is solved to 0.02 (wardrobe.lingerie.validate);
#: fitting then conforms it to her, and on the reference avatar that moves a column's edges by a
#: few millimetres, about 0.03 of a panel. Beyond these the piece is not the pattern.
COVERAGE_TOLERANCE = 0.05
#: Side height and back width: the larger of a share of the spec and a few millimetres (a
#: string's 5 mm cannot be held to 20% of itself on a mesh with 4 mm rows).
LENGTH_SHARE = 0.25
LENGTH_FLOOR_MM = 6.0
#: Column width round her, and the sampling density on the garment's triangles.
COLUMNS = 90
SAMPLE_M = 0.002
#: A column is "seen" when it has samples at least this high above the seam.
BACK_WIDTH_ABOVE_SEAM_M = 0.012
#: Samples nearer her hip axis than this are under her crotch, where the angle round it is noise.
AXIS_M = 0.03
#: A drop between samples larger than this ends a column's covered run.
GAP_M = 0.008

PATTERN_KINDS = ("brief-block", "bodysuit-block")


def _outside(out: Path) -> Path:
    out = out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit(f"{out} is inside the repository; audit output is written outside it")
    return out


def brief_spec(template) -> dict | None:
    """The bottom's pattern figures, exactly as the builder resolved them; None without a block."""
    if template.procedural_kind not in PATTERN_KINDS or not template.lingerie:
        return None
    brief = parse_block(template.procedural_kind, template.lingerie).brief
    if brief is None:
        return None
    return {
        "preset": brief.preset,
        "rise": round(brief.rise_fraction, 3),
        "backRise": round(float(brief.back_rise), 3),
        "frontCoverage": round(brief.front_fraction, 3),
        "backCoverage": round(brief.back_fraction, 3),
        "sideType": brief.side_type,
        "sideWidthMm": brief.side_width_mm,
        "legCutHeight": brief.leg_cut_height,
        "backCenterWidthMm": brief.back_center_width_mm,
    }


def _samples(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Points spread over the triangles about SAMPLE_M apart: a column sees a thin strip too."""
    a, b, c = (points[tris[:, k]].astype(np.float64) for k in range(3))
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    steps = np.clip(np.ceil(np.sqrt(area) / SAMPLE_M), 1, 24).astype(int)
    out = [points.astype(np.float64)]
    for n in np.unique(steps):
        rows = steps == n
        grid = np.array([(i / n, j / n) for i in range(n + 1) for j in range(n + 1 - i)])
        u, v = grid[:, 0][None, :, None], grid[:, 1][None, :, None]
        aa, bb, cc = a[rows][:, None, :], b[rows][:, None, :], c[rows][:, None, :]
        out.append((aa + (bb - aa) * u + (cc - aa) * v).reshape(-1, 3))
    return np.vstack(out)


def silhouette(
    points: np.ndarray, tris: np.ndarray, centre: np.ndarray, forward: float, marks, top_cap=None
) -> dict:
    """The pattern's coverage measured on the fitted piece, and its side height and back width.

    ``centre`` is her hips joint (x, z): the axis the block's columns turn about; ``marks`` her
    landmarks (wardrobe.lingerie.landmarks), so the gusset seam is where ``build_brief`` puts
    it, SEAM_ABOVE_CROTCH_M above her crotch. Each column's coverage is the run the piece covers
    unbroken from its own top in that column down toward the seam, as a share of top → seam:
    the figure ``build_brief`` solves its leg line for, since its panel runs unbroken from
    waistline to leg line. ``top_cap(phi)`` lowers a column's top to the brief's waistline: a
    bodysuit's leg line is solved against that, not against its neckline.

    Samples within AXIS_M of her hip axis are left out: under her crotch the angle round the
    axis means nothing, and a gusset point there landed in the side columns (a Brazilian's
    26 mm sides measured 161 mm) or completed a G-string's back columns (0.65 instead of 0.03).
    """
    s = _samples(points, tris)
    dx, dz = s[:, 0] - centre[0], (s[:, 2] - centre[1]) * forward
    keep = np.hypot(dx, dz) > AXIS_M
    s, dx, dz = s[keep], dx[keep], dz[keep]
    phi = np.arctan2(dx, dz)  # 0 at her front, ±pi at her back
    seam = float(marks.crotch_y) + SEAM_ABOVE_CROTCH_M
    edges = np.linspace(-math.pi, math.pi, COLUMNS + 1)
    middle = (edges[:-1] + edges[1:]) / 2
    column = np.clip(np.digitize(phi, edges) - 1, 0, COLUMNS - 1)
    share = np.zeros(COLUMNS)
    height = np.zeros(COLUMNS)
    for k in range(COLUMNS):
        ys = np.sort(s[column == k, 1])[::-1]
        ys = ys[ys > seam - 0.002]
        if top_cap is not None:
            ys = ys[ys <= float(top_cap(middle[k])) + GAP_M]
        if ys.size == 0:
            continue
        gaps = np.flatnonzero(-np.diff(ys) > GAP_M)
        top = float(ys[0])
        low = max(float(ys[gaps[0]] if gaps.size else ys[-1]), seam)
        height[k] = top - low
        share[k] = np.clip((top - low) / max(top - seam, 1e-6), 0.0, 1.0)
    front = np.abs(middle) < math.pi / 2
    sides = np.abs(np.abs(middle) - math.pi / 2) < math.pi / COLUMNS * 1.5
    band = (np.abs(s[:, 1] - (seam + BACK_WIDTH_ABOVE_SEAM_M)) < 0.003) & (np.cos(phi) < -0.5)
    back_width = float(np.ptp(dx[band])) * 1000.0 if band.sum() > 1 else 0.0
    return {
        "frontCoverage": round(float(share[front].mean()), 3),
        "backCoverage": round(float(share[~front].mean()), 3),
        "sideHeightMm": round(float(height[sides].mean()) * 1000.0, 1),
        "backWidthAboveSeamMm": round(back_width, 1),
        "seamY": round(seam, 4),
    }


def waistline(spec: dict, marks):
    """The brief's waistline round her (phi -> y), from its rise, as ``build_brief`` draws it."""
    span = max(float(marks.waist_y) - float(marks.crotch_y), 0.08)
    front = float(marks.crotch_y) + span * spec["rise"]
    back = front + span * spec["backRise"]
    return lambda phi: front + (back - front) * (1 - math.cos(phi)) / 2


def _length(rule: str, want: float, have: float, loose_above: bool = False) -> dict:
    tol = max(want * LENGTH_SHARE, LENGTH_FLOOR_MM)
    high = want + (2 * tol if loose_above else tol)
    return {
        "id": rule,
        "spec": want,
        "measured": have,
        "tolerance": round(tol, 1),
        "ok": want - tol <= have <= high,
    }


def compare(spec: dict, pattern: dict | None, fitted: dict, rules: list[dict]) -> list[dict]:
    """The chain spec → pattern → fitted piece, one link at a time, each in the measure valid for it.

    **spec → pattern.** Coverage is a share in the block's own column parameter, which is not
    an angle round her: measured geometrically, a pattern the solver hit exactly reads 0.05 to
    0.12 higher, for every style alike. So the pattern's coverage is the builder's own row
    (``brief.coverage.*``, solved to 0.02, warned when the solver cannot reach the spec);
    side height and the back's width are millimetres, measured here on the fitted piece.

    **pattern → fitted.** The same geometric measure on both meshes: whatever it reads, the
    fit must not move it. Coverage within COVERAGE_TOLERANCE, lengths within LENGTH_SHARE.
    """
    rows = []
    for side in ("front", "back"):
        row = next((r for r in rules if r["id"].endswith(f".coverage.{side}")), None)
        if row is not None:
            rows.append(
                {
                    "id": f"pattern.{side}Coverage",
                    "spec": spec[f"{side}Coverage"],
                    "measured": row["value"],
                    "tolerance": 0.02,
                    "ok": row["status"] == "pass",
                }
            )
    if spec.get("sideWidthMm") is not None and spec.get("legCutHeight") is None:
        rows.append(_length("fitted.sideHeightMm", float(spec["sideWidthMm"]), fitted["sideHeightMm"]))
    if spec.get("backCenterWidthMm") is not None:
        # Measured a little above the seam, where a thong's strip has begun to widen.
        rows.append(
            _length(
                "fitted.backWidthMm",
                float(spec["backCenterWidthMm"]),
                fitted["backWidthAboveSeamMm"],
                loose_above=True,
            )
        )
    if pattern is not None:
        for key in ("frontCoverage", "backCoverage"):
            rows.append(
                {
                    "id": f"drift.{key}",
                    "spec": pattern[key],
                    "measured": fitted[key],
                    "tolerance": COVERAGE_TOLERANCE,
                    "ok": abs(fitted[key] - pattern[key]) <= COVERAGE_TOLERANCE,
                }
            )
        for key in ("sideHeightMm", "backWidthAboveSeamMm"):
            if pattern[key] > 0:
                rows.append(_length(f"drift.{key}", pattern[key], fitted[key]))
    return rows


#: Rules whose failure means the piece is not its design: construction, not calibration.
HARD_RULES = (".gusset.midline",)


def classify(rows: list[dict], rules: list[dict]) -> tuple[list[str], list[str]]:
    """(hard, soft) failures. Hard: the piece is not its design. Soft: outside a range this
    project chose and has not yet calibrated against measured fabric or a deformable body
    (elastic strain and pressure, underband level, cup symmetry, straps): reported, not failed.
    """
    hard = [r["id"] for r in rows if not r["ok"]]
    hard += [r["id"] for r in rules if r["status"] != "pass" and r["id"].endswith(HARD_RULES)]
    soft = [
        r["id"]
        for r in rules
        if r["status"] != "pass" and not r["id"].endswith(HARD_RULES) and ".coverage." not in r["id"]
    ]
    return hard, soft


def _garment(document: GltfDocument, names: list[str]):
    """The fitted piece's own primitives (fabric, trim, gusset, waistband), merged."""
    points, tris, offset = [], [], 0
    for name, _node, _attributes, p, t in pose_contact._primitives(document):
        if any(name.startswith(n) for n in names):
            points.append(p)
            tris.append(t.reshape(-1, 3) + offset)
            offset += p.shape[0]
    if not points:
        return None, None
    return np.vstack(points), np.vstack(tris)


def geometry_hash(points: np.ndarray, tris: np.ndarray) -> str:
    """The piece's rest geometry to 0.1 mm: any change of shape changes it, a re-export does not."""
    digest = hashlib.sha256()
    digest.update(np.round(points * 10000).astype(np.int64).tobytes())
    digest.update(tris.astype(np.int64).tobytes())
    return digest.hexdigest()


def audited(catalog) -> list:
    """The underwear garments, in the published order. A body mode is not a garment (AF5).

    ``body-bare-v1`` sorts first and cannot be requested as a template without its own base
    body, so the documented full run failed on it before a single piece was fitted, and a
    template added after it could only be audited by naming it with ``--only``.
    """
    return sorted(
        (t for t in catalog if t.category == "underwear" and not t.is_body_mode), key=lambda v: v.id
    )


def piece_names(template, garments: list[dict], kinds: dict[str, str | None]) -> list[str]:
    """The planned garments that are this template's own piece.

    Its own id, when the plan kept it. Otherwise the planner rebuilt it: as another template
    of its own kind (the Leather Garter Belt is planned as the classic suspender belt, with
    the stockings and straps a belt is worn with), and then that piece is the garment, or as
    parts of other kinds (under-lingerie-set-v1 is a bralette and briefs), and then the whole
    plan is. Measuring a belt together with the stockings it clips to gave a belt 5,165
    vertices and a side height of 95 mm for the classic belt's 87: not this piece's figures.
    """
    own = [g["name"] for g in garments if g.get("templateId") == template.id]
    if own:
        return own
    same_kind = [g["name"] for g in garments if kinds.get(g.get("templateId")) == template.procedural_kind]
    return same_kind or [g["name"] for g in garments]


CONTACT_KEYS = ("maxPenetrationMm", "penetratingPct", "maxEdgeStretch", "stretchedPct")


def with_pieces(template, plan, own: list[str]) -> list[dict]:
    """The other pieces of a template the planner rebuilt as another of its own kind.

    The Leather Garter Belt *is* a belt with four straps clipped to thigh-high stockings: its
    silhouette is the belt's, measured like every other belt's, but a record of the belt alone
    says nothing about two thirds of what the card puts on her. Each piece planned with it is
    measured as well (``parts``). Empty for a template the plan kept under its own id, whose
    record is what it always was, and for a set planned as parts of other kinds, whose whole
    plan is already the measured piece.
    """
    if any(g.template_id == template.id for g in plan.garments):
        return []
    if len(own) == len(plan.garments):
        return []
    return [
        {"name": g.name, "templateId": g.template_id, "role": str(g.role), "category": str(g.category)}
        for g in plan.garments
    ]


def parts(document: GltfDocument, path: Path, poses: list[dict], pieces: list[dict]) -> list[dict]:
    """Each planned piece on the fitted look: its size, its geometry hash, its contact per pose.

    A piece is every primitive its name starts (the stockings are three: leg, top band, edge;
    the straps two: webbing and hardware), as ``_garment`` merges them. Contact is the worst
    of its primitives per pose, since the question is whether any of it is inside her.
    """
    out = []
    for piece in pieces:
        points, tris = _garment(document, [piece["name"]])
        if points is None:
            out.append({**piece, "fitted": False})
            continue
        measured = pose_contact.measure(path, poses, [piece["name"]])["garments"]
        contact: dict = {}
        for by in measured.values():
            for pose, m in by.items():
                worst = contact.setdefault(pose, dict.fromkeys(CONTACT_KEYS, 0.0))
                for key in CONTACT_KEYS:
                    worst[key] = max(worst[key], m[key])
        out.append(
            {
                **piece,
                "fitted": True,
                "primitives": sorted(measured),
                "vertices": int(points.shape[0]),
                "triangles": int(tris.shape[0]),
                "geometrySha256": geometry_hash(points, tris),
                "contact": contact,
            }
        )
    return out


def strap_summary(hosiery: dict | None) -> dict | None:
    """The fit report's own hosiery figures: each strap's length and strain per pose, the clips.

    Copied from ``wardrobe.hosiery.report``, not re-derived: the report is where strap tension
    and the clips' distance from the stocking band are computed, against the limits it warns by.
    The clips' positions and skin weights are left in the fit report; here, what was measured.
    """
    if not hosiery:
        return None
    out = {key: hosiery[key] for key in ("straps", "clips") if key in hosiery}
    tops = hosiery.get("stockingTop") or {}
    if tops:
        out["stockingTop"] = {
            side: {key: top[key] for key in ("topY", "bottomY", "widthMm") if key in top}
            for side, top in tops.items()
            if isinstance(top, dict)
        }
    return out or None


def merged(previous: dict, result: dict) -> dict:
    """A partial audit (``--only``) laid over the published one: its pieces replaced or added.

    Every other record is kept exactly as published, in id order. The tolerances and the
    avatar must be the ones the kept records were measured with, or the file would mix two
    standards under one header.
    """
    for key in ("schemaVersion", "avatar", "tolerances"):
        if previous.get(key) != result.get(key):
            raise SystemExit(f"published {key} differs from this run's; run the full audit to re-publish")
    items = {item["id"]: item for item in previous["items"]}
    items.update({item["id"]: item for item in result["items"]})
    # The header keeps the date of the last full audit, which is when the kept records were
    # measured; each partial run is listed under it with the pieces it measured.
    updates = [*previous.get("updates", []), {
        "at": result["generatedAt"],
        "ids": sorted(item["id"] for item in result["items"]),
    }]
    return {**previous, "updates": updates, "items": [items[key] for key in sorted(items)]}


def _verdict(item: dict, fitted: bool) -> str:
    if not fitted:
        return "not fitted"
    if item["hard"]:
        return "deviates from spec"
    if item["spec"] is None:
        # A bra's spec is checked by its rules (cups, underband, straps), not by a silhouette;
        # a legacy kind has no spec at all. Neither is passed on a silhouette it never had.
        return "rules only" if item["kind"] == "bra-block" else "no pattern spec"
    return "matches spec"


class _Drafts:
    """Every pattern block drafted while it is installed: the piece before fitting moves it.

    Wraps ``wardrobe.lingerie.blocks.build_block`` (procedural imports it at the call), so the
    audit can measure what the pattern drew and what fitting made of it, and tell a pattern
    that is wrong from a fit that moved a right one. Nothing in the pipeline changes.
    """

    def __init__(self):
        import wardrobe.lingerie.blocks as blocks

        self._blocks, self._original, self.made = blocks, blocks.build_block, []

    def __enter__(self):
        def build(kind, params):
            mesh = self._original(kind, params)
            self.made.append((kind, mesh.positions.copy(), mesh.indices.reshape(-1, 3).copy()))
            return mesh

        self._blocks.build_block = build
        return self

    def __exit__(self, *_exc):
        self._blocks.build_block = self._original


async def audit(out: Path, only: set[str]) -> dict:
    style = render.load_style()
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    entry = library.get(AVATAR)
    if entry is None or entry.path is None or not entry.depicts_adult:
        raise SystemExit(f"{AVATAR} must be present (make library) and declared adult in policy.json")
    poses = [
        p
        for p in json.loads((ROOT / "tests/fixtures/homepilot-poses.json").read_text())["presets"]
        if p["name"] in POSES
    ]
    (out / "vrm").mkdir(parents=True, exist_ok=True)
    items = []
    with tempfile.TemporaryDirectory(prefix="underwear-audit-") as tmp:
        settings = Settings(
            _env_file=None,
            wardrobe_storage_root=str(Path(tmp) / "store"),
            wardrobe_engine="native",
            strict_licensing=True,
        )
        store = LocalObjectStore(settings.storage_root_path, settings)
        orch = Orchestrator(
            settings=settings,
            store=store,
            jobs=InMemoryJobRepository(),
            wardrobes=InMemoryWardrobeRepository(),
            queue=AsyncioJobQueue(concurrency=1),
            catalog=catalog,
        )
        await library.seed(store)
        base = None
        # Her landmarks from the avatar as published, nothing on: a fitted look's own landmarks
        # count its garments as her (geometry_checks.body_points does, for layering), so a gusset
        # filling the gap between her thighs moved the crotch every piece is measured from.
        marks = landmarks_for_document(GltfDocument.from_bytes(Path(entry.path).read_bytes()))
        drafts = _Drafts().__enter__()
        kinds = {t.id: t.procedural_kind for t in catalog}
        for t in audited(catalog):
            if only and t.id not in only:
                continue
            profile = render.profile_for(t, style, AVATAR, "underwear")
            if base is None:
                base = await render._reference_base(orch, store, entry, profile["base"], profile["name"])
            color = render.color_for(t, catalog, profile["colors"])
            drafts.made.clear()
            result = await orch.run_now(
                CreateJobRequest.model_validate(
                    {
                        "avatar": base,
                        "outfit": {
                            "prompt": f"{color} {t.name}",
                            "mode": "template",
                            "templateId": t.id,
                            "color": color,
                        },
                        "options": {
                            "renderPreview": False,
                            "engine": "native",
                            "baseBody": profile["baseBody"],
                        },
                    }
                )
            )
            spec = brief_spec(t)
            item = {
                "id": t.id,
                "name": t.name,
                "kind": t.procedural_kind,
                "baseBody": profile["baseBody"],
                "color": color,
                "spec": spec,
            }
            report = result.fit_report
            fitted = result.state == "completed" and result.look is not None and report is not None
            item.update(
                jobState=str(result.state),
                fitPassed=bool(report and report.passed),
                warnings=[str(w)[:200] for w in (report.warnings if report else [])],
            )
            if fitted:
                garments = render._rendered(result.plan)
                # A set (under-lingerie-set-v1) is planned as its parts, each its own template.
                names = piece_names(t, garments, kinds)
                # The pieces planned with a rebuilt one (the leather belt's stockings and straps).
                worn_with = with_pieces(t, result.plan, names)
                data = await store.get(f"looks/{result.look.id}/look.vrm")
                path = out / "vrm" / f"{t.id}.vrm"
                path.write_bytes(data)
                document = GltfDocument.from_bytes(data)
                info = inspect_document(document)
                hips = document.node_world_position(info.humanoid_bones["hips"])
                forward = -1.0 if info.spec is VrmSpec.VRM0 else 1.0
                points, tris = _garment(document, names)
                if points is None:
                    fitted = False
                    item["reason"] = f"no primitive named {names} in the fitted look"
                else:
                    cap = waistline(spec, marks) if spec and t.procedural_kind == "bodysuit-block" else None
                    got = silhouette(points, tris, np.array([hips[0], hips[2]]), forward, marks, cap)
                    item["fitted"] = got
                    drafted = [d for d in drafts.made if d[0] == t.procedural_kind]
                    if spec and drafted:
                        _kind, pattern_points, pattern_tris = drafted[-1]
                        item["pattern"] = silhouette(
                            pattern_points, pattern_tris, np.array([hips[0], hips[2]]), forward, marks, cap
                        )
                    item["geometrySha256"] = geometry_hash(points, tris)
                    item["vertices"] = int(points.shape[0])
                    lingerie = report.lingerie or {}
                    item["rules"] = [r for piece in lingerie.get("pieces", []) for r in piece["rules"]]
                    item["comparison"] = (
                        compare(spec, item.get("pattern"), got, item["rules"]) if spec else []
                    )
                    contact = pose_contact.measure(path, poses, names)
                    item["contact"] = {
                        pose: {k: m[k] for k in CONTACT_KEYS}
                        for by in list(contact["garments"].values())[:1]
                        for pose, m in by.items()
                    }
                    if worn_with:
                        item["builtAs"] = next(
                            (g["templateId"] for g in garments if g["name"] in names), None
                        )
                        item["parts"] = parts(document, path, poses, worn_with)
                        item["hosiery"] = strap_summary(report.hosiery)
            item["hard"], item["soft"] = classify(item.get("comparison", []), item.get("rules", []))
            if not item.get("fitPassed"):
                item["hard"].append("fitReport.passed")
            item["verdict"] = _verdict(item, fitted)
            items.append(item)
            print(f"{t.id:34} {item['verdict']}", flush=True)
    drafts.__exit__()
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "avatar": AVATAR,
        "tolerances": {
            "coverage": COVERAGE_TOLERANCE,
            "lengthShare": LENGTH_SHARE,
            "lengthFloorMm": LENGTH_FLOOR_MM,
        },
        "items": items,
    }


def diff(before: dict, after: dict) -> list[str]:
    """What changed between two audits, look for look: geometry, verdicts, silhouette figures."""
    old = {i["id"]: i for i in before["items"]}
    lines = []
    for item in after["items"]:
        was = old.get(item["id"])
        if was is None:
            lines.append(f"{item['id']}: new")
            continue
        if was.get("geometrySha256") != item.get("geometrySha256"):
            lines.append(f"{item['id']}: geometry changed")
        if was.get("verdict") != item.get("verdict"):
            lines.append(f"{item['id']}: {was.get('verdict')} -> {item.get('verdict')}")
        for key, value in (item.get("fitted") or {}).items():
            prior = (was.get("fitted") or {}).get(key)
            if isinstance(value, float) and isinstance(prior, float) and abs(value - prior) > 1e-3:
                lines.append(f"{item['id']}: {key} {prior} -> {value}")
    return lines


def _cell(rows: list[dict], rule: str) -> str:
    row = next((r for r in rows if r["id"] == rule), None)
    if row is None:
        return "–"
    return f"{row['spec']} / {row['measured']}{'' if row['ok'] else ' ✗'}"


def markdown(result: dict) -> str:
    tol = result["tolerances"]
    counts: dict[str, int] = {}
    for item in result["items"]:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
    lines = [
        "# Underwear audit",
        "",
        f"Generated by `tools/catalog/underwear_audit.py` on {result['generatedAt'][:10]}, avatar "
        f"`{result['avatar']}`: {', '.join(f'{n} {v}' for v, n in sorted(counts.items()))}. Each piece "
        "is fitted exactly as its preview is; the tool's docstring has the definitions.",
        "",
        *[
            f"Re-measured on {update['at'][:10]} (`--only`, the other records kept as published): "
            f"{', '.join(f'`{i}`' for i in update['ids'])}.\n"
            for update in result.get("updates", [])
        ],
        "Each column is *spec / measured*, ✗ outside tolerance. **Pattern** coverage is the "
        "builder's own figure for the drafted pattern (±0.02), against that template's own spec: "
        "a G-string is held to a G-string's 0.03 at the back, a brief to a brief's 0.85. **Side** "
        "and **back width** are millimetres on the fitted piece against the spec "
        f"(±{int(tol['lengthShare'] * 100)}% or {tol['lengthFloorMm']:.0f} mm). **Drift** is the "
        "fitted piece against its own pattern, measured the same way on both: fitting must not "
        f"change the silhouette (coverage ±{tol['coverage']}).",
        "",
        "**Hard** failures mean the piece is not its design. **Soft** ones are outside ranges "
        "this project set and has not yet calibrated against measured fabric (ASTM D4964 / "
        "D2594-style tension curves) or a deformable body: the reference bodies are rigid, so "
        "pressure is a contact proxy, not a physiological figure.",
        "",
        "| Template | Kind | Verdict | Pattern front | Pattern back | Side mm | Back width mm "
        "| Drift front / back | Sit (Wide): inside, deepest, stretch | Hard | Soft |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["items"]:
        rows = item.get("comparison", [])
        sit = (item.get("contact") or {}).get("sittingWide") or {}
        drift = [r for r in rows if r["id"] in ("drift.frontCoverage", "drift.backCoverage")]
        moved = " / ".join(f"{r['measured'] - r['spec']:+.3f}{'' if r['ok'] else ' ✗'}" for r in drift) or "–"
        contact = (
            f"{sit['penetratingPct']}%, {sit['maxPenetrationMm']} mm, {sit['maxEdgeStretch']}x"
            if sit
            else "–"
        )
        hard, soft = (", ".join(item.get(k, [])) or "–" for k in ("hard", "soft"))
        lines.append(
            f"| `{item['id']}` | {item['kind']} | {item['verdict']} "
            f"| {_cell(rows, 'pattern.frontCoverage')} | {_cell(rows, 'pattern.backCoverage')} "
            f"| {_cell(rows, 'fitted.sideHeightMm')} | {_cell(rows, 'fitted.backWidthMm')} | {moved} "
            f"| {contact} | {hard} | {soft} |"
        )
    for item in result["items"]:
        if not item.get("parts"):
            continue
        lines += [
            "",
            f"## `{item['id']}`: the pieces it is worn with",
            "",
            f"Built as `{item.get('builtAs')}`; the row above is that piece. Every piece the card puts "
            "on her, measured on the same fitted look (contact is the worst of a piece's primitives):",
            "",
            "| Piece | Template | Role | Vertices | Standing: inside, deepest | "
            "Sit (Wide): inside, deepest, stretch | Geometry |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for part in item["parts"]:
            if not part.get("fitted"):
                lines.append(f"| {part['name']} | `{part.get('templateId')}` | {part['role']} | not fitted |")
                continue
            stand, sit = part["contact"].get("standing", {}), part["contact"].get("sittingWide", {})
            lines.append(
                f"| {part['name']} | `{part.get('templateId') or '–'}` | {part['role']} | {part['vertices']} "
                f"| {stand.get('penetratingPct')}%, {stand.get('maxPenetrationMm')} mm "
                f"| {sit.get('penetratingPct')}%, {sit.get('maxPenetrationMm')} mm, "
                f"{sit.get('maxEdgeStretch')}x | `{part['geometrySha256'][:12]}` |"
            )
        tension = ((item.get("hosiery") or {}).get("straps") or {}).get("tension") or {}
        if tension:
            limits = item["hosiery"]["straps"].get("thresholds", {})
            lines += [
                "",
                f"Strap strain per pose, from the fit report (warning past {limits.get('warning')}, "
                f"error past {limits.get('error')}; negative is slack):",
                "",
                "| Strap | Rest length mm | Stand | Walk | Sit |",
                "| --- | --- | --- | --- | --- |",
            ]
            for row in tension.values():
                strain, status = row["stretch"], row["status"]
                poses = ("stand", "walk", "sit")
                cells = " | ".join(f"{strain[pose]:+.3f} ({status[pose]})" for pose in poses)
                lines.append(f"| {row['strap']} | {row['restLengthM'] * 1000:.1f} | {cells} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--before", type=Path, default=None, help="an earlier run's audit.json to compare")
    parser.add_argument(
        "--publish", action="store_true", help="also write the numbers to assets/catalog/adult/ and docs/"
    )
    args = parser.parse_args()
    out = _outside(args.out)
    result = asyncio.run(audit(out, set(args.only)))
    (out / "audit.json").write_text(json.dumps(result, indent=1) + "\n")
    (out / "audit.md").write_text(markdown(result))
    if args.before is not None:
        changes = diff(json.loads(args.before.read_text()), result)
        print("\n".join(changes) or "no change from --before")
    if args.publish:
        target = ROOT / "assets/catalog/adult/underwear-audit.json"
        published = merged(json.loads(target.read_text()), result) if args.only else result
        target.write_text(json.dumps(published, indent=1) + "\n")
        (ROOT / "docs/UNDERWEAR_AUDIT.md").write_text(markdown(published))
    counts = {}
    for item in result["items"]:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
