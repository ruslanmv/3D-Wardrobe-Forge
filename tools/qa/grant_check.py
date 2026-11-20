#!/usr/bin/env python3
"""L5. What a companion's read grant sees on a deployed Forge — the second gate, end to end.

The chatbot opens its No-limits step (step 5), the After Dark occasion and the bare looks only
when Forge answers a read grant. "Does this grant work on the Space?" was answered by hand with
curl, a header and a jq one-liner each time; this asks the same routes, the same way the app
does, and says what each answered:

    FORGE_GRANT=… .venv/bin/python tools/qa/grant_check.py [--forge https://…hf.space]

* ``/v1/body-surface/catalog``  200 only for an admin or a grant (the bridge's probe for step 5)
* ``/v1/outfits``               lists After Dark only to an admin or a grant (GC2)
* ``/v1/registry``              ``access: grant``, the After Dark · Bare collections and looks (AB1)
* the same three without the grant: a guest must not get the catalogue or After Dark

The grant is read from FORGE_GRANT in the environment only: never an argument (it would sit in
the shell history and the process list), never a file, never printed. Exit 0 when the grant
opens everything and a guest gets none of it; 1 when something answered wrongly; 2 when Forge
could not be reached or no grant was given.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

SPACE = "https://ruslanmv-3d-wardrobe-forge.hf.space"


def ask(base: str, path: str, grant: str | None, timeout: float) -> tuple[int, dict]:
    headers = {"Accept": "application/json", "User-Agent": "grant-check/1"}
    if grant:
        headers["X-Wardrobe-Grant"] = grant
    request = urllib.request.Request(base.rstrip("/") + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--forge", default=SPACE, help="Forge origin (default: the Space)")
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="Seconds per request (a cold Space is slow)"
    )
    opts = parser.parse_args(argv)
    grant = os.environ.get("FORGE_GRANT", "").strip()
    if not grant:
        print("put the grant in FORGE_GRANT (environment only)", file=sys.stderr)
        return 2

    problems: list[str] = []

    def check(label: str, ok: bool, detail: str) -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {label:<44} {detail}")
        if not ok:
            problems.append(label)

    try:
        code, _ = ask(opts.forge, "/v1/body-surface/catalog", grant, opts.timeout)
        check("grant: body catalogue (step 5's probe)", code == 200, f"HTTP {code}")
        code, outfits = ask(opts.forge, "/v1/outfits", grant, opts.timeout)
        ids = [o.get("id") for o in outfits.get("occasions", [])]
        check("grant: After Dark listed", "after-dark" in ids, f"HTTP {code}, {len(ids)} occasions")
        code, reg = ask(opts.forge, "/v1/registry", grant, opts.timeout)
        bare = [c["id"] for c in reg.get("collections", []) if str(c.get("id", "")).startswith("ad-bare")]
        looks = [i for i in reg.get("items", []) if str(i.get("id", "")).startswith("look:")]
        check(
            "grant: registry, After Dark · Bare",
            reg.get("access") == "grant" and bool(bare) and bool(looks),
            f"HTTP {code}, access {reg.get('access')}, {len(bare)} collections, {len(looks)} looks",
        )
        code, _ = ask(opts.forge, "/v1/body-surface/catalog", None, opts.timeout)
        check("guest: no body catalogue", code in (401, 403), f"HTTP {code}")
        code, outfits = ask(opts.forge, "/v1/outfits", None, opts.timeout)
        check("guest: no After Dark", "after-dark" not in [o.get("id") for o in outfits.get("occasions", [])],
              f"HTTP {code}")
        code, reg = ask(opts.forge, "/v1/registry", None, opts.timeout)
        leaked = [i["id"] for i in reg.get("items", []) if i.get("private")]
        check("guest: no private registry items", not leaked, f"HTTP {code}, {len(leaked)} private")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Forge unreachable at {opts.forge}: {exc}", file=sys.stderr)
        return 2
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
