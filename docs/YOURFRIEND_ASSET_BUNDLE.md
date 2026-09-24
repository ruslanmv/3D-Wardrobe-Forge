# yourfriend.online asset bundle

3D-Wardrobe-Forge has two delivery modes that share the same wardrobe pipeline:

1. **Static asset mode (default)** packages generated looks for direct deployment with `yourfriend.online`.
2. **Hosted mode** exposes the same generation pipeline over HTTP for on-demand looks.

The generated VRM is the product in both modes. Consumers do not need Blender, provider credentials, or knowledge of fitting internals.

## Bundle layout

```text
dist/yourfriend-online/
├── wardrobe.json
├── avatars.json
├── catalog.json
├── provenance.json
└── looks/
    └── <avatar-id>/
        └── <look-id>/
            ├── look.vrm
            ├── preview.webp
            ├── fit-report.json
            └── look.json
```

`wardrobe.json` is the rich Forge manifest. `avatars.json` is emitted in the shape consumed by 3D-Avatar-Chatbot's AvatarManager. `catalog.json` is a lightweight entry point.

Static bundles always contain relative URLs so the complete directory can be copied to any static host without rewriting manifests. Hosted deployments continue to return absolute or signed artifact URLs through the existing object-store layer.

## Contract

A packaged look MUST contain a validated VRM, preserve the Forge look identifier and source avatar identity, include a fit report when available, resolve all emitted URLs inside the bundle, and include generator provenance.

The static packager is a delivery layer only. It MUST NOT contain geometry, fitting, provider, or Blender logic.

## Default CLI behavior

```bash
wardrobe-forge create \
  --avatar mira.vrm \
  --prompt "burgundy evening dress"
```

writes to `dist/yourfriend-online/` by default.

Use `--target generic` for the legacy flat output layout, or `--out` to select another destination.

## Hosted compatibility

The hosted API and static bundle describe the same canonical `LookResult`. A client can therefore load a pre-generated look and a remotely generated look through the same AvatarManager path.
