"""AN-A2. Import the pelvic region of a reviewed anatomical atlas: the HRA female skin, CC BY 4.0.

    python tools/anatomy/import_hra.py [--glb <path to 3d-vh-f-skin.glb>]

Why this source. The reference bodies' template (MakeHuman hm08, ``import_makehuman.py``) closes
the space between her thighs with an artist's flat plateau about 8 cm wide, and nothing CC0 in
MakeHuman's own assets models the external anatomy there (``docs/ANATOMY_ASSETS.md``). The
Human Reference Atlas (HuBMAP / HRA, Indiana University, NIH Common Fund) publishes a reference
organ "skin of body, female": the outer surface of the Visible Human Female, segmented from the
National Library of Medicine's cryosection data by the atlas's own anatomists and released, with
a DOI and a version history, under **CC BY 4.0**. It is a real body's surface, reviewed as part
of an atlas, and its licence lets this repository carry a derived file with attribution.

What it resolves, measured at import (``docs/ANATOMY_ASSETS.md`` has the numbers): median edges
of about 6 mm between her thighs, so the mons, the vulval outer contour as one closed mound (the
labia majora, apposed as they are in the scan), the genitocrural folds either side and the
perineum's start are there; nothing finer than the edges is. It is the surface of a cadaver
frozen lying on her back, and its legs are closer together than a standing reference body's,
which is why only the region is taken and why ``wardrobe.anatomy.pelvis`` fits it rather than
pasting it.

This tool:

* reads the GLB (by default downloads it from the atlas's CDN at the pinned version) and refuses
  a file whose SHA-256 is not the pinned one, so a changed upstream file is noticed, not absorbed;
* welds the exporter's split vertices by position (the GLB repeats a vertex per normal) and
  checks the result is one closed manifold;
* finds her midline (the centre of her trunk's breadth at three heights) and her crotch point
  (the lowest point of her trunk on that midline, as ``reference.detect_landmarks`` defines it);
* keeps the faces within ``CROP_M`` of the crotch point, translated so the crotch point is the
  origin and the midline is x = 0, and the trunk's breadth and depth 7 cm above the crotch that
  the fit scales by.

Output: ``assets/anatomy/hra-pelvis.npz`` and ``assets/anatomy/hra-provenance.json`` (source,
version, DOI, creators, licence, the attribution to reproduce, every change made, both hashes).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.anatomy import measure as M  # noqa: E402
from wardrobe.anatomy.topology import check  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402

VERSION = "v1.5"
GLB_URL = f"https://cdn.humanatlas.io/digital-objects/ref-organ/skin-female/{VERSION}/assets/3d-vh-f-skin.glb"
LANDING = f"https://lod.humanatlas.io/ref-organ/skin-female/{VERSION}"
GLB_SHA256 = "b7dc8b3e5bae070f22f2619b10194b012a6f3cf930836d251828d5893e69594c"
DOI = "https://doi.org/10.48539/HBM453.MVPL.398"
CITATION = (
    "Browne, Kristen, and Heidi Schlehlein. 2024. 3D Reference Organ for Skin, Female v1.5. "
    "Human Reference Atlas, HuBMAP. https://doi.org/10.48539/HBM453.MVPL.398"
)
OUT_NPZ = ROOT / "assets" / "anatomy" / "hra-pelvis.npz"
OUT_JSON = ROOT / "assets" / "anatomy" / "hra-provenance.json"
#: Welding tolerance: the exporter's copies of one vertex agree to the float.
WELD_M = 1e-6
#: The crop around her crotch point. Larger than the fit's reach (14 cm, plus 4 cm of search).
CROP_M = {"x": 0.17, "below": 0.17, "above": 0.21}
#: Where her trunk's breadth and depth are taken to scale the region to a body.
SCALE_HEIGHT_M = 0.07


def read_glb(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    doc = GltfDocument.from_bytes(data)
    (mesh,) = doc.gltf["meshes"]
    (prim,) = mesh["primitives"]
    V = np.asarray(doc.read_accessor(prim["attributes"]["POSITION"]), dtype=np.float64)
    F = np.asarray(doc.read_accessor(prim["indices"]), dtype=np.int64).reshape(-1, 3)
    for node in doc.gltf.get("nodes", []):
        if any(k in node for k in ("matrix", "translation", "rotation", "scale")):
            raise ValueError("the skin node carries a transform; positions would not be metres in her frame")
    return V, F


def weld(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    keys = np.round(V / WELD_M).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    W = V[first]
    G = inverse.reshape(-1)[F]
    G = G[(G[:, 0] != G[:, 1]) & (G[:, 1] != G[:, 2]) & (G[:, 2] != G[:, 0])]
    return W, G


def trunk_section(V: np.ndarray, F: np.ndarray, y: float) -> np.ndarray:
    """Her trunk's loop at height ``y``: the widest loop (x, z) there, arms being separate loops."""
    return max(M.section_loops(V, F, 1, y), key=lambda lp: float(np.ptp(lp[:, 0])))


