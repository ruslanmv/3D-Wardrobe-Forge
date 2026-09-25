/**
 * Render named views of VRMs with the Studio's own viewer: the web preview backend.
 *
 *   node tools/gallery/views.mjs WORK_DIR
 *
 * WORK_DIR/views.json lists the views: [{file, out, yaw, focus: [y0, y1] | null, size: [w, h]}].
 * `file` and `out` are names inside WORK_DIR. Called by wardrobe.hosiery.previews; the same
 * page, viewer and lights as the gallery (render.mjs), so a preview is what the Studio shows.
 * PLAYWRIGHT_CHROMIUM and GALLERY_CDN_ROUTE work as they do for render.mjs.
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..');
const work = path.resolve(process.argv[2] || '.');
const views = JSON.parse(fs.readFileSync(path.join(work, 'views.json'), 'utf8'));

const types = { '.html': 'text/html', '.js': 'text/javascript', '.vrm': 'model/gltf-binary' };
const server = http.createServer((request, response) => {
    const name = decodeURIComponent(new URL(request.url, 'http://x').pathname).slice(1);
    const file =
        name === 'page.html' ? path.join(here, 'page.html')
        : name === 'viewer.js' ? path.join(root, 'apps', 'studio', 'js', 'viewer.js')
        : path.join(work, path.basename(name));
    fs.readFile(file, (error, data) => {
        if (error) return response.writeHead(404).end();
        response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' }).end(data);
    });
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});
try {
    for (const view of views) {
        const [width, height] = view.size || [1086, 1448];
        const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
        if (process.env.GALLERY_CDN_ROUTE) {
            const { routeCdn } = await import(path.resolve(process.env.GALLERY_CDN_ROUTE));
            await routeCdn(context);
        }
        const page = await context.newPage();
        page.on('pageerror', (error) => console.error('page error:', error.message));
        const focus = view.focus ? `&focus=${view.focus.map((n) => n.toFixed(4)).join(',')}` : '';
        await page.goto(`${base}/page.html?a=${encodeURIComponent(view.file)}&yaw=${view.yaw || 0}${focus}`);
        await page.waitForFunction(() => window.ready, null, { timeout: 90000 });
        await page.waitForTimeout(700);
        await page.screenshot({ path: path.join(work, view.out) });
        await context.close();
        console.log('rendered', view.out);
    }
} finally {
    await browser.close();
    server.close();
}
