# Forge wardrobe audit

Adapted from the HomePilot audit in 3D-Avatar-Chatbot (`audits/wardrobe_sitting_desk`). That runner drives the Try-On page in a browser. This one uses Forge's own fit, because a catalog preview is refused here before any browser picture exists.

`reproduce.py` prints the failed rows in `assets/catalog/build-report.json`, fits each one through `fit_look.py`, and writes a front diagnostic under `/tmp/forge-qa`. That PNG is evidence. It is not a catalog thumbnail. `fit_look.py` uses Auto Foundation, so a pass there is not the catalog gate. The catalog gate is `render_templates.py`: the reference base first (beige tube and slip shorts), then the template with the shorts removed.

On 2026-11-07 that catalog path failed all three leggings with `clippingCheck: failed` and `clearance: failed`. The plain pair's 41 failing vertices were the front groin, 12.5 mm inside the radial hull and outside the skin. The hull bridges the thigh gap. Those rows are now marked `groin` and left out of that check, the same way the legs already were. The three previews are generated WebPs with `fitPassed: true`. The seated jeans issue is still open.

The fix order is `docs/plans/forge-wardrobe-defects/PLAN.md`. Do not publish a WebP while `fitPassed` is false.
