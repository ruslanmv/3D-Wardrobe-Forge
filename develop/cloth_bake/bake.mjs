// EXPERIMENT. Settle one garment of a Forge look on the posed avatar with Rapier, offline.
//
//   node bake.mjs --vrm look.vrm --template dress-a-line-v1 --out out/aline-bake.json
//
// Why offline. Two rounds of real-time cloth in the viewer failed (docs/CLOTH_FAILED_ATTEMPTS.md).
// Here the solver runs once per pose at export time, against her real posed body as a triangle
// mesh collider (not two thigh capsules: failures F5/F6), and nothing runs on the phone. The
// settled shapes are then turned into skin weights by fit_weights.py, so the viewer's master
// draws the result with no code change.
//
// The avatar is posed exactly as the viewer poses her: three r147 + three-vrm 2.1.0 (the
// viewer's pair), presets from poses.json copied from VRPoseSystem.js, set on the normalized
// humanoid bones. The garment mesh keeps the file's vertex order: nothing here calls
// removeUnnecessaryVertices (failure F3).

import fs from 'node:fs';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';
import RAPIER from '@dimforge/rapier3d-compat';

const args = Object.fromEntries(
    process.argv.slice(2).reduce((pairs, arg, i, all) => (arg.startsWith('--') ? [...pairs, [arg.slice(2), all[i + 1]]] : pairs), [])
);
const POSES = JSON.parse(fs.readFileSync(new URL('./poses.json', import.meta.url)));
const poseNames = (args.poses || 'standing,sittingDesk,sittingWide,sittingCrossed').split(',');
const FRAMES = Number(args.frames || 90);
const SOFTNESS_HZ = Number(args.hz || 120);

// ---------------------------------------------------------------- GLB in, textures out
function readGlb(buffer) {
    const view = new DataView(buffer.buffer, buffer.byteOffset, buffer.byteLength);
    const jsonLength = view.getUint32(12, true);
    const json = JSON.parse(new TextDecoder().decode(buffer.subarray(20, 20 + jsonLength)));
    const binStart = 20 + jsonLength + 8;
    const binLength = view.getUint32(20 + jsonLength, true);
    return { json, bin: buffer.subarray(binStart, binStart + binLength) };
}

function writeGlb(json, bin) {
    const enc = new TextEncoder().encode(JSON.stringify(json));
    const jsonPad = (4 - (enc.length % 4)) % 4;
    const binPad = (4 - (bin.length % 4)) % 4;
    const total = 12 + 8 + enc.length + jsonPad + 8 + bin.length + binPad;
    const out = new Uint8Array(total);
    const dv = new DataView(out.buffer);
    dv.setUint32(0, 0x46546c67, true);
    dv.setUint32(4, 2, true);
    dv.setUint32(8, total, true);
    dv.setUint32(12, enc.length + jsonPad, true);
    dv.setUint32(16, 0x4e4f534a, true);
    out.set(enc, 20);
    out.fill(0x20, 20 + enc.length, 20 + enc.length + jsonPad);
    const binHeader = 20 + enc.length + jsonPad;
    dv.setUint32(binHeader, bin.length + binPad, true);
    dv.setUint32(binHeader + 4, 0x004e4942, true);
    out.set(bin, binHeader + 8);
    return out;
}

// Node has no image decoder, and the physics needs no texture: drop them before parsing.
function stripTextures(json) {
    delete json.images;
    delete json.textures;
    delete json.samplers;
    for (const material of json.materials || []) {
        const pbr = material.pbrMetallicRoughness || {};
        delete pbr.baseColorTexture;
        delete pbr.metallicRoughnessTexture;
        delete material.normalTexture;
        delete material.occlusionTexture;
        delete material.emissiveTexture;
        if (material.extensions) delete material.extensions.VRMC_materials_mtoon;
    }
    const vrm0 = json.extensions && json.extensions.VRM;
    if (vrm0) {
        vrm0.materialProperties = [];
        if (vrm0.meta) delete vrm0.meta.texture;
    }
    const vrm1 = json.extensions && json.extensions.VRMC_vrm;
    if (vrm1 && vrm1.meta) delete vrm1.meta.thumbnailImage;
}

