# Wardrobe registry (WS1)

One listing of the whole wardrobe: every garment template and every ready look,
each with a primary clothing type and any number of collection memberships,
filtered on the server for whoever asks.

## Where things are

| What | Where |
| --- | --- |
| Types, collections, sections, rules | `wardrobe/registry/classify.py` |
| The view for one caller, the dashboard counts | `wardrobe/registry/registry.py` |
| The admin's decisions (JSON, `state/wardrobe-registry.json`) | `wardrobe/registry/store.py` |
| HTTP | `apps/api/routes/registry.py` |
| Studio page (WS2): the Collections browser and manager, from the top bar | `apps/studio/js/collections.js` |
| Tests | `tests/unit/test_wardrobe_registry.py`, `tests/integration/test_registry_api.py` |

## API

- `GET /v1/registry` — sections, categories (with counts), collections (with
  count, cover and items) and items, for this caller. Everyone gets the general
  and **Adult** wardrobe; an admin session also gets **Private**, and anyone
  else gets an answer with no Private item or collection in it.
- `GET /v1/registry/collections/{id}` — one collection with its items expanded.
  A private collection is 404 for a non-admin.
- Admin only (`X-Wardrobe-Admin`, else 401):
  - `GET /v1/admin/registry/dashboard` — totals, categorized / uncategorized,
    general / adult / private, body content (presets, states, extras), thumbnails, needs fit testing, needs review, unassigned,
    suspected duplicates, empty collections.
  - `PATCH /v1/admin/registry/garments/{id}` — `category`, `tags`, `visibility`
    (`public` | `private`), `reviewed`.
  - `POST /v1/admin/registry/collections` — create (private by default).
  - `PATCH /v1/admin/registry/collections/{id}` — rename, describe, cover,
    archive; privacy only on collections an admin made.
  - `POST /v1/admin/registry/collections/{id}/items` — bulk `add` / `remove`.
  - `PUT` / `DELETE /v1/admin/registry/favourites/{id}`.

## Rules

- **A membership is a reference, never a copy.** A garment sits in as many
  collections as fit it; its template file is the only copy.
- **An admin's decision always wins** over a rule and is never overwritten by
  one: what a rule can work out is recomputed from the templates every time, and
  only what a person decided is stored.
- **Unsure goes to Needs Review**, never into a guessed shelf. Every wearable
  garment is in All Clothes whatever else happens to it.
- **Three tiers.** *General* is everything else. *Adult* is what guests already
  enjoyed before the registry (intimate templates — underwear, swimwear — and
  adult-only ones; looks rated above general or in a private group); the UI
  names it "Adult" and the registry shows it to everyone. *Private* is the
  admin's intense tier: the bare base, the painted body presets, states
  (open, gaped, finishes…) and extras (marks, tattoos, piercings) from
  `assets/body_detail/`, plus anything an admin marks private. It is filtered on
  the server: a guest's answer holds no Private item, and a Private collection
  is 404 to them.
- **The existing endpoints are unchanged.** `/v1/outfits`, `/v1/collections`,
  `/v1/templates` and `/v1/assets` answer exactly as they did before the
  registry; it adds a view, it does not re-gate the backend.

## Collections aligned with the 3D Avatar Chatbot's Private

Adult: Striptease Show and Table Dance (its shows, UN36/VA3), Undress Step by
Step (looks with both `partial` states, which Private undresses one layer at a
time), Bedroom & Boudoir, Role-Play, Erotic Sets. Private (admin): Naked Skin,
Open & Gaped, Finishes, the positions (Doggy, Missionary, Cowgirl), Sado,
Arousal & Afterglow, Marks/Tattoos/Piercings — the body states the chatbot's
Private switches through skin packs. They list the same ids the chatbot plays.

## Private categories and body thumbnails (WS3)

