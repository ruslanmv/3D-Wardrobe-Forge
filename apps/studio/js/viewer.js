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
 *
 * OC2. Compare is two viewports, not two positions. It used to stand the original and the
 * look 0.62 m either side of the origin along world X and orbit one camera round both. From
 * the front that is side by side; from her side, or from underneath, the X separation turns
 * into depth and one figure stands inside the other — the original's jacket through the new
 * dress, which reads as one broken outfit when nothing is wrong with either. Now both stand
 * at the origin and each frame is drawn twice, the original into the left half of the canvas
 * and the look into the right, through the same camera at half the aspect. They can no longer
 * overlap from any angle, and turning one turns the other the same way, which is the
 * comparison. Compare also keeps the camera within 5° of level, as Front/Side/Back do: a
 * view from beneath is for inspecting one garment, in Look.
 *
 * SV1. The camera is an inspection camera, on a phone as on a desk: one finger turns
 * her, a pinch zooms toward the fingers, two fingers pan, a double tap puts the shot back.
 * Front, side and back are the same shot from three places (inspect()), and keep the camera
 * within 5° of level while they are chosen, so a preset never opens on a view from beneath.
 * Free — and the Studio outside full screen — orbits all the way round, under the hem too:
 * the full freedom the viewer had before SV1, which the person inspecting a garment needs.
 * The point it orbits cannot be dragged off her figure, so a stray pan never leaves an
 * empty screen.
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
// SV1. The orbit's limits from straight overhead for the Front, Side and Back presets: never
// quite overhead (the controls spin about the pole there), and at most 5° under level.
const MIN_POLAR = THREE.MathUtils.degToRad(8);
const MAX_POLAR = THREE.MathUtils.degToRad(95);
// SV2. Free, and the Studio outside full screen: over the top and right underneath her, for
// QA of a hem, the underside of a garment and clipping. SV1 put the presets' limit on every
// view and took that away. One degree short of each pole, not on it: at the pole the orbit's
// "up" is undefined and the camera can flip or spin about its own axis as it crosses.
const FREE_MIN_POLAR = THREE.MathUtils.degToRad(1);
const FREE_MAX_POLAR = THREE.MathUtils.degToRad(179);
// The inspection views: her own front, her left side and her back (see turnTo()).
const INSPECT_FACING = { front: 'front', side: 'left', back: 'back' };
// A tap is a press that neither moved nor lasted; two of them close together are a double tap.
const TAP_MS = 260;
const TAP_SLOP_PX = 10;
const DOUBLE_TAP_MS = 400; // phones' own double-tap windows run 300–500 ms
const DOUBLE_TAP_PX = 32;

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
        this.controls.enablePan = true;
        this.controls.screenSpacePanning = true;
        this.orbitFor('free');
        this.controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
        // A pinch over the hem zooms onto the hem, not onto her middle.
        this.controls.zoomToCursor = true;
        // What the visible figures fill, from the last frame(): the orbit's target stays inside.
        this.bounds = null;
        // The view inspect() last chose: a double tap returns to it. 'free' returns to the front.
        this.view = 'free';
        // Full screen inspection (app.js) has no controls across the top to keep her head under.
        this.immersive = false;
        // Called on a single tap and on a double tap of the canvas (after the reset).
        this.onTap = null;
        this.onDoubleTap = null;
        this.watchTaps(this.renderer.domElement);

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
        // OC2. In Compare each figure gets half the canvas, so the camera frames for half.
        this.camera.aspect = width / height / (this.comparing() ? 2 : 1);
        this.camera.updateProjectionMatrix();
    }

    /** OC2. Compare, with both figures loaded: the frame is drawn as two halves. */
    comparing() {
        return this.mode === 'compare' && Boolean(this.slots.original && this.slots.look);
    }

    tick() {
        const delta = Math.min(this.clock.getDelta(), 0.1);
        for (const slot of Object.values(this.slots)) if (slot) slot.vrm.update(delta);
        this.controls.update();
        this.keepTargetOnHer();
        if (!this.comparing()) {
            this.renderer.render(this.scene, this.camera);
            return;
        }
        // OC2. The original on the left half, the look on the right, through one camera.
        const size = this.renderer.getSize(new THREE.Vector2());
        const half = Math.floor(size.x / 2);
        const { original, look } = this.slots;
        this.renderer.setScissorTest(true);
        for (const [shown, hidden, x, width] of [
            [original, look, 0, half],
            [look, original, half, size.x - half],
        ]) {
            shown.group.visible = true;
            hidden.group.visible = false;
            this.renderer.setViewport(x, 0, width, size.y);
            this.renderer.setScissor(x, 0, width, size.y);
            this.renderer.render(this.scene, this.camera);
        }
        this.renderer.setScissorTest(false);
        this.renderer.setViewport(0, 0, size.x, size.y);
        original.group.visible = look.group.visible = true;
    }

    /**
     * SV1. Pull the orbit's target back inside her figure, moving the camera with it.
     * Two-finger pan moves both; without this a pan could carry the target under the floor
     * or off to one side, and every turn after it swung the camera round empty space.
     */
    keepTargetOnHer() {
        if (!this.bounds) return;
        const target = this.controls.target;
        const { min, max } = this.bounds;
        const margin = 0.15;
        const clamped = target.clone();
        clamped.x = THREE.MathUtils.clamp(clamped.x, min.x - margin, max.x + margin);
        clamped.y = THREE.MathUtils.clamp(clamped.y, min.y + (max.y - min.y) * 0.08, max.y);
        clamped.z = THREE.MathUtils.clamp(clamped.z, min.z - margin, max.z + margin);
        if (clamped.distanceToSquared(target) < 1e-10) return;
        const shift = clamped.sub(target);
        target.add(shift);
        this.camera.position.add(shift);
    }

    /**
     * SV1. Taps on the canvas, told apart from drags. OrbitControls owns every drag, so this
     * only listens: a press that did not move and did not linger is a tap, and a second one
     * soon after and near the first is a double tap, which resets the shot.
     */
    watchTaps(element) {
        const presses = new Map();
        let lastTap = null;
        element.addEventListener('pointerdown', (event) => {
            presses.set(event.pointerId, { x: event.clientX, y: event.clientY, at: event.timeStamp, multi: presses.size > 0 });
            if (presses.size > 1) for (const press of presses.values()) press.multi = true;
        });
        const release = (event) => {
            const press = presses.get(event.pointerId);
            presses.delete(event.pointerId);
            if (!press || press.multi || event.type === 'pointercancel') return;
            const moved = Math.hypot(event.clientX - press.x, event.clientY - press.y);
            if (moved > TAP_SLOP_PX || event.timeStamp - press.at > TAP_MS) return;
            const double =
                lastTap &&
                event.timeStamp - lastTap.at < DOUBLE_TAP_MS &&
                Math.hypot(event.clientX - lastTap.x, event.clientY - lastTap.y) < DOUBLE_TAP_PX;
            if (double) {
                lastTap = null;
                this.reset();
                this.onDoubleTap?.();
                return;
            }
            lastTap = { x: event.clientX, y: event.clientY, at: event.timeStamp };
            this.onTap?.();
        };
        element.addEventListener('pointerup', release);
        element.addEventListener('pointercancel', release);
    }

    /**
     * SV1. Garment inspection: frame her, then look from her front, her left side or her
     * back. 'free' keeps the camera where it is and only stops the turntable, so the person
     * can take it from there.
     */
    inspect(view = 'front') {
        this.view = view;
        this.controls.autoRotate = false;
        this.orbitFor(view);
        if (view === 'free') return;
        this.frame();
        this.turnTo(INSPECT_FACING[view] || 'front');
    }

    /** The shot a double tap returns to: the chosen inspection view, else the front, framed. */
    reset() {
        const view = this.view;
        this.inspect(view === 'free' ? 'front' : view);
        this.view = view; // a reset from Free is still Free: the bar keeps showing the person's choice
        this.orbitFor(view); // and so is its orbit
    }

    /** SV2. The orbit a view allows: near level for Front, Side and Back; the whole sphere for Free. */
    orbitFor(view) {
        const free = view === 'free' && !this.comparing();
        this.controls.minPolarAngle = free ? FREE_MIN_POLAR : MIN_POLAR;
        this.controls.maxPolarAngle = free ? FREE_MAX_POLAR : MAX_POLAR;
        this.controls.update();
    }

    /** The camera's angle down from straight overhead, in degrees (90 is level, 180 beneath). */
    polarDegrees() {
        return THREE.MathUtils.radToDeg(this.controls.getPolarAngle());
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
        // OC2. Into Compare from the front, level; out of it, the view's own orbit again.
        this.orbitFor(this.view);
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
        // OC2. Both stand at the origin in every mode; Compare separates them on screen (tick()).
        if (original) original.group.visible = this.mode !== 'look' || !look;
        if (look) look.group.visible = this.mode !== 'original';
        this.resize(); // a slot filled or emptied in Compare changes the frame's aspect
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
        const narrow = this.camera.aspect < 0.9 && !this.immersive;
        // Full screen: tight in portrait, where she is the whole height; roomier on a phone on
        // its side, where the inspection bar crosses her feet until it fades.
        const fill = this.immersive ? (this.camera.aspect < 0.9 ? 1.1 : 1.24) : narrow ? 1.34 : 1.18;
        const distance = Math.max(byHeight, byWidth) * fill + size.z;
        if (narrow) center.y += size.y * 0.05;
        this.bounds = box.clone();
        this.controls.target.copy(center);
        this.camera.position.set(center.x, center.y + size.y * 0.04, center.z + distance);
        this.camera.near = Math.max(distance / 100, 0.01);
        this.camera.far = distance * 10;
        this.camera.updateProjectionMatrix();
        this.controls.update();
    }

    /**
     * BA7. Swing the camera round her to look at one side of her: "front", "back", "left"
     * or "right" (hers). Distance and height are kept, so it is the same shot from
     * elsewhere. Every VRM here faces +Z once loaded — load() runs rotateVRM0 on 0.x
     * models — so her back is seen from -Z, and her left side (+X) from +X.
     */
    turnTo(facing = 'front') {
        const yaw = { front: 0, back: Math.PI, left: Math.PI / 2, right: -Math.PI / 2 }[facing] ?? 0;
        const target = this.controls.target;
        const offset = this.camera.position.clone().sub(target);
        const flat = Math.hypot(offset.x, offset.z);
        this.controls.autoRotate = false;
        this.camera.position.set(target.x + Math.sin(yaw) * flat, this.camera.position.y, target.z + Math.cos(yaw) * flat);
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
