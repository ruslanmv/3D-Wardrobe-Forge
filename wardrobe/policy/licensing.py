class ModificationNotPermitted(ValueError):
    pass


def require_modification_permission(metadata: dict) -> None:
    """Reject a source that explicitly prohibits modification."""
    value = str((metadata or {}).get("modification", "")).strip().lower()
    if value in {"disallowed", "prohibited", "no", "false"}:
        raise ModificationNotPermitted("source avatar terms prohibit modification")
