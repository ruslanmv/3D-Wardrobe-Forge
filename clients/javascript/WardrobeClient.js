export class WardrobeClient {
  constructor({ baseUrl, fetchImpl = fetch }) {
    this.baseUrl = String(baseUrl || '').replace(/\/$/, '');
    this.fetch = fetchImpl;
  }

  async createLook({ avatarUrl, sha256 = null, licenseMetadata = {}, prompt, mode = 'auto' }) {
    const res = await this.fetch(`${this.baseUrl}/v1/jobs`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        avatar: { url: avatarUrl, sha256, license_metadata: licenseMetadata },
        outfit: { prompt, mode },
      }),
    });
    if (!res.ok) throw new Error(`Wardrobe Forge create failed: ${res.status}`);
    return res.json();
  }

  async getJob(jobId) {
    const res = await this.fetch(`${this.baseUrl}/v1/jobs/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(`Wardrobe Forge job failed: ${res.status}`);
    return res.json();
  }

  async wait(jobId, { intervalMs = 1000, timeoutMs = 120000 } = {}) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const job = await this.getJob(jobId);
      if (job.state === 'completed') return job;
      if (job.state === 'failed') throw new Error(job.error || 'Wardrobe job failed');
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error('Wardrobe job timed out');
  }
}
