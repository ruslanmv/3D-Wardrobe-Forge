/**
 * WS2. The wardrobe's collections, browsable and managed in the Studio.
 *
 * WS1 built the registry — every garment, outfit and body item typed into a clothing type and
 * collected into public, Adult and admin-only Private collections — and an admin API to manage
 * it, but the Studio never showed any of it: the only way to see a collection or move a garment
 * was a raw HTTP call. This is that missing page: a full-screen browser opened from the top bar.
 *
 * What it shows is exactly what the server answers for this caller. Private collections arrive
 * only for an admin session; nothing here hides or reveals anything on its own (the registry
 * filters on the server, and a page must never be the gate). An admin also gets the dashboard
 * (totals, what needs review, suspected duplicates), a favourite toggle, adding and removing an
 * item from any collection, a new collection, and archiving one they made. Every change goes to
 * the server and the page re-reads the registry after it, so what is drawn is what is stored.
 *
 * Pictures load only when a card comes into view (`whenVisible`), as the Wardrobe shelf does
 * since WS1: a collection of 120 items fired 120 requests at once and the Space answered 429.
 */

const state = {
    view: null,
    dashboard: null,
    selected: 'all-clothes',
    query: '',
    busy: false,
    urls: [],
};

let deps = null;

function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) if (child) node.append(child);
    return node;
}

function dialog() {
    return document.getElementById('registry-dialog');
}

function note(text, isError = false) {
    const node = document.getElementById('registry-note');
    if (!node) return;
    node.textContent = text || '';
    node.classList.toggle('error', Boolean(isError));
}

function message(error) {
    return deps && deps.describe ? deps.describe(error) : (error && error.message) || String(error);
}

function revokeAll() {
    for (const url of state.urls.splice(0)) URL.revokeObjectURL(url);
}

async function load() {
    note('Loading the wardrobe…');
    try {
        state.view = await deps.api.registry();
        state.dashboard = state.view.admin ? await deps.api.registryDashboard().catch(() => null) : null;
        if (!state.view.collections.some((c) => c.id === state.selected)) state.selected = 'all-clothes';
        note('');
    } catch (error) {
        state.view = null;
        note(message(error), true);
    }
    render();
}

/** One change on the server, then the registry read again: the page draws what is stored. */
async function change(label, run) {
    if (state.busy) return;
    state.busy = true;
    note(`${label}…`);
    try {
        await run();
        await load();
        note(`${label}: done.`);
    } catch (error) {
        note(`${label}: ${message(error)}`, true);
    } finally {
        state.busy = false;
    }
}

function dashboardStrip() {
    const d = state.dashboard;
    if (!d) return null;
    const stat = (label, value, warn = false) =>
        el('div', { class: `reg-stat${warn && value ? ' warn' : ''}` }, el('b', { text: String(value) }), el('span', { text: label }));
    const body = d.bodyContent || {};
    return el(
        'div',
        { class: 'reg-dashboard', 'aria-label': 'Wardrobe at a glance' },
        stat('garments', d.garments),
        stat('outfits', d.outfits),
        stat('adult', d.adult + (d.adultOutfits || 0)),
        stat('body items', (body.preset || 0) + (body.state || 0) + (body.extra || 0)),
        stat('need a picture', d.missingThumbnails, true),
        stat('need fit testing', d.needsFitTesting, true),
        stat('need review', d.needsReview, true),
        stat('possible duplicates', (d.suspectedDuplicates || []).length, true),
        d.storeDamaged ? el('div', { class: 'reg-stat warn', text: 'The decisions file could not be read' }) : null
    );
}

function sidebar() {
    const view = state.view;
    const groups = view.sections.map((section) => {
        const list = view.collections.filter((c) => c.section === section.id && !c.archived);
        if (!list.length) return null;
        return el(
            'div',
            { class: 'reg-section' },
            el('h3', { text: section.title }),
            el(
                'ul',
                {},
                list.map((c) =>
                    el(
                        'li',
                        {},
                        el(
                            'button',
                            {
                                type: 'button',
                                class: 'reg-col',
                                'aria-current': String(c.id === state.selected),
                                onclick: () => {
                                    state.selected = c.id;
                                    render();
                                },
                            },
                            el('span', { class: 'reg-col-name', text: c.title }),
                            c.private ? el('span', { class: 'reg-badge private', text: 'Private' }) : null,
                            el('span', { class: 'reg-count', text: String(c.count) })
                        )
                    )
                )
            )
        );
    });
    const make = view.admin
        ? el('button', { type: 'button', class: 'secondary reg-new', text: '+ New collection', onclick: newCollection })
        : null;
    return el('nav', { class: 'reg-sidebar', 'aria-label': 'Collections' }, make, groups);
}

function newCollection() {
    const title = window.prompt('Name of the new collection');
    if (!title || !title.trim()) return;
    const isPrivate = window.confirm('Private (admin only)? OK = private, Cancel = shown to everyone');
    change('Creating the collection', async () => {
        const made = await deps.api.registryCreate({ title: title.trim(), private: isPrivate });
        if (made && made.id) state.selected = made.id;
    });
}

function picture(item) {
    const holder = el('span', { class: 'reg-ph', text: item.kind === 'body' ? '◌' : item.kind === 'outfit' ? '👚' : '👗' });
    if (item.previewUrl && deps.whenVisible) {
        deps.whenVisible(holder, () =>
            deps.api
                .blobUrl(item.previewUrl)
                .then((url) => {
                    state.urls.push(url);
                    holder.replaceWith(el('img', { src: url, alt: '', loading: 'lazy' }));
                })
                .catch(() => {})
        );
    }
    return holder;
}

