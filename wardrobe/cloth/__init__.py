"""The cloth asset a runtime is allowed to simulate.

The solver does not invent seams or a seated drape. Forge records what the mesh
actually contains, and a look still exports when that record says "do not simulate".
"""

from wardrobe.cloth.asset import ClothAsset, ClothAssetRejected, compile_cloth_asset

__all__ = ["ClothAsset", "ClothAssetRejected", "compile_cloth_asset"]
