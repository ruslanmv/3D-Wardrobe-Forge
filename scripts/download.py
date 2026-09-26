#!/usr/bin/env python3
"""Download the VRoid Hub models in scripts/vroid_models.json, with their licences.

    python scripts/download.py --check        # read each model's licence; no login, no download
    python scripts/download.py                # sign in once, then download everything allowed
    python scripts/download.py --only vroid-helen,vroid-boy-g
    python scripts/download.py --copy-to ../3D-Avatar-Chatbot/vendor/avatars
    python scripts/download.py --logout       # revoke and forget the saved token

What it does, in order:

1. Reads ``.env`` (and the environment, which wins) for the VRoid Hub application:
   ``VROID_CLIENT_ID``, ``VROID_CLIENT_SECRET``, ``VROID_REDIRECT_URI`` (default
   ``http://localhost:18927/callback``) and ``VROID_SCOPE`` (default ``default``).
   ``VROID_ACCESS_TOKEN``, if set, is used as-is and the sign-in is skipped.
2. Signs in with OAuth 2.0 authorization code + PKCE, the only flow VRoid Hub offers:
   the app ID and secret alone cannot download anything, a signed-in user must
   approve. It opens the browser, catches the redirect on the registered localhost
   port, checks ``state``, and exchanges the code. The token is saved to
   ``.vroid-token.json`` (gitignored, mode 600) and refreshed when it expires, so
   the browser is needed once. ``--paste`` is for a machine with no browser: open
   the printed URL anywhere, then paste the address the browser ends up on.
3. For each model, reads its *current* conditions from VRoid Hub and refuses it
   unless it is downloadable, available to other users, and its creator allows
   redistribution and modification. That is the bar because of what happens to the
   file next: this repository re-cuts it to dress it (modification), and the look
   it makes is served to others (redistribution). The listing in vroid_models.json
   is a request, never a permission.
4. Issues a download licence, follows VRoid Hub's redirect to the presigned file
   URL *without* the bearer token (a presigned URL refuses a second credential),
   checks the bytes are a glTF 2.0 binary, reads the VRM's own embedded licence and
   warns where it disagrees with the listing, then invalidates the download licence.
5. Writes ``assets/library/vroid/<slug>.vrm`` (gitignored, like every library VRM),
   ``licenses/<slug>.json`` (the dated snapshot: who made it, what they allow, any
   extra terms URL, VRoid Hub's own age flags) and ``models.json`` (size and SHA-256
   of each file, the same shape as assets/library/models.json), both committable.

Whether an application may be used this way is set when it is registered on VRoid
Hub (redistribution, alterations, commercial use, usage as an avatar): its
settings must allow what this repository does with the files. The script prints
the application's use of each file; it cannot read the registration.

Stdlib only, like tools/fetch_library.py.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.server
import json
import os
import secrets
import shutil
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_FILE = Path(__file__).resolve().parent / "vroid_models.json"
OUT_DIR = REPO_ROOT / "assets" / "library" / "vroid"
TOKEN_FILE = REPO_ROOT / ".vroid-token.json"
ENV_FILE = REPO_ROOT / ".env"

HUB = "https://hub.vroid.com"
API_VERSION = "11"
DEFAULT_REDIRECT = "http://localhost:18927/callback"
TIMEOUT_S = 60
SIGN_IN_WAIT_S = 300

#: What a model's creator must allow for this repository to hold and re-cut it.
VRM1_MODIFICATION_OK = {"allowModification", "allowModificationRedistribution"}
VRM0_MODIFICATION_OK = {"allow", "allow_modification", "allow_modification_redistribution"}


class DownloadError(RuntimeError):
    pass


# ---------------------------------------------------------------- configuration
def read_env(path: Path = ENV_FILE, environ: dict | None = None) -> dict[str, str]:
    """``.env`` as a dict, overridden by the real environment.

    Comments, blank lines, ``export`` prefixes and quoted values are handled.
    """
    values: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            values[key.strip()] = value
    env = os.environ if environ is None else environ
    for key in list(values) + [k for k in env if k.startswith("VROID_")]:
        if env.get(key):
            values[key] = env[key]
    return values


def load_models(path: Path = MODELS_FILE, only: set[str] | None = None) -> list[dict]:
    models = json.loads(path.read_text(encoding="utf-8"))["models"]
    if only:
        unknown = only - {m["slug"] for m in models}
        if unknown:
            raise DownloadError(f"not in {path.name}: {', '.join(sorted(unknown))}")
        models = [m for m in models if m["slug"] in only]
    return models


# ---------------------------------------------------------------- http
def _request(method: str, url: str, *, token: str | None = None, form: dict | None = None,
             body: dict | None = None, redirects: bool = True) -> tuple[int, dict, bytes]:
    headers = {"X-Api-Version": API_VERSION, "Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener() if redirects else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read() if error.fp else b""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand a redirect back instead of following it with the bearer token attached."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _json(status: int, raw: bytes, what: str) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise DownloadError(f"{what}: HTTP {status}, not JSON: {raw[:200]!r}") from exc
    if status >= 400:
        error = payload.get("error") if isinstance(payload, dict) else None
        detail = error.get("message") if isinstance(error, dict) else payload
        raise DownloadError(f"{what}: HTTP {status}: {detail}")
    return payload


# ---------------------------------------------------------------- sign-in
def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) per RFC 7636, S256 — the only method VRoid Hub accepts."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(config: dict, state: str, challenge: str) -> str:
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": config["VROID_CLIENT_ID"],
        "redirect_uri": config["VROID_REDIRECT_URI"],
        "scope": config["VROID_SCOPE"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{HUB}/oauth/authorize?{query}"


def code_from_redirect(address: str, state: str) -> str:
    """The ``code`` from the address VRoid Hub redirected to, once ``state`` matches."""
    params = urllib.parse.parse_qs(urllib.parse.urlparse(address.strip()).query)
    if params.get("error"):
        raise DownloadError(f"VRoid Hub refused the sign-in: {params['error'][0]} "
                            f"{params.get('error_description', [''])[0]}".strip())
    if params.get("state", [""])[0] != state:
        raise DownloadError("the sign-in answer's state does not match this request; start again")
    code = params.get("code", [""])[0]
    if not code:
        raise DownloadError("no code in that address; paste the whole address the browser ended on")
    return code


def _wait_for_redirect(redirect_uri: str, state: str) -> str:
    """Serve the registered localhost redirect once and return the code it brings."""
    target = urllib.parse.urlparse(redirect_uri)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if urllib.parse.urlparse(self.path).path != (target.path or "/"):
                self.send_response(404)
                self.end_headers()
                return
            try:
                result["code"] = code_from_redirect(self.path, state)
                message = "Signed in. You can close this tab and return to the terminal."
            except DownloadError as exc:
                result["error"] = str(exc)
                message = f"Sign-in failed: {exc}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer((target.hostname or "localhost", target.port or 80), Handler)
    server.timeout = 1
    deadline = time.monotonic() + SIGN_IN_WAIT_S
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "error" in result:
        raise DownloadError(result["error"])
    if "code" not in result:
        raise DownloadError(f"no sign-in within {SIGN_IN_WAIT_S // 60} minutes")
    return result["code"]


def _token_request(config: dict, **grant) -> dict:
    status, _, raw = _request("POST", f"{HUB}/oauth/token", form={
        "client_id": config["VROID_CLIENT_ID"],
        "client_secret": config["VROID_CLIENT_SECRET"],
        "redirect_uri": config["VROID_REDIRECT_URI"],
        **grant,
    })
    token = _json(status, raw, "token request")
    if "access_token" not in token:
        raise DownloadError("VRoid Hub answered the token request without an access token")
    token["expires_at"] = time.time() + float(token.get("expires_in") or 3600) - 60
    return token


def _save_token(token: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(token, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):  # a filesystem without modes still gets the file
        TOKEN_FILE.chmod(0o600)


def access_token(config: dict, *, paste: bool) -> str:
    """A usable token: the environment's, the saved one, a refreshed one, or a fresh sign-in."""
    if config.get("VROID_ACCESS_TOKEN"):
        return config["VROID_ACCESS_TOKEN"]
    missing = [k for k in ("VROID_CLIENT_ID", "VROID_CLIENT_SECRET") if not config.get(k)]
    if missing:
        raise DownloadError(f"set {' and '.join(missing)} in .env (see .env.example)")
    if TOKEN_FILE.is_file():
        saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        if saved.get("expires_at", 0) > time.time():
            return saved["access_token"]
        if saved.get("refresh_token"):
            try:
                token = _token_request(config, grant_type="refresh_token",
                                       refresh_token=saved["refresh_token"])
                token.setdefault("refresh_token", saved["refresh_token"])
                _save_token(token)
                return token["access_token"]
            except DownloadError as exc:
                print(f"  saved sign-in could not be renewed ({exc}); signing in again")

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    url = authorize_url(config, state, challenge)
    print("\nSign in to VRoid Hub and approve the application:\n\n  " + url + "\n")
    local = urllib.parse.urlparse(config["VROID_REDIRECT_URI"]).hostname in {"localhost", "127.0.0.1"}
    if paste or not local:
        code = code_from_redirect(input("Paste the full address the browser ended on: "), state)
    else:
        webbrowser.open(url)
        print(f"Waiting for the browser on {config['VROID_REDIRECT_URI']} …")
        code = _wait_for_redirect(config["VROID_REDIRECT_URI"], state)
    token = _token_request(config, grant_type="authorization_code", code=code, code_verifier=verifier)
    _save_token(token)
    print("Signed in; the token is saved in .vroid-token.json.\n")
    return token["access_token"]


