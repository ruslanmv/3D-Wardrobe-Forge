# scripts

## `download.py` — VRoid Hub models, with their licences

Downloads the models listed in `vroid_models.json` into
`assets/library/vroid/`, after checking each creator's current conditions on
VRoid Hub. Standard library only.

```bash
cp .env.example .env            # then fill VROID_CLIENT_ID and VROID_CLIENT_SECRET
python scripts/download.py --check   # licences only: no sign-in, nothing downloaded
python scripts/download.py           # sign in once in the browser, then download
```

Useful options:

| Option | Does |
| --- | --- |
| `--only vroid-helen,vroid-boy-g` | just these slugs |
| `--copy-to ../3D-Avatar-Chatbot/vendor/avatars` | also copy each VRM and its licence there |
| `--force` | download again even if the file is present |
| `--paste` | no local browser: open the printed URL anywhere, paste back the address it ends on |
| `--logout` | revoke and delete the saved token |

**Sign-in.** VRoid Hub only lets a signed-in user download, through OAuth
authorization code + PKCE. The app ID and secret identify the application; they
cannot download anything alone. The script opens the browser, catches the
redirect on `VROID_REDIRECT_URI` (default `http://localhost:18927/callback`,
which must be registered on the application), and saves the token to
`.vroid-token.json` (gitignored, refreshed automatically).

**What gets refused.** A model is downloaded only if it is downloadable,
available to other users, and its creator allows both redistribution and
modification — this repository re-cuts the file to dress it and serves the
looks it makes. The list is a request, not a permission: the check runs against
VRoid Hub every time. Where a creator links extra terms (Celeste, Auralithis),
the script prints the link; read it.

**What it writes.**

```text
assets/library/vroid/
├── <slug>.vrm              gitignored, like every library VRM
├── licenses/<slug>.json    dated snapshot: creator, conditions, VRoid's age flags, the file's own licence
└── models.json             size and SHA-256 of each file (same shape as assets/library/models.json)
```

Commit `models.json` and `licenses/`; they are the provenance. The VRMs stay
out of git for the same reason the library's do (size, and a Hugging Face
Space refuses plain-git files over 10 MB).

**Your application's registration.** VRoid Hub registers what an application
may do with the models it loads — redistribution, alterations, commercial use,
use as an avatar — and its developer terms require an application to stay
within those settings. Make sure the application whose credentials you use is
registered for what this repository does with the files.

**Adulthood is not declared here.** Downloading a model makes it available,
nothing more. Private outfits stay off for it until the operator declares it in
`assets/library/policy.json`, as for every library avatar.
