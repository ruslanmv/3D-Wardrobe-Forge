"""Tripo text-to-model adapter (experimental).

Tripo's task API wraps its payload in ``{"code": 0, "data": {...}}``, so the
extraction differs from Meshy's while the submit/poll/download shape is the
same.
"""

from __future__ import annotations

from wardrobe.config import Settings
from wardrobe.domain.avatars import AvatarAnalysis
from wardrobe.domain.garments import GarmentArtifact, GarmentTemplate
from wardrobe.domain.looks import OutfitPlan
from wardrobe.errors import ProviderError
from wardrobe.providers.base import GarmentProvider
from wardrobe.providers.remote import RemoteMeshClient, RemoteTask, dig

TASK_PATH = "/v2/openapi/task"


def _parse_task(payload: dict) -> RemoteTask:
    if payload.get("code") not in (0, None):
        raise ProviderError(
            f"tripo: API returned code {payload.get('code')}",
            detail={"message": str(payload.get("message"))[:300]},
        )
    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    model_url = dig(
        body,
        ("output", "pbr_model"),
        ("output", "model"),
        ("output", "base_model"),
        ("result", "pbr_model", "url"),
        ("result", "model", "url"),
    )
    if isinstance(model_url, dict):
        model_url = model_url.get("url")
    return RemoteTask(
        task_id=str(dig(body, ("task_id",), ("id",), default="")),
        status=str(dig(body, ("status",), ("state",), default="pending")),
        progress=float(dig(body, ("progress",), default=0.0) or 0.0),
        model_url=model_url,
        raw=body if isinstance(body, dict) else None,
    )


class TripoProvider(GarmentProvider):
    name = "tripo"
    produces_raw_mesh = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = RemoteMeshClient(
            base_url=settings.tripo_base_url,
            api_key=settings.tripo_api_key,
            provider=self.name,
            timeout_s=settings.provider_timeout_s,
        )

    def build_prompt(self, plan: OutfitPlan) -> str:
        pieces = [plan.material.color_name or "", plan.material.fabric or "", plan.silhouette, plan.category]
        described = " ".join(p for p in pieces if p).strip()
        return (
            f"a single {described}, garment only, no character, no mannequin, "
            "symmetrical, clean quad topology, centered at origin"
        )

    async def create(
        self,
        plan: OutfitPlan,
        *,
        template: GarmentTemplate | None = None,
        analysis: AvatarAnalysis | None = None,
    ) -> GarmentArtifact:
        prompt = self.build_prompt(plan)
        submitted = await self.client.post_json(
            TASK_PATH, {"type": "text_to_model", "prompt": prompt, "texture": True, "pbr": True}
        )
        task_id = dig(submitted, ("data", "task_id"), ("task_id",), ("data", "id"))
        if not task_id:
            raise ProviderError("tripo: submit response contained no task id", detail={"payload": submitted})
        task_id = str(task_id)

        task = await self.client.poll(lambda: f"{TASK_PATH}/{task_id}", _parse_task)
        if not task.model_url:
            raise ProviderError("tripo: finished task exposed no model url", detail={"task": task.raw or {}})

        return GarmentArtifact(
            id=f"garment_tripo_{task_id[:16]}",
            source=self.name,
            templateId=template.id if template else plan.template_id,
            meshPath=task.model_url,
            coverage=list(template.coverage) if template else [],
            anchors=list(template.anchors) if template else [],
            material=plan.material.to_dict(),
            metadata={
                "prompt": prompt,
                "taskId": task_id,
                "requiresCleanup": True,
                "requiresBlender": True,
            },
        )

    async def download_mesh(self, artifact: GarmentArtifact) -> bytes:
        if not artifact.mesh_path:
            raise ProviderError("tripo: artifact has no mesh url to download")
        return await self.client.download(artifact.mesh_path)

    async def aclose(self) -> None:
        await self.client.aclose()


__all__ = ["TripoProvider"]
