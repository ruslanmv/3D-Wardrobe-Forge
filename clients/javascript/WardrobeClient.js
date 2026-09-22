/**
 * Wardrobe Forge HTTP client.
 *
 * Transport only: it knows about jobs, looks and wardrobes, and nothing about
 * Blender, Meshy, fitting or skin weights. Pair it with WardrobeController to
 * drive a viewer.
 *
 * @example
 * const forge = new WardrobeClient({ baseUrl: WARDROBE_FORGE_URL });
 * const job = await forge.createLook({ avatarUrl, prompt: 'soft black date-night dress' });
 * const done = await forge.waitForJob(job.id, { onState: (s) => console.log(s) });
 * console.log(done.look.vrmUrl);
 */

const TERMINAL_STATES = new Set(['completed', 'failed', 'rejected']);

export class WardrobeForgeError extends Error {
    /**
     * @param {string} message
     * @param {{status?: number, reason?: string, detail?: any}} [info]
     */
    constructor(message, info = {}) {
        super(message);
        this.name = 'WardrobeForgeError';
        this.status = info.status ?? 0;
        /** Stable machine-readable code, e.g. 'source_model_modification_not_permitted'. */
        this.reason = info.reason ?? null;
        this.detail = info.detail ?? null;
    }

    /** True when the caller must supply licence terms before we can proceed. */
    get needsLicenseAttestation() {
        return this.reason === 'requires_user_license_attestation';
    }

    /** True when the source model's own terms forbid deriving a new look. */
    get modificationForbidden() {
        return this.reason === 'source_model_modification_not_permitted';
    }
}

export class WardrobeClient {
    /**
     * @param {Object} options
     * @param {string} options.baseUrl - Wardrobe Forge base URL.
     * @param {typeof fetch} [options.fetchImpl] - Injectable for tests.
     * @param {number} [options.pollIntervalMs=1200]
     * @param {number} [options.timeoutMs=300000]
     */
    constructor({ baseUrl, fetchImpl, pollIntervalMs = 1200, timeoutMs = 300000 } = {}) {
        this.baseUrl = String(baseUrl || '').replace(/\/+$/, '');
        this.fetch = fetchImpl || ((...args) => globalThis.fetch(...args));
        this.pollIntervalMs = pollIntervalMs;
        this.timeoutMs = timeoutMs;
    }

    // =====================================================================
    // low-level
    // =====================================================================

    /**
     * @param {string} path
     * @param {RequestInit} [init]
     * @returns {Promise<any>}
     */
    async request(path, init = {}) {
        const response = await this.fetch(`${this.baseUrl}${path}`, init);

        if (!response.ok) {
            let detail = null;
            try {
                detail = await response.json();
            } catch (_) {
                detail = null;
            }
            const payload = detail && detail.detail ? detail.detail : detail;
            const reason = payload && typeof payload === 'object' ? payload.reason : null;
            const message =
                (payload && typeof payload === 'object' && payload.message) ||
                (typeof payload === 'string' ? payload : null) ||
                `Wardrobe Forge request failed: ${response.status}`;
            throw new WardrobeForgeError(message, { status: response.status, reason, detail: payload });
        }

        if (response.status === 204) return null;
        return response.json();
    }

    /** @returns {Promise<Object>} What this deployment can do. */
    capabilities() {
        return this.request('/v1/capabilities');
    }

    /** @returns {Promise<Array>} The garment template library. */
    templates(category) {
        const query = category ? `?category=${encodeURIComponent(category)}` : '';
        return this.request(`/v1/templates${query}`);
    }

    // =====================================================================
    // avatars
    // =====================================================================

    /**
     * Report what a VRM contains and whether its terms allow modification,
     * without creating a job.
     * @param {File|Blob} file
     */
    async inspectAvatar(file) {
        const body = new FormData();
        body.append('file', file);
        return this.request('/v1/avatars/inspect', { method: 'POST', body });
    }

    /**
     * Upload a VRM and get back a storageKey to reuse across looks. Preferred
     * over passing a URL: the file never has to be publicly reachable.
     * @param {File|Blob} file
     * @returns {Promise<{storageKey: string, sha256: string, analysis: Object}>}
     */
    async uploadAvatar(file) {
        const body = new FormData();
        body.append('file', file);
        return this.request('/v1/avatars', { method: 'POST', body });
    }

    // =====================================================================
    // jobs
    // =====================================================================