def landmarks(V: np.ndarray, F: np.ndarray) -> dict:
    mids = []
    for y in (0.0, 0.05, 0.10):  # her pelvis, in the atlas's frame (origin near her navel)
        lp = trunk_section(V, F, y)
        mids.append((lp[:, 0].min() + lp[:, 0].max()) / 2)
    x0 = float(np.mean(mids))
    loop = max(M.section_loops(V, F, 0, x0), key=len)  # (y, z)
    low = loop[np.argmin(loop[:, 0])]
    crotch = np.array([x0, low[0], low[1]])
    section = trunk_section(V, F, crotch[1] + SCALE_HEIGHT_M)
    return {
        "midlineX": x0,
        "crotch": crotch,
        "breadth": float(np.ptp(section[:, 0])),
        "depth": float(np.ptp(section[:, 1])),
    }


def crop(V: np.ndarray, F: np.ndarray, crotch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r = V - crotch
    inside = (np.abs(r[:, 0]) < CROP_M["x"]) & (r[:, 1] > -CROP_M["below"]) & (r[:, 1] < CROP_M["above"])
    faces = F[inside[F].all(axis=1)]
    used = np.unique(faces)
    remap = np.full(V.shape[0], -1, dtype=np.int64)
    remap[used] = np.arange(used.size)
    return r[used], remap[faces]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--glb", type=Path, help="a local copy of 3d-vh-f-skin.glb (else downloaded)")
    args = parser.parse_args(argv)
    if args.glb:
        data = args.glb.read_bytes()
    else:
        with urllib.request.urlopen(GLB_URL, timeout=300) as response:  # noqa: S310 - pinned https URL
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != GLB_SHA256:
        print(f"refused: SHA-256 {digest} is not the pinned {GLB_SHA256}", file=sys.stderr)
        return 1
    V, F = weld(*read_glb(data))
    whole = check(V, F, self_intersection=False)
    if not whole.closed_manifold or whole.components != 1:
        print(f"refused: the welded skin is not one closed manifold: {whole.to_dict()}", file=sys.stderr)
        return 1
    marks = landmarks(V, F)
    PV, PF = crop(V, F, marks["crotch"])  # the crotch point is on her midline, so that is x = 0
    edges = np.linalg.norm(PV[PF] - PV[np.roll(PF, 1, axis=1)], axis=2)
    np.savez_compressed(
        OUT_NPZ,
        vertices=PV.astype(np.float32),
        faces=PF.astype(np.int32),
        breadth=np.float64(marks["breadth"]),
        depth=np.float64(marks["depth"]),
    )
    provenance = {
        "source": "Human Reference Atlas (HuBMAP), 3D Reference Organ: skin of body, female",
        "version": VERSION,
        "landingPage": LANDING,
        "file": GLB_URL,
        "doi": DOI,
        "creators": ["Kristen Browne", "Heidi Schlehlein"],
        "funder": "National Institutes of Health (Common Fund, HuBMAP)",
        "underlyingData": "National Library of Medicine Visible Human Project, female (Spitzer et al. 1998, "
        "Anat Rec 253(2):49-57)",
        "licence": "CC BY 4.0",
        "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": CITATION + ". Licensed under CC BY 4.0. Cropped and registered by 3D-Wardrobe-Forge.",
        "changes": [
            "split vertices welded by position",
            "cropped to the pelvic region: faces within "
            f"{CROP_M['x']} m of the midline, {CROP_M['below']} m below and {CROP_M['above']} m above "
            "the crotch",
            "translated so the crotch point is the origin and the midline is x = 0",
            "fitted onto each reference body by wardrobe.anatomy.pelvis (scaled, pitched, mirrored and "
            "averaged, "
            "blended), which changes its shape",
        ],
        "glbSha256": digest,
        "welded": {"vertices": int(V.shape[0]), "triangles": int(F.shape[0]), "closedManifold": True},
        "crop": {
            "vertices": int(PV.shape[0]),
            "triangles": int(PF.shape[0]),
            "medianEdgeMm": round(float(np.median(edges)) * 1000, 2),
            "crotchInAtlasFrame": [round(float(c), 5) for c in marks["crotch"]],
            "midlineX": round(marks["midlineX"], 5),
            "trunkBreadthM": round(marks["breadth"], 4),
            "trunkDepthM": round(marks["depth"], 4),
            "scaleHeightM": SCALE_HEIGHT_M,
        },
        "npzSha256": hashlib.sha256(OUT_NPZ.read_bytes()).hexdigest(),
    }
    OUT_JSON.write_text(json.dumps(provenance, indent=1) + "\n")
    print(json.dumps(provenance["crop"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
