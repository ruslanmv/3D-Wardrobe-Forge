/**
 * Wardrobe Controller — binds Wardrobe Forge to the 3D-Avatar-Chatbot viewer.
 *
 * It drives `window.NEXUS_VIEWER.avatarManager` through its existing public
 * API (`getCurrent`, `setAvatarByUrl`, `frameAvatar`), so the viewer needs no
 * changes: a generated look is just another VRM URL to load.
 *
 * @example
 * const forge = new WardrobeClient({ baseUrl: WARDROBE_FORGE_URL });
 * const wardrobe = new WardrobeController({ forge, viewer: window.NEXUS_VIEWER });
 *
 * const look = await wardrobe.createLook({ prompt: 'soft black date-night dress' });
 * await wardrobe.applyLook(look);
 * await wardrobe.restore();
 */

import { WardrobeForgeError } from './WardrobeClient.js';

export class WardrobeController {
    /**
     * @param {Object} options
     * @param {import('./WardrobeClient.js').WardrobeClient} options.forge
     * @param {Object} [options.viewer=window.NEXUS_VIEWER]
     * @param {string} [options.avatarId] - Wardrobe id; defaults to the avatar name.
     * @param {(state: string, event: Object) => void} [options.onState]
     */
    constructor({ forge, viewer = null, avatarId = null, onState = null } = {}) {
        if (!forge) throw new WardrobeForgeError('WardrobeController needs a WardrobeClient');

        this.forge = forge;
        this.viewer = viewer || (typeof window !== 'undefined' ? window.NEXUS_VIEWER : null);
        this.avatarId = avatarId;
        this.onState = onState;

        /** The avatar that was loaded before any look was applied. */
        this.original = null;
        /** The look currently worn, if any. */
        this.activeLook = null;
        /** Looks generated in this session, newest last. */
        this.looks = [];
    }

    // =====================================================================
    // viewer plumbing
    // =====================================================================

    /** @returns {Object|null} The viewer's AvatarManager. */
    get avatarManager() {
        return this.viewer?.avatarManager ?? null;
    }

    _requireManager() {
        const manager = this.avatarManager;
        if (!manager) {
            throw new WardrobeForgeError(
                'no AvatarManager on the viewer; pass { viewer } or wait for NEXUS_VIEWER'
            );
        }
        return manager;
    }

    /**
     * Remember the avatar currently in the viewer so restore() can bring it
     * back. Called automatically before the first applyLook().
     * @returns {Object|null} `{ url, name, index }`
     */
    snapshot() {
        const manager = this.avatarManager;
        const current = manager?.getCurrent?.() ?? manager?.current ?? null;
        this.original = current ? { ...current } : null;
        if (this.original && !this.avatarId) {
            this.avatarId = this.original.name || 'avatar';
        }
        return this.original;
    }

    /**
     * Load a look into the viewer.
     * @param {Object} look - A look from createLook() or a wardrobe manifest.
     * @returns {Promise<Object>} The look that was applied.
     */
    async applyLook(look) {
        const url = this.forge.resolveUrl(look?.vrmUrl ?? look?.vrm_url);
        if (!url) throw new WardrobeForgeError('look has no vrmUrl');

        const manager = this._requireManager();
        if (!this.original) this.snapshot();

        console.log('[WardrobeController] applying look:', look.name || look.id);
        await manager.setAvatarByUrl(url, look.name || 'Generated look', -1);
        manager.frameAvatar?.();

        this.activeLook = look;
        return look;
    }

    /**
     * Put the original avatar back.
     * @returns {Promise<boolean>} False when there was nothing to restore.
     */
    async restore() {
        if (!this.original?.url) return false;

        const manager = this._requireManager();
        console.log('[WardrobeController] restoring:', this.original.name || this.original.url);
        await manager.setAvatarByUrl(
            this.original.url,
            this.original.name || 'Avatar',
            this.original.index ?? -1
        );
        manager.frameAvatar?.();

        this.activeLook = null;
        return true;
    }

    // =====================================================================
    // generation
    // =====================================================================

