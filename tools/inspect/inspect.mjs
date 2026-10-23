/**
 * Fit inspection frames: tools/inspect/page.html, one screenshot per view.
 *
 *   node tools/inspect/inspect.mjs WORK_DIR
 *
 * WORK_DIR/views.json: [{file, out, yaw, focus, size, mannequin: [garment names]}]. Called by
 * fit_inspect.py only. A copy of the gallery's loop rather than a flag on it, so the catalogue
 * renderer stays exactly as it is and cannot be asked for a mannequin frame.
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
        const [width, height] = view.size || [480, 640];
        const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
        if (process.env.GALLERY_CDN_ROUTE) {
            const { routeCdn } = await import(path.resolve(process.env.GALLERY_CDN_ROUTE));
            await routeCdn(context);
        }
        const page = await context.newPage();
        page.on('pageerror', (error) => console.error('page error:', error.message));
        const focus = view.focus ? `&focus=${view.focus.map((n) => n.toFixed(4)).join(',')}` : '';
        const mannequin = view.mannequin ? `&mannequin=${encodeURIComponent(JSON.stringify(view.mannequin))}` : '';
        await page.goto(`${base}/page.html?a=${encodeURIComponent(view.file)}&yaw=${view.yaw || 0}${focus}${mannequin}`);
        await page.waitForFunction(() => window.ready, null, { timeout: 90000 });
        await page.waitForTimeout(500);
        await page.screenshot({ path: path.join(work, view.out) });
        await context.close();
    }
} finally {
    await browser.close();
    server.close();
}
