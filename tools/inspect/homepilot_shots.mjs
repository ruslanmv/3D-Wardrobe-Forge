#!/usr/bin/env node
/**
 * A look as HomePilot shows it: its own viewer, its own Pose Studio, its own cloth correction.
 *
 *   node tools/inspect/homepilot_shots.mjs LOOK.vrm OUT_DIR [--app http://127.0.0.1:8090]
 *       [--poses standing,sittingWide,sittingDesk,sittingCrossed] [--views front,threequarter,side,back]
 *       [--only 'Boots'] [--skinned]
 *
 * Start HomePilot first (`npm start` in a 3D-Avatar-Chatbot checkout; PORT=8090 to match the
 * default). The look is served from here with CORS, loaded with `NEXUS_VIEWER.loadAvatar`, and
 * each pose is applied through Pose Studio's own controls (Apply), exactly as a person would,
 * so the frame includes `PoseClothCorrector` after it has settled. For each pose and view it
 * writes OUT_DIR/<pose>-<view>.png (the viewer's canvas, UI hidden, a light grey background)
 * and, with --skinned, OUT_DIR/<pose>-<view>-skinned.png with the correction released: skinning
 * only. OUT_DIR/report.json has the viewer's own before/after numbers per garment and pose.
 *
 * `--only` is a regular expression over material names: only those meshes are drawn, for
 * garment-only views (a boot alone, the foundation alone). Views turn the avatar, not the
 * camera, so every view has the viewer's own framing: front 0, threequarter 45°, side 90°,
 * back 180°. Whole-body views are taken at the viewer's distance; nothing here zooms in.
 *
 * Why it exists: SW4's torn boots and FC4's straps were both seen first on a phone, in this
 * viewer, and never in Forge's own renders — it skins and corrects differently. Compare two
 * looks by running it twice and assembling the folders with tools/inspect/shot_board.py.
 * PLAYWRIGHT_CHROMIUM works as it does for tools/gallery.
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const flag = (name, fallback) => {
    const i = args.indexOf(`--${name}`);
    return i >= 0 ? args[i + 1] : fallback;
};
const positional = args.filter((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--') && args[i - 1] !== '--skinned'));
const [look, outDir] = positional;
if (!look || !outDir) {
    console.error('usage: homepilot_shots.mjs LOOK.vrm OUT_DIR [--app URL] [--poses a,b] [--views front,side] [--only RE] [--skinned]');
    process.exit(2);
}
const app = flag('app', 'http://127.0.0.1:8090');
const poses = flag('poses', 'standing,sittingWide,sittingDesk,sittingCrossed').split(',');
const views = flag('views', 'front,threequarter,side,back').split(',');
const only = flag('only', '');
const skinned = args.includes('--skinned');
const YAW = { front: 0, threequarter: Math.PI / 4, side: Math.PI / 2, back: Math.PI };
for (const v of views) if (!(v in YAW)) throw new Error(`unknown view ${v}: ${Object.keys(YAW).join(', ')}`);
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
if (!path.relative(repo, path.resolve(outDir)).startsWith('..')) {
    console.error(`OUT_DIR must be outside the repository (${repo}): no shot can be committed by accident`);
    process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });

const server = http.createServer((request, response) => {
    response.setHeader('Access-Control-Allow-Origin', '*');
    fs.readFile(path.resolve(look), (error, data) => {
        if (error) return response.writeHead(404).end();
        response.writeHead(200, { 'content-type': 'model/gltf-binary' }).end(data);
    });
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const lookUrl = `http://127.0.0.1:${server.address().port}/look.vrm`;

const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
});
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 2 })).newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto(app, { waitUntil: 'load' });
await page.waitForFunction(() => window.NEXUS_VIEWER?.avatarManager?.currentRoot, null, { timeout: 240000 });
await page.evaluate((u) => window.NEXUS_VIEWER.loadAvatar(u, 'look'), lookUrl);
await page.waitForTimeout(8000);

/** The correction's report once it differs from `previous`: it settles some frames after a pose. */
async function settled(previous) {
    for (let i = 0; i < 360; i += 1) {
        const last = await page.evaluate(() => window.vrPoseSystem?.cloth?.last || null);
        if (last && JSON.stringify(last) !== JSON.stringify(previous)) return last;
        await page.waitForTimeout(500);
    }
    return null;
}

