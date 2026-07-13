"""Repository-anchored locations for runtime data that may contain PII."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = REPO_ROOT / "private"


def resolve_private_path(path: Path, *, create_root: bool = False) -> Path:
    """Resolve a sensitive path fail-closed under the real repository private root."""
    root_absolute = PRIVATE_ROOT.absolute()
    candidate_absolute = path.expanduser().absolute()
    if not candidate_absolute.is_relative_to(root_absolute):
        raise ValueError("Sensitive path must stay under the repository private/ directory.")

    if create_root:
        root_absolute.mkdir(parents=True, exist_ok=True)
    if not root_absolute.exists():
        return candidate_absolute

    root_resolved = root_absolute.resolve(strict=True)
    if root_resolved != root_absolute:
        raise ValueError("Repository private/ directory must not be redirected.")
    candidate_resolved = candidate_absolute.resolve(strict=False)
    if not candidate_resolved.is_relative_to(root_resolved):
        raise ValueError("Sensitive path must stay under the repository private/ directory.")
    return candidate_resolved
