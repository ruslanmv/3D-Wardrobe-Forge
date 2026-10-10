/**
 * OC3. The occasion-first Studio's decisions, with no DOM and no network.
 *
 * The first question the Studio asks is where she is going, not which garment category;
 * this module is everything that question needs to decide, so app.js only draws and asks.
 * It is plain functions over the server's own `GET /v1/outfits` answer (the outfit
 * dictionary and wardrobe.pipeline.occasions), which is what keeps the Studio from
 * offering a look the Forge cannot make, and testable without a browser
 * (tests/unit/test_studio_occasions.py runs it under node).
 *
 * Who may see what is decided here and nowhere else in the page:
 * - a look the planner rates `private` is shown only where private mode is on for the
 *   avatar — the same `depictsAdult` the server's job gate reads;
 * - a style left with no looks is not shown, nor an occasion left with no styles;
 * - an occasion marked `private` is not shown at all without private mode, never as a
 *   locked tile, whatever its looks are rated.
 * The server refuses a job the avatar may not wear regardless; this only means the page
 * never offers one.
 */

/** The occasions as this avatar may see them, each style's looks resolved to dictionary entries. */
export function visibleOccasions(catalogue, { adult = false } = {}) {
    if (!catalogue || !Array.isArray(catalogue.occasions)) return [];
    const entries = new Map((catalogue.outfits || []).map((entry) => [entry.id, entry]));
    const out = [];
    for (const occasion of catalogue.occasions) {
        if (occasion.private && !adult) continue;
        const styles = [];
        for (const style of occasion.styles || []) {
            const looks = (style.looks || [])
                .map((id) => entries.get(id))
                .filter((entry) => entry && (entry.rating === 'general' || adult));
            if (looks.length) styles.push({ ...style, looks });
        }
        if (styles.length) out.push({ ...occasion, styles });
    }
    return out;
}

/** Every look an occasion (or one of its styles) offers, once each. */
export function looksOf(occasion, styleId = null) {
    const seen = new Set();
    const out = [];
    for (const style of occasion.styles) {
        if (styleId && style.id !== styleId) continue;
        for (const look of style.looks) {
            if (seen.has(look.id)) continue;
            seen.add(look.id);
            out.push({ look, style });
        }
    }
    return out;
}

/**
 * "Surprise me": one of the curated looks, never a random prompt — every candidate is a
 * dictionary entry the pipeline is known to finish. Avoids the look on stage when it can.
 */
export function surprise(candidates, { avoidPrompt = null, random = Math.random } = {}) {
    const pool = candidates.filter((c) => c.look.prompt !== avoidPrompt);
    const from = pool.length ? pool : candidates;
    return from.length ? from[Math.floor(random() * from.length) % from.length] : null;
}

/** The pieces of an outfit prompt, as the planner splits them: "dress + boots" → two. */
export function pieces(prompt) {
    return String(prompt || '')
        .split('+')
        .map((part) => part.trim())
        .filter(Boolean);
}

/**
 * What a piece is, near enough to know what it replaces: shoes, a dress (which is a top and a
 * bottom), an outer layer, a bottom or a top. Order matters — "stiletto ankle boots" are shoes,
 * a "shirt dress" is a dress and a "cropped cardigan" a layer, before "shirt" or "crop" say top.
 */
const KINDS = [
    ['shoes', /\b(boots?|shoes|heels|flats|sneakers|trainers|sandals|stilettos?|pumps)\b/],
    ['dress', /\b(dress|gown|nightgown|catsuit|jumpsuit|swimsuit|bodysuit|gu[eê]pi[eè]re)\b/],
    ['outer', /\b(coat|blazer|cardigan|jacket|trench)\b/],
    ['bottom', /\b(jeans|trousers|pants|leggings|skirt|shorts|bottoms)\b/],
    ['top', /\b(top|tee|t-shirt|blouse|cami|camisole|shirt|corset|bralette|tank)\b/],
];

