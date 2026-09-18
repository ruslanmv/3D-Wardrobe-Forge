"""Blender-side pipeline modules.

Every module in this package imports ``bpy`` and can only run inside Blender.
Nothing in :mod:`wardrobe` imports from here — the boundary between the two is
the job spec JSON written by :class:`wardrobe.engines.blender.BlenderEngine`.
"""

__all__ = [
    "import_vrm",
    "analyze_humanoid",
    "normalize_pose",
    "measure_body",
    "import_garment",
    "fit_template",
    "fit_generated_mesh",
    "transfer_weights",
    "resolve_clipping",
    "generate_body_mask",
    "setup_materials",
    "export_vrm",
    "validate_scene",
    "render_turntable",
]
