/**
 * The Studio's only door to Forge.
 *
 * Same origin, so there is no base URL to configure on the Space. The one piece
 * of state is an optional API key, for a deployment running
 * `WARDROBE_AUTH_MODE=api_key` that does not trust this page (F5: the Studio a
 * Space serves is trusted, and never asked); it lives in this browser's
 * localStorage and is sent as a Bearer token on every call.
 *
 * Binary assets — the avatar, a look's VRM, its preview — are fetched through
 * `blobUrl()` rather than put straight into `<img src>` or a loader URL. An
 * `<img>` cannot send an Authorization header, so on a keyed deployment every
 * picture would 401. Going through fetch makes keyed and open deployments
 * behave the same.
 *
 * An admin session's token (the account menu, bottom-left) is the second piece
 * of state. It lives in sessionStorage, so it dies with the tab, and it goes in
 * its own header: a keyed Space needs the API key and the session together.
 */

const KEY_STORAGE = 'wardrobe_studio_api_key';

function readKey() {
    try {
        return localStorage.getItem(KEY_STORAGE) || '';
    } catch (_) {
        return '';
    }
}

export const auth = {
    get key() {
        return readKey();
    },
    set key(value) {
        try {
            if (value) localStorage.setItem(KEY_STORAGE, value);
            else localStorage.removeItem(KEY_STORAGE);
        } catch (_) {
            /* storage blocked: the key lasts for this page only, which is acceptable */
        }
    },
};

const ADMIN_STORAGE = 'wardrobe_studio_admin';

export const admin = {
    get token() {
        try {
            return sessionStorage.getItem(ADMIN_STORAGE) || '';
        } catch (_) {
            return '';
        }
    },
    set token(value) {
        try {
            if (value) sessionStorage.setItem(ADMIN_STORAGE, value);
            else sessionStorage.removeItem(ADMIN_STORAGE);
        } catch (_) {
            /* storage blocked: the session will not survive a reload, which is acceptable */
        }
    },
};

export class ApiError extends Error {
    constructor(message, status, detail) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.detail = detail;
    }
}

function headers(extra = {}) {
    const out = { Accept: 'application/json', ...extra };
    const key = readKey();
    if (key) out.Authorization = `Bearer ${key}`;
    const session = admin.token;
    if (session) out['X-Wardrobe-Admin'] = session;
    return out;
}

/**
 * WS1. A GET the server or its proxy turned away for load (429, 503) is asked again after the wait
 * it names (Retry-After), or a short growing one, up to three times. The Space's proxy refused a
 * 12 MB look with 429 while the shelf was fetching a hundred previews at once: the person saw
 * "Could not load" for a look that a second later would have loaded.
 */
