"""Build outfits from the outfit dictionary end to end over a reference body — sandbox only.

    .venv/bin/python tools/body_surface/build_outfits.py --body <ref.vrm> --out <dir> \\
        [--prefix show-] [--ids show-table-lace-body,show-strip-red]

Each outfit is a real job through the orchestrator (native engine, template mode, bare-dressed
base), exactly as a request from the chatbot would run, and its look is written to
``<out>/<id>.vrm`` with ``<out>/results.json`` (state, reason, seconds). Then look at them in the
chatbot's own viewer, head to heels:

    node tools/qa/body-detail-render.mjs --vrm <out>/<id>.vrm --views full,fullback     # in the chatbot

The reference body's exact bytes are cleared in a temporary copy of the review registry, as the
integration tests do; nothing is written to the committed registry. Use the synthetic reference
(``tools/body_surface/detail_preview.py`` writes one); ``ref-atlas.vrm`` is over the size limit,
the plain one is not.

VA4 lessons, so the next run does not repeat them:

- One job at a time, and when a build is killed for memory, build that id alone
  (``--ids <id>``): the red lace bodysuit asked for 9.4 GiB in ``lingerie/fit.py`` before that was
  fixed, and the kernel killed the whole run without a line in the log.
- A look that builds is not a look that fits: render it. Denim shorts with a bralette built fine
  and rode up over the band, with a loop hanging at the thigh.

Outputs are private: never commit them.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.conftest import TEMPLATE_ROOT, clear_design_for_test  # noqa: E402
from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.pipeline import outfit_dictionary as od  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402


async def main(body_path: Path, out: Path, prefix: str, only: set[str], base: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        wardrobe_storage_root=str(out / "storage"),
        wardrobe_job_backend="memory",
        wardrobe_engine="native",
        wardrobe_provider="template",
        wardrobe_template_root=str(TEMPLATE_ROOT),
        strict_licensing=True,
        public_base_url="",
        wardrobe_adult_body_surface=True,
        wardrobe_bare_body_completion=False,
    )
    store = LocalObjectStore(settings.storage_root_path, settings)
    body = body_path.read_bytes()
    clear_design_for_test(settings, body)
    await store.put("sources/ref.vrm", body)
    orch = Orchestrator(
        settings=settings,
        store=store,
        jobs=InMemoryJobRepository(),
        wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(TEMPLATE_ROOT),
    )
    wanted = [o for o in od.OUTFITS if (o.id in only if only else o.id.startswith(prefix))]
    if not wanted:
        raise SystemExit("no outfit matches")
    results = []
    for o in wanted:
        payload = {
            "avatar": {"storageKey": "sources/ref.vrm", "avatarId": "ref", "depictsAdult": True},
            "outfit": o.request().model_dump(by_alias=True, exclude_none=True) | {"mode": "template"},
            "options": {"renderPreview": False, "engine": "native", "baseBody": base, "private": True},
        }
        t0 = time.time()
        try:
            r = await orch.run_now(CreateJobRequest.model_validate(payload))
            state = r.state.value
            why = getattr(r, "reason", None) or getattr(r, "error", None)
            look = r.look.id if getattr(r, "look", None) else None
            if look:
                (out / f"{o.id}.vrm").write_bytes(await store.get(f"looks/{look}/look.vrm"))
        except Exception as e:  # report and go on: one outfit must not stop the others
            state, why = "error", str(e)[:200]
        seconds = round(time.time() - t0, 1)
        why = str(why)[:200] if why else None
        results.append({"id": o.id, "state": state, "why": why, "seconds": seconds})
        print(json.dumps(results[-1]), flush=True)
    (out / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--body", required=True, type=Path, help="reference body VRM (synthetic adult)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--prefix", default="show-", help="outfit ids with this prefix (default: the show looks)")
    ap.add_argument("--ids", default="", help="comma-separated outfit ids (overrides --prefix)")
    ap.add_argument("--base", default="bare-dressed", help="options.baseBody")
    a = ap.parse_args()
    asyncio.run(main(a.body, a.out, a.prefix, set(filter(None, a.ids.split(","))), a.base))