function manageRow(item, collection) {
    if (!state.view.admin) return null;
    const others = state.view.collections.filter((c) => !c.smart && !c.archived && c.id !== collection.id);
    const add = el(
        'select',
        {
            'aria-label': `Add ${item.name} to a collection`,
            onchange: (event) => {
                const target = event.target.value;
                event.target.value = '';
                if (target) change(`Adding ${item.name}`, () => deps.api.registryAssign(target, { add: [item.id] }));
            },
        },
        el('option', { value: '', text: 'Add to…' }),
        others.filter((c) => !(item.collections || []).includes(c.id)).map((c) => el('option', { value: c.id, text: c.title }))
    );
    const remove = collection.smart
        ? null
        : el('button', {
              type: 'button',
              class: 'link',
              text: 'Remove',
              onclick: () => change(`Removing ${item.name}`, () => deps.api.registryAssign(collection.id, { remove: [item.id] })),
          });
    const reviewed =
        item.kind === 'garment' && item.needsReview
            ? el('button', {
                  type: 'button',
                  class: 'link',
                  text: 'Mark reviewed',
                  onclick: () => change(`Reviewing ${item.name}`, () => deps.api.registryEditGarment(item.id, { reviewed: true })),
              })
            : null;
    return el('div', { class: 'reg-manage' }, add, remove, reviewed);
}

function card(item, collection) {
    const badges = [
        item.private ? el('span', { class: 'reg-badge private', text: 'Private' }) : null,
        !item.private && item.adult ? el('span', { class: 'reg-badge adult', text: 'Adult' }) : null,
        item.needsReview ? el('span', { class: 'reg-badge warn', text: 'Review' }) : null,
        item.kind === 'garment' && item.ready === false ? el('span', { class: 'reg-badge', text: 'Not fit-tested' }) : null,
    ];
    const fav = state.view.admin
        ? el('button', {
              type: 'button',
              class: `reg-fav${item.favourite ? ' on' : ''}`,
              'aria-pressed': String(Boolean(item.favourite)),
              title: item.favourite ? 'Remove from favourites' : 'Add to favourites',
              text: item.favourite ? '★' : '☆',
              onclick: () =>
                  change(item.favourite ? 'Removing a favourite' : 'Adding a favourite', () =>
                      deps.api.registryFavourite(item.id, !item.favourite)
                  ),
          })
        : null;
    const kind = item.kind === 'garment' ? item.type : item.kind === 'outfit' ? `outfit · ${item.group || ''}` : item.type;
    return el(
        'article',
        { class: 'reg-card' },
        el('div', { class: 'reg-pic' }, picture(item), fav),
        el('div', { class: 'reg-name', text: item.name, title: item.id }),
        el('div', { class: 'reg-kind', text: String(kind || '').replace(/-/g, ' ') }),
        el('div', { class: 'reg-badges' }, badges),
        manageRow(item, collection)
    );
}

function body() {
    const view = state.view;
    const collection = view.collections.find((c) => c.id === state.selected) || view.collections[0];
    const byId = new Map(view.items.map((i) => [i.id, i]));
    const q = state.query.trim().toLowerCase();
    const items = collection.items
        .map((id) => byId.get(id))
        .filter(Boolean)
        .filter((i) => !q || `${i.name} ${i.id} ${(i.tags || []).join(' ')}`.toLowerCase().includes(q));
    const archive =
        view.admin && collection.custom
            ? el('button', {
                  type: 'button',
                  class: 'link',
                  text: 'Archive this collection',
                  onclick: () =>
                      window.confirm(`Archive “${collection.title}”? Its items stay in every other collection.`) &&
                      change('Archiving', () => deps.api.registryEditCollection(collection.id, { archived: true })),
              })
            : null;
    return el(
        'section',
        { class: 'reg-body', 'aria-label': collection.title },
        el(
            'header',
            { class: 'reg-head' },
            el(
                'div',
                {},
                el('h3', { text: collection.title }),
                el('p', { class: 'reg-desc', text: `${collection.description || ''} · ${items.length} shown` })
            ),
            archive
        ),
        items.length
            ? el('div', { class: 'reg-grid' }, items.map((i) => card(i, collection)))
            : el('p', { class: 'reg-empty', text: q ? 'Nothing here matches the search.' : 'This collection is empty.' })
    );
}

function render() {
    const root = document.getElementById('registry-root');
    if (!root) return;
    revokeAll();
    root.replaceChildren();
    if (!state.view) return;
    root.append(dashboardStrip() || '', el('div', { class: 'reg-layout' }, sidebar(), body()));
}

/** Wire the dialog once; `options` hands in the Studio's api, error wording and lazy loader. */
export function initCollections(options) {
    deps = options;
    const open = document.getElementById('collections-btn');
    const box = dialog();
    if (!open || !box) return;
    open.addEventListener('click', () => {
        box.showModal();
        load();
    });
    document.getElementById('registry-close').addEventListener('click', () => box.close());
    document.getElementById('registry-search').addEventListener('input', (event) => {
        state.query = event.target.value;
        render();
    });
    box.addEventListener('close', revokeAll);
}

export const _test = { state };
