"""CB2. Named regions of a reference body, so a contact result says where on her it was taken.

The old reports gave one minimum for a whole garment, and a gusset's −4 mm and a strap's +1 mm
were indistinguishable in it. ``clearance`` reports by region when the contact body has labels;
these are those labels, one per vertex, found from her own landmarks so they move with her size.

The regions are deliberately coarse and are defined geometrically, not painted:

* ``external-genital-region`` — between her thighs from the crotch point forward and up to the
  pubic area: the mound, the folds beside it and the mons of her pelvic outlet (AN-A2), from a
  reviewed atlas at its resolution (``reference.ANATOMY``). The label keeps a garment's contact
  there reported by name, so a report says it was taken on that approximation — one woman's
  surface at about 5 mm, closed — and never on finer anatomy than was built;
* ``breast`` — each breast, from the bust point out to the inframammary fold and the upper pole;
* ``gluteal`` — each buttock, around the buttock point down to the gluteal fold;
* ``inner-thigh`` — the medial thighs below the crotch, where leg openings and gussets sit;
* ``body`` — everything else.

A vertex belongs to the first region in that order whose rule it meets, so the labels partition
her surface.
"""

from __future__ import annotations

import numpy as np

from wardrobe.anatomy.contact import EXTERNAL_GENITAL_REGION

BREAST = "breast"
GLUTEAL = "gluteal"
INNER_THIGH = "inner-thigh"
BODY = "body"
REGIONS = (EXTERNAL_GENITAL_REGION, BREAST, GLUTEAL, INNER_THIGH, BODY)

#: Half-width of the genital region either side of her midline. About the width of the pubic arch
#: at the surface on the median body; wide enough that a gusset seam beside it is not in it.
GENITAL_HALF_WIDTH_M = 0.03
#: ... from this far behind the crotch point (the perineum is not part of it). The pelvic outlet's
#: mound (AN-A2) reaches 33 mm behind the crotch point on every size, the vulva's posterior end;
#: at the 15 mm this was before, its back third was reported as thigh and plain body.
GENITAL_BACK_M = 0.035
#: ... up to this fraction of the way from the crotch point to the navel (the pubic area's top).
GENITAL_TOP_FRACTION = 0.45
#: Breast: within this distance of the bust point, and in front of her chest wall.
BREAST_RADIUS_M = 0.085
#: Buttock: within this distance of the buttock point, behind her hip joints.
GLUTEAL_RADIUS_M = 0.11
#: Inner thigh: this far down from the crotch, within this distance of the midline.
INNER_THIGH_DEPTH_M = 0.20
INNER_THIGH_HALF_WIDTH_M = 0.12


def region_labels(V: np.ndarray, landmarks: dict, joints: dict) -> np.ndarray:
    """One region name per vertex (a numpy array of str)."""
    V = np.asarray(V, dtype=np.float64)
    x, y, z = V[:, 0], V[:, 1], V[:, 2]
    lm = {k: np.asarray(v, dtype=np.float64) for k, v in landmarks.items()}
    crotch, navel = lm["crotch"], lm["omphalion"]
    labels = np.full(V.shape[0], BODY, dtype=object)
    free = np.ones(V.shape[0], dtype=bool)

    def claim(mask, name):
        m = mask & free
        labels[m] = name
        free[m] = False

    top = crotch[1] + GENITAL_TOP_FRACTION * (navel[1] - crotch[1])
    claim(
        (np.abs(x) < GENITAL_HALF_WIDTH_M)
        & (y >= crotch[1] - 0.005)
        & (y <= top)
        & (z >= crotch[2] - GENITAL_BACK_M),
        EXTERNAL_GENITAL_REGION,
    )
    wall = float(np.mean([joints["joint-spine-1"][2], joints["joint-spine-2"][2]]))
    for name in ("bustPointLeft", "bustPointRight"):
        p = lm[name]
        claim(
            (np.linalg.norm(V - p, axis=1) < BREAST_RADIUS_M)
            & (z > wall + 0.05)
            & (np.sign(x) == np.sign(p[0])),
            BREAST,
        )
    hip_z = float(joints["joint-pelvis"][2])
    for sign in (1.0, -1.0):
        p = lm["buttockPoint"].copy()
        p[0] = sign * abs(p[0])
        claim(
            (np.linalg.norm(V - p, axis=1) < GLUTEAL_RADIUS_M) & (z < hip_z) & (np.sign(x) == sign), GLUTEAL
        )
    thigh = (y < crotch[1]) & (y > crotch[1] - INNER_THIGH_DEPTH_M) & (np.abs(x) < INNER_THIGH_HALF_WIDTH_M)
    # Medial half of each thigh only: closer to the midline than the thigh's own centre line.
    centre = {
        s: np.array([joints[f"joint-{s}-upper-leg"][0], joints[f"joint-{s}-knee"][0]]).mean() for s in "lr"
    }
    medial = np.where(x > 0, x < centre["l"], x > centre["r"])
    claim(thigh & medial, INNER_THIGH)
    return labels.astype(str)


__all__ = ["BODY", "BREAST", "GLUTEAL", "INNER_THIGH", "REGIONS", "region_labels"]
