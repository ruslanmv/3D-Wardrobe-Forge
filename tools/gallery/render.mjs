/**
 * Render every look in OUT_DIR twice — front 3/4 and front, both in the A-pose —
 * with the Studio's own viewer (three.js + three-vrm, the versions yourfriend.online
 * ships), so what the gallery shows is what the Studio and the chatbot show.
 *
 *   node tools/gallery/render.mjs OUT_DIR [NN ...]
 *
 * Needs Playwright with a Chromium (PLAYWRIGHT_CHROMIUM=/path/to/chromium to pick
 * one) and network access to cdn.jsdelivr.net for three.js. GALLERY_CDN_ROUTE may
 * name a module exporting routeCdn(context), for sandboxes that proxy the CDN.
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..');
const [outArg, ...wanted] = process.argv.slice(2);
if (!outArg) throw new Error('usage: node tools/gallery/render.mjs OUT_DIR [NN ...]');
const out = path.resolve(outArg);

const types = { '.html': 'text/html', '.js': 'text/javascript', '.vrm': 'model/gltf-binary' };
const server = http.createServer((request, response) => {
    const name = decodeURIComponent(new URL(request.url, 'http://x').pathname).slice(1);
    const file =
        name === 'page.html' ? path.join(here, 'page.html')
        : name === 'viewer.js' ? path.join(root, 'apps', 'studio', 'js', 'viewer.js')
        : path.join(out, path.basename(name));
    fs.readFile(file, (error, data) => {
        if (error) return response.writeHead(404).end();
        response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' }).end(data);
    });
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;

const ids = wanted.length
    ? wanted
    : fs.readdirSync(out).filter((f) => /^g-(\d+|source-dressed)\.vrm$/.test(f)).map((f) => f.slice(2, -4));

const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});
// 1x device scale: the viewer's canvas is sized in CSS pixels, and at 2x the
// screenshot captured only its top-left quarter.
const context = await browser.newContext({ viewport: { width: 1040, height: 1800 }, deviceScaleFactor: 1 });
if (process.env.GALLERY_CDN_ROUTE) {
    const { routeCdn } = await import(path.resolve(process.env.GALLERY_CDN_ROUTE));
    await routeCdn(context);
}
const page = await context.newPage();
page.on('pageerror', (error) => console.error('page error:', error.message));
for (const id of ids) {
    for (const [view, yaw] of [['34', 35], ['front', 0]]) {
        await page.goto(`${base}/page.html?a=g-${id}.vrm&yaw=${yaw}`);
        await page.waitForFunction(() => window.ready, null, { timeout: 90000 });
        await page.waitForTimeout(700);
        await page.screenshot({ path: path.join(out, `r-${id}-${view}.png`) });
    }
    console.log('rendered', id);
}
await browser.close();
server.close();