export function pieceKind(piece) {
    const text = String(piece || '').toLowerCase();
    const found = KINDS.find(([, pattern]) => pattern.test(text));
    return found ? found[0] : null;
}

/**
 * The whole outfit after one piece was put on it: what a change made on a look (a job with
 * `baseLookId`, whose own prompt names only the new piece) now wears. The new piece takes the
 * place of what it replaces — boots for boots, a dress for a dress or for a top and bottom —
 * and anything it does not replace stays; a piece of no kind known here is added. A top on a
 * dress is added, not swapped, because the Forge layers it the same way: a top does not cover
 * what a dress does, so the dress is not taken off.
 */
export function compose(recipe, piece) {
    const kind = pieceKind(piece);
    const parts = pieces(recipe);
    const replaces = (part) => {
        const other = pieceKind(part);
        return kind !== null && (other === kind || (kind === 'dress' && (other === 'top' || other === 'bottom')));
    };
    const at = parts.findIndex(replaces);
    const kept = parts.filter((part) => !replaces(part));
    if (at >= 0) kept.splice(Math.min(at, kept.length), 0, piece);
    else {
        const shoes = kept.findIndex((part) => pieceKind(part) === 'shoes');
        kept.splice(kind !== 'shoes' && shoes >= 0 ? shoes : kept.length, 0, piece);
    }
    return kept.join(' + ');
}

/** OC3. The whole outfit of each look made by a change, per avatar, in this browser. */
export const recipes = {
    key: (slug) => `wardrobe_studio_recipes:${slug}`,
    read(slug, storage = globalThis.localStorage) {
        try {
            const value = JSON.parse(storage.getItem(this.key(slug)) || '{}');
            return value && typeof value === 'object' ? value : {};
        } catch (_) {
            return {};
        }
    },
    write(slug, lookId, recipe, storage = globalThis.localStorage) {
        const all = this.read(slug, storage);
        all[lookId] = recipe;
        try {
            storage.setItem(this.key(slug), JSON.stringify(all));
        } catch (_) {
            /* storage blocked: the look's own prompt is used instead */
        }
    },
};

/** Colour names, longest first, so "dark grey" is one colour and not "grey" after "dark". */
function byLength(colours) {
    return [...colours].map((c) => String(c).toLowerCase()).sort((a, b) => b.length - a.length);
}

