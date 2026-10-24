# Pose contact QA: measuring garments in HomePilot's poses

A garment that fits standing can still fail when the avatar sits: it sinks into her,
stretches, or tears at a seam. The fit report's own pose check
(`geometry_checks.pose_stress_test`) deforms the garment alone and only asks whether
it stays finite and how far an edge stretches, so it cannot see any of that. These
tools pose the whole fitted file — her skin and every garment, each by its own joints
and weights — with the exact rotations HomePilot's Pose Studio applies, and measure
each garment against her posed skin.

Use them for every new release of the avatar library, the garment templates, the
skinning (`wardrobe/vrm/weight_transfer.py`, `wardrobe/engines/native.py`) or Pose
Studio, and keep the numbers beside the change.

## The tools

| Tool                                        | What it does                                                                                |
| ------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `tools/inspect/export_homepilot_poses.mjs`  | Exports Pose Studio's presets from a HomePilot checkout as quaternions                      |
| `tools/inspect/fit_look.py`                 | Fits one look on a library avatar through the real pipeline and saves the VRM               |
| `tools/inspect/pose_contact.py`             | Measures every garment of a VRM in each pose: clearance, depth inside, share inside, stretch |
| `tools/inspect/contact_sheet.py`            | Builds the QA sheet for one look and one pose, with an optional before/after comparison     |
| `tools/inspect/fit_inspect.py`              | Garment-on-a-grey-dress-form frames for fit inspection (see its docstring)                  |

Output always goes to a directory **outside the repository**; the tools refuse a path
inside it, so no inspection file can be committed by accident.

## Requirements

- The Forge Python environment (`pip install -e '.[dev]'`) and `make library` for the
  library avatars.
- For the sheet: Node, Playwright and Chromium, as `tools/gallery` needs
  (`PLAYWRIGHT_CHROMIUM`, and `GALLERY_CDN_ROUTE` where three.js must come from a local
  copy).
