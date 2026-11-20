/**
 * DP2. The Studio's Collections browser, photographed as a guest or an admin, desktop and phone.
 *
 *   node tools/qa/studio_shot.cjs --base https://ruslanmv-3d-wardrobe-forge.hf.space --out <dir>
 *   node tools/qa/studio_shot.cjs --base http://127.0.0.1:8090 --admin-token-file <file> --out <dir>
 *
 * Uses the pre-installed Playwright (cloud sessions: never reinstall it). An admin token is read
 * from a file and put in sessionStorage only, as the Studio's own sign-in does; never printed.
 * Prints what it saw (sections, Private badges, dashboard, page errors) — look at the frames too.
 * Frames of Private content are never committed: write them to a scratch folder.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const arg = (name, fallback) => {
    const i = process.argv.indexOf(name);
    return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
};

(async () => {
    const base = arg('--base', 'https://ruslanmv-3d-wardrobe-forge.hf.space').replace(/\/$/, '');
    const out = path.resolve(arg('--out', 'studio-shots'));
    const tokenFile = arg('--admin-token-file', '');
    const token = tokenFile ? fs.readFileSync(tokenFile, 'utf8').trim() : '';
    fs.mkdirSync(out, { recursive: true });
    const browser = await chromium.launch();
    let failed = false;
    for (const [name, viewport] of [
        ['desktop', { width: 1400, height: 900 }],
        ['phone', { width: 390, height: 844 }],
    ]) {
        const page = await browser.newPage({ viewport });
        const errors = [];
        page.on('pageerror', (e) => errors.push(e.message));
        if (token) await page.addInitScript((t) => sessionStorage.setItem('wardrobe_studio_admin', t), token);
        await page.goto(`${base}/studio/`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(3000);
        const started = Date.now();
        await page.click('#collections-btn');
        await page.waitForSelector('.reg-card', { timeout: 120000 });
        const ms = Date.now() - started;
        await page.waitForTimeout(2500);
        const file = path.join(out, `collections-${token ? 'admin' : 'guest'}-${name}.png`);
        await page.screenshot({ path: file });
        const seen = {
            openedMs: ms,
            sections: await page.locator('.reg-section').count(),
            privateBadges: await page.locator('.reg-badge.private').count(),
            dashboard: await page.locator('.reg-dashboard').count(),
            errors,
        };
        // A guest must never see Private: the server filters, so a badge here is a leak.
        if (!token && (seen.privateBadges || seen.dashboard)) failed = true;
        if (errors.length) failed = true;
        console.log(name, JSON.stringify(seen), '→', file);
        await page.close();
    }
    await browser.close();
    process.exit(failed ? 1 : 0);
})();
