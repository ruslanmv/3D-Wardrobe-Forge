// The README's phone screenshots of Wardrobe Studio, taken from a running Studio.
//
//     make studio                                   # or: uvicorn apps.api.main:app --port 8080
//     node tools/gallery/studio.mjs [BASE_URL] [OUT_DIR]
//     python tools/gallery/studio_sheet.py OUT_DIR  # composes docs/images/studio-mobile.webp
//
// At phone width (414 x 896, device scale 2) it picks AvatarSample A, generates
// the look below through the real API exactly as a user would, and captures
// three screens: the Wardrobe tab with the new look beside her own outfit, the
// Design tab, and the finished job with its fit report. Nothing is staged: the
// job, the renders and the report are the server's.
//
// PLAYWRIGHT_CHROMIUM and GALLERY_CDN_ROUTE work as they do for render.mjs.

import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const base = process.argv[2] || 'http://127.0.0.1:8080';
const out = path.resolve(process.argv[3] || 'studio-shots');
// Generated in order; the last is the one the design and report screens show.
const PROMPTS = (process.env.STUDIO_PROMPTS || [
    'red skater skirt',
    'navy pleated mini skirt',
    'black long sleeve fitted tee + rose a-line midi skirt',
    'silk lavender a-line midi skirt',
].join('|')).split('|');
const PROMPT = PROMPTS[PROMPTS.length - 1];
const AVATAR = process.env.STUDIO_AVATAR || 'avatar-sample-a';
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});
try {
    const context = await browser.newContext({
        viewport: { width: 414, height: 896 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
    });
    if (process.env.GALLERY_CDN_ROUTE) {
        const { routeCdn } = await import(path.resolve(process.env.GALLERY_CDN_ROUTE));
        await routeCdn(context);
    }
    const page = await context.newPage();
    page.on('pageerror', (error) => console.error('page error:', error.message));
    await page.goto(`${base}/studio/`);

    // Her, from the library.
    await page.click('[data-tab-target="library"]');
    await page.waitForSelector(`#avatar-list [data-slug="${AVATAR}"]:not([disabled])`, { timeout: 60000 });
    await page.click(`#avatar-list [data-slug="${AVATAR}"]`);
    await page.waitForFunction(() => !document.getElementById('generate-btn').disabled, null, { timeout: 120000 });
    await page.waitForTimeout(2500);

    // The looks, generated one after another, as a user would.
    let state = '';
    for (const prompt of PROMPTS) {
        await page.click('[data-tab-target="design"]');
        await page.fill('#prompt', prompt);
        await page.click('#generate-btn');
        await page.waitForFunction(
            () => ['completed', 'failed', 'rejected'].includes(document.getElementById('job-state').textContent.trim()),
            null,
            { timeout: 600000 },
        );
        state = (await page.textContent('#job-state')).trim();
        console.error(`${prompt}: ${state}`);
        if (state !== 'completed') throw new Error(`"${prompt}" ended ${state}`);
        await page.waitForFunction(() => !document.getElementById('generate-btn').disabled, null, { timeout: 60000 });
    }
    await page.waitForTimeout(3000);
    // Both outfits on the stage, side by side.
    const both = page.locator('#view-mode [data-mode="compare"]');
    if (await both.isEnabled()) await both.click();
    await page.waitForTimeout(2500);

    // 1. The wardrobe, with the new look in it.
    await page.click('[data-tab-target="wardrobe"]');
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(out, 'studio-wardrobe.png') });

    // 2. The designer, from the top of its panel (it scrolls on its own under the stage).
    await page.click('[data-tab-target="design"]');
    await page.evaluate(() => {
        window.scrollTo(0, 0);
        for (const el of [document.getElementById('designer'), document.scrollingElement]) if (el) el.scrollTop = 0;
    });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(out, 'studio-design.png') });

    // 3. The finished job and its fit report, with the prompt that made them just above.
    // The panel scrolls under the stage, so aim for its prompt; if the report would
    // fall below the fold, scroll on until it ends at the panel's bottom edge.
    await page.evaluate(() => {
        const panel = document.getElementById('designer');
        const top = () => panel.getBoundingClientRect().top;
        const prompt = document.getElementById('prompt');
        panel.scrollTop += prompt.getBoundingClientRect().top - top() - 24;
        const report = document.getElementById('report');
        const bottom = panel.getBoundingClientRect().bottom;
        const overflow = report.getBoundingClientRect().bottom - bottom + 16;
        if (overflow > 0) panel.scrollTop += overflow;
    });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(out, 'studio-report.png') });
    console.log(JSON.stringify({ state, prompt: PROMPT, avatar: AVATAR, out }));
    await context.close();
} finally {
    await browser.close();
}