    /**
     * Generate a look for the avatar currently in the viewer.
     *
     * @param {Object} options
     * @param {string} options.prompt
     * @param {string} [options.mode='auto']
     * @param {Object} [options.conditionsOfUse] - VRoid Hub conditions, when known.
     * @param {boolean} [options.attestModificationAllowed]
     * @param {boolean} [options.apply=false] - Wear it as soon as it is ready.
     * @returns {Promise<Object>} The completed look.
     */
    async createLook({ prompt, mode = 'auto', conditionsOfUse = null,
                       attestModificationAllowed = false, apply = false, ...rest } = {}) {
        if (!this.original) this.snapshot();

        const avatarUrl = this.original?.url;
        if (!avatarUrl) {
            throw new WardrobeForgeError('no avatar is loaded in the viewer');
        }

        const job = await this.forge.createLookAndWait(
            {
                avatarUrl,
                prompt,
                mode,
                avatarId: this.avatarId,
                name: this.original?.name ?? null,
                conditionsOfUse,
                attestModificationAllowed,
                ...rest,
            },
            {
                onState: (state, event) => {
                    console.log(`[WardrobeController] ${state}`, event?.message ?? '');
                    this.onState?.(state, event);
                },
            }
        );

        const look = job.look;
        this.looks.push(look);
        if (apply) await this.applyLook(look);
        return look;
    }

    /**
     * Every look available for this avatar: the original plus generated ones.
     * @returns {Promise<Array>}
     */
    async getLooks() {
        if (!this.avatarId) this.snapshot();
        if (!this.avatarId) return this.looks.slice();

        try {
            const manifest = await this.forge.getWardrobe(this.avatarId);
            return manifest.looks ?? [];
        } catch (error) {
            if (error instanceof WardrobeForgeError && error.status === 404) {
                return this.looks.slice();
            }
            throw error;
        }
    }

    // =====================================================================
    // try-on haul
    // =====================================================================

    /**
     * Wear a sequence of looks in turn, then return to the original avatar.
     *
     * @param {Array<Object|string>} looks - Looks, or prompts to generate first.
     * @param {Object} [options]
     * @param {number} [options.holdMs=4000] - How long to wear each look.
     * @param {(look: Object, index: number) => void} [options.onLook]
     * @param {boolean} [options.restoreAtEnd=true]
     * @returns {Promise<Array>} The looks that were worn.
     */
    async tryOnHaul(looks, { holdMs = 4000, onLook = null, restoreAtEnd = true } = {}) {
        if (!this.original) this.snapshot();
        const worn = [];

        for (const [index, entry] of looks.entries()) {
            const look = typeof entry === 'string' ? await this.createLook({ prompt: entry }) : entry;

            await this.applyLook(look);
            worn.push(look);
            onLook?.(look, index);

            if (holdMs > 0 && index < looks.length - 1) {
                await new Promise((done) => setTimeout(done, holdMs));
            }
        }

        if (restoreAtEnd) {
            if (holdMs > 0) await new Promise((done) => setTimeout(done, holdMs));
            await this.restore();
        }
        return worn;
    }

    /**
     * Merge this avatar's wardrobe into the viewer's avatar list, so generated
     * looks appear alongside the built-in avatars in the picker.
     * @returns {Promise<number>} How many looks were added.
     */
    async mergeIntoAvatarList() {
        const manager = this._requireManager();
        if (!this.avatarId) this.snapshot();
        if (!this.avatarId) return 0;

        const manifest = await this.forge.getWardrobeAsAvatarManifest(this.avatarId);
        const existing = new Set((manager.getAvatars?.() ?? []).map((item) => item.url));

        let added = 0;
        for (const item of manifest.items ?? []) {
            const url = this.forge.resolveUrl(item.url);
            if (!url || existing.has(url)) continue;
            manager.avatars.push({ name: item.name, file: item.file, url });
            added += 1;
        }

        console.log(`[WardrobeController] merged ${added} generated look(s) into the avatar list`);
        return added;
    }
}

export default WardrobeController;
