"""Avatar-side domain models: inputs, license attestation, analysis results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

#: VRoid Hub "conditions of use" keys, exactly as 3D-Avatar-Chatbot's VRM
#: Manager stores them. Accepting this shape verbatim means the chatbot can
#: forward what it already has without translating anything.
VROID_CONDITION_KEYS = (
    "avatarUse",
    "violentExpression",
    "sexualExpression",
    "corporateCommercialUse",
    "personalCommercialUse",
    "redistribution",
    "modification",
    "credit",
)


class LicenseAttestation(BaseModel):
    """What the caller asserts about the source model's usage terms.

    This supplements — never overrides — the terms embedded in the VRM itself.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: VRoid Hub conditions-of-use object, if the caller has one.
    conditions_of_use: dict[str, str] = Field(default_factory=dict, alias="conditionsOfUse")
    #: Set when the caller takes responsibility for terms we cannot read.
    user_attests_modification_allowed: bool = Field(default=False, alias="userAttestsModificationAllowed")
    source: str | None = None
    note: str | None = None


class AvatarInput(BaseModel):
    """Where the source VRM comes from and what we are allowed to do with it."""

    model_config = ConfigDict(populate_by_name=True)

    url: HttpUrl | None = None
    #: Alternative to ``url`` for local/CLI use and for previously uploaded assets.
    storage_key: str | None = Field(default=None, alias="storageKey")
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    avatar_id: str | None = Field(default=None, alias="avatarId")
    name: str | None = None
    license: LicenseAttestation = Field(default_factory=LicenseAttestation)

    @model_validator(mode="after")
    def _require_a_source(self) -> AvatarInput:
        if self.url is None and self.storage_key is None:
            raise ValueError("avatar requires either 'url' or 'storageKey'")
        return self

    @property
    def reference(self) -> str:
        return str(self.url) if self.url is not None else f"storage://{self.storage_key}"


class AvatarAnalysis(BaseModel):
    """Everything the pipeline learned about the source avatar."""

    model_config = ConfigDict(populate_by_name=True)

    spec: str
    title: str | None = None
    humanoid_bones: dict[str, int] = Field(default_factory=dict, alias="humanoidBones")
    measurements: dict = Field(default_factory=dict)
    license: dict = Field(default_factory=dict)
    expressions: list[str] = Field(default_factory=list)
    mesh_count: int = Field(default=0, alias="meshCount")
    material_count: int = Field(default=0, alias="materialCount")
    sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)


__all__ = ["VROID_CONDITION_KEYS", "LicenseAttestation", "AvatarInput", "AvatarAnalysis"]
