# Verification gallery

Regenerates `assets/gallery/`: 21 looks on one mannequin, and
`assets/gallery/real/`: fifteen looks on each of the four library avatars. Each
look is rendered front 3/4 and front in the A-pose by the Studio's own viewer,
and captioned with what the pipeline planned and how the fit report scored it.

```bash
OUT=$(mktemp -d)
python tools/gallery/looks.py "$OUT"          # the looks, through the real orchestrator
node tools/gallery/render.mjs "$OUT"          # two renders per look (Playwright + Chromium)
python tools/gallery/compose.py "$OUT"        # captioned images + gallery.json -> assets/gallery
```

`looks.py OUT 3 19` and `render.mjs OUT 03 19` redo only those looks;
`g-records.json` keeps the rest.

### On the real avatars

```bash
for a in AvatarSample_A AvatarSample_B AvatarSample_C fem_vroid; do
  python tools/gallery/looks.py "$OUT/$a" --avatar assets/library/$a.vrm
  node tools/gallery/render.mjs "$OUT/$a"
  python tools/gallery/compose.py "$OUT/$a" assets/gallery/real/$a
done
python tools/gallery/showcase.py "$OUT"      # docs/images/lookbook.webp, before-after.webp
```

`--avatar` runs `EVERYDAY_LOOKS`, fifteen outfits, on that VRM exactly as it
arrives: dressed, with its own body, skeleton and hair. A library avatar goes in
the way the Studio sends it, with the licence from the provenance manifest and
any declaration from `policy.json`. The tool adds nothing: it is not the
operator. So the real-avatar set holds the looks no adult gate applies to. They
exercise the same fitting code as the rest, on bodies nobody generated.
`make library` fetches the avatars first.

`showcase.py` builds the README's pictures from those renders. Which looks
appear is a list in the script, so a change of selection shows in a diff.

## What it needs

- The Forge's Python environment (`pip install -e .[dev]`) plus Pillow for
  `compose.py`.
- Node with `playwright` resolvable from this directory and a Chromium.
  `PLAYWRIGHT_CHROMIUM=/path/to/chromium` picks the browser.
- Network access to `cdn.jsdelivr.net` for three.js and three-vrm, which the
  viewer loads by URL. Sandboxes that proxy the CDN can set `GALLERY_CDN_ROUTE`
  to a module exporting `routeCdn(context)`.

## Why it is built this way

- **The real pipeline, not a mock-up.** `looks.py` submits jobs to the
  `Orchestrator` exactly as the API does, so a picture is what a user would get
  from that prompt. The captions come from the job's plan and fit report, not
  from anyone describing the picture afterwards: a caption that disagrees with
  its image is a finding.
- **One faceless, clearly adult mannequin.** `calibration-c-tall` from
  `wardrobe/vrm/build.py`, given an MToon material so toon transparency is what
  gets tested. The job declares `depictsAdult: true` for it, as an operator does
  for a real avatar; nothing in a prompt can.
- **The Studio's viewer, not a bespoke renderer.** `render.mjs` serves
  `apps/studio/js/viewer.js` next to the looks, so a material that renders wrong
  here renders wrong in the Studio and the chatbot too.
- **Device scale 1, framed by height.** The viewer sizes its canvas in CSS
  pixels, and at 2x a screenshot caught only its top-left quarter. The rest
  pose's bounds include T-pose arms, so `page.html` frames her by her own
  height: 1.5 m for a VRoid girl, 1.83 m for the mannequin.
- **#20 starts from a dressed source.** `dressed_mannequin()` gives her a VRoid
  named top and trousers 1 cm off her skin; the look has to take them off before
  underwear goes on. Its image shows the source first.
