#!/usr/bin/env node
/**
 * Export HomePilot's Pose Studio presets as the quaternions its renderer applies.
 *
 *   node tools/inspect/export_homepilot_poses.mjs /path/to/3D-Avatar-Chatbot OUT.json [--with-adult]
 *
 * Reads src/gltf-viewer/VRPoseSystem.js from a HomePilot checkout and imports it (through a
 * temporary copy whose three.js import points at that checkout's vendored copy), so the
 * rotations are the ones the app computes, not values copied by hand. Writes
 * {about, source, presets: [{name, label, bones: {humanoidBone: [x, y, z, w]}}]} in Pose
 * Studio's order. Presets flagged adult are left out unless --with-adult is given.
 *
 * tests/fixtures/homepilot-poses.json was made this way; re-run it when Pose Studio changes.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const [checkout, out, ...flags] = process.argv.slice(2);
if (!checkout || !out) {
    console.error('usage: node tools/inspect/export_homepilot_poses.mjs HOMEPILOT_CHECKOUT OUT.json [--with-adult]');
    process.exit(2);
}
const root = path.resolve(checkout);
const source = path.join(root, 'src', 'gltf-viewer', 'VRPoseSystem.js');
const three = path.join(root, 'vendor', 'three-0.147.0', 'build', 'three.module.js');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'poses-'));
const copy = path.join(tmp, 'VRPoseSystem.mjs');
fs.writeFileSync(
    copy,
    fs.readFileSync(source, 'utf8').replace(
        "'../../vendor/three-0.147.0/build/three.module.js'",
        JSON.stringify(pathToFileURL(three).href)
    )
);
try {
    const m = await import(pathToFileURL(copy).href);
    const presets = [];
    for (const name of m.PRESET_ORDER) {
        const p = m.POSE_PRESETS[name];
        if (!p || (p.adult && !flags.includes('--with-adult'))) continue;
        const bones = {};
        for (const [bone, q] of Object.entries(p.bones || {})) bones[bone] = [q.x, q.y, q.z, q.w];
        presets.push({ name, label: p.label, bones });
    }
    let commit = 'unknown';
    try {
        commit = execFileSync('git', ['-C', root, 'rev-parse', '--short', 'HEAD']).toString().trim();
    } catch {
        /* not a git checkout: the source stays unnamed */
    }
    const doc = {
        about:
            'HomePilot Pose Studio presets (src/gltf-viewer/VRPoseSystem.js), normalized humanoid bone ' +
            'quaternions [x, y, z, w], exported by tools/inspect/export_homepilot_poses.mjs.',
        source: `3D-Avatar-Chatbot@${commit}`,
        presets,
    };
    fs.writeFileSync(out, JSON.stringify(doc, null, 1) + '\n');
    console.log(`${presets.length} presets → ${out}`);
} finally {
    fs.rmSync(tmp, { recursive: true, force: true });
}
