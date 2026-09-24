/**
 * The Studio viewport: two VRM slots, one camera.
 *
 * `original` holds the library avatar and `look` holds a generated variant. The
 * three view modes are just which slots are visible and where they stand, so
 * switching between them never reloads a model — and side-by-side puts the same
 * body in two outfits under the same light, which is the comparison the fit
 * report can only describe in numbers.
 *
 * Pose is a real editing aid, not decoration. Garments are fitted in the rest
 * pose (arms out), but people judge clothes on a figure with its arms down, and
 * clipping under the arm only shows in one of the two. So the default is relaxed
 * and the toolbar can put her back in the rest pose to inspect the fit.
 *
 * Every load carries a token. Clicking three looks quickly starts three loads;
 * only the last one to be requested may land, and the others dispose themselves
 * on arrival rather than flashing onto the stage out of order.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

// Normalized-bone rotations (radians), written for VRM 0.x. A VRM 0.x model faces
// -Z, so its left arm lies along -X and lowering it is a positive roll about Z.
// VRM 1.0 faces +Z, its left arm lies along +X, and the same roll raises it — so
// applyPose() flips the sign for 1.0. Without that, every VRM 1.0 upload stood
// with both arms over its head.
const RELAXED = {
    leftUpperArm: [0, 0, 1.18],
    rightUpperArm: [0, 0, -1.18],
    leftLowerArm: [0, 0.18, 0],
    rightLowerArm: [0, -0.18, 0],
};
const COMPARE_GAP = 0.62; // metres between the two figures' centres, per side

export class Viewer {
    constructor(container) {
        this.container = container;
        this.slots = { original: null, look: null };
        this.tokens = { original: 0, look: 0 };
        this.mode = 'original';
        this.pose = 'relaxed';

        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
        container.appendChild(this.renderer.domElement);

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(28, 1, 0.05, 50);
        this.camera.position.set(0, 1.3, 4);

        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.controls.minDistance = 0.6;
        this.controls.maxDistance = 9;
        this.controls.autoRotateSpeed = 1.4;
        this.controls.target.set(0, 1, 0);

        // MToon shades from the scene's lights, not from an environment map.
        const key = new THREE.DirectionalLight(0xfff4ec, 2.1);
        key.position.set(1.2, 2.4, 2.2);
        const rim = new THREE.DirectionalLight(0xe8c8ff, 0.9);
        rim.position.set(-1.8, 1.6, -2.4);
        this.scene.add(key, rim, new THREE.HemisphereLight(0xfff6f0, 0x3a2f33, 1.0));

        this.shadowTexture = makeShadowTexture();
        this.loader = new GLTFLoader();
        this.loader.register((parser) => new VRMLoaderPlugin(parser));
        this.clock = new THREE.Clock();

        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(container);
        this.resize();
        this.renderer.setAnimationLoop(() => this.tick());
    }

    resize() {
        const { clientWidth: width, clientHeight: height } = this.container;
        if (!width || !height) return;
        this.renderer.setSize(width, height, false);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
    }

    tick() {
        const delta = Math.min(this.clock.getDelta(), 0.1);
        for (const slot of Object.values(this.slots)) if (slot) slot.vrm.update(delta);
        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    /** Load a VRM into a slot. Resolves true when it landed, false when superseded. */
    async load(slotName, url) {
        const token = ++this.tokens[slotName];
        const gltf = await this.loader.loadAsync(url);
        const vrm = gltf.userData.vrm;
        if (!vrm) throw new Error('This file is not a VRM');

        VRMUtils.removeUnnecessaryVertices(gltf.scene);
        (VRMUtils.combineSkeletons || VRMUtils.removeUnnecessaryJoints)?.call(VRMUtils, gltf.scene);
        VRMUtils.rotateVRM0(vrm);
        vrm.scene.traverse((object) => {
            object.frustumCulled = false; // skinned bounds are the rest pose's, not the drawn one
        });

        if (token !== this.tokens[slotName]) {
            VRMUtils.deepDispose(vrm.scene);
            return false;
        }

        this.clear(slotName, { keepToken: true });
        const group = new THREE.Group();
        group.add(vrm.scene, this.makeShadow());
        this.scene.add(group);
        this.slots[slotName] = { vrm, group };
        this.applyPose(vrm);
        this.layout();
        return true;
    }

    clear(slotName, { keepToken = false } = {}) {
        if (!keepToken) this.tokens[slotName] += 1; // anything in flight for this slot is now stale
        const slot = this.slots[slotName];
        if (!slot) return;
        this.scene.remove(slot.group);
        VRMUtils.deepDispose(slot.vrm.scene);
        this.slots[slotName] = null;
        this.layout();
    }

    has(slotName) {
        return Boolean(this.slots[slotName]);
    }

    setMode(mode) {
        this.mode = mode;
        this.layout();
        this.frame();
    }

    setPose(pose) {
        this.pose = pose;
        for (const slot of Object.values(this.slots)) if (slot) this.applyPose(slot.vrm);
    }

    setTurntable(on) {
        this.controls.autoRotate = Boolean(on);
    }

    applyPose(vrm) {
        const humanoid = vrm.humanoid;
        if (!humanoid) return;
        const sign = vrm.meta && vrm.meta.metaVersion === '1' ? -1 : 1;
        for (const [bone, [x, y, z]] of Object.entries(RELAXED)) {
            const node = humanoid.getNormalizedBoneNode(bone);
            if (!node) continue;
            if (this.pose === 'relaxed') node.rotation.set(x, y * sign, z * sign);
            else node.rotation.set(0, 0, 0);
        }
    }

    layout() {
        const { original, look } = this.slots;
        const compare = this.mode === 'compare' && original && look;
        if (original) {
            original.group.visible = this.mode !== 'look' || !look;
            original.group.position.x = compare ? -COMPARE_GAP : 0;
        }
        if (look) {
            look.group.visible = this.mode !== 'original';
            look.group.position.x = compare ? COMPARE_GAP : 0;
        }
    }

    /** Fit whatever is visible into the frame, head to toe. */
    frame() {
        const box = new THREE.Box3();
        for (const slot of Object.values(this.slots)) {
            if (slot && slot.group.visible) box.expandByObject(slot.vrm.scene);
        }
        if (box.isEmpty()) return;
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const fov = THREE.MathUtils.degToRad(this.camera.fov);
        const byHeight = size.y / 2 / Math.tan(fov / 2);
        const byWidth = size.x / 2 / Math.tan(fov / 2) / Math.max(this.camera.aspect, 0.2);
        // A tall, narrow viewport (a phone) has the view controls across its top, so
        // it gets more headroom and a target nudged up to put her head below them.
        const narrow = this.camera.aspect < 0.9;
        const distance = Math.max(byHeight, byWidth) * (narrow ? 1.34 : 1.18) + size.z;
        if (narrow) center.y += size.y * 0.05;
        this.controls.target.copy(center);
        this.camera.position.set(center.x, center.y + size.y * 0.04, center.z + distance);
        this.camera.near = Math.max(distance / 100, 0.01);
        this.camera.far = distance * 10;
        this.camera.updateProjectionMatrix();
        this.controls.update();
    }

    makeShadow() {
        const shadow = new THREE.Mesh(
            new THREE.CircleGeometry(0.42, 48),
            new THREE.MeshBasicMaterial({ map: this.shadowTexture, transparent: true, depthWrite: false })
        );
        shadow.rotation.x = -Math.PI / 2;
        shadow.position.y = 0.002;
        return shadow;
    }

    /** A still of the current view, for a thumbnail or a bug report. */
    snapshot() {
        return this.renderer.domElement.toDataURL('image/png');
    }
}

function makeShadowTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 128;
    const context = canvas.getContext('2d');
    const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
    gradient.addColorStop(0, 'rgba(0,0,0,0.5)');
    gradient.addColorStop(1, 'rgba(0,0,0,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, 128, 128);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
}
