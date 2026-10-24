# Lingerie measurement methods

How a lingerie dimension is measured here, and which of five different things a number
is. Units: millimetres for lengths, fractions for shares, kPa for pressure, degrees for
angles.

## Five kinds of number, never mixed

| Kind | What it is | Where it comes from in this repository |
| --- | --- | --- |
| **Body** | A measurement of her, unclothed, standing | `wardrobe/lingerie/landmarks.py` on the avatar; ANSUR II percentiles in `assets/anatomy/reference-sizes.json`; reference bodies such as GarmentCode's in `assets/reference/lingerie/measurements/` |
| **Flat pattern** | A dimension of a pattern piece as drafted, before it is on anyone | A template's `lingerie` block (`wardrobe/lingerie/specs.py`); a reference draft (`patterns/*/*.json`) |
| **Relaxed garment** | The made-up garment off the body: the pattern after seams and trims | Not modelled separately yet: the builder drafts straight onto her frame |
| **Fitted** | The garment on her at rest | The fitted mesh: `tools/catalog/underwear_audit.py` (`fitted` block) |
| **Posed** | The garment on her in a pose | `tools/inspect/pose_contact.py` in HomePilot's poses |

A coverage share, for example, exists as a flat-pattern figure (the template's
`backCoverage`, which the leg-line solver meets to 0.02 in its own column parameter) and as a
fitted figure (the audit's, measured geometrically round her hip axis). The two are on
different scales — on the same mesh the geometric figure reads 0.05–0.12 higher, for every
style alike — so the audit compares spec to pattern in the pattern's own measure, and pattern
to fitted in the geometric one, and never one scale against the other.

## Body landmarks (`wardrobe/lingerie/landmarks.py`)

Taken from her surface, not from bone ratios, as a technical designer marks a dress form:
waist (narrowest section between hips and chest), full hip (widest above the crotch), high
hip (halfway), bust points (per side, the most forward point of the chest band), underbust
fold (below each bust point, where the front meets the ribcage), sternum, centre front and
back, side seams, crotch. Each records whether it was measured or fell back to a formula;
a fallback warns, it does not fail.

## Measurement definitions after GarmentMeasurements

GarmentMeasurements (GPL-3.0, not copied; see `LINGERIE_SOURCE_LICENSES.md`) defines its
body measurements on a template mesh in two families, described here in our own words:

* **Landmark distances** — the distance between two named landmarks, optionally along one
  axis: `bust_points` is the distance between the left and right bust landmarks.
* **Girths** — the length of a ring round a selection of the body cut by a plane, optionally
  over its convex hull (a tape measure bridges hollows): `underbust` is a convex-hull girth
  in a horizontal plane through the underbust selection; `bust`, `waist` and `hips` likewise.

Forge's own measurements follow the same two families. A convex-hull girth is the one to use
wherever a tape would bridge (across the cleavage, between the buttocks).

## Reference body: GarmentCode's average female

`measurements/garmentcode/garmentcode-mean-female.json`, from GarmentMeasurements' own body
model (not SMPL), in mm: bust 974, underbust 807, bust points 162 apart, waist 803, hips 1041,
crotch-to-hip difference 79. Use it as a second, independently measured body to check that
a pattern rule grades sensibly, not as a size standard.

## Uncertainty

| Number | Uncertainty | Why |
| --- | --- | --- |
| Avatar landmark | ±2–5 mm | 5 mm sampling slabs (`SLAB_M`); VRoid topology varies |
| Flat-pattern coverage | ±0.02 | the solver's tolerance |
| Fitted coverage | ±0.03 drift between pattern and fit, measured | `underwear-audit.json` |
| Contact depth in a pose | ranks, not absolute | rigid skin; nearest-vertex normals (`POSE_CONTACT_QA.md`) |
| Elastic pressure | a contact proxy only | the bodies are rigid; no measured elastic curve yet |