def logout(config: dict) -> None:
    if not TOKEN_FILE.is_file():
        print("No saved sign-in.")
        return
    saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    if config.get("VROID_CLIENT_ID") and config.get("VROID_CLIENT_SECRET"):
        _request("POST", f"{HUB}/oauth/revoke", token=saved.get("access_token"), form={
            "client_id": config["VROID_CLIENT_ID"], "client_secret": config["VROID_CLIENT_SECRET"],
            "token": saved.get("access_token", "")})
    TOKEN_FILE.unlink()
    print("Signed out; the saved token is revoked and deleted.")


# ---------------------------------------------------------------- licences
def evaluate(model: dict) -> tuple[dict, list[str]]:
    """(licence summary, reasons to refuse) for one ``character_model`` from VRoid Hub.

    VRM 1.0 models carry their conditions in the VRM meta VRoid Hub reports
    (``latest_character_model_version.vrm_meta``); VRM 0.0 models in ``license``.
    """
    version = model.get("latest_character_model_version") or {}
    meta = version.get("vrm_meta") or {}
    meta = meta.get("vrm10") or meta
    spec = str(version.get("spec_version") or "")
    problems: list[str] = []
    if not model.get("is_downloadable"):
        problems.append("the creator does not allow downloads")
    if not model.get("is_other_users_available"):
        problems.append("the creator does not allow use by other users")

    if "allowRedistribution" in meta or "modification" in meta:
        summary = {
            "spec": spec or "1.0",
            "redistribution": bool(meta.get("allowRedistribution")),
            "modification": meta.get("modification"),
            "avatarUse": meta.get("avatarPermission"),
            "commercialUse": meta.get("commercialUsage"),
            "credit": meta.get("creditNotation"),
            "sexualUse": meta.get("allowExcessivelySexualUsage"),
            "violentUse": meta.get("allowExcessivelyViolentUsage"),
            "licenseUrl": meta.get("licenseUrl"),
            "otherLicenseUrl": meta.get("otherLicenseUrl"),
        }
        modification_ok = summary["modification"] in VRM1_MODIFICATION_OK
    else:
        licence = model.get("license") or {}
        summary = {
            "spec": spec or "0.0",
            "redistribution": licence.get("redistribution") == "allow",
            "modification": licence.get("modification"),
            "avatarUse": licence.get("characterization_allowed_user"),
            "commercialUse": {"corporate": licence.get("corporate_commercial_use"),
                              "personal": licence.get("personal_commercial_use")},
            "credit": licence.get("credit"),
            "sexualUse": licence.get("sexual_expression"),
            "violentUse": licence.get("violent_expression"),
            "licenseUrl": None,
            "otherLicenseUrl": meta.get("otherLicenseUrl") or meta.get("otherPermissionUrl"),
        }
        modification_ok = summary["modification"] in VRM0_MODIFICATION_OK
    if str(summary["otherLicenseUrl"] or "").startswith(f"{HUB}/license"):
        # VRoid Hub's own licence page, restating the conditions above: not extra terms.
        summary["conditionsUrl"], summary["otherLicenseUrl"] = summary["otherLicenseUrl"], None
    if not summary["redistribution"]:
        problems.append("the creator does not allow redistribution")
    if not modification_ok:
        problems.append(f"the creator does not allow modification ({summary['modification']!r})")
    return summary, problems


