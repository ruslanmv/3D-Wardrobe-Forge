# Anatomical assets for the reference bodies: what exists, under what licence, and what is missing

Stage 1 of the anatomical-completeness requirement (task AN-A): before any anatomy is added to
the four reference bodies (`docs/ANATOMY_REFERENCE.md`), every candidate asset is identified with
its provenance and licence, and judged against the requirement: anatomically credible geometry
for the pelvic, groin and external genital regions and for the nipple and areola, fit for close-
fitting and sheer garments, under a licence this repository can carry (MIT code; data must be
MIT-compatible — CC0, CC BY, public domain; not share-alike, not non-commercial, not
no-derivatives), and kept behind the adult-only gates that already exist.

Nothing here is integrated yet. This page is the decision the next stage needs.

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
* **External female genital anatomy has no qualifying asset in reach.** Nothing available here is
  both anatomically reviewed and under a licence this repository can carry. It is not to be
  sculpted from guesses.

## The decision needed

One of these, for the external anatomy:

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
