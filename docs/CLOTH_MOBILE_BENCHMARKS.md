# Cloth export cost

Forge does not draw a frame. There is no phone measurement in this repository.
The viewer timings are in 3D-Avatar-Chatbot `docs/CLOTH_MOBILE_BENCHMARKS.md`.

Measured on the cloud agent VM while compiling one straight mini skirt
(792 render vertices, 768 simulation particles, three LOD records):

| Step | Time |
|---|---|
| `compile_cloth_asset` | 0.25 s |
| Payload | 154 KB |

The 200-particle and 500-particle LODs are edge collapses that leave boundary
and fully attached vertices in place. `mobile-low` is recorded as skinning and
adds no mesh. This is one cold export, not a sustained thermal run, and it is
not a frame time.
