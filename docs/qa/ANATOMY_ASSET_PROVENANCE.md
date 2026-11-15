# AF3 — Anatomical assets: provenance, rights and where each may be used

Audited 2026-11-15 on `feat/bare-base-body`. Checksums are SHA-256 of the files as committed
(`sha256sum assets/anatomy/*`). Licence terms are the licences' own; this is not legal advice.

## The assets

| File | What it is | Creator / source | Licence | SHA-256 (first 16) | Source type |
|---|---|---|---|---|---|
| `makehuman-hm08.npz` | hm08 base mesh, `body` group only, + 75 calibration targets | MakeHuman community, `makehumancommunity/makehuman` @ `a8bc2d54`; per-file hashes in `makehuman-provenance.json` | CC0 1.0 (each file's own header; importer refuses one that is not) | `a739f722455a2143` | Artist-made template (not a scan) |
| `makehuman-provenance.json` | Import record for the above | this repository | — (metadata) | `02b54d45bfab2fd5` | — |
| `makehuman-rig.npz` | default skeleton + skin weights for hm08 | MakeHuman (© 2020–21 Data Collection AB, J. Palmius, J. Hauquier) | CC0 1.0 (file headers) | `b4f699175bd05d8a` | Artist-made |
| `makehuman-rig-provenance.json` | Import record for the rig | this repository | — | `d76e4080a3835441` | — |
| `hra-pelvis.npz` | pelvic crop (18 365 vertices, 4.9 mm edges) of the HRA female skin | Human Reference Atlas 3D Reference Organ *skin of body, female* v1.5 — K. Browne, H. Schlehlein (HuBMAP, NIH Common Fund), doi 10.48539/HBM453.MVPL.398; GLB pinned `b7dc8b3e…` | **CC BY 4.0** | `f3b587e91b28a21e` | **Donated human remains**: the outer surface of the NLM Visible Human Female |
| `hra-provenance.json` | Import, crop and attribution record | this repository | — | `4955bbd9e963e1b9` | — |
| `pelvic-outlet.npz` / `.json` | the HRA crop fitted to each reference body | derived here from `hra-pelvis.npz` | CC BY 4.0 (derivative; attribution in the file) | `81b5f01b006be936` / `17233331c1ff3ad8` | Derived from donated remains |
| `reference-sizes.json` | ANSUR II female body measurements | U.S. Army Natick (Gordon et al. 2012), public CSV via Penn State OpenLab | U.S. Government work, "approved for public release; distribution is unlimited" | `7272e148750b43e3` | Measurement statistics (no geometry) |
| `reference-bodies.json` | the four calibrated reference-body definitions | derived here | MIT (repository code/data) | `58c446925bd82206` | Derived |
| `validation-report.json` | generated validation numbers | `tools/anatomy/validate_reference.py` | MIT | `68abfdf81508e892` | Generated |
| `assets/body_surface/templates/navel-v1.json` | the shipped navel dimple | authored procedurally in `tools/body_surface/install_template.py` | CC0 1.0 | field `8a96beb621755970` | Original synthetic |

## Rights, per licence

| Licence | Attribution | Derivatives | Commercial use | Redistribution | Embedding in a VRM | Restrictions |
|---|---|---|---|---|---|---|
| CC0 1.0 (MakeHuman hm08, rig, navel) | not required | yes | yes | yes | yes | none from the licence |
| CC BY 4.0 (HRA skin, pelvic outlet) | required (credit Browne & Schlehlein, HRA/HuBMAP, the DOI, and that it was changed) | yes | yes | yes, with attribution and licence notice | yes, with attribution in the file | no additional restrictions may be imposed downstream |
| U.S. Government public release (ANSUR II) | courtesy citation | yes | yes | yes | n/a (numbers) | none stated |

**Rights are not consent.** The Human Reference Atlas surface is lawfully licensed CC BY 4.0. It is
also the body of a woman who donated it to science (the Visible Human Project). Neither the licence
nor its scientific role establishes consent for her anatomy to appear in adult entertainment. It keeps
its role in the anatomical reference path — fitting and contact measurement on the reference bodies,
never shown on a character — and is **excluded from body-surface templates**, in code (AF3):

- `wardrobe.body_surface.library.EXCLUDED_SOURCES` refuses any template whose provenance names the
  Visible Human Project, the Human Reference Atlas / HuBMAP, the DOI's `HBM453` stem, the NLM, or
  donated/post-mortem remains — even with `containsRealPersonScan: false` written by hand;
- the installer refuses the same before writing a file.

No asset in this repository carries authored external genital anatomy. The MakeHuman `helper-genital`
group was deliberately not imported (an attachment helper, not anatomy). The HRA crop resolves the
mons and outer contour coarsely (4.9 mm edges) and is never shown.

## What a body-surface template must now record (AF3)

- `license` — one of CC0-1.0, CC-BY-4.0, MIT, Apache-2.0, LicenseRef-Commissioned (an actual
  agreement), unchanged;
- `containsRealPersonScan: false`, unchanged;
- `sourceType` — **required for intimate regions** (`nipples`, `chestDetail`, `externalAnatomy`,
  `pubic`): `original-synthetic`, `commissioned` or `open-asset`. Any other value is refused;
  templates without it in non-intimate regions (the shipped navel) load as before.

## Who intimate detail may be applied to (AF3)

A fourth gate question, asked only for profiles with an intimate region: has a person reviewed this
**exact file** (SHA-256 of its bytes) and found the character clearly adult in design? Reviews live in
`assets/body_surface/adult-design-reviews.json` (`outcome: "clearly-adult"`, reviewer, date,
evidence); a caller cannot send one, and an edited file is not covered. The registry ships empty:
**none of the eight stylised library characters is established as clearly adult by review**, so none
receives intimate detail. The bare body (`body-bare-v1`) and non-intimate profiles are unaffected.