A second admin-only section, **Private · Categories**, files every bare-body
variant the way top-rated adult sites file their content: Shaved & Smooth,
Natural & Hairy, Pale & Porcelain, Anime & Hentai Style, Solo & Tease, Pussy
Close-ups, Anal, Gaping & Stretched, Creampie, Cumshot & Cum on Body, Fisting,
BDSM & Rough, Oiled/Sweaty & Wet, After Sex, Tattooed, Pierced, Tan Lines, Love
Marks & Body Writing, Glitter & Body Paint, Natural Body; then by **position**
(Doggy, Missionary, Cowgirl, Tied & Used), by **finish** (Inside, On Her Back &
Ass, On Her Belly, On Her Chest, All Over, Open & Dripping), and the admin's
picks **Most Erotic · Hardcore** and **Sensual & Elegant**
(`classify.PRIVATE_CATEGORIES`, 32 in all). Every one of the 99 body items (13 presets, 57
states, 29 extras) is in at least one; a test fails the day one is not. A body
pattern ending in `$` is an exact id (`preset:natural$` is not `natural-hair`).

Thumbnails (`wardrobe/registry/body_previews.py`): each item is painted in
memory exactly as a bare job paints it and plotted at her own body coordinates,
framed on what it changes (vulva, anus, nipple, torso, lower belly and thighs,
back), ~18 s each. Stored at `body-previews/<slug>/<kind>-<value>.webp`, served
by `/v1/assets` to an admin session, and to a read grant for the characters it
covers plus the reference body — the companion's Private mode — never to a
guest, never to the dataset.

The companion (a read grant) gets everything it needs to offer every variant
from `GET /v1/body-surface/catalog?slug=<her slug>` (version 2): each preset,
state and extra with its label and body line, the categories with their item
ids, and a thumbnail URL per item (hers when she has them, else the reference
body's). What it can actually *show* on her is what her looks carry
(`WardrobeLook.body`: the skin pack's states and the extras painted in), made by
`tools/prebuild_private.py` — which needs her detail clearance like every bare
job.

- `GET /v1/admin/body-previews` — how many thumbnails each character has.
- `POST /v1/admin/body-previews/{slug}/render` — Forge paints up to 4 items on
  her own plain bare look, **only after the bare job's detail clearance** for her
  exact file (403 `detail-review` otherwise; 409 when she has no plain bare look).
- `PUT /v1/admin/body-previews/reference/{item}` — the defaults, painted on
  Forge's synthetic adult reference body by the script; the only slug that takes
  uploads.
- `GET /v1/registry?previews=<slug>` — an admin's body items carry that
  character's thumbnails (`reference` by default); the Studio's Collections has
  a "Body thumbnails of" picker.

Make them all: `tools/render_body_previews.py --forge … --admin-token-file …
--reference <ref-atlas.vrm>` (the reference from
`tools/body_surface/detail_preview.py`, ~5 min to build once), then every
character Forge clears. On 2026-11-20 none of the library's characters had
detail clearance (their reviews have no packet and 17 characters of evidence;
detail needs the packet and 40): they are reported as refused until a person
reviews them (`tools/body_surface/review_packet.py`, then the review record).

## A companion app's read grant (GC1)

`GET /v1/registry` and `/v1/registry/collections/{id}` read with a valid read
grant (`X-Wardrobe-Grant`) exactly what an admin session reads — Private and its
categories included — with `admin: false`, `access: "grant"`: no manager control,
no adult garment picture (still admin-only on `/v1/catalog`), body thumbnails for
a character the grant covers (else the reference body's). It is the second of the
companion's two gates; the first, the person's own adult confirmation, is the
app's. Every `/v1/admin/registry/*` route still answers 401 to a grant.

## Faster loading: a combination is built once (PB1, RU1, RU4)

A finished look is recorded under the keys of its request
(`wardrobe/pipeline/prebuilt.py`: the words key, and the plan key of the
garments the planner builds), and published to the dataset with the next
batch. The next request with the same key — the same avatar, garments, colours
and options, however it was worded — is answered at once from that record
instead of being built again. RU4 extends this to explicit layers (a Try-On
stack, an Outfit Lab set). Not cached: body art, and bare requests (rechecked
every time, never answered from the cache).

## Adding to it

- A new garment template appears in All Clothes by itself, typed by the rules;
  if no rule is sure it lands in Needs Review.
- A new collection: add a `_c(...)` to `PUBLIC` or `PRIVATE` in `classify.py`
  with real ids, tags, types or outfit groups. The unit test refuses an id,
  group or tag that does not exist, and an empty curated collection.