function escape(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** A piece with its colour words taken out: what "Change colour of …" names. */
export function withoutColour(piece, colours) {
    let text = ` ${piece.toLowerCase()} `;
    for (const colour of byLength(colours)) text = text.replace(new RegExp(` ${escape(colour)} `, 'g'), ' ');
    return text.replace(/\s+/g, ' ').trim();
}

/** The piece in a new colour: its colour words replaced by `colour`, or `colour` put first. */
export function recolour(piece, colour, colours) {
    return `${colour} ${withoutColour(piece, colours)}`.trim();
}

/** Words that mean an occasion (and sometimes a style in it) in what someone types. */
const OCCASION_WORDS = [
    [/\b(discoteca|disco)\b/, 'night-out', 'discoteca'],
    [/\b(club|clubbing|nightclub|night ?out|going out|party|cocktail)\b/, 'night-out', null],
    [/\b(office|work|business|meeting|interview)\b/, 'work', null],
    [/\b(yoga)\b/, 'gym', 'yoga'],
    [/\b(gym|workout|work out|training|running|run|sport|sporty|fitness)\b/, 'gym', null],
    [/\b(sleep|bed|bedtime|pajamas|pyjamas|night in)\b/, 'sleep', null],
    [/\b(shopping|shop|mall|errands)\b/, 'shopping', null],
    [/\b(beach)\b/, 'vacation', 'beach'],
    [/\b(vacation|holiday|holidays|resort|trip|travel|sightseeing)\b/, 'vacation', null],
    [/\b(campus|school|college|class|classes|university|uni)\b/, 'campus', null],
    [/\b(fan service|lingerie|private)\b/, 'private', null],
];

const LEAD_IN = /^(please\s+)?(can you\s+|could you\s+)?(make (it|her|them)|try( on)?|put (on|her in)|dress her in|wear|give her|change (it )?to|i want|let'?s (try|go)|something( for)?)\s+/;

/**
 * What "Tell me what to change…" asks for:
 * - `{kind: 'occasion', occasion, style}` — "something for the beach", "let's go clubbing";
 * - `{kind: 'colour', colour}` — "make it red", "navy";
 * - `{kind: 'garment', prompt}` — anything else, sent to the planner as a garment to put
 *   on the look on stage (it replaces what it covers);
 * - `null` — nothing to do.
 * An occasion is only read when it names one the page shows (`available`), so "private"
 * typed without private mode is a garment request the server answers, not a hidden door.
 */
export function readIntent(text, { colours = [], available = [] } = {}) {
    const said = String(text || '')
        .toLowerCase()
        .replace(/[!?.,]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    if (!said) return null;
    for (const [pattern, occasion, style] of OCCASION_WORDS) {
        if (pattern.test(said) && available.includes(occasion)) return { kind: 'occasion', occasion, style };
    }
    const rest = said.replace(LEAD_IN, '').replace(/^(it |her )/, '').trim();
    const colour = byLength(colours).find((c) => rest === c || rest === `${c} instead` || rest === `in ${c}`);
    if (colour) return { kind: 'colour', colour };
    return rest.length >= 2 ? { kind: 'garment', prompt: rest } : null;
}

/** OC3. How often each occasion was chosen in this browser: "For you" is the top few. */
export const usage = {
    key: 'wardrobe_studio_occasions',
    read(storage = globalThis.localStorage) {
        try {
            const value = JSON.parse(storage.getItem(this.key) || '{}');
            return value && typeof value === 'object' ? value : {};
        } catch (_) {
            return {}; // blocked or corrupt storage: nobody's favourites, which is fine
        }
    },
    bump(id, storage = globalThis.localStorage) {
        const counts = this.read(storage);
        counts[id] = (counts[id] || 0) + 1;
        try {
            storage.setItem(this.key, JSON.stringify(counts));
        } catch (_) {
            /* storage blocked: "For you" just stays empty */
        }
        return counts;
    },
};

/** The occasions chosen most, at least twice, among those shown: "For you". */
export function forYou(occasions, counts, limit = 3) {
    return occasions
        .filter((o) => (counts[o.id] || 0) >= 2)
        .sort((a, b) => counts[b.id] - counts[a.id])
        .slice(0, limit);
}

/** OC3. Looks saved with ♡, per avatar, in this browser. */
export const favourites = {
    key: (slug) => `wardrobe_studio_saved:${slug}`,
    read(slug, storage = globalThis.localStorage) {
        try {
            const value = JSON.parse(storage.getItem(this.key(slug)) || '[]');
            return new Set(Array.isArray(value) ? value : []);
        } catch (_) {
            return new Set();
        }
    },
    toggle(slug, lookId, storage = globalThis.localStorage) {
        const saved = this.read(slug, storage);
        if (saved.has(lookId)) saved.delete(lookId);
        else saved.add(lookId);
        try {
            storage.setItem(this.key(slug), JSON.stringify([...saved]));
        } catch (_) {
            /* storage blocked: the heart lasts for this page */
        }
        return saved;
    },
};

/** The wardrobe's looks grouped by the occasion each was made for, in the catalogue's order. */
export function shelfGroups(looks, occasions) {
    const titles = new Map(occasions.map((o) => [o.id, o]));
    const groups = new Map();
    for (const look of looks) {
        const key = look.occasion && titles.has(look.occasion) ? look.occasion : '';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(look);
    }
    const order = [...occasions.map((o) => o.id), ''];
    return order
        .filter((key) => groups.has(key))
        .map((key) => ({
            id: key,
            title: key ? titles.get(key).title : 'Designed',
            icon: key ? titles.get(key).icon : '✏️',
            looks: groups.get(key),
        }));
}
