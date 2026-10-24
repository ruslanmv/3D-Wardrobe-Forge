# Lingerie fabric physics: what is known, what is not, and how to measure it

Behaviour and appearance are separate. Appearance (colour, sheerness, lace motif,
shading) stays in `wardrobe/lingerie/fabrics.py` and the material plan. Behaviour is in
`assets/reference/lingerie/materials/fabrics.json`, one record per fabric class, every
value with a **status**:

| Status | Meaning | May drive geometry? |
| --- | --- | --- |
| `measured` | a cited test on a named fabric | yes |
| `designer-convention` | a cited pattern-maker's allowance (e.g. FreeSewing Uma's 15% stretch) | yes, labelled as such |
| `class-typical` | this project's estimate for the class | yes, labelled; replace when measured |
| `unmeasured` | `null`, with the procedure to measure it | no |

`tools/data/verify_lingerie_sources.py` refuses a number without a source, and an
unmeasured value that is not null or has no procedure.

## What is known today (2026-10-24)

* **Stretch allowance of a stretch knit:** 15% across, 5% along — FreeSewing Uma's
  defaults, a designer's negative ease, not a test result. It is the one material value
  that changes geometry: the Uma-drafted gusset width divides by `1 + stretch`
  (`wardrobe.lingerie.references`). A fabric class without its own allowance falls back to
  Uma's and the fit report says so.
* **Elastic force curves:** `wardrobe/lingerie/elastic.py ELASTICS`, typical of picot-edge
  and plush-back lingerie elastic, not a measured lot. They drive the reported strain and
  pressure, not the geometry.
* **Everything else** — areal density, thickness, course/wale stretch at load, recovery,
  shear and bending stiffness, friction, lace opening — is unmeasured. No open, licensed
  dataset of these for lingerie fabrics was found: T2P is gated and research-only, and
  GarmentCode's simulator constants are solver tuning, not measurements.

## How to measure a fabric (calibration procedure)

The procedures are in each value's `calibrate` field. In short, on a conditioned specimen:
weigh 100 cm² for areal density; a thickness gauge at a stated pressure; extension at a
stated load across and along (the low-power knit family of tests, ASTM D2594 class) and
residual growth after a timed hold for recovery; force–extension of each elastic (the
ASTM D4964 family) replaces its class-typical curve. Record the lab, the fabric, the date
and the standard actually followed; set `status: measured` and `source` to a lock record.
Never mark a value as certified unless the test certificate says so.

## Physical limits of the simulation

* The bodies are rigid. Elastic "pressure" is Laplace's law on a rigid ring: a contact
  proxy, useful to rank, not a physiological pressure.
* There is no cloth solver in the request path: garments are drafted on her and pushed out
  of her surface (shell, `fit.seat_gusset`), then skinned. Stretch under pose is measured
  (`tools/inspect/pose_contact.py`), not simulated.
* A higher-fidelity solver belongs offline (catalogue rendering, research), not in an API
  request; see `docs/POSE_CONTACT_QA.md` for the posed-correction plan.

## Adding a fabric class

Add a record to `classes` with every mechanical property (unmeasured unless you have a
source), `patternStretchCourse` / `patternStretchWale`, and an `opacity`. Reference it from a
template's `lingerie.fabric`. Run `python tools/data/verify_lingerie_sources.py`.
