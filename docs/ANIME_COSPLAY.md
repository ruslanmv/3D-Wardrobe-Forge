# Anime cosplay reference collection (draft)

**Status: engineering preview only. NOT commercially cleared; NOT character-faithful finished assets.**

This collection registers 12 reference-oriented wardrobe recipes using existing, tested garment prompts. Each is explicitly a **silhouette proxy**, not a faithful reconstruction. These entries appear under Private → Anime cosplay references, and swimwear remains subject to the current intimate-garment permission gate. The private occasion requires the existing adult declaration and usage rights; the registration does not weaken any server-side policy.

## Licensing gate for commercial release

- All 12 references point to third-party anime character designs. No rights or endorsements are granted by this repository.
- Before publishing character names, identifiable artwork, logos, costumes, or downloadable derivatives commercially, obtain legal review and necessary licenses/permissions from the respective rightsholders. Character-name labels in this draft are internal references, not production-approved marketing copy.
- Do not ship copied character texture images, unauthorized ripped meshes, logos, or reference screenshots. No third-party art or models are added in this change.
- Respect source VRM modification, sexual-expression, redistribution, and commercial-use restrictions independently of franchise permissions.
- Use demonstrably adult avatar models for swimwear/intimate outputs and preserve existing server-side adult and license gates. No school-age characters are included.

## Implemented vs. pending

| Reference | Current wardrobe proxy | Fidelity gap |
|---|---|---|
| Nami (One Piece) | `triangle-bikini` | Pattern and accessory pass pending |
| Faye Valentine (Cowboy Bebop) | `denim-shorts` | Yellow garment palette, red jacket and suspenders pending |
| Yor Forger (Spy × Family) | `little-black-dress` | Gold ornaments, straps, and signature headpiece pending |
| Boa Hancock (One Piece) | `red-bodycon` | Floral red gown, split skirt, sash and jewelry pending |
| Nico Robin (One Piece) | `cami-wrap-skirt` | Purple top, pink floral sarong and sunglasses pending |
| Fujiko Mine (Lupin III) | `catsuit-boots` | Glossy material pass and belt pending |
| Vinsmoke Reiju (One Piece) | `red-bodycon` | Pink suit, cape, gloves, insignia and boots require new geometry |
| Mirko (My Hero Academia) | `catsuit-boots` | White suit, rabbit ears and guards require new geometry |
| Esdeath (Akame ga Kill!) | `grey-skirt-suit` | White military coat, hat and belt require new templates |
| Motoko Kusanagi (Ghost in the Shell) | `catsuit-boots` | Purple-grey palette, tactical hardware, cropped jacket pending |
| Rangiku Matsumoto (Bleach) | `evening-gown` | Black robe sleeves, white sash and split skirt require new shapes |
| Albedo (Overlord) | `evening-gown` | White gothic gown, horns, wings and black accents require new assets |

Data source: `assets/cosplay/anime_reference_catalog.json` records the 12 references, rights review state and missing components. The built-in outfit dictionary and private occasion use stable `anime-*` IDs; no art assets or new geometry are introduced.

## Acceptance and follow-up

1. Run `pytest tests/unit/test_outfit_dictionary.py tests/unit/test_occasions.py tests/unit/test_anime_cosplay_catalog.py`.
2. Verify all registered entries plan, have consistent group ratings, and are served in `GET /v1/outfits`.
3. Produce visual previews and fit reports on licensed adult VRMs; compare costume elements front, side and back.
4. Implement missing hats, wings, belts, corset details, patterns, palettes and modular accessories individually.
5. Maintain a rights clearance checklist and do not change `rights.status` to approved without documented authorization.
