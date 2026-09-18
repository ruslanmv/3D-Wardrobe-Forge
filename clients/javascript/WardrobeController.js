export class WardrobeController {
  constructor({ viewer }) {
    this.viewer = viewer;
    this.original = null;
    this.activeLook = null;
  }

  snapshot() {
    const manager = this.viewer?.avatarManager;
    this.original = manager?.current ? { ...manager.current } : null;
    return this.original;
  }

  async applyLook(look) {
    if (!look?.vrm_url) throw new Error('look.vrm_url is required');
    if (!this.original) this.snapshot();
    await this.viewer.loadAvatar(look.vrm_url, look.name || 'Generated look');
    this.activeLook = look;
    return look;
  }

  async restore() {
    if (!this.original?.url) return false;
    await this.viewer.loadAvatar(this.original.url, this.original.name || 'Avatar');
    this.activeLook = null;
    return true;
  }
}
