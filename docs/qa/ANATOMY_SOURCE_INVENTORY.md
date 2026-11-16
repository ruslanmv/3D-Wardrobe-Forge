# AF1 — What anatomy the library sources actually contain

Measured 2026-11-15 on `feat/bare-base-body` (`a57ef3b`) with `tools/audit/anatomy_inventory.py`,
which reads each source with the pipeline's own readers (`inspect_document`, `measure_body`,
`skin_parts` — her skin chosen by material, her clothes excluded) and changes nothing.

Regions: **pubic** = skin within 6 cm of a point between the thigh roots, 6 cm below them, on the
front surface; **bust** = skin within 4 cm of each breast apex. "Relief" is the RMS departure from a
smooth quadric fit; in the pubic sphere it is dominated by the thigh–torso junction, not by detail.

| Source | Pubic: skin vertices / median edge | Pubic texture | Bust: vertices / edge / relief | Bust texture | Class |
|---|---|---|---|---|---|
| AvatarSample A | 59 / 22.0 mm | painted shorts | 102 / 5.8 mm / 0.6 mm | flat skin | C |
| AvatarSample B | 63 / 21.5 mm | painted shorts | 103 / 5.7 mm / 0.6 mm | painted top | C |
| AvatarSample C | 34 / 24.0 mm | painted shorts | 13 / 21.9 mm / 1.2 mm | flat | C |
| VRoid Female | 69 / 22.2 mm | painted black briefs | 92 / 6.3 mm / 0.6 mm | flat skin | C |
| VRoid Male | 61 / 22.0 mm | painted black briefs | 9 / 27.4 mm / 0 mm | flat | C |
| AvatarSample O | 87 / 16.5 mm | painted panties | 21 / 18.9 mm / 1.2 mm | flat | C |
| Model Girl | 75 / 16.8 mm | flat skin | 81 / 5.9 mm / 0.9 mm | flat skin | C |
| Rinna | 36 / 23.1 mm | painted pink set | 22 / 22.3 mm / 2.9 mm | painted top | C |

Texture classes were confirmed by looking at the texels under those vertices, not by the colour
heuristic alone (the heuristic flags painted underwear and authored pigmentation alike).

## What this means

- **Case A (anatomy exists, lost in processing): none.** No source has genital or nipple geometry: a
  16–24 mm pelvic mesh cannot hold detail a few millimetres across, and no bust region departs from a
  smooth surface by more than 3 mm.
- **Case B (detail in texture/normal map, damaged in processing): none.** The only non-skin texels in
  these regions are painted underwear, which `restore_skin` is meant to remove. No source has a body
  normal map carrying anatomical detail. No material is labelled anatomical.
- **Case C (the source has no such anatomy): all eight.** A bare look of these sources is, faithfully,
  a smooth body. Garment removal cannot reveal what was never authored.

## Concealment audit

No censor mesh, blur, mosaic, pixelation or modesty material exists in Forge (`wardrobe/`, `apps/`,
`tools/`) or in the companion app's `src/`. The bare path (`wardrobe/pipeline/bare_body.py`)
fingerprints and verifies every retained accessor (positions, normals, UVs, weights, indices, morph
targets), preserves normal maps, and refuses rather than repaints author-labelled anatomical
materials. The simplified appearance comes from the sources, not from the pipeline.

## Operation B

Adding anatomy these sources lack needs an asset the repository can carry. The asset review
(`docs/ANATOMY_ASSETS.md`) found none for external genital anatomy: MakeHuman's `helper-genital` is a
generic attachment helper, community proxies are unverified, and the Human Reference Atlas surface is a
real person's body (the Visible Human Female), which the body-surface installer's real-person-scan
rule excludes from anything shown. The options remain a licensed commercial model, a verified CC0/CC
BY community asset, or a commissioned mesh.
