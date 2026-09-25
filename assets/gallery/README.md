# Verification gallery

21 looks, each through the real pipeline, on one faceless, clearly adult
calibration mannequin (`calibration-c-tall`, MToon), rendered front 3/4 and
front in the A-pose by the Studio's viewer. Every caption is the job's own plan
and fit report. `gallery.json` has the full record per look. Regenerate with
[`tools/gallery`](../../tools/gallery/README.md).

These are **quality evidence, not marketing**. The mannequin is deliberately
low-poly and faceless; what to judge is the garment: whether it sits on her,
whether its material reads as the prompt asked, and whether layers stay in
order. The same fitting code on four real VRoid avatars is in
[`real/`](real/README.md).

| #   | Look                                                                     | Prompt                                                                                            | What it checks                                                                            |
| --- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| 1   | [Opaque everyday baseline](01-opaque-everyday-baseline.webp)             | black fitted crop top + blue straight jeans                                                       | Opaque baseline; nothing adult-gated                                                      |
| 2   | [Classic lingerie set](02-classic-lingerie-set.webp)                     | black satin bralette + matching briefs                                                            | Satin finish; "matching" carries colour and finish                                        |
| 3   | [Sheer lace lingerie](03-sheer-lace-lingerie.webp)                       | black unlined lace bralette + matching high-leg briefs                                            | Unlined lace is an alpha **mask** (holes, not a tint); opaque elastic trim; high leg      |
| 4   | [Transparent mesh lingerie](04-transparent-mesh-lingerie.webp)           | burgundy mesh bralette + matching briefs                                                          | Mesh is blend 0.55 on both pieces; opaque trim                                            |
| 5   | [Minimal / micro lingerie](05-minimal-micro-lingerie.webp)               | black minimal triangle bralette + black micro string-side briefs                                  | Coverage presets; triangle cups; straps start at the cup                                  |
| 6   | [Lingerie under a sheer dress](06-lingerie-under-a-sheer-dress.webp)     | black bralette + matching briefs + red sheer bodycon mini dress                                   | Layer order through a blend layer; underwear visible, not poking through                  |
| 7   | [Lingerie under an opaque dress](07-lingerie-under-an-opaque-dress.webp) | black bralette + matching briefs + red bodycon mini dress                                         | Underwear fully hidden; no poke-through                                                   |
| 8   | [Fishnet stockings](08-fishnet-stockings.webp)                           | black fishnet thigh-high stockings                                                                | Fishnet mask; solid top band; leg conform                                                 |
| 9   | [Lace bodysuit](09-lace-bodysuit.webp)                                   | black unlined lace high-leg bodysuit                                                              | Planner picks the Bodysuit, not the Lingerie Set                                          |
| 10  | [One-piece swimsuit](10-one-piece-swimsuit.webp)                         | glossy red high-leg one-piece swimsuit                                                            | Gloss finish; high-leg cut                                                                |
| 11  | [Micro bikini](11-micro-bikini.webp)                                     | black micro triangle string bikini                                                                | Micro coverage; string straps                                                             |
| 12  | [Glossy latex](12-glossy-latex.webp)                                     | neon green latex leggings + black crop top                                                        | Latex finish; leggings conform to the legs                                                |
| 13  | [Sequin mini dress](13-sequin-mini-dress.webp)                           | pink sequin bodycon mini dress                                                                    | Sequin texture and matcap                                                                 |
| 14  | [Denim short shorts](14-denim-short-shorts.webp)                         | blue high-waisted denim shorts + white crop top                                                   | High rise                                                                                 |
| 15  | [Sheer top over an opaque bra](15-sheer-top-over-an-opaque-bra.webp)     | black bra + translucent black chiffon cami                                                        | Translucent 0.7 over an opaque foundation                                                 |
| 16  | [Lined lace dress](16-lined-lace-dress.webp)                             | black lined lace bodycon mini dress                                                               | Lined lace is opaque and **not** gated; motif reads on its lining                         |
| 17  | [Satin slip dress](17-satin-slip-dress.webp)                             | champagne satin slip dress with spaghetti straps                                                  | Champagne colour; satin; spaghetti straps                                                 |
| 18  | [Catsuit](18-catsuit.webp)                                               | glossy black catsuit                                                                              | One-piece with legs and sleeves                                                           |
| 19  | [Layered complete outfit](19-layered-complete-outfit.webp)               | black lace bralette + black briefs + black thigh-high stockings + red sheer mini dress + black cropped jacket | Five layers in one VRM, inner first                                           |
| 20  | [Source-clothing replacement](20-source-clothing-replacement.webp)       | black bralette + matching briefs + red bodycon mini dress                                         | Base Body Prep: her own top and trousers come off, underwear goes on first                |
| 21  | [Metallic mini dress](21-metallic-mini-dress.webp)                       | shiny silver bodycon mini dress                                                                   | Metallic matcap                                                                           |

All 21 jobs complete and pass fit. #8 and #19 report clearance as
`clearance-only` because stockings are worn wholly on the legs. The torso index
has nothing of theirs to check, so they are fitted by the limb conform, and a
layered outfit reports its weakest layer's verdict.

## Adult gate

A look is marked `[18+ gated]` when any of its garments is: an intimate category
(underwear, swimwear), a template that requires it, or a material that exposes
the body (unlined lace, mesh, sheer, fishnet). Lined lace (#16), an opaque dress
over underwear (#7's dress) and an opaque catsuit (#18) are not. The mannequin's
job declares `depictsAdult`; a prompt cannot, and `assets/library/policy.json`
ships empty.

## Known limitations visible here

- **Sleeves stand off this mannequin's arms** (#1, #14, #18, #19). Its arms are
  thin, square prisms, and a sleeve is a round tube with ease over them. On the
  real avatars, whose arms are measured, sleeves sit close: see
  [`real/`](real/README.md).
- **Lace trim is not its own region.** The lace sets (#3, #9) have an opaque
  elastic band, but no scalloped edge.
- **A seam where a bodice meets its skirt** (#17), and where a yoke meets the
  legs (#1, #12, #14, #18): the two pieces are separate meshes, and the join
  shows as a line.
- **A-pose only.** The gallery renders the viewer's relaxed pose; other poses
  are covered by the pose stress test, not by pictures.
- **Layered outfits use the native engine only.** Blender does not yet attach
  more than one layer.

Fixed since the first version of this gallery, by dressing the real avatars:
jeans and shorts had side panels standing off the hips, and leggings a ledge at
the waistband. Every torso band now ends at the measured crotch, and every leg
starts there ([docs/FIT_QUALITY.md](../../docs/FIT_QUALITY.md)).
