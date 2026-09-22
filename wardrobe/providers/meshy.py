"""Meshy text-to-3D adapter (experimental).

Flow: submit a `preview` task, poll it, then submit a `refine` task for PBR
textures and poll that. The resulting GLB is raw generated geometry, so it can
only be worn after the Blender engine cleans, retopologises and fits it.
"""

from __future__ import annotations

from wardrobe.config import Settings
from wardrobe.domain.avatars import AvatarAnalysis
from wardrobe.domain.garments import GarmentArtifact, GarmentTemplate
from wardrobe.domain.looks import OutfitPlan
from wardrobe.errors import ProviderError
from wardrobe.providers.base import GarmentProvider
from wardrobe.providers.remote import RemoteMeshClient, RemoteTask, dig

TEXT_TO_3D_PATH = "/openapi/v2/text-to-3d"


def _parse_task(payload: dict) -> RemoteTask:
    body = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    return RemoteTask(
        task_id=str(dig(body, ("id",), ("task_id",), default="")),
        status=str(dig(body, ("status",), ("state",), default="pending")),
        progress=float(dig(body, ("progress",), default=0.0) or 0.0),
        model_url=dig(body, ("model_urls", "glb"), ("model_url",), ("model_urls", "gltf")),
        raw=body if isinstance(body, dict) else None,
    )


def _submitted_id(payload: dict) -> str:
    task_id = dig(payload, ("result",), ("id",), ("task_id",), ("data", "task_id"))
    if isinstance(task_id, dict):
        task_id = task_id.get("id") or task_id.get("task_id")
    if not task_id:
        raise ProviderError("meshy: submit response contained no task id", detail={"payload": payload})
    return str(task_id)


class MeshyProvider(GarmentProvider):
    name = "meshy"
    produces_raw_mesh = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = RemoteMeshClient(
            base_url=settings.meshy_base_url,
            api_key=settings.meshy_api_key,
            provider=self.name,
            timeout_s=settings.provider_timeout_s,
        )

    def build_prompt(self, plan: OutfitPlan) -> str:
        """A garment-only prompt: a body in the mesh would break fitting."""
        pieces = [plan.material.color_name or "", plan.material.fabric or "", plan.silhouette, plan.category]
        described = " ".join(p for p in pieces if p).strip()
        return (
            f"a single {described}, clothing item only, no person, no mannequin, "
            "no head, no limbs, T-pose friendly, clean topology, centered, neutral lighting"
        )

    async def create(
        self,
        plan: OutfitPlan,
        *,
        template: GarmentTemplate | None = None,
        analysis: AvatarAnalysis | None = None,
    ) -> GarmentArtifact:
        prompt = self.build_prompt(plan)

        preview_id = _submitted_id(
            await self.client.post_json(
                TEXT_TO_3D_PATH,
                {"mode": "preview", "prompt": prompt, "art_style": "realistic", "should_remesh": True},
            )
        )
        await self.client.poll(lambda: f"{TEXT_TO_3D_PATH}/{preview_id}", _parse_task)

        refine_id = _submitted_id(
            await self.client.post_json(
                TEXT_TO_3D_PATH,
                {"mode": "refine", "preview_task_id": preview_id, "enable_pbr": True},
            )
        )
        task = await self.client.poll(lambda: f"{TEXT_TO_3D_PATH}/{refine_id}", _parse_task)

        if not task.model_url:
            raise ProviderError("meshy: finished task exposed no GLB url", detail={"task": task.raw or {}})

        return GarmentArtifact(
            id=f"garment_meshy_{refine_id[:16]}",
            source=self.name,
            templateId=template.id if template else plan.template_id,
            meshPath=task.model_url,
            coverage=list(template.coverage) if template else [],
            anchors=list(template.anchors) if template else [],
            material=plan.material.to_dict(),
            metadata={
                "prompt": prompt,
                "previewTaskId": preview_id,
                "refineTaskId": refine_id,
                "requiresCleanup": True,
                "requiresBlender": True,
            },
        )

    async def download_mesh(self, artifact: GarmentArtifact) -> bytes:
        if not artifact.mesh_path:
            raise ProviderError("meshy: artifact has no mesh url to download")
        return await self.client.download(artifact.mesh_path)

    async def aclose(self) -> None:
        await self.client.aclose()


__all__ = ["MeshyProvider"]
