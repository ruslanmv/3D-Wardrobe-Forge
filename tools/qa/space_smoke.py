#!/usr/bin/env python3
"""DP1. Is the deployed Space what `ultimate` says, and does it keep Private private?

Read-only, no token: what a guest can reach, how fast, and that nothing private reaches a guest.
Run it after every deploy (Actions ▸ Deploy to Hugging Face Space ▸ branch `ultimate`), and before
an audit. Written from the checks done by hand on 2026-11-20, so the next session runs one command.

    .venv/bin/python tools/qa/space_smoke.py                     # the public Space
    .venv/bin/python tools/qa/space_smoke.py --base http://127.0.0.1:8090 --slug avatar-sample-a

What each check guards:

* the routes answer (health, capabilities, library, outfits, registry, Studio and its modules);
* the gates refuse a guest: the body catalogue 403, the admin dashboard 401 — a 404 means the
  Space runs code older than BD21/WS1, a 200 means a gate is open;
* the registry a guest reads holds no Private collection or item, and her ready-made looks hold
  no private look and no ``body`` (BD21) — the server filters, never the page;
* timings: the registry's first call after a restart took 18 s (cold), the next 0.3 s; a warm
  call over ``--slow`` seconds is reported.

Exit 0 when every check passes, 1 when any fails, 2 when the Space cannot be reached.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://ruslanmv-3d-wardrobe-forge.hf.space"


def get(base: str, path: str, timeout: float = 60.0):
    started = time.monotonic()
    request = urllib.request.Request(base + path, headers={"User-Agent": "forge-space-smoke/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body, status = exc.read(), exc.code
    return status, body, time.monotonic() - started


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default=DEFAULT_BASE, help="Forge origin")
    parser.add_argument("--slug", default="avatar-sample-a", help="A library character to read")
    parser.add_argument("--slow", type=float, default=3.0, help="Seconds a warm call may take")
    opts = parser.parse_args(argv)
    base = opts.base.rstrip("/")
    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(("ok    " if ok else "FAIL  ") + label)
        if not ok:
            failures.append(label)

    try:
        status, _, took = get(base, "/health")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Space unreachable at {base}: {exc}", file=sys.stderr)
        return 2
    check(status == 200, f"/health {status} ({took:.2f}s)")

    expect = {
        "/v1/capabilities": 200,
        "/v1/library": 200,
        "/v1/outfits": 200,
        "/v1/body-surface/profiles": 200,
        "/studio/": 200,
        "/studio/js/collections.js": 200,
        "/v1/body-surface/catalog": 403,
        "/v1/admin/registry/dashboard": 401,
    }
    for path, want in expect.items():
        status, _, took = get(base, path)
        check(status == want, f"{path} {status} (want {want}, {took:.2f}s)")

    get(base, "/v1/registry", timeout=120)  # the first call warms it (18 s cold, 2026-11-20)
    status, body, took = get(base, "/v1/registry")
    check(status == 200, f"/v1/registry {status} ({took:.2f}s warm)")
    check(took <= opts.slow, f"/v1/registry warm within {opts.slow:.0f}s ({took:.2f}s)")
    if status == 200:
        view = json.loads(body)
        private_cols = [c["id"] for c in view.get("collections", []) if c.get("private")]
        private_items = [i["id"] for i in view.get("items", []) if i.get("private")]
        check(not view.get("admin"), "registry: a guest is not an admin")
        check(not private_cols, f"registry: no Private collection for a guest {private_cols[:3]}")
        check(not private_items, f"registry: no Private item for a guest {private_items[:3]}")
        print(f"      {len(view.get('collections', []))} collections, {len(view.get('items', []))} items")

    status, body, took = get(base, f"/v1/library/{opts.slug}/prebuilt")
    check(status == 200, f"/v1/library/{opts.slug}/prebuilt {status} ({took:.2f}s)")
    if status == 200:
        looks = json.loads(body).get("looks", [])
        check(not any(look.get("private") for look in looks), f"{opts.slug}: no private look to a guest")
        check(not any("body" in look for look in looks), f"{opts.slug}: no bare body details to a guest")
        print(f"      {len(looks)} ready looks")

    print(f"\n{'all checks passed' if not failures else f'{len(failures)} failed'} · {base}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