// ---------------------------------------------------------------- WCL1 (wardrobe/cloth/binary.py)
function decodeWcl1(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const magic = String.fromCharCode(...bytes.subarray(0, 4));
    if (magic !== 'WCL1') throw new Error(`not a WCL1 asset: ${magic}`);
    const [, , particles, tris, stretchN, shearN, bendN, seamsN, attachN, renderN] = Array.from({ length: 10 }, (_, i) =>
        dv.getUint32(4 + i * 4, true)
    );
    let o = 48;
    const positions = new Float32Array(particles * 3);
    for (let i = 0; i < particles * 3; i++, o += 4) positions[i] = dv.getFloat32(o, true);
    const triangles = new Uint32Array(tris * 3);
    for (let i = 0; i < tris * 3; i++, o += 4) triangles[i] = dv.getUint32(o, true);
    const pairs = (n) => {
        const out = [];
        for (let i = 0; i < n; i++, o += 12) out.push([dv.getUint32(o, true), dv.getUint32(o + 4, true), dv.getFloat32(o + 8, true)]);
        return out;
    };
    const stretch = pairs(stretchN);
    o += shearN * 16;
    const bend = pairs(bendN);
    o += seamsN * 8;
    const attachment = new Float32Array(particles);
    for (let i = 0; i < attachN; i++, o += 8) attachment[dv.getUint32(o, true)] = dv.getFloat32(o + 4, true);
    const binding = new Uint32Array(renderN);
    for (let i = 0; i < renderN; i++, o += 24) binding[i] = dv.getUint32(o, true); // i0; w0 is 1 in WCL1/1
    return { particles, positions, triangles, stretch, bend, attachment, binding };
}

// ---------------------------------------------------------------- load and pose
async function load(path, template) {
    const raw = new Uint8Array(fs.readFileSync(path));
    const { json, bin } = readGlb(raw);
    const node = json.nodes.find((n) => n.extras?.wardrobeForge?.templateId === template);
    if (!node) throw new Error(`no node with templateId ${template}`);
    const summary = node.extras.wardrobeForge.clothAsset;
    if (!summary || !Number.isInteger(summary.bufferView)) throw new Error(`${template} carries no WCL1 buffer`);
    const view = json.bufferViews[summary.bufferView];
    const cloth = decodeWcl1(bin.subarray(view.byteOffset || 0, (view.byteOffset || 0) + view.byteLength));
    stripTextures(json);
    const glb = writeGlb(json, bin);
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await new Promise((ok, bad) => loader.parse(glb.buffer, '', ok, bad));
    return { gltf, vrm: gltf.userData.vrm, cloth, summary, nodeName: node.name };
}

function applyPose(vrm, name) {
    const preset = POSES[name];
    if (!preset) throw new Error(`unknown pose ${name}`);
    vrm.humanoid.resetNormalizedPose();
    for (const [bone, deg] of Object.entries(preset)) {
        const node = vrm.humanoid.getNormalizedBoneNode(bone);
        if (!node) continue;
        node.quaternion.setFromEuler(new THREE.Euler(...deg.map(THREE.MathUtils.degToRad)));
    }
    vrm.humanoid.update();
    vrm.scene.updateMatrixWorld(true);
}

function skinned(mesh) {
    const pos = mesh.geometry.attributes.position;
    const out = new Float32Array(pos.count * 3);
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i);
        mesh.boneTransform(i, v);
        v.applyMatrix4(mesh.matrixWorld);
        out.set([v.x, v.y, v.z], i * 3);
    }
    return out;
}

// S_j such that world = sum_j w_j S_j v_bind, the same algebra as SkinnedMesh.boneTransform.
function skinMatrices(mesh) {
    const pre = new THREE.Matrix4().multiplyMatrices(mesh.matrixWorld, mesh.bindMatrixInverse);
    return mesh.skeleton.bones.map((bone, j) => {
        const m = new THREE.Matrix4().multiplyMatrices(bone.matrixWorld, mesh.skeleton.boneInverses[j]);
        return Array.from(new THREE.Matrix4().multiplyMatrices(pre, m).multiply(mesh.bindMatrix).elements);
    });
}

// ---------------------------------------------------------------- body and signed depth
function bodyMesh(meshes) {
    const verts = [];
    const index = [];
    for (const mesh of meshes) {
        const base = verts.length / 3;
        verts.push(...skinned(mesh));
        const idx = mesh.geometry.index;
        const count = idx ? idx.count : mesh.geometry.attributes.position.count;
        for (let i = 0; i < count; i++) index.push(base + (idx ? idx.getX(i) : i));
    }
    const v = new Float32Array(verts);
    const ind = new Uint32Array(index);
    const normals = new Float32Array(v.length);
    for (let t = 0; t < ind.length; t += 3) {
        const [a, b, c] = [ind[t], ind[t + 1], ind[t + 2]];
        const ab = [v[b * 3] - v[a * 3], v[b * 3 + 1] - v[a * 3 + 1], v[b * 3 + 2] - v[a * 3 + 2]];
        const ac = [v[c * 3] - v[a * 3], v[c * 3 + 1] - v[a * 3 + 1], v[c * 3 + 2] - v[a * 3 + 2]];
        const n = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]];
        for (const k of [a, b, c]) for (let d = 0; d < 3; d++) normals[k * 3 + d] += n[d];
    }
    return { vertices: v, indices: ind, normals };
}

