# Fixtures

Generated VRM avatars for testing and local development. **This directory is
intentionally empty of binaries** — the files are produced on demand:

```bash
wardrobe-forge fixtures --out assets/fixtures
```

That writes eight avatars: each of the four
[calibration bodies](../calibration/README.md) in both VRM 0.x and VRM 1.0.

```
calibration-a-petite-vrm0.vrm   calibration-a-petite-vrm1.vrm
calibration-b-medium-vrm0.vrm   calibration-b-medium-vrm1.vrm
calibration-c-tall-vrm0.vrm     calibration-c-tall-vrm1.vrm
calibration-d-broad-vrm0.vrm    calibration-d-broad-vrm1.vrm
```

Each is a complete, valid VRM: a 22-bone humanoid rig, a skinned body mesh,
expression presets and licence metadata. They open in any VRM viewer.

## Why generated rather than checked in

- no third-party model is redistributed, so there is no licence exception to
  manage in a repository that is itself about respecting licences
- no binary weight in git
- the bodies stay in sync with `CALIBRATION_BODIES`; they cannot drift
- CI needs no asset download step

The test suite builds them in memory (`tests/conftest.py`), so `pytest` works
on a clean checkout with nothing in this directory.

## Using a real avatar instead

Generated fixtures verify the pipeline's correctness, not how a garment looks
on a production VRoid model. For that, check a real file first:

```bash
wardrobe-forge inspect --avatar path/to/avatar.vrm
```

It reports the spec, humanoid map, measurements and any issues, and exits
non-zero if the model would be rejected. Drop real avatars here if you like —
`*.vrm` is gitignored.