def model_detail(model_id: str, token: str | None) -> dict:
    status, _, raw = _request("GET", f"{HUB}/api/character_models/{model_id}", token=token)
    payload = _json(status, raw, f"model {model_id}")
    model = (payload.get("data") or {}).get("character_model")
    if not model:
        raise DownloadError(f"model {model_id}: VRoid Hub returned no character_model")
    return model


def snapshot(entry: dict, model: dict, summary: dict) -> dict:
    character = model.get("character") or {}
    return {
        "slug": entry["slug"],
        "name": model.get("name") or entry["name"],
        "character": character.get("name"),
        "creator": (character.get("user") or {}).get("name"),
        "modelId": str(model.get("id") or entry["modelId"]),
        "source": f"{HUB}/en/characters/{character.get('id', '')}/models/{model.get('id', entry['modelId'])}",
        "license": summary,
        "vroidAgeLimit": model.get("age_limit"),
        "checkedAtUtc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- the file
def glb_json(path: Path) -> dict:
    """The JSON chunk of a glTF binary; raises unless the file is glTF 2.0."""
    with path.open("rb") as handle:
        header = handle.read(20)
        if len(header) < 20 or header[:4] != b"glTF":
            raise DownloadError(f"{path.name} is not a glTF binary")
        version, _, chunk_length, chunk_type = struct.unpack("<IIII", header[4:20])
        if version != 2 or chunk_type != 0x4E4F534A:
            raise DownloadError(f"{path.name} is glTF {version} without a leading JSON chunk")
        return json.loads(handle.read(chunk_length).decode("utf-8"))


def embedded_licence(document: dict) -> dict:
    """What the VRM file itself says, VRM 1.0 (VRMC_vrm) or VRM 0.x (VRM)."""
    extensions = document.get("extensions") or {}
    if "VRMC_vrm" in extensions:
        meta = extensions["VRMC_vrm"].get("meta") or {}
        return {"spec": "1.0", "name": meta.get("name"), "authors": meta.get("authors"),
                "redistribution": meta.get("allowRedistribution"), "modification": meta.get("modification")}
    meta = (extensions.get("VRM") or {}).get("meta") or {}
    return {"spec": "0.x", "name": meta.get("title"),
            "authors": [meta.get("author")] if meta.get("author") else [],
            "licenseName": meta.get("licenseName"), "otherPermissionUrl": meta.get("otherPermissionUrl")}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(entry: dict, token: str, out_dir: Path) -> Path:
    status, _, raw = _request("POST", f"{HUB}/api/download_licenses", token=token,
                              body={"character_model_id": entry["modelId"]})
    licence_id = (_json(status, raw, "download licence").get("data") or {}).get("id")
    if not licence_id:
        raise DownloadError("VRoid Hub issued no download licence")
    try:
        status, headers, raw = _request("GET", f"{HUB}/api/download_licenses/{licence_id}/download",
                                        token=token, redirects=False)
        location = headers.get("Location") or headers.get("location")
        if status not in (301, 302, 303, 307, 308) or not location:
            _json(status, raw, "download")  # raises with VRoid Hub's reason
            raise DownloadError(f"download: expected a redirect, got HTTP {status}")
        target = out_dir / f"{entry['slug']}.vrm"
        out_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=out_dir, suffix=".part", delete=False) as part:
            temporary = Path(part.name)
            # The presigned URL is the credential: no bearer token, no API headers.
            with urllib.request.urlopen(location, timeout=TIMEOUT_S * 5) as response:
                shutil.copyfileobj(response, part, 1 << 20)
        try:
            glb_json(temporary)
        except DownloadError:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(target)
        return target
    finally:
        # One file, one licence: invalidate it rather than leave it live until it expires.
        _request("DELETE", f"{HUB}/api/download_licenses/{licence_id}", token=token)


