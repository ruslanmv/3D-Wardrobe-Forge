# Integrating with 3D-Avatar-Chatbot

Target: [`ruslanmv/3D-Avatar-Chatbot`](https://github.com/ruslanmv/3D-Avatar-Chatbot).

The integration is deliberately small, because the chatbot is already
architected around loading a complete VRM. A generated look is just another
`.vrm` URL.

## What the chatbot already provides

`src/gltf-viewer/AvatarManager.js`, reachable as
`window.NEXUS_VIEWER.avatarManager`:

| Member | Use here |
| --- | --- |
| `getCurrent()` → `{ url, name, index }` | snapshot the avatar to derive from |
| `setAvatarByUrl(url, name, index)` | load a generated look |
| `getAvatars()` → `[{ name, file, url }]` | the avatar picker's list |
| `frameAvatar()` | re-frame the camera after a swap |
| `initFromManifest(url)` | parses `avatars.json` |
| `onAvatarChanged` / `onAvatarLoading` / `onAvatarError` | UI hooks |

Wardrobe Forge uses exactly these. **No change to AvatarManager is required.**

## Two classes, nothing else

```js
import { WardrobeClient } from './wardrobe/WardrobeClient.js';
import { WardrobeController } from './wardrobe/WardrobeController.js';

const forge = new WardrobeClient({ baseUrl: WARDROBE_FORGE_URL });

const wardrobe = new WardrobeController({
    forge,
    viewer: window.NEXUS_VIEWER,
});
```

Copy `clients/javascript/*.js` into the chatbot (they are dependency-free ES
modules in the project's existing style).

## Generate and wear a look

```js
const look = await wardrobe.createLook({
    prompt: 'soft black date-night dress',
    apply: true,
});
```

`createLook` snapshots the current avatar, submits the job, follows it to
completion, and — with `apply: true` — loads the result. To separate the steps:

```js
const look = await wardrobe.createLook({ prompt: 'soft black date-night dress' });
await wardrobe.applyLook(look);
await wardrobe.restore();          // back to the original avatar
```

## Progress in the UI

The pipeline reports real states, not a spinner:

```js
const wardrobe = new WardrobeController({
    forge,
    viewer: window.NEXUS_VIEWER,
    onState: (state) => {
        chatUI.setStatus({
            'validating':         'Checking your avatar…',
            'analyzing-avatar':   'Measuring…',
            'planning-outfit':    'Choosing the outfit…',
            'generating-garment': 'Making the garment…',
            'fitting':            'Fitting it to you…',
            'skinning':           'Making it move with you…',
            'resolving-clipping': 'Tidying up the fit…',
            'exporting':          'Finishing…',
            'rendering-preview':  'Taking a photo…',
        }[state] ?? 'Working…');
    },
});
```

It uses Server-Sent Events when the browser supports them and falls back to
polling automatically.

## Try-On Haul

```js
await wardrobe.tryOnHaul([
    'elegant burgundy evening dress',
    'cozy oversized wool coat',
    'slim blue denim jeans',
], {
    holdMs: 5000,
    onLook: (look, index) => chatUI.say(`Look ${index + 1}: ${look.name}`),
});
// returns to the original avatar at the end
```

Strings are generated on the fly; already-generated look objects are worn
directly, so a second haul over the same wardrobe costs nothing.

## Persisting looks between sessions

```js
const looks = await wardrobe.getLooks();   // the wardrobe manifest
await wardrobe.applyLook(looks[1]);
```

To make generated looks appear in the avatar picker alongside the built-in ones:

```js
await wardrobe.mergeIntoAvatarList();
```

That reads `/v1/wardrobes/{avatarId}/avatars.json`, which is emitted in the
exact shape `initFromManifest` parses.

## Passing licence terms

The chatbot's VRM Manager already stores VRoid Hub conditions of use per
installed avatar (`vrm_manager_installed`). Forward them and most licence
questions answer themselves:

```js
const installed = JSON.parse(localStorage.getItem('vrm_manager_installed') || '{}');
const entry = Object.values(installed).find((item) => item.localFile === currentFile);

const look = await wardrobe.createLook({
    prompt,
    conditionsOfUse: entry?.conditionsOfUse,
});
```

Handle the two licence outcomes explicitly:

```js
try {
    await wardrobe.createLook({ prompt, conditionsOfUse });
} catch (error) {
    if (error.modificationForbidden) {
        chatUI.say("This avatar's creator does not allow modified versions.");
    } else if (error.needsLicenseAttestation) {
        const ok = await chatUI.confirm('Do you have permission to modify this avatar?');
        if (ok) await wardrobe.createLook({ prompt, attestModificationAllowed: true });
    } else {
        throw error;
    }
}
```

## Avatars the forge must be able to reach

`createLook` passes the viewer's current avatar URL. If it is served from the
chatbot's own origin, the forge must be able to fetch it — and by default only
`https` and public hosts are allowed, so `http://localhost:5173/...` will be
rejected.

Two options:

1. **Upload once** (recommended). `forge.uploadAvatar(file)` returns a
   `storageKey`; pass that instead of a URL. Nothing needs to be publicly
   reachable and repeat looks skip the download.
2. Relax `ALLOWED_SOURCE_SCHEMES` / `BLOCK_PRIVATE_NETWORKS` in a trusted
   development environment only.

## Deployment shape

```
browser ── chatbot (static) ──► Wardrobe Forge API ──► worker(s)
                │                        │
                └──── loads look.vrm ◄───┘  object storage
```

Set `PUBLIC_BASE_URL` so returned `vrmUrl` values are absolute; otherwise
`WardrobeClient.resolveUrl()` resolves them against its own `baseUrl`.

CORS is permissive by default so the browser can call the API cross-origin —
put authentication in front of it before exposing it publicly.

## What stays stable

The contract is "a prompt in, a normal VRM out". Improving garment generation —
better templates, AI meshes, Blender-side masking — changes nothing in the
chatbot. Try-On Haul written against v0.2 keeps working.
