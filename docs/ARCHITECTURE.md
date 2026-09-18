# Architecture

Wardrobe Forge is a separate service because Blender/3D processing is a worker workload, not a browser concern.

## Boundary

The consuming avatar application sends:
- an authorized VRM reference;
- avatar hash / source metadata;
- licensing metadata;
- an outfit prompt.

Wardrobe Forge returns:
- a derived VRM variant;
- preview;
- fit report;
- wardrobe metadata.

## Reliability principle

A generated output is publishable only after:
1. export;
2. re-import;
3. humanoid validation;
4. deformation/weight checks;
5. clipping quality checks;
6. preview render.