def write_manifest(out_dir: Path, items: list[dict]) -> Path:
    path = out_dir / "models.json"
    existing = json.loads(path.read_text(encoding="utf-8")).get("items", []) if path.is_file() else []
    by_slug = {item["slug"]: item for item in existing}
    by_slug.update({item["slug"]: item for item in items})
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "license_note": ("Downloaded from VRoid Hub by scripts/download.py. Each creator's conditions, "
                         "checked at download time, are in licenses/<slug>.json. The VRM files are not "
                         "committed; run the script to fetch them."),
        "items": [by_slug[slug] for slug in sorted(by_slug)],
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="read each licence only; no sign-in, no download")
    parser.add_argument("--only", help="comma-separated slugs from scripts/vroid_models.json")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help=f"default {OUT_DIR.relative_to(REPO_ROOT)}")
    parser.add_argument("--copy-to", type=Path,
                        help="also copy each file here (e.g. the chatbot's vendor/avatars)")
    parser.add_argument("--force", action="store_true", help="download again even if the file is present")
    parser.add_argument("--paste", action="store_true", help="sign in without a local browser redirect")
    parser.add_argument("--logout", action="store_true", help="revoke and delete the saved token")
    args = parser.parse_args(argv)

    config = read_env()
    config.setdefault("VROID_REDIRECT_URI", DEFAULT_REDIRECT)
    config["VROID_REDIRECT_URI"] = config["VROID_REDIRECT_URI"] or DEFAULT_REDIRECT
    config["VROID_SCOPE"] = config.get("VROID_SCOPE") or "default"
    if args.logout:
        logout(config)
        return 0

    only = {slug.strip() for slug in args.only.split(",")} if args.only else None
    models = load_models(only=only)
    token = None if args.check else access_token(config, paste=args.paste)
    licences = args.out / "licenses"
    items, refused, failed = [], [], []

    for entry in models:
        label = f"{entry['name']} ({entry['slug']})"
        try:
            model = model_detail(entry["modelId"], token)
            summary, problems = evaluate(model)
        except DownloadError as exc:
            failed.append((label, str(exc)))
            print(f"✗ {label}: {exc}")
            continue
        if problems:
            refused.append((label, "; ".join(problems)))
            print(f"✗ {label}: refused — {'; '.join(problems)}")
            continue
        record = snapshot(entry, model, summary)
        other = summary["otherLicenseUrl"]
        extra = f"  extra terms: {other} — read them" if other else ""
        print(f"✓ {label}: redistribution and modification allowed by {record['creator']}{extra}")
        if args.check:
            continue

        target = args.out / f"{entry['slug']}.vrm"
        try:
            if args.force or not target.is_file():
                print("  downloading …")
                download(entry, token, args.out)
            document = glb_json(target)
        except DownloadError as exc:
            failed.append((label, str(exc)))
            print(f"  ✗ {exc}")
            continue
        record["embedded"] = embedded_licence(document)
        if record["embedded"].get("redistribution") is False:
            print("  ! the file itself says redistribution is not allowed; VRoid Hub's listing says it is")
        licences.mkdir(parents=True, exist_ok=True)
        (licences / f"{entry['slug']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        items.append({
            "slug": entry["slug"], "name": record["name"], "file": target.name,
            "presentation": entry.get("presentation", ""), "source": record["source"],
            "license": f"VRoid Hub conditions of use; see licenses/{entry['slug']}.json",
            "creator": record["creator"], "vroidModelId": record["modelId"],
            "bytes": target.stat().st_size, "sha256": sha256_of(target), "glb_version": 2,
        })
        print(f"  {target.relative_to(REPO_ROOT) if target.is_relative_to(REPO_ROOT) else target}"
              f"  {target.stat().st_size / 1e6:.1f} MB")
        if args.copy_to:
            args.copy_to.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, args.copy_to / target.name)
            shutil.copy2(licences / f"{entry['slug']}.json", args.copy_to / f"{entry['slug']}.license.json")

    if items:
        print(f"\nManifest: {write_manifest(args.out, items)}")
    for heading, rows in (("Refused", refused), ("Failed", failed)):
        if rows:
            print(f"\n{heading}:")
            for label, why in rows:
                print(f"  {label}: {why}")
    return 1 if failed or refused else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
