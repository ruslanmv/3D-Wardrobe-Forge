#!/usr/bin/env python3
"""BD21. Make every private bare look for every library character, once.

Why. A companion in Private can show only the body states her look's skin pack holds, and only
the extras (piercings, tattoos, tan lines, marks) painted into a look she can change into. Forge
had at most one bare look per character, made by hand, often without any detail — so in a real
evening she stopped at her underwear and, asked for a piercing, could only say no. This makes the
whole set: every state Forge can paint (``assets/body_detail/states.json``) in a few skin packs
grouped the way a scene uses them, plus a few looks with extras, for every character declared
adult, so the client lists them (``WardrobeLook.body``) and tells her what each one can show.

Like ``tools/prebuild.py`` it drives a running Forge over HTTP, through the same route and the
same gates as an admin in the Studio: ``POST /v1/library/{slug}/jobs`` with ``baseBody: bare``,
``bareDetail``, ``bareStates`` (≤ 10, a skin pack) and ``bareExtras`` (≤ 4). Nothing here decides
who may have a bare body: a character not declared adult is skipped, and Forge refuses a source
without detail clearance — that refusal is reported with its reason code, never worked around.

    python tools/prebuild_private.py --forge http://127.0.0.1:8090 --admin-token-file ~/.forge-token
    python tools/prebuild_private.py --forge ... --slugs avatar-sample-a --presets natural,trimmed
    python tools/prebuild_private.py --forge ... --plan-only            # what would be made
    python tools/prebuild_private.py --forge ... --groups core,doggy --extras-sets none

Idempotent: a look whose body (preset, states, extras) is already in the character's list is not
sent again. Every look is private: listed only to an admin session or a read grant for her.

The admin token is read from a file and only ever sent in the request header — never printed,
never written to the report.

Exit status: 0 when every planned look is built or was already there (refusals by the gates are
reported, not failures); 1 when any job failed; 2 when Forge could not be reached.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATES_PATH = ROOT / "assets/body_detail/states.json"
EXTRAS_PATH = ROOT / "assets/body_detail/extras.json"

#: Forge's limits on one job (wardrobe/domain/jobs.py): a skin pack of ten states, four extras.
MAX_STATES = 10
MAX_EXTRAS = 4
TERMINAL = {"completed", "failed", "rejected"}
#: Gate refusals: the policy said no. Reported, never a failure of this tool.
GATE_REASONS = {
    "body_surface_not_permitted",
    "requires_adult_declaration",
    "body-incomplete-for-bare",
    "body_surface_profile_unavailable",
}

#: The skin packs, in the order a scene meets them. Each pack starts at ``closed`` (her body at
#: rest, so every look can go back to it) and holds the states one moment of an evening switches
#: between live. A state is put in the first group whose pattern matches it; a state no group
#: matches (one Forge adds later) still gets made, in an ``other`` pack — never silently left out.
GROUPS: list[tuple[str, str]] = [
    ("core", r"^(aroused|open|wide-open|anus-open|both-open|flushed|goosebumps|sweaty|afterglow)$"),
    ("oiled", r"^(pumped|pumped-open|oiled|oiled-aroused|stretched|anus-stretched|cum|creampie)$"),
    (
        "doggy",
        r"^(doggy-(sweaty|sweaty-open|creampie|finish|open-cum|double-creampie|gaping-cum|cum-covered)"
        r"|anal-creampie)$",
    ),
    ("back", r"^(lower-back-cum.*|cum-on-back|doggy-pumped-creampie|doggy-second-creampie)$"),
    ("missionary", r"^missionary-"),
    ("cowgirl", r"^cowgirl-"),
    ("rough", r"^sado-"),
    # L5. One pack per act from behind, so "fisted, then filled" switches live in the same look:
    # the three fisted states and their filled ones; the bottle and its filled ones.
    ("fist", r"^doggy-.*fisted(-cum)?$"),
    ("bottle", r"^doggy-bottle"),
    # BD28. The open ring after a fist (a new kind, beside the fisted pack): one pack, live switch.
    ("ring", r"^doggy-.*ring(-cum)?$"),
    # Unrestrained (gate 2): the evening's build-up states, composed from existing effects.
    ("unrestrained",
     r"^(edge|dripping|breasts-belly|oiled-used|used|round-three|tied-edge|after-shower)$"),
]

#: Looks with extras painted in: they cannot be switched live, so each is its own look, with the
#: core states so she is still alive in it. Each set is at most four extras.
EXTRAS_SETS: dict[str, list[str]] = {
    "pierced": ["piercings-nipples", "piercings-intimate"],
    "pierced-all": ["piercings-all", "piercings-christina"],
    "tattooed": ["tattoo-mons-rose", "tattoo-lower-back-tribal"],
    "tanned": ["tan-triangle-thong"],
    "marked": ["kisses-red", "love-bites", "spanked"],
    "written": ["writing-yours", "writing-lower-back"],
    "glitter": ["glitter", "body-paint-gold"],
}


def _load_prebuild():
    """tools/prebuild.py's HTTP client (its ``Forge``), so both tools speak to Forge the same way."""
    spec = importlib.util.spec_from_file_location("prebuild", ROOT / "tools/prebuild.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_names(path: Path, key: str) -> list[str]:
    return list(json.loads(path.read_text(encoding="utf-8"))[key])


def state_groups(states: list[str]) -> dict[str, list[str]]:
    """Every state, in skin packs of at most ``MAX_STATES``, each starting with ``closed``.

    A group with more states than one pack holds is split (``doggy``, ``doggy-2``…): Forge's limit
    is per job, and splitting keeps every state reachable rather than cutting the tail off.
    """
    found: dict[str, list[str]] = {}
    for name in states:
        if name == "closed":
            continue
        group = next((g for g, pattern in GROUPS if re.search(pattern, name)), "other")
        found.setdefault(group, []).append(name)
    order = [g for g, _ in GROUPS] + ["other"]
    packs: dict[str, list[str]] = {}
    room = MAX_STATES - 1
    for group in order:
        names = found.get(group) or []
        for i in range(0, len(names), room):
            label = group if i == 0 else f"{group}-{i // room + 1}"
            packs[label] = ["closed", *names[i : i + room]]
    return packs


def bare_looks() -> dict:
    """AB1. After Dark · Bare (assets/body_detail/bare_looks.json), checked by Forge's own loader."""
    sys.path.insert(0, str(ROOT))
    from wardrobe.registry import bare_looks as loader

    return loader.load()["looks"]


def plan(
    avatars: list[dict],
    presets: list[str],
    packs: dict[str, list[str]],
    extras_sets: dict[str, list[str]],
    named: dict | None = None,
) -> list[dict]:
    """Every (character, preset, look) worth asking for.

    AB1. ``named`` looks (After Dark · Bare) come with their own preset, so each is made once per
    character in its own skin rather than once per ``--presets`` value: a look is a design, and
    "Pumped & Begging" is puffy whatever the run's default.
    """
    looks = [{"look": name, "states": states, "extras": []} for name, states in packs.items()]
    core = packs.get("core") or ["closed"]
    looks += [
        {"look": f"core+{name}", "states": core, "extras": extras[:MAX_EXTRAS]}
        for name, extras in extras_sets.items()
    ]
    pairs = []
    for avatar in avatars:
        for preset in presets:
            for look in looks:
                pair = {"slug": avatar["slug"], "preset": preset, **look}
                if not avatar.get("depictsAdult"):
                    pair["skip"] = "a bare body needs a character declared adult"
                pairs.append(pair)
        for look_id, spec in (named or {}).items():
            pair = {
                "slug": avatar["slug"],
                "preset": spec["preset"],
                "look": f"ad:{look_id}",
                "states": ["closed", spec["state"]],
                "extras": list(spec.get("extras", []))[:MAX_EXTRAS],
            }
            if not avatar.get("depictsAdult"):
                pair["skip"] = "a bare body needs a character declared adult"
            pairs.append(pair)
    return pairs


def job_body(pair: dict) -> dict:
    """What the Studio sends for a detailed bare look (tests/integration/test_bare_body.py)."""
    options = {
        "baseBody": "bare",
        "renderPreview": True,
        "engine": "native",
        "bareDetail": pair["preset"],
        "bareStates": pair["states"],
    }
    if pair["extras"]:
        options["bareExtras"] = pair["extras"]
    return {
        "outfit": {"prompt": "Bare authored body", "mode": "template", "templateId": "body-bare-v1"},
        "options": options,
    }


def identity(detail, states, extras) -> tuple:
    return (detail, tuple(sorted(states or [])), tuple(sorted(extras or [])))


def listed(forge, slug: str) -> set:
    """The bodies a character's list already has (BD21 ``body`` on each bare look)."""
    looks = forge.call(f"/v1/library/{slug}/prebuilt").get("looks", [])
    return {
        identity(b.get("detail"), b.get("states"), b.get("extras"))
        for b in (look.get("body") for look in looks)
        if isinstance(b, dict)
    }


def anus_open_of(states_path: Path = None) -> dict[str, float]:
    """How far each state opens her anus (``states.json`` ``set.anusOpen``), 0 when it does not."""
    data = json.loads((states_path or STATES_PATH).read_text())
    table = data.get("states", data)
    return {
        k: float((v.get("set") or {}).get("anusOpen") or 0)
        for k, v in table.items()
        if isinstance(v, dict)
    }


def repaint_plan(looks: list[dict], slug: str, before: str, min_open: float, opened: dict) -> list[dict]:
    """BD25. The listed detailed looks to paint again, exactly as they were asked for.

    Why. Looks built before BD24's ``_behind_mask`` carry the anus colour layers below the crotch:
    thin red streaks down both inner thighs, worst where she is open (fisted, gaped, the bottle's
    aftermath). Missing-only runs never touch a listed look, so these stay forever unless they are
    made again. Chosen here: a look with a body detail, built before ``before`` (ISO time), whose
    skin pack opens her anus at least ``min_open``. Each comes back with its own preset, states and
    extras, so the new build has the same identity (key) and replaces the old one on publish
    (``--overwrite``); nothing else in her list is touched.
    """
    out = []
    for look in looks:
        body = look.get("body")
        if not isinstance(body, dict) or not body.get("detail"):
            continue
        if str(look.get("builtAt") or "") >= before:
            continue
        states = list(body.get("states") or ([body["state"]] if body.get("state") else []))
        if max((opened.get(s, 0.0) for s in states), default=0.0) < min_open:
            continue
        out.append(
            {
                "slug": slug,
                "preset": body["detail"],
                "look": f"repaint:{look.get('lookId', '')}",
                "states": states,
                "extras": list(body.get("extras") or [])[:MAX_EXTRAS],
                "repaint": True,
            }
        )
    return out


def build(forge, pair: dict, held: set, job_timeout: float) -> dict:
    out = dict(pair)
    if pair.get("skip"):
        out["result"] = "skipped"
        return out
    if not pair.get("repaint") and identity(pair["preset"], pair["states"], pair["extras"]) in held:
        out.update(result="present", reason="already listed: kept, not rebuilt")
        return out
    started = time.monotonic()
    try:
        job = forge.call(f"/v1/library/{pair['slug']}/jobs", job_body(pair))
        while job.get("state") not in TERMINAL:
            if time.monotonic() - started > job_timeout:
                out.update(result="failed", reason=f"timed out after {job_timeout:.0f}s")
                return out
            time.sleep(2.0)
            try:
                job = forge.call(f"/v1/jobs/{job['id']}")
            except (urllib.error.URLError, TimeoutError) as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    raise
                continue  # a busy Forge answering slowly is not a failed look
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        detail = (
            exc.read().decode("utf-8", "replace")[:300] if isinstance(exc, urllib.error.HTTPError) else ""
        )
        out.update(result="failed", reason=f"{type(exc).__name__}: {exc} {detail}".strip())
        return out
    out["seconds"] = round(time.monotonic() - started, 1)
    if job["state"] == "completed":
        out.update(result="built", lookId=(job.get("look") or {}).get("id"))
    elif job["state"] == "rejected" or job.get("reason") in GATE_REASONS:
        # The gates said no (no adult declaration, no detail clearance…): what the policy is for.
        out.update(result="refused", reason=job.get("error") or job["state"], reasonCode=job.get("reason"))
    else:
        out.update(result="failed", reason=job.get("error") or job["state"], reasonCode=job.get("reason"))
    return out


def _pick(value: str | None, available: dict) -> dict:
    if value is None or value == "all":
        return dict(available)
    if value == "none":
        return {}
    names = [v.strip() for v in value.split(",") if v.strip()]
    unknown = [n for n in names if n not in available]
    if unknown:
        raise SystemExit(f"unknown: {', '.join(unknown)} (have {', '.join(available)})")
    return {n: available[n] for n in names}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--forge", required=True, help="Forge origin, e.g. http://127.0.0.1:8090")
    parser.add_argument("--admin-token-file", help="Forge admin session token (bare looks need one)")
    parser.add_argument("--slugs", help="Comma-separated library characters; default all available")
    parser.add_argument("--presets", default="natural", help="Comma-separated body-detail presets")
    parser.add_argument(
        "--groups", help="Skin packs to make (default all): " + ", ".join(g for g, _ in GROUPS)
    )
    parser.add_argument(
        "--extras-sets",
        default="all",
        help="Looks with extras: all, none, or names: " + ", ".join(EXTRAS_SETS),
    )
    parser.add_argument(
        "--bare-looks",
        default="all",
        help="AB1 After Dark · Bare named looks: all, none, or ids (bare_looks.json)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many looks (0 = all)")
    parser.add_argument("--workers", type=int, default=1, help="Jobs in flight (a skin pack is heavy)")
    parser.add_argument("--job-timeout", type=float, default=1800.0, help="Seconds per look")
    parser.add_argument("--report", type=Path, help="Write the per-look results here as JSON")
    parser.add_argument("--plan-only", action="store_true", help="List the looks and stop")
    parser.add_argument(
        "--repaint-before",
        help="BD25: instead of planning, paint again the listed detailed looks built before this ISO "
        "time whose states open her anus (publish them with --overwrite)",
    )
    parser.add_argument(
        "--repaint-min-open", type=float, default=0.5, help="BD25: least anusOpen that counts (0..1)"
    )
    opts = parser.parse_args(argv)

    states = load_names(STATES_PATH, "states")
    extras = set(load_names(EXTRAS_PATH, "extras"))
    for name, chosen in EXTRAS_SETS.items():
        missing = [e for e in chosen if e not in extras]
        if missing:
            print(f"extras set {name}: Forge has no {', '.join(missing)}", file=sys.stderr)
            return 2
    packs = state_groups(states)
    if opts.groups:
        wanted = {g.strip() for g in opts.groups.split(",")}
        packs = {k: v for k, v in packs.items() if k.split("-")[0] in wanted or k in wanted}
    extras_sets = _pick(opts.extras_sets, EXTRAS_SETS)
    presets = [p.strip() for p in opts.presets.split(",") if p.strip()]

    token = Path(opts.admin_token_file).expanduser().read_text().strip() if opts.admin_token_file else None
    forge = _load_prebuild().Forge(opts.forge, token)
    try:
        avatars = [a for a in forge.call("/v1/library").get("avatars", []) if a.get("available")]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Forge unreachable at {opts.forge}: {exc}", file=sys.stderr)
        return 2
    if opts.slugs:
        avatars = [a for a in avatars if a["slug"] in opts.slugs.split(",")]
    named = {} if opts.bare_looks == "none" else bare_looks()
    if opts.bare_looks not in ("all", "none"):
        wanted = {w.strip() for w in opts.bare_looks.split(",")}
        named = {k: v for k, v in named.items() if k in wanted}
    if opts.repaint_before:
        opened = anus_open_of()
        pairs = []
        try:
            for avatar in avatars:
                looks = forge.call(f"/v1/library/{avatar['slug']}/prebuilt").get("looks", [])
                pairs += repaint_plan(
                    looks, avatar["slug"], opts.repaint_before, opts.repaint_min_open, opened
                )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"could not read the characters' lists: {exc}", file=sys.stderr)
            return 2
    else:
        pairs = plan(avatars, presets, packs, extras_sets, named)
    if opts.limit:
        pairs = pairs[: opts.limit]
    covered = {s for p in pairs for s in p["states"]}
    print(
        f"{len(pairs)} private looks planned across {len(avatars)} characters; "
        f"{len(covered)} of {len(states)} states covered",
        flush=True,
    )
    if opts.plan_only:
        for p in pairs:
            print(
                f"  {p['slug']:<24} {p['preset']:<14} {p['look']:<20} {len(p['states']):>2} states "
                f"{'+'.join(p['extras'])} {p.get('skip', '')}"
            )
        return 0
    if not token:
        print("bare looks need an admin session: pass --admin-token-file", file=sys.stderr)
        return 2

    held: dict[str, set] = {}
    try:
        for slug in {p["slug"] for p in pairs if not p.get("skip")}:
            held[slug] = listed(forge, slug)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"could not read the characters' lists: {exc}", file=sys.stderr)
        return 2

    results = []
    marks = {"built": "+", "present": "=", "skipped": "-", "refused": "x", "failed": "!"}
    with ThreadPoolExecutor(max_workers=max(1, opts.workers)) as pool:
        for done in pool.map(lambda p: build(forge, p, held.get(p["slug"], set()), opts.job_timeout), pairs):
            results.append(done)
            print(
                f"{marks[done['result']]} {done['slug']:<24} {done['preset']:<14} {done['look']:<20} "
                f"{done.get('seconds', '')} {done.get('reasonCode') or ''} {done.get('reason', '')}",
                flush=True,
            )

    counts = {k: sum(r["result"] == k for r in results) for k in marks}
    if opts.report:
        opts.report.parent.mkdir(parents=True, exist_ok=True)
        opts.report.write_text(
            json.dumps({"forge": opts.forge, "planned": len(pairs), **counts, "results": results}, indent=2)
        )
    print(
        "built {built}, already there {present}, skipped {skipped}, refused {refused}, "
        "failed {failed}".format(**counts)
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
