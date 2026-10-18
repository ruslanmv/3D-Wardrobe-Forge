"""RB5. The evidence for the reference bodies and the contact body, regenerated, not written down.

    python tools/anatomy/validate_reference.py [--quick]

For every reference size, from its recorded modifiers:

* **dimensions** — each calibrated dimension against its ANSUR II target and tolerance, and the
  reported ones beside their survey or literature values;
* **reproduction** — re-measuring the rebuilt body gives the numbers its record stores;
* **topology** — the reference surface (rest pose) and the T-posed surface the VRM is built from:
  closed, manifold, one component, Euler characteristic 2, and the exact self-intersection count;
* **landmarks** — the vertex each dimension is measured at against detection by the measurer's
  rules on that body;
* **creases** — gluteal fold, inframammary fold and inguinal crease depths
  (``wardrobe.anatomy.creases``);
* **contact** — ``ContactBody`` against brute force (exactness), and its sign against the winding
  number and against cross-section even-odd tests (consistency);
* **regions** — how much of her surface each contact region holds.

The old fit form is put through the same topology and crease checks, so the two can be compared.
The report is ``assets/anatomy/validation-report.json``; ``docs/ANATOMY_VALIDATION.md`` is generated
from it. ``--quick`` skips self-intersection on the posed surfaces and uses fewer contact samples.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.anatomy import creases as C  # noqa: E402
from wardrobe.anatomy import reference as R  # noqa: E402
from wardrobe.anatomy import regions as G  # noqa: E402
from wardrobe.anatomy import topology as TOP  # noqa: E402
from wardrobe.anatomy.contact import ContactBody, closest_on_triangles  # noqa: E402
from wardrobe.anatomy.vrm import t_pose  # noqa: E402

REPORT = ROOT / "assets" / "anatomy" / "validation-report.json"
SUMMARY = ROOT / "docs" / "ANATOMY_VALIDATION.md"
SEED = 20261017


def dimensions(size_id: str, measured: dict, template: dict) -> dict:
    """Her dimensions as built (with her pelvic outlet) against the survey; reproduction is of the
    template surface the record was measured on (``template``), since the outlet is fitted after it."""
    record = R.reference_bodies()["bodies"][size_id]
    rows = {}
    bound = R.acceptance(size_id)
    for k, tol in R.TOLERANCE.items():
        t = R.targets(size_id)[k]
        rows[k] = {
            "measured": round(measured[k], 1),
            "target": round(t, 1),
            "difference": round(measured[k] - t, 1),
            "tolerance": tol,
            "within": bool(abs(measured[k] - t) <= tol),
            "acceptanceBound": round(bound[k], 2),
            "accepted": bool(abs(measured[k] - t) <= bound[k]),
        }
    reported = {}
    for k, t in R.reported_targets(size_id).items():
        reported[k] = {
            "measured": round(measured[k], 1),
            "reference": round(t, 1),
            "difference": round(measured[k] - t, 1),
        }
    reported["underbustcircumference"] = {
        "measured": round(measured["underbustcircumference"], 1),
        "reference": None,
    }
    drift = max(abs(template[k] - record["measured"][k]) for k in record["measured"])
    return {"calibrated": rows, "reported": reported, "reproductionMaxDifference": round(drift, 4)}


def landmark_agreement(V, T, J) -> dict:
    by_vertex = {k: V[i] for k, i in R.landmark_vertices().items()}
    detected = R.detect_landmarks(V, T, J)
    out = {k: round(float(np.linalg.norm(by_vertex[k] - detected[k])) * 1000, 1) for k in by_vertex}
    # The crotch is held on its height (the dimension taken there): its underside is flat front to
    # back, and "lowest point" slides along it.
    out["crotch"] = round(abs(float(by_vertex["crotch"][1] - detected["crotch"][1])) * 1000, 1)
    return out


def contact_checks(V, T, labels, samples: int, winding: int, rng) -> dict:
    started = time.time()
    body = ContactBody(V, T, labels=labels)
    built = time.time() - started
    # Points within 2 cm of her surface, either side.
    tri = rng.integers(0, T.shape[0], samples)
    w = rng.dirichlet([1, 1, 1], samples)
    p = np.einsum("ij,ijk->ik", w, V[T[tri]])
    n = body.face_normal[tri]
    p = p + n * rng.uniform(-0.02, 0.02, samples)[:, None]
    started = time.time()
    q = body.query(p)
    per = (time.time() - started) / samples
    clear = np.isfinite(q.distance) & (np.abs(q.distance) > 2e-4)
    # Exactness: brute force over every triangle for a subset.
    sub = np.flatnonzero(clear)[:60]
    a, b, c = (V[T[:, k]] for k in range(3))
    worst = 0.0
    for i in sub:
        cp, _ = closest_on_triangles(np.repeat(p[i][None], T.shape[0], axis=0), a, b, c)
        exact = float(np.linalg.norm(cp - p[i], axis=1).min())
        worst = max(worst, abs(exact - abs(float(q.distance[i]))))
    # Sign against the winding number.
    wsub = np.flatnonzero(clear)[:winding]
    wn = body.winding_number(p[wsub])
    agree_w = int(((wn > 0.5) == (q.distance[wsub] < 0)).sum())
    # Sign against cross-section even-odd, on points lying in four transverse planes.
    sections = {}
    lm = {k: V[i] for k, i in R.landmark_vertices().items()}
    planes = {
        "belowCrotch": float(lm["crotch"][1]) - 0.03,
        "seat": float(lm["buttockPoint"][1]),
        "waist": float(lm["omphalion"][1]),
        "bust": float(lm["bustPointLeft"][1]),
    }
    for name, y in planes.items():
        lo, hi = V.min(axis=0), V.max(axis=0)
        pts = np.column_stack(
            [rng.uniform(lo[0], hi[0], 4000), np.full(4000, y), rng.uniform(lo[2], hi[2], 4000)]
        )
        d = body.signed_distance(pts)
        near = np.isfinite(d) & (np.abs(d) > 2e-4)
        inside = body.section_inside(
            pts[near], 1, y - 1e-6
        )  # the loops are cut 1e-6 above y; meet them there
        sections[name] = {"points": int(near.sum()), "agree": int((inside == (d[near] < 0)).sum())}
    by_region = {}
    for name in G.REGIONS:
        m = clear & (labels[T[np.where(q.triangle >= 0, q.triangle, 0), 0]] == name) & (q.triangle >= 0)
        by_region[name] = int(m.sum())
    return {
        "buildSeconds": round(built, 1),
        "querySecondsPer1000": round(per * 1000, 2),
        "samples": int(samples),
        "exactness": {"points": int(sub.size), "maxDifferenceMm": round(worst * 1000, 6)},
        "windingAgreement": {"points": int(wsub.size), "agree": agree_w},
        "sectionAgreement": sections,
        "samplesByRegion": by_region,
    }


def region_areas(V, T, labels) -> dict:
    a, b, c = (V[T[:, k]] for k in range(3))
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    tl = labels[T[:, 0]]
    return {name: round(float(area[tl == name].sum()) * 1e4, 1) for name in G.REGIONS}  # cm²


def old_fit_form() -> dict:
    from wardrobe.vrm.fashion_body import build_fit_form_mesh, fit_form, form_landmarks, positions_for

    form = fit_form("fit-form-a-misses")
    pos = positions_for(form)
    mesh = build_fit_form_mesh(form, pos)
    V = np.asarray(mesh.positions, dtype=np.float64)
    T = np.asarray(mesh.indices, dtype=np.int64).reshape(-1, 3)
    topo = TOP.check(V, T).to_dict()
    marks = form_landmarks(form, pos)
    seat = V[
        (np.abs(V[:, 0]) > 0.02)
        & (np.abs(V[:, 0]) < 0.14)
        & (V[:, 1] > marks["crotch"])
        & (V[:, 1] < marks["waist"])
    ]
    bust = V[(V[:, 0] > 0.03) & (V[:, 0] < 0.2) & (np.abs(V[:, 1] - marks["bust"]) < 0.05)]
    landmarks = {
        "crotch": [0.0, marks["crotch"], 0.0],
        "omphalion": [0.0, marks["waist"], 0.0],
        "buttockPoint": seat[np.argmin(seat[:, 2])].tolist(),
        "bustPointLeft": bust[np.argmax(bust[:, 2])].tolist(),
    }
    joints = {"joint-l-upper-leg": np.asarray(pos["leftUpperLeg"])}
    return {
        "name": form.name,
        "topology": topo,
        "creases": C.creases(V, T, landmarks, joints),
        "creasesNote": "Not comparable with the reference bodies: the form's leg tube runs up through its "
        "trunk's flat floor, and the profile measure reads the step between the two pieces, not a fold.",
    }


def main(argv: list[str]) -> int:
    quick = "--quick" in argv
    rng = np.random.default_rng(SEED)
    report = {
        "schema": "wardrobe.anatomy.validationReport.v1",
        "subdivisionLevels": R.LEVELS,
        "unmodelled": R.UNMODELLED,
        "anatomy": R.ANATOMY,
        "bodies": {},
    }
    outlet = json.loads((ROOT / "assets" / "anatomy" / "pelvic-outlet.json").read_text())
    for size_id in R.reference_bodies()["bodies"]:
        started = time.time()
        V, T, J, m = R.reference_body(size_id)
        template = R.reference_body(size_id, pelvic_outlet=False)[3]
        labels = G.region_labels(V, m.landmarks, J)
        P, _ = t_pose(V, J)
        report["bodies"][size_id] = {
            "dimensions": dimensions(size_id, m.values, template.values),
            "pelvicOutlet": {
                "fit": outlet[size_id]["fit"],
                "measurementShiftMm": outlet[size_id]["measurementShiftMm"],
            },
            "topology": {
                "rest": TOP.check(V, T).to_dict(),
                "tPose": TOP.check(P, T, self_intersection=not quick).to_dict(),
            },
            "landmarkAgreementMm": landmark_agreement(V, T, J),
            "creases": C.creases(V, T, m.landmarks, J),
            "bustProjection": C.bust_projection(V, T, m.landmarks),
            "contact": contact_checks(V, T, labels, 2000 if quick else 8000, 60 if quick else 200, rng),
            "regionAreasCm2": region_areas(V, T, labels),
            "seconds": None,
        }
        report["bodies"][size_id]["seconds"] = round(time.time() - started, 1)
        print(f"{size_id}: {report['bodies'][size_id]['seconds']} s", flush=True)
    report["oldFitForm"] = old_fit_form()
    REPORT.write_text(json.dumps(report, indent=1) + "\n")
    SUMMARY.write_text(summary(report))
    return 0


def summary(r: dict) -> str:
    sizes = list(r["bodies"])
    out = [
        "# Anatomy reference bodies — validation",
        "",
        "Generated by `python tools/anatomy/validate_reference.py` from "
        "`assets/anatomy/validation-report.json`. Do not edit by hand; see `docs/ANATOMY_REFERENCE.md` for "
        "what the checks mean.",
        "",
        "## Dimensions (measured − ANSUR II target, mm; weight kg)",
        "",
        "| dimension | tolerance | " + " | ".join(sizes) + " |",
        "|---|---|" + "---|" * len(sizes),
    ]
    for k, tol in R.TOLERANCE.items():
        cells = []
        for s in sizes:
            row = r["bodies"][s]["dimensions"]["calibrated"][k]
            mark = "" if row["within"] else (" ¹" if row["accepted"] else " ²")
            cells.append(f"{row['difference']:+.1f}{mark}")
        out.append(f"| {k} | ±{tol:g} | " + " | ".join(cells) + " |")
    out += [
        "",
        "¹ outside tolerance, within the acceptance bound: twice the larger of the tolerance and the "
        "regression's residual SD for that dimension (see `reference.acceptance`). ² outside the bound.",
        "",
        "## Reported, not calibrated",
        "",
        "| dimension | " + " | ".join(sizes) + " |",
        "|---|" + "---|" * len(sizes),
    ]
    for k in r["bodies"][sizes[0]]["dimensions"]["reported"]:
        cells = []
        for s in sizes:
            row = r["bodies"][s]["dimensions"]["reported"][k]
            ref = "—" if row["reference"] is None else f"{row['reference']:.0f}"
            cells.append(f"{row['measured']:.0f} (ref {ref})")
        out.append(f"| {k} | " + " | ".join(cells) + " |")
    out += [
        "",
        "## Topology",
        "",
        "| surface | closed manifold | components | χ | self-intersections | volume L |",
        "|---|---|---|---|---|---|",
    ]
    for s in sizes:
        for pose, t in r["bodies"][s]["topology"].items():
            closed = (
                t["boundaryEdges"] == 0 and t["nonManifoldEdges"] == 0 and t["duplicateDirectedEdges"] == 0
            )
            out.append(
                f"| {s} ({pose}) | {'yes' if closed else 'no'} | {t['components']} | "
                f"{t['eulerCharacteristic']} | {t['selfIntersections']} | {t['volumeL']} |"
            )
    t = r["oldFitForm"]["topology"]
    out.append(
        f"| old {r['oldFitForm']['name']} | {'yes' if t['boundaryEdges'] == 0 else 'no'} "
        f"({t['boundaryEdges']} open edges) | {t['components']} | {t['eulerCharacteristic']} | "
        f"{t['selfIntersections']} | {t['volumeL']} |"
    )
    out += [
        "",
        "## Creases (depth below a taut tape over the profile, mm)",
        "",
        "| crease | " + " | ".join(sizes) + " | old fit form |",
        "|---|" + "---|" * (len(sizes) + 1),
    ]
    for k in ("glutealFold", "inframammaryFold", "inguinalCrease"):
        cells = [f"{r['bodies'][s]['creases'][k]['depthMm']:.1f}" for s in sizes]
        out.append(
            f"| {k} | " + " | ".join(cells) + f" | ({r['oldFitForm']['creases'][k]['depthMm']:.1f}) ³ |"
        )
    cells = [f"{r['bodies'][s]['bustProjection']['projectionMm']:+.1f}" for s in sizes]
    out.append("| bust point in front of abdomen (reported, not a rule) | " + " | ".join(cells) + " | — |")
    out += ["", "³ " + r["oldFitForm"]["creasesNote"]]
    out += [
        "",
        "## Landmarks (measuring vertex vs detection on the body, mm; the crotch on its height)",
        "",
        "| landmark | " + " | ".join(sizes) + " |",
        "|---|" + "---|" * len(sizes),
    ]
    for k in r["bodies"][sizes[0]]["landmarkAgreementMm"]:
        out.append(
            f"| {k} | " + " | ".join(f"{r['bodies'][s]['landmarkAgreementMm'][k]:.1f}" for s in sizes) + " |"
        )
    out += [
        "",
        "## Contact body",
        "",
        "| size | exact vs brute force (max mm) | winding agrees | sections agree | query ms/1000 |",
        "|---|---|---|---|---|",
    ]
    for s in sizes:
        c = r["bodies"][s]["contact"]
        sec = sum(v["agree"] for v in c["sectionAgreement"].values())
        tot = sum(v["points"] for v in c["sectionAgreement"].values())
        out.append(
            f"| {s} | {c['exactness']['maxDifferenceMm']:.6f} ({c['exactness']['points']} pts) | "
            f"{c['windingAgreement']['agree']}/{c['windingAgreement']['points']} | {sec}/{tot} | "
            f"{c['querySecondsPer1000'] * 1000:.0f} |"
        )
    out += [
        "",
        "## Regions (surface area, cm²)",
        "",
        "| region | " + " | ".join(sizes) + " |",
        "|---|" + "---|" * len(sizes),
    ]
    for k in G.REGIONS:
        out.append(
            f"| {k} | " + " | ".join(f"{r['bodies'][s]['regionAreasCm2'][k]:.0f}" for s in sizes) + " |"
        )
    out += [
        "",
        "## Pelvic outlet (AN-A2: HRA female skin, CC BY 4.0, fitted to each size)",
        "",
        "| size | scale x/y/z | pitch ° | ring agreement mm | residual mm | vertices moved | max move mm | "
        "measurements moved (mm) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in sizes:
        o = r["bodies"][s]["pelvicOutlet"]
        f = o["fit"]
        shift = ", ".join(f"{k} {v:+.1f}" for k, v in o["measurementShiftMm"].items() if abs(v) >= 0.5)
        out.append(
            f"| {s} | {'/'.join(f'{x:.3f}' for x in f['scale'])} | {f['pitchDegrees']:g} | "
            f"{f['ringAgreementMm']:.1f} | {f['weightedResidualMm']:.3f} | {f['verticesMoved']} | "
            f"{f['maxMoveMm']:.1f} | {shift} |"
        )
    for title, key in (("Modelled", "modelled"), ("Approximated", "approximated"),
                       ("Not supported", "unsupported")):
        out += ["", f"## {title}", ""] + [f"- **{k}** — {v}" for k, v in r["anatomy"][key].items()]
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