- For exporting poses: a checkout of
  [3D-Avatar-Chatbot](https://github.com/ruslanmv/3D-Avatar-Chatbot).

Lingerie and other adult-gated garments fit only on an avatar the operator has declared
adult in `assets/library/policy.json` (today `fem-vroid`). The tools have no way round
that gate, by design.

## A full run

```bash
OUT=/tmp/pose-qa            # anywhere outside the repository

# 1. The poses HomePilot applies (skip when tests/fixtures/homepilot-poses.json is current).
node tools/inspect/export_homepilot_poses.mjs ../3D-Avatar-Chatbot $OUT/poses.json

# 2. A look, fitted the way the API fits it.
python tools/inspect/fit_look.py --avatar fem-vroid --prompt "red bodycon mini dress" \
    --template dress-mini-bodycon-v1 --out $OUT/bodycon.vrm

# 3. The numbers, every garment, every pose in the file.
python tools/inspect/pose_contact.py $OUT/bodycon.vrm --poses tests/fixtures/homepilot-poses.json \
    --json $OUT/bodycon.contact.json

# 4. The sheet for one pose, against the same look made before a change.
python tools/inspect/contact_sheet.py $OUT/bodycon.vrm --before $OUT/bodycon-before.vrm \
    --pose sittingWide --garment "Red Bodycon Mini Dress" --garment "Beige Tailored Briefs" \
    --out $OUT/sheet
```

To compare two versions of the code, run step 2 on each (for instance in a
`git worktree` of the older commit), then pass the older file as `--before`.

## Reading the numbers

Per garment and pose (`pose_contact.py`, and `metrics.json` beside a sheet):

| Field              | Meaning                                                                      |
| ------------------ | ---------------------------------------------------------------------------- |
| `minClearanceMm`   | Smallest signed distance from a garment vertex to her skin; negative inside  |
| `maxPenetrationMm` | The deepest a garment vertex is inside her                                   |
| `penetratingPct`   | Share of garment vertices more than 1 mm inside her                          |
| `maxEdgeStretch`   | The most any garment edge is stretched against its rest length               |
| `stretchedPct`     | Share of edges stretched past 1.5×                                           |
| `insideBy`         | Where the inside vertices are: the bone carrying her nearest skin, counted   |

Inside is decided against her nearest skin vertex's normal, posed with her. It is
exact enough to rank garments, poses and versions; it is not a watertight solid test,
and where her own skin folds into itself (the hip crease at 90° of flexion) a garment
following the skin exactly is still counted partly inside.

## Reading the sheet

- **A** — the whole look, front, side, back, in the pose.
- **B** — each garment alone (body and other garments hidden): product view,
  wireframe (the topology of seams, gusset and leg openings), side.
- **C** — each garment coloured by its clearance (blue clear, green contact 0–2 mm,
  yellow to red inside, red at 15 mm or more) and by stretch (white at rest length,
  yellow 1.5×, red 2.5× or more).
- **D** — with `--before`: the old file's clearance beside the new one, and the numbers.

The technical rows show garments only, never the body: the measurements carry what a
picture of the body would.

## Baseline, recorded 2026-10-24

VRoid Female, Sitting (Wide), from this branch:

| Garment                 | Binding            | Inside | Deepest | Max stretch |
| ----------------------- | ------------------ | ------ | ------- | ----------- |
| Red Bodycon Mini Dress  | pelvis (before PS3) | 11.47% | 33.5 mm | 2.10×       |
| Red Bodycon Mini Dress  | her skin (PS3)     | 4.76%  | 22.3 mm | 3.92×       |
| Beige Tailored Briefs   | her skin           | 7.63%  | 14.1 mm | 2.92×       |
| Black Micro Tailored Thong | her skin        | 1.26%  | 4.0 mm  | 2.02×       |
| Black Tailored Bodysuit | her skin           | 3.02%  | 16.3 mm | 2.57×       |
| Black Thigh-High Stockings | hosiery         | 8.58%  | 21.7 mm | 2.44×       |

Known defects these numbers pointed at:

1. **Briefs tear at the gusset when she sits wide — reduced by PF2, see below.** The
   first diagnosis (neighbouring gusset vertices following opposite thighs) was only part
   of it: of the 200 worst-stretched edges, few flip sides. Most join a vertex with a lot
   of thigh weight to one with little, because its nearest skin was her pelvis (leggings'
   crotch: 0.46 against 0.06; a brief's leg opening: 0.62 against 0.33).
2. **10–17 mm inside at the seat and thigh creases** for every second-skin bottom when
   seated: linear blend skinning at 90° hip flexion. Needs a posed correction pass
   (push garment vertices out of the posed body once per pose change), not a weight
   change; narrowing the transfer to one skin vertex was tried and stretched more.
3. **Stockings sink up to 54 mm into her thighs** with legs crossed: a hosiery binding
   problem of its own.

## PF2: second-skin weights smoothed between her legs, 2026-10-24

`wardrobe/vrm/weight_transfer.py: smooth_below_hips`. A second-skin garment (`whole`)
copies the weights of the skin nearest each vertex, and between her legs and round her
seat the nearest skin changes owner abruptly. The weights are now diffused over the
garment's own surface, seams welded, from the top of her hip band down to 14 cm below
her hip bone, fading out by 22 cm (well above her knee). A step becomes a slope about
2 cm wide.

Five looks on VRoid Female, fitted with `tools/inspect/fit_look.py`, before (PS3) and
after; deepest point and maximum edge stretch:

| Garment                    | Sitting (Wide) before | after          | Sitting (Crossed) before | after          |
| -------------------------- | --------------------- | -------------- | ------------------------ | -------------- |
| Beige Tailored Briefs      | 14.3 mm, 2.37×        | 14.3 mm, 1.68× | 11.7 mm, 3.33×           | 11.4 mm, 2.06× |
| Black Micro Tailored Thong | 4.0 mm, 2.02×         | 5.1 mm, 1.34×  | 6.7 mm, 3.21×            | 4.1 mm, 1.70×  |
| Black Tailored Bodysuit    | 16.3 mm, 2.57×        | 16.0 mm, 1.68× | 12.0 mm, 4.08×           | 10.2 mm, 2.57× |
| Red Bodycon Mini Dress     | 22.3 mm, 3.92×        | 23.0 mm, 2.32× | 16.5 mm, 5.66×           | 17.0 mm, 3.48× |
| Black Leggings             | 16.9 mm, 7.11×        | 16.8 mm, 5.07× | 13.1 mm, 9.38×           | 16.0 mm, 6.80× |

Kneeling is unchanged (leggings 13.3 mm, briefs 5.7 mm). Standing is unchanged.

**The radius is a trade.** At 3 cm the seated brief reached 1.44×, but a vertex whose
weights are further from the skin under it lags her when she moves: striding, briefs went
0.58 mm into the median reference body, which `test_second_skin_binding.py` rightly
forbids. At 2 cm that is zero again. Reaching wider across the knee was worse still:
leggings sank 20 mm into the knee kneeling, which is why the smoothing fades out above it.

**What is left.** Leggings still stretch 5–7× at the crotch point, where her thighs
cross under a single vertex: no choice of weights lets one point follow two thighs that
move apart. That, and the 10–17 mm at the seat creases, need the posed correction pass
(defect 2), not skinning weights.
