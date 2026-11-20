#!/usr/bin/env python3
"""WS3. A thumbnail for every bare-body variant, for every character, for the admin's collections.

The registry's Private collections (by position, and since WS3 by category: shaved, hairy, anal,
creampie, tattooed…) list 99 body items — 13 presets, 57 states, 29 extras. This fills in their
pictures, so the Studio's Collections show what each one is.

Two sources, one rule — detail is painted only where Forge's own gate allows it:

* ``--reference <ref-atlas.vrm>``: Forge's synthetic adult reference body (built by
  ``tools/body_surface/detail_preview.py``, never a character). Painted here, uploaded to
  ``PUT /v1/admin/body-previews/reference/{item}``. These are the default thumbnails the Studio
  shows for every body item.
* every library character (``--slugs`` or all): Forge paints her thumbnails itself,
  ``POST /v1/admin/body-previews/{slug}/render``, on her own plain bare look, and only after the
  same detail clearance a bare job asks for (a full adult-design review of her exact file, with
  its packet and evidence). A character without it is reported as refused, with Forge's reason,
  and nothing is painted on her.

    python tools/render_body_previews.py --forge http://127.0.0.1:8090 --admin-token-file ~/.forge-token \\
        --reference <scratch>/ref/ref-atlas.vrm
    python tools/render_body_previews.py --forge ... --slugs vroid-rinna --only state:,extra:tattoo
    python tools/render_body_previews.py --forge ... --plan-only

Idempotent: an item a character already has is skipped (``--force`` paints it again). The admin
token is read from a file, sent only in its header, never printed or written. Thumbnails are
explicit: they stay in Forge's private store; never commit them, never put them in a public route.

Exit status: 0 when everything planned is there or was refused by the gate; 1 when a request
failed; 2 when Forge could not be reached.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADMIN_HEADER = "X-Wardrobe-Admin"
#: Forge paints at most this many per request (apps/api/routes/registry.py RENDER_BATCH).
BATCH = 4


class Forge:
    def __init__(self, base: str, token: str, timeout: float = 600.0):
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def call(self, method: str, path: str, body=None, raw: bytes | None = None, ctype="application/json"):
        headers = {"Accept": "application/json", ADMIN_HEADER: self.token, "User-Agent": "body-previews/1"}
        data = raw
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode("utf-8"), "application/json"
        elif raw is not None:
            headers["Content-Type"] = ctype
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")


def items(only: str | None) -> list[str]:
    from wardrobe.registry.registry import body_items

    ids = [i["id"] for i in body_items()]
    if only:
        wanted = [w.strip() for w in only.split(",") if w.strip()]
        ids = [i for i in ids if any(w in i for w in wanted)]
    return ids


def reference(forge: Forge, vrm: Path, wanted: list[str], force: bool) -> dict:
    """Paint on Forge's synthetic reference body here, and upload each thumbnail."""
    from wardrobe.registry import body_previews

    have: set = set()
    if not force:
        index = forge.call("GET", "/v1/registry?previews=reference")
        have = {i["id"] for i in index.get("items", []) if i.get("kind") == "body" and i.get("previewUrl")}
    todo = [i for i in wanted if i not in have]
    out = {
        "slug": "reference",
        "planned": len(wanted),
        "present": len(wanted) - len(todo),
        "built": 0,
        "failed": [],
    }
    if not todo:
        return out
    started = time.monotonic()
    images = body_previews.render_items(vrm.read_bytes(), todo)
    for item_id, data in images.items():
        try:
            forge.call("PUT", f"/v1/admin/body-previews/reference/{item_id}", raw=data, ctype="image/webp")
            out["built"] += 1
        except urllib.error.URLError as exc:
            out["failed"].append(f"{item_id}: {exc}")
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


def character(forge: Forge, slug: str, wanted: list[str], force: bool) -> dict:
    """Ask Forge to paint her thumbnails, batch by batch; stop at the first refusal (the gate)."""
    out = {"slug": slug, "planned": len(wanted), "present": 0, "built": 0, "failed": []}
    started = time.monotonic()
    for i in range(0, len(wanted), BATCH):
        batch = wanted[i : i + BATCH]
        try:
            answer = forge.call(
                "POST", f"/v1/admin/body-previews/{slug}/render", {"items": batch, "force": force}
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code in (403, 409):
                # 403: no detail clearance for her file; 409: no plain bare look to paint on yet.
                out["refused"] = f"HTTP {exc.code}: {detail}"
                break
            out["failed"].append(f"HTTP {exc.code}: {detail}")
            continue
        except urllib.error.URLError as exc:
            out["failed"].append(str(exc))
            continue
        out["built"] += len(answer.get("rendered", []))
        out["present"] += len(answer.get("skipped", []))
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--forge", required=True, help="Forge origin, e.g. http://127.0.0.1:8090")
    parser.add_argument("--admin-token-file", help="Forge admin session token (required unless --plan-only)")
    parser.add_argument(
        "--reference", type=Path, help="ref-atlas.vrm from detail_preview.py: paint the defaults"
    )
    parser.add_argument("--slugs", help="Comma-separated characters; default every available one")
    parser.add_argument("--no-characters", action="store_true", help="Only the reference thumbnails")
    parser.add_argument("--only", help="Only items whose id contains one of these (comma-separated)")
    parser.add_argument("--force", action="store_true", help="Paint again what is already there")
    parser.add_argument("--report", type=Path, help="Write the results here as JSON")
    parser.add_argument("--plan-only", action="store_true", help="List what would be painted and stop")
    opts = parser.parse_args(argv)

    wanted = items(opts.only)
    if opts.plan_only:
        print(f"{len(wanted)} body items: " + ", ".join(wanted))
        return 0
    if not opts.admin_token_file:
        print("thumbnails need an admin session: pass --admin-token-file", file=sys.stderr)
        return 2
    forge = Forge(opts.forge, Path(opts.admin_token_file).expanduser().read_text().strip())
    try:
        index = forge.call("GET", "/v1/admin/body-previews")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Forge unreachable at {opts.forge}: {exc}", file=sys.stderr)
        return 2
    slugs = [s for s in index.get("characters", {}) if s != "reference"]
    if opts.slugs:
        slugs = [s for s in slugs if s in opts.slugs.split(",")]

    results = []
    if opts.reference:
        results.append(reference(forge, opts.reference, wanted, opts.force))
    if not opts.no_characters:
        results += [character(forge, slug, wanted, opts.force) for slug in slugs]
    for r in results:
        line = f"{r['slug']:<26} built {r['built']:>3}  present {r['present']:>3}  of {r['planned']}"
        if r.get("refused"):
            line += f"  · refused: {r['refused']}"
        if r["failed"]:
            line += f"  · {len(r['failed'])} failed: {r['failed'][0]}"
        print(line, flush=True)
    if opts.report:
        opts.report.parent.mkdir(parents=True, exist_ok=True)
        opts.report.write_text(json.dumps(results, indent=2))
    return 1 if any(r["failed"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
