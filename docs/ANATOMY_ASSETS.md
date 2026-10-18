# Anatomical assets for the reference bodies: what exists, under what licence, and what is missing

Stage 1 of the anatomical-completeness requirement (task AN-A): before any anatomy is added to
the four reference bodies (`docs/ANATOMY_REFERENCE.md`), every candidate asset is identified with
its provenance and licence, and judged against the requirement: anatomically credible geometry
for the pelvic, groin and external genital regions and for the nipple and areola, fit for close-
fitting and sheer garments, under a licence this repository can carry (MIT code; data must be
MIT-compatible — CC0, CC BY, public domain; not share-alike, not non-commercial, not
no-derivatives), and kept behind the adult-only gates that already exist.

The decision was made: **a simple, open, reviewed mesh under CC0 or CC BY**. The candidate that
meets it is the Human Reference Atlas female skin, below; it is integrated as the reference
bodies' pelvic outlet ([ANATOMY_PELVIS](ANATOMY_PELVIS.md)). The rest of this page is the search
that led there.

## What the current bodies contain

The reference bodies are MakeHuman hm08's `body` group (CC0, pinned commit
`a8bc2d54ff0ac92e78ff71431b1023eda42bf482`, `3dobjs/base.obj` SHA-256
`8e761e66…f6fb4c`), calibrated by 75 CC0 targets (`pelvisTone` among them) and subdivided. The import dropped, on
purpose, `helper-genital` and every other helper group, and imported no nipple target.
The contact region named `external-genital-region` is a label on the smooth surface: metadata,
not anatomy.

## Candidates checked

All from the same pinned MakeHuman commit; each file's own header states *"This asset was
explicitly released as CC0 in september 2020"*, which is what `tools/anatomy/import_makehuman.py`
already requires of every file it imports.

| Asset | File (SHA-256 prefix) | What it is, measured | Fit for the requirement |
| --- | --- | --- | --- |
| Nipple projection | `targets/breast/nipple-point-incr.target` (`2f9ac628`), `-decr` (`0f4fe644`) | 32 body vertices, up to 7.1 mm displacement | **Yes, for the chest.** Real geometry on her own mesh, so it inherits her rig and subdivision; incr/decr give variation |
| Nipple and areola size | `targets/breast/nipple-size-incr.target` (`4b23e80e`), `-decr` (`af1a11c3`, 162 vertices) | 32–162 body vertices, up to 6.7 mm | **Yes, for the chest**, with the above |
| Pelvic soft tissue | `targets/pelvis/pelvis-tone-incr.target` (`cdf7cb0e`), `-decr` (`6ff89c89`) | 925 / 327 body vertices, up to 30 mm | **Already imported** (the `pelvisTone` calibration modifier): pelvic soft-tissue volume and tone. Not external genital anatomy |
| `helper-genital` group in `base.obj` | in the pinned `base.obj` | 200 vertices, 182 faces, 6 × 9 cm | **No.** A generic low-poly attachment helper for proxy meshes, not reviewed female anatomy; using it would be the "arbitrary bump" the requirement rules out |
| `targets/genitals/penis-*` | 6 targets | male, act on the helper | Not for the female bodies; noted for a future male variant |
| MakeHuman community genital proxies | `makehuman-assets` repository | not reachable from this session (the clone is refused) | **Unverified.** Licence is per asset and per author; each file would need its provenance and licence checked before use |

## Conclusion

* **Nipple and areola** can be built now, from CC0 targets already pinned, as variation morphs on
  her own mesh: geometry, not a normal map, so they reach the silhouette and the contact surface.
* **Pelvic soft tissue** (mons, groin volume) already has a CC0 variation axis, `pelvisTone`. The
  inguinal folds and the perineal transition are in the hm08 body surface, at its resolution.
* **External female genital anatomy has no qualifying asset in MakeHuman.** Nothing there is
  both anatomically reviewed and under a licence this repository can carry. It is not to be
  sculpted from guesses — which is why the source below is a published atlas.

## The source chosen: the Human Reference Atlas female skin (CC BY 4.0)

| | |
| --- | --- |
| What | *3D Reference Organ: skin of body, female*, v1.5, of the Human Reference Atlas (HuBMAP, NIH Common Fund): the outer surface of the National Library of Medicine's Visible Human Female, segmented by the atlas's anatomists |
| Where | [lod.humanatlas.io/ref-organ/skin-female/v1.5](https://lod.humanatlas.io/ref-organ/skin-female/v1.5), file `3d-vh-f-skin.glb`, SHA-256 `b7dc8b3e…69594c` |
| Who | Kristen Browne and Heidi Schlehlein, 2024, doi [10.48539/HBM453.MVPL.398](https://doi.org/10.48539/HBM453.MVPL.398) |
| Licence | **CC BY 4.0**: compatible, with attribution and a statement of changes (`assets/anatomy/hra-provenance.json`, `docs/LICENSING.md`) |
| Review | Published as part of a versioned reference atlas with a DOI and its own release history (v1.0–v1.5). The atlas documents review at the level of the programme, not per object; this page claims no more than that |
| Measured | One closed manifold after welding: 133 350 vertices. Between her thighs, about 5 mm edges (4.9 mm median in the imported region) |
| What it resolves there | The mons, the vulval outer contour as one closed mound (the labia majora, apposed as they are in the scan), the genitocrural folds either side of it and the start of the perineum. At the crotch a coronal section is a mound about 9 mm wide at the top, where the template's is a plateau about 30 mm wide |
| What it does not | Nothing finer than its edges: no labia minora, clitoral hood or vestibule. High-pass relief of the region against its own 3 cm smoothing is under 3 mm: there is no detail there to take beyond the contour |
| Caveats | One woman, not a population; a cadaver frozen lying on her back, so her pelvis is tilted about 10° against a standing body and her thighs are closer together; the scan is not symmetric |

How it is used — scaled, pitched, mirrored and fitted onto each reference body only where it is
the anatomy — is in [ANATOMY_PELVIS](ANATOMY_PELVIS.md).

## The decision that was needed

One of these, for the external anatomy (the second was chosen, with the atlas above):

1. **A licensed commercial anatomical model**, bought for this purpose. Such licences usually
   forbid redistribution: the asset would stay out of the repository, installed by the operator
   from a path they supply, its hash pinned, loaded only behind the existing adult gates, and the
   public test suite would run without it.
2. **A community asset under CC0 or CC BY**, named by you (for example a MakeHuman community
   proxy), whose file, author and licence we verify the way `import_makehuman.py` verifies hm08.
3. **A commissioned, anatomist-reviewed mesh**, released under CC0 or CC BY.

Whichever is chosen, stages 2–7 of the requirement follow it: register it to the hm08 surface,
fit it to the four profiles, carry the rig across it, give the contact body the region, then
garments, poses and evidence.

The chest work does not wait on this decision.
