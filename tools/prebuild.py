#!/usr/bin/env python3
"""PB2. Make every catalog garment for every library character, once (docs/PREBUILT_WARDROBE.md).

Drives a running Forge over HTTP, exactly as Try-On does: ``POST /v1/library/{slug}/jobs`` with
one template and a foundation underneath. Going through the routes, not around them, means the
same policy decides and the cache keys are the ones a real request produces. Forge remembers
each finished look (``wardrobe.pipeline.prebuilt``); a rerun finds them and builds nothing.

    python tools/prebuild.py --forge http://127.0.0.1:8090 --admin-token-file ~/.forge-token
    python tools/prebuild.py --forge ... --slugs fem-vroid --only lingerie --report out.json

Without an admin token only the public catalog is listed (62 of 105 on 2026-11-13). A
restricted template is asked for only on a character declared adult; Forge refuses it on any
other, so asking would only record a refusal.

Exit status: 0 when every planned look is built or was already there; 1 when any failed
(each failure is in the report with Forge's reason); 2 when Forge could not be reached.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ADMIN_HEADER = "X-Wardrobe-Admin"
TERMINAL = {"completed", "failed", "rejected"}


class Forge:
    def __init__(self, base: str, token: str | None, timeout: float = 180.0):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def call(self, path: str, body: dict | None = None) -> dict:
        headers = {"Accept": "application/json", "User-Agent": "wardrobe-prebuild/1"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers[ADMIN_HEADER] = self.token
        request = urllib.request.Request(self.base + path, data=data, headers=headers,
                                         method="POST" if body is not None else "GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def plan(forge: Forge, slugs: list[str] | None, only: str | None) -> list[dict]:
    """Every (character, template) pair worth asking for."""
    avatars = [a for a in forge.call("/v1/library").get("avatars", []) if a.get("available")]
    if slugs:
        avatars = [a for a in avatars if a["slug"] in slugs]
    query = "?includeRestricted=true" if forge.token else ""
    catalog = forge.call("/v1/catalog/garments" + query)
    templates = [g for c in catalog.get("categories", []) for g in c.get("garments", [])]
    if only:
        templates = [t for t in templates if only.lower() in (t["name"] + " " + t["id"]).lower()]
    pairs = []
    for avatar in avatars:
        for template in templates:
            pair = {"slug": avatar["slug"], "templateId": template["id"], "name": template["name"]}
            if template.get("requiresAdult") and not avatar.get("depictsAdult"):
                pair["skip"] = "the template needs a character declared adult"
            pairs.append(pair)
    return pairs


def job_body(pair: dict) -> dict:
    """What Try-On sends for a fresh garment: the template, over a foundation, previewed."""
    return {
        "outfit": {"prompt": pair["name"], "mode": "template", "templateId": pair["templateId"]},
        "options": {"renderPreview": True, "engine": "auto", "ensureFoundation": True},
    }


def build(forge: Forge, pair: dict, job_timeout: float) -> dict:
    out = dict(pair)
    if pair.get("skip"):
        out["result"] = "skipped"
        return out
    started = time.monotonic()
    try:
        job = forge.call(f"/v1/library/{pair['slug']}/jobs", job_body(pair))
        prebuilt = job.get("state") == "completed"
        while job.get("state") not in TERMINAL:
            if time.monotonic() - started > job_timeout:
                out.update(result="failed", reason=f"timed out after {job_timeout:.0f}s")
                return out
            time.sleep(1.0)
            try:
                job = forge.call(f"/v1/jobs/{job['id']}")
            except (urllib.error.URLError, TimeoutError) as exc:
                # A busy Forge answering slowly is not a failed look: ask again until the
                # job's own timeout. An HTTP error (the job is gone) is final.
                if isinstance(exc, urllib.error.HTTPError):
                    raise
                continue
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        detail = ""
        if isinstance(exc, urllib.error.HTTPError):
            detail = exc.read().decode("utf-8", "replace")[:300]
        out.update(result="failed", reason=f"{type(exc).__name__}: {exc} {detail}".strip())
        return out
    out["seconds"] = round(time.monotonic() - started, 1)
    if job["state"] == "completed":
        out.update(result="present" if prebuilt else "built", lookId=(job.get("look") or {}).get("id"))
    else:
        out.update(result="failed", reason=job.get("error") or job["state"])
    return out


def main(argv=None) -> int:
    raw = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=raw)
    parser.add_argument("--forge", required=True, help="Forge origin, e.g. http://127.0.0.1:8090")
    parser.add_argument("--admin-token-file", help="Forge admin session token, for the full catalog")
    parser.add_argument("--slugs", help="Comma-separated library characters; default all available")
    parser.add_argument("--only", help="Only templates whose name or id contains this text")
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many pairs (0 = all)")
    parser.add_argument("--workers", type=int, default=2, help="Jobs in flight (Forge's concurrency)")
    parser.add_argument("--job-timeout", type=float, default=900.0, help="Seconds per look")
    parser.add_argument("--report", type=Path, help="Write the per-look results here as JSON")
    parser.add_argument("--plan-only", action="store_true", help="List the pairs and stop")
    opts = parser.parse_args(argv)

    token = Path(opts.admin_token_file).expanduser().read_text().strip() if opts.admin_token_file else None
    forge = Forge(opts.forge, token)
    try:
        pairs = plan(forge, opts.slugs.split(",") if opts.slugs else None, opts.only)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Forge unreachable at {opts.forge}: {exc}", file=sys.stderr)
        return 2
    if opts.limit:
        pairs = pairs[: opts.limit]
    print(f"{len(pairs)} looks planned across {len({p['slug'] for p in pairs})} characters", flush=True)
    if opts.plan_only:
        for pair in pairs:
            print(f"  {pair['slug']:<24} {pair['templateId']:<36} {pair.get('skip', '')}")
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=max(1, opts.workers)) as pool:
        for done in pool.map(lambda p: build(forge, p, opts.job_timeout), pairs):
            results.append(done)
            mark = {"built": "+", "present": "=", "skipped": "-", "failed": "!"}[done["result"]]
            print(f"{mark} {done['slug']:<24} {done['templateId']:<36} {done.get('seconds', '')} "
                  f"{done.get('reason', '')}", flush=True)

    counts = {k: sum(r["result"] == k for r in results) for k in ("built", "present", "skipped", "failed")}
    summary = {"forge": opts.forge, "planned": len(pairs), **counts, "results": results}
    if opts.report:
        opts.report.parent.mkdir(parents=True, exist_ok=True)
        opts.report.write_text(json.dumps(summary, indent=2))
    print("built {built}, already there {present}, skipped {skipped}, failed {failed}".format(**counts))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
