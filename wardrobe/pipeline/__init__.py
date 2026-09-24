"""Pipeline stages, in the order the orchestrator runs them.

    validate_source -> analyze_avatar -> plan (plan_outfit_stack) -> prepare_base_body
                    -> generate_garment -> fit_garment -> assemble_vrm
                    -> validate_output -> render_preview

The stage modules are deliberately *not* imported here. They depend on
``wardrobe.engines``, whose own modules import :mod:`wardrobe.pipeline.context`
— eager imports in this file would close that loop. Import the stages directly
(``from wardrobe.pipeline import validate_source``), which is what the
orchestrator does.
"""

__all__ = [
    "context",
    "orchestrator",
    "validate_source",
    "analyze_avatar",
    "plan_outfit",
    "plan_outfit_stack",
    "prepare_base_body",
    "generate_garment",
    "fit_garment",
    "assemble_vrm",
    "validate_output",
    "render_preview",
]
