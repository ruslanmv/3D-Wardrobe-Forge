/**
 * The Studio's only door to Forge.
 *
 * Same origin, so there is no base URL to configure on the Space. The one piece
 * of state is an optional API key, for a deployment running
 * `WARDROBE_AUTH_MODE=api_key`; it lives in this browser's localStorage and is
 * sent as a Bearer token on every call.
 *
 * Binary assets — the avatar, a look's VRM, its preview — are fetched through
 * `blobUrl()` rather than put straight into `<img src>` or a loader URL. An
 * `<img>` cannot send an Authorization header, so on a keyed deployment every
 * picture would 401. Going through fetch makes keyed and open deployments
 * behave the same.
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
    return out;
}

async function request(path, { method = 'GET', body, expect = 'json' } = {}) {
    const init = { method, headers: headers(body ? { 'Content-Type': 'application/json' } : {}) };
    if (body) init.body = JSON.stringify(body);
    const response = await fetch(path, init);
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
        throw new ApiError(message, response.status, inner);
    }
    if (response.status === 204) return null;
    return expect === 'blob' ? response.blob() : response.json();
}

export const api = {
    capabilities: () => request('/v1/capabilities'),
    library: () => request('/v1/library'),
    vocabulary: () => request('/v1/vocabulary'),
    templates: (category) => request(`/v1/templates${category ? `?category=${encodeURIComponent(category)}` : ''}`),
    job: (id) => request(`/v1/jobs/${encodeURIComponent(id)}`),
    createLibraryJob: (slug, body) =>
        request(`/v1/library/${encodeURIComponent(slug)}/jobs`, { method: 'POST', body }),

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

    bundle: (avatarId, passedOnly) =>
        request(`/v1/wardrobes/${encodeURIComponent(avatarId)}/bundle.zip${passedOnly ? '?passedOnly=true' : ''}`, {
            expect: 'blob',
        }),

    /** An object URL for a protected asset. The caller owns it and must revoke it. */
    async blobUrl(path) {
        const blob = await request(path, { expect: 'blob' });
        return URL.createObjectURL(blob);
    },
};