function depthProbe(world, collider, body) {
    // Signed distance of a point to her body: negative inside. Rapier finds the closest point
    // on her surface; the sign comes from the posed vertex normal nearest that point. Rapier's
    // own feature ids are not used: it cleans the triangle mesh on the way in, so its triangle
    // numbers do not match ours, and reading them marked points 10 cm outside her as inside.
    const v = body.vertices;
    const cell = 0.02;
    const grid = new Map();
    const key = (x, y, z) => `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
    for (let i = 0; i < v.length / 3; i++) {
        const k = key(v[i * 3], v[i * 3 + 1], v[i * 3 + 2]);
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push(i);
    }
    const nearest = (q) => {
        const [cx, cy, cz] = [Math.floor(q.x / cell), Math.floor(q.y / cell), Math.floor(q.z / cell)];
        let best = -1;
        let bestD = Infinity;
        for (let dx = -1; dx <= 1; dx++)
            for (let dy = -1; dy <= 1; dy++)
                for (let dz = -1; dz <= 1; dz++)
                    for (const i of grid.get(`${cx + dx},${cy + dy},${cz + dz}`) || []) {
                        const dd = (v[i * 3] - q.x) ** 2 + (v[i * 3 + 1] - q.y) ** 2 + (v[i * 3 + 2] - q.z) ** 2;
                        if (dd < bestD) [best, bestD] = [i, dd];
                    }
        return best;
    };
    return (p) => {
        const hit = world.projectPoint(p, false, undefined, undefined, undefined, undefined, (c) => c.handle === collider.handle);
        if (!hit) return Infinity;
        const q = hit.point;
        const d = [p.x - q.x, p.y - q.y, p.z - q.z];
        const dist = Math.hypot(...d);
        const i = nearest(q);
        if (i < 0) return dist;
        const n = [body.normals[i * 3], body.normals[i * 3 + 1], body.normals[i * 3 + 2]];
        return d[0] * n[0] + d[1] * n[1] + d[2] * n[2] < 0 ? -dist : dist;
    };
}

function metrics(render, probe, bindEdges) {
    let maxPen = 0;
    let inside = 0;
    for (let i = 0; i < render.length / 3; i++) {
        const s = probe({ x: render[i * 3], y: render[i * 3 + 1], z: render[i * 3 + 2] });
        if (s < -0.001) {
            inside++;
            maxPen = Math.max(maxPen, -s);
        }
    }
    let maxStretch = 0;
    for (const [a, b, rest] of bindEdges) {
        if (rest < 1e-5) continue;
        const l = Math.hypot(render[a * 3] - render[b * 3], render[a * 3 + 1] - render[b * 3 + 1], render[a * 3 + 2] - render[b * 3 + 2]);
        maxStretch = Math.max(maxStretch, l / rest);
    }
    return { maxPenetrationMm: +(maxPen * 1000).toFixed(1), insidePct: +((100 * inside) / (render.length / 3)).toFixed(2), maxEdgeStretch: +maxStretch.toFixed(2) };
}

// ---------------------------------------------------------------- settle
function settle(cloth, renderStart, body) {
    const world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
    // TRIMESH_FLAGS (env) lets the experiment tell Rapier which side of her surface is inside.
    const flags = (process.env.TRIMESH_FLAGS || '').split(',').filter(Boolean).reduce((f, n) => f | RAPIER.TriMeshFlags[n], 0);
    world.createCollider(RAPIER.ColliderDesc.trimesh(body.vertices, body.indices, flags || undefined).setFriction(0.8));
    const particles = new Float32Array(cloth.particles * 3);
    const counts = new Float32Array(cloth.particles);
    cloth.binding.forEach((p, r) => {
        for (let d = 0; d < 3; d++) particles[p * 3 + d] += renderStart[r * 3 + d];
        counts[p]++;
    });
    for (let p = 0; p < cloth.particles; p++) for (let d = 0; d < 3; d++) particles[p * 3 + d] /= counts[p] || 1;
    const pinned = [];
    cloth.attachment.forEach((w, p) => w >= 0.999 && pinned.push(p));
    const desc = new RAPIER.SoftBodyDesc(particles)
        .setEdges(new Uint32Array(cloth.stretch.flatMap(([a, b]) => [a, b])))
        .setBendEdges(new Uint32Array(cloth.bend.flatMap(([a, b]) => [a, b])))
        .setSurface(cloth.triangles)
        .setOriented(false)
        .setSurfaceCollider(RAPIER.ColliderDesc.ball(0.01).setFriction(0.8))
        .setParticleRadius(0.002)
        .setPinnedParticles(new Uint32Array(pinned))
        .setSoftness(SOFTNESS_HZ, 1)
        .setMass(0.25);
    const body3 = world.createSoftBody(desc);
    const started = performance.now();
    for (let f = 0; f < FRAMES; f++) world.step();
    const ms = performance.now() - started;
    const x = body3.particlePositions();
    const render = new Float32Array(renderStart.length);
    cloth.binding.forEach((p, r) => render.set([x[p * 3], x[p * 3 + 1], x[p * 3 + 2]], r * 3));
    return { world, render, ms, pinned: pinned.length };
}

// ---------------------------------------------------------------- main
await RAPIER.init();
const { vrm, gltf, cloth, summary, nodeName } = await load(args.vrm, args.template);
let target = null;
gltf.scene.traverse((o) => {
    if (o.userData?.wardrobeForge?.templateId === args.template) target = o;
});
const garmentMeshes = [];
target.traverse((o) => o.isSkinnedMesh && garmentMeshes.push(o));
const others = [];
gltf.scene.traverse((o) => {
    if (!o.isSkinnedMesh || garmentMeshes.includes(o)) return;
    // Hair is not her body: on fem_vroid the back hair is a primitive of the body mesh itself,
    // so it is found by material, not by node name.
    const material = Array.isArray(o.material) ? o.material[0] : o.material;
    if (/hair/i.test(o.name) || /hair/i.test(material?.name || '')) return;
    others.push(o);
});
const renderCount = garmentMeshes.reduce((n, m) => n + m.geometry.attributes.position.count, 0);
if (renderCount !== cloth.binding.length) throw new Error(`render vertices ${renderCount} != WCL1 binding ${cloth.binding.length}`);

// Bind-space edge rests for the stretch metric (render edges, all garment meshes in order).
const bind = [];
const bindEdges = [];
const meshOf = [];
let base = 0;
for (const [mi, mesh] of garmentMeshes.entries()) {
    const pos = mesh.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
        bind.push(pos.getX(i), pos.getY(i), pos.getZ(i));
        meshOf.push([mi, i]);
    }
    const idx = mesh.geometry.index;
    for (let t = 0; t < idx.count; t += 3) {
        for (const [i, j] of [[0, 1], [1, 2], [2, 0]]) {
            const a = base + idx.getX(t + i);
            const b = base + idx.getX(t + j);
            bindEdges.push([a, b, 0]);
        }
    }
    base += pos.count;
}

const report = { template: args.template, node: nodeName, renderVertices: renderCount, particles: cloth.particles, frames: FRAMES, softnessHz: SOFTNESS_HZ, poses: {} };
const fit = {
    template: args.template,
    meshes: garmentMeshes.map((m) => ({ name: m.name, count: m.geometry.attributes.position.count, joints: m.skeleton.bones.map((b) => b.name) })),
    bind,
    meshOf,
    skinIndex: garmentMeshes.flatMap((m) => Array.from(m.geometry.attributes.skinIndex.array)),
    skinWeight: garmentMeshes.flatMap((m) => Array.from(m.geometry.attributes.skinWeight.array)),
    pinnedRender: Array.from(cloth.binding, (p) => (cloth.attachment[p] >= 0.999 ? 1 : 0)),
    poses: {},
};

for (const name of poseNames) {
    applyPose(vrm, name);
    const start = new Float32Array(garmentMeshes.flatMap((m) => Array.from(skinned(m))));
    if (name === poseNames[0]) {
        // Rest lengths of render edges in the first pose (standing), for the stretch ratio.
        for (const e of bindEdges) e[2] = Math.hypot(start[e[0] * 3] - start[e[1] * 3], start[e[0] * 3 + 1] - start[e[1] * 3 + 1], start[e[0] * 3 + 2] - start[e[1] * 3 + 2]);
    }
    const body = bodyMesh(others);
    const { world, render, ms, pinned } = settle(cloth, start, body);
    // The probe gets a world of its own with only her body in it. In the solver's world the
    // projection snapped onto the garment's own surface collider despite the filter, and a
    // dress that was nowhere inside her measured 32 % inside.
    const probeWorld = new RAPIER.World({ x: 0, y: 0, z: 0 });
    const probeBody = probeWorld.createCollider(RAPIER.ColliderDesc.trimesh(body.vertices, body.indices));
    probeWorld.step(); // a fresh world answers no query until its query structure is built
    const probe = depthProbe(probeWorld, probeBody, body);
    report.poses[name] = { skinned: metrics(start, probe, bindEdges), settled: metrics(render, probe, bindEdges), solveMs: Math.round(ms), pinned };
    fit.poses[name] = { target: Array.from(render), skinned: Array.from(start), S: garmentMeshes.map(skinMatrices) };
    console.log(name, JSON.stringify(report.poses[name]));
    world.free();
    probeWorld.free();
}
fs.mkdirSync(new URL('./out/', import.meta.url), { recursive: true });
fs.writeFileSync(args.out, JSON.stringify(fit));
fs.writeFileSync(args.out.replace(/\.json$/, '-report.json'), JSON.stringify(report, null, 2));
console.log('wrote', args.out);