async function shot(yaw, name) {
    await page.evaluate(
        ([keep, turn]) => {
            const re = keep ? new RegExp(keep) : null;
            const root = window.NEXUS_VIEWER.avatarManager.currentRoot;
            window.__hidden = [];
            if (re) {
                root.traverse((o) => {
                    if (!o.isMesh || !o.visible) return;
                    const m = Array.isArray(o.material) ? o.material[0] : o.material;
                    if (!re.test((m && m.name) || '')) {
                        o.visible = false;
                        window.__hidden.push(o);
                    }
                });
            }
            window.__yaw = root.rotation.y;
            root.rotation.y += turn;
            const scene = window.NEXUS_VIEWER.scene;
            window.__bg = scene.background && scene.background.getHex ? scene.background.getHex() : null;
            if (window.__bg !== null) scene.background.setHex(0xd9dde3);
            const style = document.createElement('style');
            style.id = '__shots';
            style.textContent =
                'header,.app-header,.chat-panel,.nexus-stage-label,.nexus-stage-info{visibility:hidden!important}';
            document.head.appendChild(style);
        },
        [only, yaw]
    );
    await page.waitForTimeout(1200);
    const box = await page.evaluate(() => {
        const c = [...document.querySelectorAll('canvas')].sort((a, b) => b.width * b.height - a.width * a.height)[0];
        const r = c.getBoundingClientRect();
        return { x: r.left, y: r.top, width: r.width, height: r.height };
    });
    await page.screenshot({ path: path.join(outDir, `${name}.png`), clip: box });
    await page.evaluate(() => {
        window.__hidden.forEach((o) => (o.visible = true));
        window.NEXUS_VIEWER.avatarManager.currentRoot.rotation.y = window.__yaw;
        if (window.__bg !== null) window.NEXUS_VIEWER.scene.background.setHex(window.__bg);
        document.getElementById('__shots')?.remove();
    });
}

const report = { look: path.basename(look), app, only, poses: {}, errors };
let previous = await settled(null);
for (const pose of poses) {
    await page.$eval('#openPoseStudioBtn', (e) => e.click());
    await page.waitForSelector('#posePresetSelect', { state: 'attached', timeout: 15000 });
    const known = await page.$eval('#posePresetSelect', (s, p) => {
        if (![...s.options].some((o) => o.value === p)) return false;
        s.value = p;
        s.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    }, pose);
    if (!known) {
        report.poses[pose] = { error: 'not a Pose Studio preset' };
        await page.$eval('#poseStudioCloseBtn', (e) => e.click()).catch(() => {});
        continue;
    }
    await page.$eval('#poseApplyBtn', (e) => e.click());
    const cloth = await settled(previous);
    previous = cloth;
    await page.$eval('#poseStudioCloseBtn', (e) => e.click()).catch(() => {});
    await page.waitForTimeout(1000);
    for (const view of views) await shot(YAW[view], `${pose}-${view}`);
    if (skinned) {
        await page.evaluate(() => window.vrPoseSystem.cloth.release(window.vrPoseSystem.avatarRoot));
        await page.waitForTimeout(800);
        for (const view of views) await shot(YAW[view], `${pose}-${view}-skinned`);
    }
    report.poses[pose] = {
        garments: (cloth || []).map((g) => ({ name: g.name.split(' [')[0], before: g.before, after: g.after })),
    };
    console.log(pose, cloth ? 'settled' : 'no correction reported');
}
fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 1));
await browser.close();
server.close();