const RETRY_STATUSES = new Set([429, 503]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function fetchPatiently(path, init) {
    for (let attempt = 0; ; attempt += 1) {
        const response = await fetch(path, init);
        if (!RETRY_STATUSES.has(response.status) || init.method !== 'GET' || attempt >= 3) return response;
        const named = Number(response.headers.get('Retry-After'));
        await sleep(Number.isFinite(named) && named > 0 ? Math.min(named, 20) * 1000 : 600 * 2 ** attempt);
    }
}

/**
 * WS1. Pictures and files fetched through blobUrl wait their turn: at most four at a time, so the
 * shelf never fires a hundred requests at once. A look the person asked to wear jumps the queue.
 */
const BLOB_SLOTS = 4;
let blobsInFlight = 0;
const blobQueue = [];
function blobTurn(urgent) {
    return new Promise((resolve) => {
        const go = () => {
            blobsInFlight += 1;
            resolve(() => {
                blobsInFlight -= 1;
                const next = blobQueue.shift();
                if (next) next();
            });
        };
        if (blobsInFlight < BLOB_SLOTS || urgent) go();
        else if (urgent) blobQueue.unshift(go);
        else blobQueue.push(go);
    });
}

async function request(path, { method = 'GET', body, form, expect = 'json' } = {}) {
    const init = { method, headers: headers(body ? { 'Content-Type': 'application/json' } : {}) };
    if (body) init.body = JSON.stringify(body);
    if (form) init.body = form;
    const response = await fetchPatiently(path, init);
    if (!response.ok) {
        let detail = null;
        try {
            detail = await response.json();
        } catch (_) {
            detail = null;
        }
        const inner = detail && detail.detail !== undefined ? detail.detail : detail;
        const message =
            (inner && typeof inner === 'object' && inner.message) ||
            (typeof inner === 'string' ? inner : null) ||
            `${method} ${path} failed (${response.status})`;
        // The server no longer knows this session (expired, signed out, restarted).
        if (response.status === 401 && inner && inner.reason === 'admin_required') admin.token = '';
        throw new ApiError(message, response.status, inner);
    }
    if (response.status === 204) return null;
    return expect === 'blob' ? response.blob() : response.json();
}

export const api = {
    capabilities: () => request('/v1/capabilities'),
    library: () => request('/v1/library'),
    vocabulary: () => request('/v1/vocabulary'),
    /** OC3. The outfit dictionary and the occasions built on it: the Studio's first screen. */
    outfits: () => request('/v1/outfits'),
    inspectAvatar(file) {
        const form = new FormData();
        form.append('file', file, file.name);
        return request('/v1/avatars/inspect', { method: 'POST', form });
    },
    importAvatar(file, { presentation = 'avatar', attestModification = false } = {}) {
        const form = new FormData();
        form.append('file', file, file.name);
        form.append('presentation', presentation);
        form.append('user_attests_modification_allowed', String(Boolean(attestModification)));
        return request('/v1/library/import', { method: 'POST', form });
    },
    templates: (category) => request(`/v1/templates${category ? `?category=${encodeURIComponent(category)}` : ''}`),
    job: (id) => request(`/v1/jobs/${encodeURIComponent(id)}`),
    createLibraryJob: (slug, body) =>
        request(`/v1/library/${encodeURIComponent(slug)}/jobs`, { method: 'POST', body }),

    /** What that job would do — layers, gate, what comes off, the body under it — without doing it. */
    planLibrary: (slug, body) =>
        request(`/v1/library/${encodeURIComponent(slug)}/plan`, { method: 'POST', body }),

    /** The avatar's wardrobe, or null when it has never had a look generated. */
    async wardrobe(avatarId) {
        try {
            return await request(`/v1/wardrobes/${encodeURIComponent(avatarId)}`);
        } catch (error) {
            if (error.status === 404) return null;
            throw error;
        }
    },

    removeLook: (avatarId, lookId) =>
        request(`/v1/wardrobes/${encodeURIComponent(avatarId)}/looks/${encodeURIComponent(lookId)}`, {
            method: 'DELETE',
        }),

    /** W14. The wardrobe as a v2 pack: what 3D-Avatar-Chatbot imports, hashed and rated. */
    pack: (avatarId, passedOnly) =>
        request(`/v1/wardrobes/${encodeURIComponent(avatarId)}/pack.zip?passedOnly=${passedOnly ? 'true' : 'false'}`, {
            expect: 'blob',
        }),

    bundle: (avatarId, passedOnly) =>
        request(`/v1/wardrobes/${encodeURIComponent(avatarId)}/bundle.zip${passedOnly ? '?passedOnly=true' : ''}`, {
            expect: 'blob',
        }),

    /** Whether there is an admin, and this tab's session if it has one. */
    adminStatus: () => request('/v1/admin'),
    adminSignIn: (username, password) =>
        request('/v1/admin/session', { method: 'POST', body: { username, password } }),
    adminSignOut: () => request('/v1/admin/session', { method: 'DELETE' }),
    /** BD18. The bare-body panel's presets, states, extras and erotic sets (admin session only). */
    adminBodyDetail: () => request('/v1/admin/body-detail'),
    /** CG7. A read-only, expiring grant for these library avatars' private looks (admin session only). */
    mintGrant: (slugs, ttlSeconds, label) =>
        request('/v1/admin/grants', { method: 'POST', body: { slugs, ttlSeconds, label } }),
    /** DC1. The same grant as a six-character one-time code, for a headset (admin session only). */
    issueDeviceCode: (slugs, ttlSeconds, label) =>
        request('/v1/admin/device-codes', { method: 'POST', body: { slugs, ttlSeconds, label } }),
    /** CG8. Revoke one grant, by presenting it (admin session only). */
    revokeGrant: (token) => request('/v1/admin/access/revocations', { method: 'POST', body: { token } }),
    /** CG4. Every library character's review state, licence, body and status (admin session only). */
    reviews: () => request('/v1/admin/reviews'),
    /** CG4. One person's own finding for the exact file they were shown. Never called with a default. */
    recordReview: (slug, finding) =>
        request(`/v1/admin/reviews/${encodeURIComponent(slug)}`, { method: 'POST', body: finding }),
    /** CG4. The exact bytes of a library character, for hashing and rendering the same file. */
    libraryAvatarBlob: (slug) => request(`/v1/library/${encodeURIComponent(slug)}/avatar.vrm`, { expect: 'blob' }),
    /** Declare, for this session only, that a library avatar depicts an adult (or withdraw it). */
    adminDeclare: (slug, depictsAdult, ageConfirmed = false) =>
        request(`/v1/admin/declarations/${encodeURIComponent(slug)}`, {
            method: 'PUT',
            body: { depictsAdult, ageConfirmed },
        }),

    /** AB4. An independent collection (wardrobe.collections): its designs, each with Forge's rating. */
    collection: (id) => request(`/v1/collections/${encodeURIComponent(id)}`),

    /** BA7. The tattoo catalogue, and where a finished look leaves her skin visible. */
    bodyArt: () => request('/v1/body-art'),
    /** BA10. The operator's own tattoo artwork: an admin session's only, and private. */
    customBodyArt: () => request('/v1/admin/body-art'),
    uploadBodyArt: (file, name) => {
        const form = new FormData();
        form.append('file', file);
        form.append('name', name || '');
        return request('/v1/admin/body-art', { method: 'POST', form });
    },
    deleteBodyArt: (id) => request(`/v1/admin/body-art/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    lookExposure: (slug, lookId) =>
        request(`/v1/library/${encodeURIComponent(slug)}/looks/${encodeURIComponent(lookId)}/exposure`),

    /**
     * UI-004. The product-facing garment catalogue: pre-rendered previews only, never a generation.
     * Restricted pieces are listed only for an admin session (the server decides; asking without one
     * is a 403), so the gallery asks for them only once the session exists.
     */
    catalogGarments: ({ category, includeRestricted = false } = {}) => {
        const query = new URLSearchParams();
        if (category) query.set('category', category);
        if (includeRestricted) query.set('includeRestricted', 'true');
        const suffix = query.toString();
        return request(`/v1/catalog/garments${suffix ? `?${suffix}` : ''}`);
    },

    /**
     * UI-006. What may be changed on a garment and what may only be shown, from the template itself:
     * adjustable groups name the OutfitRequest field each value is sent as. Restricted garments answer
     * only an admin session, as their previews do.
     */
    garmentParameters: (templateId) => request(`/v1/catalog/garments/${encodeURIComponent(templateId)}/parameters`),

    // WS2. The wardrobe registry (docs/WARDROBE_REGISTRY.md): the Collections browser and its manager.
    registry: () => request('/v1/registry'),
    registryDashboard: () => request('/v1/admin/registry/dashboard'),
    registryCreate: (body) => request('/v1/admin/registry/collections', { method: 'POST', body }),
    registryEditCollection: (id, body) =>
        request(`/v1/admin/registry/collections/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
    registryAssign: (id, body) =>
        request(`/v1/admin/registry/collections/${encodeURIComponent(id)}/items`, { method: 'POST', body }),
    registryEditGarment: (id, body) =>
        request(`/v1/admin/registry/garments/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
    registryFavourite: (id, on) =>
        request(`/v1/admin/registry/favourites/${encodeURIComponent(id)}`, { method: on ? 'PUT' : 'DELETE' }),
    /**
     * An object URL for a protected asset. The caller owns it and must revoke it. WS1: queued, at
     * most four at a time; `urgent` (a look the person chose to wear) goes straight through.
     */
    async blobUrl(path, { urgent = false } = {}) {
        const done = await blobTurn(urgent);
        try {
            const blob = await request(path, { expect: 'blob' });
            return URL.createObjectURL(blob);
        } finally {
            done();
        }
    },
};
