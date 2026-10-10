# Occasions: where she is going, before what she wears

The Studio opens on one question — **What are we dressing for?** — and only then on
garments. Batches OC1–OC3.

```text
OCCASION        Night out · Work · Gym · Sleep · Shopping · Vacation · Campus · Private
   ↓
STYLE           Night out → Discoteca · Elegant · Party · Edgy
   ↓
LOOK            Discoteca → stiletto ankle · platform · combat · over-the-knee
   ↓
WEAR IT         she wears it straight away (made once, worn again after that)
   ↓
QUICK CHANGES   another look · other styles · other boots · change colour · "tell me what to change…"
   ↓
EXTRAS          a tattoo — only when this outfit leaves skin for one
   ↓
♡ SAVE          and the wardrobe shelf grouped by occasion
```

The garment designer is unchanged and one tap away, under **Customize**. Both paths send
the same kind of job to the same route.

## The catalogue (OC1)

`wardrobe/pipeline/occasions.py` is a menu and nothing else. An occasion holds styles, a
style holds looks, and a look is an id in the outfit dictionary
(`wardrobe/pipeline/outfit_dictionary.py`). The dictionary already says what the planner
builds for each prompt and rates it the way the job's gate does, so an occasion cannot
offer something the Forge cannot make, nor mislabel who may wear it.
`tests/unit/test_occasions.py` holds it to that, and to these:

- every style of a general occasion has at least one look anyone may wear, so hiding the
  private ones never leaves a style empty;
- **Campus** (not "school") is ordinary clothes: nothing private, nothing mini, no corset,
  tube or halter top;
- **Discoteca** is the Sexy Discoteca collection and its four boots, in the collection's
  order.

`GET /v1/outfits` carries the catalogue as `occasions`, beside `groups` and `outfits`. It
is additive: a client that reads only the dictionary sees no change. Each style says what
its looks are rated — `general`, `private` or `mixed` — so a client can lay it out without
planning anything.

Twenty-three dictionary entries were added for it (gym, work suits, campus, sleep, streetwear,
resort, edgy night-out looks), each planned before it was written, and a new `active`
group ("Active & gym").

## Privacy is a property of the look, not of the occasion

Occasion and privacy are different questions. A bikini is *Vacation* and *private*; a
corset top is *Night out* and *general*. So:

- a look rated `private` is shown only where private mode is on for the avatar — the same
  `depictsAdult` the job's gate reads;
- a style left with no looks is not shown, nor an occasion left with no styles;
- the **Private** occasion (`private=True`) is not shown at all without private mode —
  never as a locked tile — whatever its looks are rated, because it is the private
  experience. Inside it: Fan service, Lingerie and Glamour (stockings).

Nothing here grants anything. A look is planned, fitted and gated as if its prompt had been
typed, and the server refuses what the avatar may not wear. The page's rules live in
`apps/studio/js/occasions.js` and nowhere else in it; `tests/unit/test_studio_occasions.py`
runs that module under node against this Forge's own `/v1/outfits`.

## Tattoos are an extra, not an occasion

Whether there is skin for a tattoo is known only once the outfit exists
([BODY_ART_PLAN](BODY_ART_PLAN.md)). So body art never sits beside Work and Gym: after a
look is made, **Make it yours** offers *Tattoo* when that look's exposure has a placement
for one, and offers nothing — no tile, no "not available" — when it has none.

## Labelling a look (`options.occasion`)

A job may say what the look was made for:

```json
{ "options": { "occasion": { "occasion": "night-out", "style": "discoteca" } } }
```

The tag is kept on the wardrobe entry (`occasion`, `style`) so the shelf can group by it.
It plans and gates nothing. A tag naming no occasion in the catalogue is dropped, and a
style not in that occasion is dropped while the occasion is kept: a label is not worth
failing a fitted look over. The Studio sends it on every job it can attribute, quick
changes and tattoos included, so a change stays filed under the occasion it came from.

## Quick changes are changes to the look on stage

Every quick change is a job on the look she is wearing (`baseLookId`), with
`ensureFoundation` on, so only what the new piece covers changes:

- **Another … look** — a different look of the same style (a curated one, never a random
  prompt), and the other styles of the occasion one tap away;
- **Other boots** — on a style with a collection (Discoteca): A–D, re-fitting only the
  boots, which re-stand her on their heels ([DISCOTECA](DISCOTECA.md));
- **Change colour** — of one piece, chosen by name; the piece keeps its cut;
- **Tell me what to change…** — read by `readIntent`: an occasion ("something for the
  beach", "let's go clubbing") goes there; a colour ("make it red") recolours the chosen
  piece; anything else is put on her as a garment, which replaces what it covers. An
  occasion this avatar is not shown — Private without private mode — is not a door: the
  words go to the planner as a garment request, and the server's gate answers it.

A look made by a change carries only the new piece as its prompt (it is the job's own), so
the page remembers the whole outfit for it (`compose`: boots for boots, a dress for a dress
or a top and bottom, a top over a dress added the way the Forge layers it). Without that,
"make it red" after new boots could only ever recolour the boots.

## Compare (OC2)

**Compare** — it was "Both", which reads as "both outfits on her at once" — draws her
original and the look in two halves of the viewport through one camera. It used to stand
them 0.62 m apart along world X; from her side or from beneath, that separation became
depth and one figure stood inside the other, so a correct outfit looked like a broken one.
Two viewports cannot overlap from any angle, and turning one turns the other the same way.
Compare also keeps the camera within 5° of level; a view from underneath is for inspecting
one garment, in **Look**. A finished job now opens on **Look**, not on both.
