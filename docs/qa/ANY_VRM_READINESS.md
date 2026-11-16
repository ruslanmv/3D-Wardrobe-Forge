# Any-VRM preflight: ordinary clothes versus adult-only body states

The same VRM can support an ordinary outfit without being eligible for an adult body
state. The two questions must not be conflated. This tool reports them separately
for **any local VRM 0.x or 1.0**, without pinning the model in the library or
asking a user to pretend they already have an operator declaration.

```bash
python tools/vrm_compatibility.py /path/to/character.vrm > /tmp/character-readiness.json
python -m pytest -q tests/unit/test_vrm_compatibility.py
```

The resulting JSON gives the exact file SHA-256, VRM version, humanoid rig status,
embedded licence interpretation, and independent `ordinaryClothing`,
`privateClothing`, and `bareBody` statuses. No asset, registry, setting, or
avatar is modified. This is an **advisory preflight**; it never issues a grant
or replaces the server-side verdict.

## What the statuses mean

| Status | What to do |
|---|---|
| `ready-for-wardrobe` | The rig and embedded/attested source terms are sufficient for an ordinary-clothing attempt. Actual fitting, job constraints, and renderer checks still apply. |
| `needs-license-evidence` | Creator modification terms are not established. Obtain the existing licence attestation; do not overwrite a prohibition. |
| `blocked-source-terms` | Embedded author terms prohibit this derivative or sexual-usage category. Use a different, correctly licensed source. |
| `blocked-invalid-rig` | Repair required humanoid bones before fitting any garment. |
| `needs-session-and-operator-check` | A private garment can be considered only after the server verifies the operator's adult declaration and authorized private session. |
| `needs-reviewed-adult-body-assets` | A bare-state build has more prerequisites: approved adult design for the **exact source file**, creator rights, operator opt-in, a complete body, reviewed output, and private import acceptance. None is assumed or granted by this CLI. |

Ordinary opaque garments **do not need an adult-design review**. Their
usual modification rights, VRM rigging, fitting, and rendering checks still apply.
An age-ambiguous model is not thereby eligible for sexualized or bare-body
rendering.

For approved adult characters and body states, follow
`docs/qa/ADULT_CHARACTER_INTAKE.md` and
`docs/qa/BARE_STATE_HANDOFF.md`. Adult-design reviews and permission
records must be genuine; creating a file or flipping a local CLI flag
never substitutes for them.