    /**
     * Request a new look. Returns immediately with a queued job.
     *
     * @param {Object} options
     * @param {string} [options.avatarUrl] - Public URL of the source VRM.
     * @param {string} [options.storageKey] - Key returned by uploadAvatar().
     * @param {string} options.prompt
     * @param {string} [options.mode='auto'] - auto | template | generated
     * @param {string} [options.sha256]
     * @param {string} [options.avatarId] - Wardrobe this look belongs to.
     * @param {Object} [options.conditionsOfUse] - VRoid Hub conditions object.
     * @param {boolean} [options.attestModificationAllowed=false]
     * @param {boolean} [options.renderPreview=true]
     * @param {string} [options.templateId]
     * @returns {Promise<Object>} The queued job record.
     */
    async createLook({
        avatarUrl = null,
        storageKey = null,
        prompt,
        mode = 'auto',
        sha256 = null,
        avatarId = null,
        name = null,
        conditionsOfUse = null,
        attestModificationAllowed = false,
        renderPreview = true,
        templateId = null,
        engine = 'auto',
    }) {
        if (!avatarUrl && !storageKey) {
            throw new WardrobeForgeError('createLook needs either avatarUrl or storageKey');
        }
        if (!prompt) {
            throw new WardrobeForgeError('createLook needs a prompt');
        }

        const avatar = { sha256, avatarId, name, license: {} };
        if (avatarUrl) avatar.url = avatarUrl;
        if (storageKey) avatar.storageKey = storageKey;
        if (conditionsOfUse) avatar.license.conditionsOfUse = conditionsOfUse;
        if (attestModificationAllowed) avatar.license.userAttestsModificationAllowed = true;

        return this.request('/v1/jobs', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
                avatar,
                outfit: { prompt, mode, templateId },
                options: { renderPreview, engine, wardrobeId: avatarId },
            }),
        });
    }

    /** @param {string} jobId */
    getJob(jobId) {
        return this.request(`/v1/jobs/${encodeURIComponent(jobId)}`);
    }

    /**
     * Follow a job to completion.
     *
     * Uses Server-Sent Events when available so the UI can show real pipeline
     * states ('fitting', 'resolving-clipping', ...), and falls back to polling.
     *
     * @param {string} jobId
     * @param {{onState?: (state: string, event: Object) => void, timeoutMs?: number}} [options]
     * @returns {Promise<Object>} The completed job record.
     */
    async waitForJob(jobId, { onState = null, timeoutMs = null } = {}) {
        const deadline = Date.now() + (timeoutMs ?? this.timeoutMs);

        if (typeof globalThis.EventSource === 'function') {
            try {
                return await this._waitViaEvents(jobId, onState, deadline);
            } catch (error) {
                console.warn('[WardrobeClient] event stream unavailable, polling instead:', error);
            }
        }
        return this._waitViaPolling(jobId, onState, deadline);
    }

    /** @private */
    _waitViaEvents(jobId, onState, deadline) {
        return new Promise((resolve, reject) => {
            const url = `${this.baseUrl}/v1/jobs/${encodeURIComponent(jobId)}/events`;
            const source = new globalThis.EventSource(url);

            const finish = async (error) => {
                clearTimeout(timer);
                source.close();
                if (error) return reject(error);
                try {
                    resolve(await this._settle(jobId));
                } catch (settleError) {
                    reject(settleError);
                }
            };

            const timer = setTimeout(
                () => finish(new WardrobeForgeError('Wardrobe job timed out')),
                Math.max(deadline - Date.now(), 0)
            );

            source.onmessage = (message) => {
                let event = null;
                try {
                    event = JSON.parse(message.data);
                } catch (_) {
                    return;
                }
                if (onState) onState(event.state, event);
                if (TERMINAL_STATES.has(event.state)) finish(null);
            };

            source.onerror = () => {
                // The stream closes normally once the job is terminal, so check
                // the job before treating this as a failure.
                this.getJob(jobId)
                    .then((job) => (TERMINAL_STATES.has(job.state) ? finish(null) : null))
                    .catch(() => finish(new WardrobeForgeError('Wardrobe event stream failed')));
            };
        });
    }

    /** @private */
    async _waitViaPolling(jobId, onState, deadline) {
        let lastState = null;
        while (Date.now() < deadline) {
            const job = await this.getJob(jobId);
            if (onState && job.state !== lastState) {
                lastState = job.state;
                onState(job.state, job.events?.[job.events.length - 1] ?? {});
            }
            if (TERMINAL_STATES.has(job.state)) return this._check(job);
            await new Promise((done) => setTimeout(done, this.pollIntervalMs));
        }
        throw new WardrobeForgeError('Wardrobe job timed out');
    }

    /** @private */
    async _settle(jobId) {
        return this._check(await this.getJob(jobId));
    }

    /** @private */
    _check(job) {
        if (job.state === 'completed') return job;
        throw new WardrobeForgeError(job.error || `Wardrobe job ${job.state}`, {
            reason: job.reason,
            detail: job.fitReport ?? null,
        });
    }

    /**
     * Create a look and wait for it. Convenience wrapper over the two calls.
     * @returns {Promise<Object>} The completed job record (with `.look`).
     */
    async createLookAndWait(options, { onState = null } = {}) {
        const job = await this.createLook(options);
        return this.waitForJob(job.id, { onState });
    }

    // =====================================================================
    // wardrobes
    // =====================================================================

    /** @param {string} avatarId @returns {Promise<Object>} The wardrobe manifest. */
    getWardrobe(avatarId) {
        return this.request(`/v1/wardrobes/${encodeURIComponent(avatarId)}`);
    }

    /** The wardrobe in 3D-Avatar-Chatbot `avatars.json` shape. */
    getWardrobeAsAvatarManifest(avatarId) {
        return this.request(`/v1/wardrobes/${encodeURIComponent(avatarId)}/avatars.json`);
    }

    /** @returns {Promise<string[]>} */
    listWardrobes() {
        return this.request('/v1/wardrobes');
    }

    /** @param {string} avatarId @param {string} lookId */
    removeLook(avatarId, lookId) {
        return this.request(
            `/v1/wardrobes/${encodeURIComponent(avatarId)}/looks/${encodeURIComponent(lookId)}`,
            { method: 'DELETE' }
        );
    }

    /** Resolve a possibly-relative artifact URL against the forge base URL. */
    resolveUrl(url) {
        if (!url) return null;
        return /^https?:\/\//i.test(url) ? url : `${this.baseUrl}${url.startsWith('/') ? '' : '/'}${url}`;
    }
}

export default WardrobeClient;
