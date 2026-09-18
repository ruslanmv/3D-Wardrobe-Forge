from pydantic import BaseModel, Field


class GarmentTemplate(BaseModel):
    id: str
    name: str
    category: str
    mesh: str
    coverage: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    body_clearance_mm: float = 6.0
    metadata: dict = Field(default_factory=dict)


class GarmentArtifact(BaseModel):
    id: str
    source: str
    mesh_path: str
    material_metadata: dict = Field(default_factory=dict)
