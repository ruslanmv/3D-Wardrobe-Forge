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
