"""RB2. The anatomical template: MakeHuman's hm08 body, varied by its own targets, subdivided.

The template is imported once by ``tools/anatomy/import_makehuman.py`` (CC0 assets; provenance in
``assets/anatomy/makehuman-provenance.json``). This module is the arithmetic MakeHuman's
modifiers stand for, written here from their published conventions — it uses none of
MakeHuman's (AGPL) program code:

* **macro** modifiers interpolate between target sets: ``weight`` in [0, 1] blends the min-,
  average- and max-weight targets (0.5 is average and adds nothing); ``height`` and
  ``proportions`` blend their min/max targets, each weighted by the same weight factors, as the
  macro system couples them;
* **breast** ``cup`` and ``firmness`` in [0, 1] blend the six cup x firmness targets (0.5 / 0.5
  adds nothing);
* **paired** modifiers in [-1, 1] apply their ``decr`` target below zero and ``incr`` above.

The surface is then subdivided once (Catmull–Clark). The base mesh's edges are about 2 cm in
the pelvis — too coarse to carry millimetre contact — and a subdivision surface is the smooth
limit the artists modelled toward. The subdivision is a fixed sparse linear operator, built once,
so a calibration step costs a matrix product. A closed all-quad mesh subdivides to a closed
all-quad mesh: watertightness is preserved by construction (and tested).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT / "assets" / "anatomy" / "makehuman-hm08.npz"

WEIGHTS = ("minweight", "averageweight", "maxweight")
#: Modifiers and their ranges. Neutral values add nothing.
MACRO = {
    "weight": (0.0, 1.0, 0.5),
    "height": (0.0, 1.0, 0.5),
    "proportions": (0.0, 1.0, 0.5),
    "cup": (0.0, 1.0, 0.5),
    "firmness": (0.0, 1.0, 0.5),
}
PAIRED = {
    "bust": ("measure/measure-bust-circ-decr", "measure/measure-bust-circ-incr"),
    "underbust": ("measure/measure-underbust-circ-decr", "measure/measure-underbust-circ-incr"),
    "waist": ("measure/measure-waist-circ-decr", "measure/measure-waist-circ-incr"),
    "hips": ("measure/measure-hips-circ-decr", "measure/measure-hips-circ-incr"),
    "thigh": ("measure/measure-thigh-circ-decr", "measure/measure-thigh-circ-incr"),
    "knee": ("measure/measure-knee-circ-decr", "measure/measure-knee-circ-incr"),
    "calf": ("measure/measure-calf-circ-decr", "measure/measure-calf-circ-incr"),
    "ankle": ("measure/measure-ankle-circ-decr", "measure/measure-ankle-circ-incr"),
    "neck": ("measure/measure-neck-circ-decr", "measure/measure-neck-circ-incr"),
    "upperarm": ("measure/measure-upperarm-circ-decr", "measure/measure-upperarm-circ-incr"),
    "wrist": ("measure/measure-wrist-circ-decr", "measure/measure-wrist-circ-incr"),
    "frontchest": ("measure/measure-frontchest-dist-decr", "measure/measure-frontchest-dist-incr"),
    "napetowaist": ("measure/measure-napetowaist-dist-decr", "measure/measure-napetowaist-dist-incr"),
    "waisttohip": ("measure/measure-waisttohip-dist-decr", "measure/measure-waisttohip-dist-incr"),
    "shoulder": ("measure/measure-shoulder-dist-decr", "measure/measure-shoulder-dist-incr"),
    "upperleg": ("measure/measure-upperleg-height-decr", "measure/measure-upperleg-height-incr"),
    "lowerleg": ("measure/measure-lowerleg-height-decr", "measure/measure-lowerleg-height-incr"),
    "buttocks": ("buttocks/buttocks-volume-decr", "buttocks/buttocks-volume-incr"),
    "stomach": ("stomach/stomach-pregnant-decr", "stomach/stomach-pregnant-incr"),
    "pelvisTone": ("pelvis/pelvis-tone-decr", "pelvis/pelvis-tone-incr"),
    "torsoDepth": ("torso/torso-scale-depth-decr", "torso/torso-scale-depth-incr"),
    "hipForward": ("hip/hip-trans-backward", "hip/hip-trans-forward"),
    "breastDist": ("breast/breast-dist-decr", "breast/breast-dist-incr"),
    "breastHeight": ("breast/breast-trans-down", "breast/breast-trans-up"),
    "torsoWidth": ("torso/torso-scale-horiz-decr", "torso/torso-scale-horiz-incr"),
    "hipWidth": ("hip/hip-scale-horiz-decr", "hip/hip-scale-horiz-incr"),
    "hipDepth": ("hip/hip-scale-depth-decr", "hip/hip-scale-depth-incr"),
}


@dataclass
class Modifiers:
    values: dict[str, float] = field(default_factory=dict)

    def get(self, name: str) -> float:
        if name in MACRO:
            return float(self.values.get(name, MACRO[name][2]))
        return float(self.values.get(name, 0.0))


def _blend3(v: float) -> tuple[float, float, float]:
    """(min, average, max) factors for a [0, 1] macro value; 0.5 is all average."""
    return max(0.0, 1.0 - 2.0 * v), 1.0 - abs(2.0 * v - 1.0), max(0.0, 2.0 * v - 1.0)


class Template:
    def __init__(self, path: Path = TEMPLATE_PATH):
        data = np.load(path)
        self.base = data["vertices"].astype(np.float64)
        self.faces = data["faces"].astype(np.int64)
        self.body_count = int(data["body_count"])
        names = [str(n) for n in data["target_names"]]
        self.targets = {}
        for k, name in enumerate(names):
            self.targets[name.removesuffix(".target")] = (
                data[f"t{k}_idx"].astype(np.int64),
                data[f"t{k}_delta"].astype(np.float64),
            )
        offsets = data["joint_offsets"]
        self.joints = {
            str(n): (int(offsets[i]), int(offsets[i + 1])) for i, n in enumerate(data["joint_names"])
        }

    def _add(self, out: np.ndarray, name: str, weight: float) -> None:
        if weight == 0.0:
            return
        idx, delta = self.targets[name]
        np.add.at(out, idx, delta * weight)

    def vertices(self, modifiers: Modifiers) -> np.ndarray:
        """Body and joint-helper vertices for these modifier values (metres)."""
        out = self.base.copy()
        wf = dict(zip(WEIGHTS, _blend3(modifiers.get("weight")), strict=True))
        self._add(out, "macrodetails/universal-female-young-averagemuscle-minweight", wf["minweight"])
        self._add(out, "macrodetails/universal-female-young-averagemuscle-maxweight", wf["maxweight"])
        hmin, _, hmax = _blend3(modifiers.get("height"))
        pmin, _, pmax = _blend3(modifiers.get("proportions"))
        for w, f in wf.items():
            self._add(out, f"macrodetails/height/female-young-averagemuscle-{w}-minheight", f * hmin)
            self._add(out, f"macrodetails/height/female-young-averagemuscle-{w}-maxheight", f * hmax)
            self._add(
                out, f"macrodetails/proportions/female-young-averagemuscle-{w}-uncommonproportions", f * pmin
            )
            self._add(
                out, f"macrodetails/proportions/female-young-averagemuscle-{w}-idealproportions", f * pmax
            )
        cmin, _, cmax = _blend3(modifiers.get("cup"))
        for firmness, ff in zip(
            ("minfirmness", "averagefirmness", "maxfirmness"), _blend3(modifiers.get("firmness")), strict=True
        ):
            self._add(out, f"breast/female-young-averagemuscle-averageweight-mincup-{firmness}", cmin * ff)
            self._add(out, f"breast/female-young-averagemuscle-averageweight-maxcup-{firmness}", cmax * ff)
        for name, (decr, incr) in PAIRED.items():
            v = modifiers.get(name)
            self._add(out, decr, max(0.0, -v))
            self._add(out, incr, max(0.0, v))
        return out

    def joint_positions(self, vertices: np.ndarray) -> dict[str, np.ndarray]:
        return {name: vertices[a:b].mean(axis=0) for name, (a, b) in self.joints.items()}


# ---------------------------------------------------------------------------------------------
# Catmull–Clark subdivision as a fixed sparse operator
# ---------------------------------------------------------------------------------------------
@dataclass
class Subdivision:
    """``apply(V)`` = new vertex positions; ``faces`` = the subdivided quads."""

    rows: np.ndarray
    cols: np.ndarray
    vals: np.ndarray
    count: int
    faces: np.ndarray

    def apply(self, vertices: np.ndarray) -> np.ndarray:
        out = np.zeros((self.count, 3))
        np.add.at(out, self.rows, vertices[self.cols] * self.vals[:, None])
        return out


def catmull_clark(faces: np.ndarray, vertex_count: int) -> Subdivision:
    """One Catmull–Clark step for a closed quad mesh, as a linear operator on vertex positions.

    New vertices are laid out as the originals, then one face point per face, then one edge
    point per edge. With n the valence of a vertex v, the rules written in original positions:

    * face point  = 1/4 of each corner;
    * edge point  = (a + b + both face points) / 4 = a/4 + b/4 + 1/16 of each corner of both faces;
    * vertex      = (Q + 2R + (n - 3) v) / n, with Q the mean of its faces' points and R the mean of
      its edges' midpoints: v gets (n - 2)/n, each neighbour 1/n^2, and each corner of each
      adjacent face 1/(4 n^2).
    """
    F = faces.shape[0]
    edges = np.stack([faces, np.roll(faces, -1, axis=1)], axis=2).reshape(-1, 2)  # face k's edges at 4k..4k+3
    unique, edge_of = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True)
    edge_of = edge_of.reshape(-1)
    E = unique.shape[0]
    fp0, ep0 = vertex_count, vertex_count + F
    n = np.bincount(unique.reshape(-1), minlength=vertex_count).astype(np.float64)
    rows, cols, vals = [], [], []

    def add(r, c, v):
        rows.append(np.asarray(r).reshape(-1))
        cols.append(np.asarray(c).reshape(-1))
        vals.append(np.broadcast_to(np.asarray(v, dtype=np.float64), np.asarray(r).reshape(-1).shape).copy())

    add(np.repeat(fp0 + np.arange(F), 4), faces.reshape(-1), 0.25)  # face points
    add(ep0 + np.repeat(np.arange(E), 2), unique.reshape(-1), 0.25)  # edge points: ends
    face_of = np.repeat(np.arange(F), 4)  # ... both faces
    add(np.repeat(ep0 + edge_of, 4), faces[face_of].reshape(-1), 0.0625)
    corner_v = faces.reshape(-1)  # vertex points
    add(np.repeat(corner_v, 4), faces[face_of].reshape(-1), np.repeat(0.25 / n[corner_v] ** 2, 4))
    add(unique[:, 0], unique[:, 1], 1.0 / n[unique[:, 0]] ** 2)
    add(unique[:, 1], unique[:, 0], 1.0 / n[unique[:, 1]] ** 2)
    add(np.arange(vertex_count), np.arange(vertex_count), np.where(n > 0, (n - 2.0) / np.maximum(n, 1), 1.0))
    nxt = edge_of.reshape(F, 4)
    prv = np.roll(nxt, 1, axis=1)
    new_faces = np.stack(
        [faces, ep0 + nxt, np.repeat(fp0 + np.arange(F)[:, None], 4, axis=1), ep0 + prv], axis=2
    ).reshape(-1, 4)
    return Subdivision(
        np.concatenate(rows), np.concatenate(cols), np.concatenate(vals), vertex_count + F + E, new_faces
    )


@lru_cache(maxsize=1)
def template() -> Template:
    return Template()


@lru_cache(maxsize=2)
def subdivision(levels: int = 1) -> tuple[Subdivision, ...]:
    t = template()
    out, faces, count = [], t.faces, t.body_count
    for _ in range(levels):
        step = catmull_clark(faces, count)
        out.append(step)
        faces, count = step.faces, step.count
    return tuple(out)


def triangles(quads: np.ndarray) -> np.ndarray:
    return np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])


def body_surface(
    modifiers: Modifiers, levels: int = 1
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """(vertices, triangles, joints) of the subdivided body for these modifiers, standing on y = 0.

    The template's origin is not the floor: MakeHuman puts its soles about 85 mm below it (its
    ``joint-ground`` helper is at -89 mm). Every height the survey defines is from the floor she
    stands on, so the surface — and its joints, by the same amount — is lifted until its lowest
    point is at 0. Measured from the template origin instead, the first calibration made a woman
    1714 mm tall that it reported as 1629, with every height below the head short by the offset.
    The lift is taken on the subdivided surface (subdivision pulls the soles up slightly), so a
    body is grounded at the level it is measured at.
    """
    t = template()
    v = t.vertices(modifiers)
    joints = t.joint_positions(v)
    body = v[: t.body_count]
    faces = t.faces
    for step in subdivision(levels):
        body, faces = step.apply(body), step.faces
    lift = np.array([0.0, -float(body[:, 1].min()), 0.0])
    return body + lift, triangles(faces), {k: p + lift for k, p in joints.items()}


__all__ = [
    "MACRO",
    "PAIRED",
    "Modifiers",
    "Subdivision",
    "Template",
    "body_surface",
    "catmull_clark",
    "subdivision",
    "template",
    "triangles",
]
