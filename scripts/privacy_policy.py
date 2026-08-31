"""Fail-closed privacy exception for the committed v1.1 safety corpus.

The corpus contains PNG evidence, so the general privacy policy must reject it unless
the *complete* tree is authenticated.  A path prefix is never sufficient: callers get
an allowlist only after the canonical inventory, manifest freeze, provenance, Git index,
and worktree bytes have all agreed.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from data.safety_corpus import (
    INVENTORY_NAME,
    PROVENANCE_NAME,
    SAFETY_COUNT,
    SAFETY_SPLIT,
    VerifiedSafetyCorpus,
    load_verified_safety_corpus,
    parse_inventory_pin,
)
from data.safety_corpus import (
    SAFETY_CORPUS_PIN_RELATIVE as _DATA_SAFETY_CORPUS_PIN_RELATIVE,
)
from data.tier_c_contract import (
    SAFETY_LOGICAL_FREEZE_RELATIVE as _DATA_SAFETY_LOGICAL_FREEZE_RELATIVE,
)
from data.tier_c_contract import (
    TierCContractError,
    parse_logical_freeze,
)

SAFETY_CORPUS_RELATIVE = Path("data", "eval_corpora", "v1.1", "bench-balanced-val")
SAFETY_CORPUS_PIN_RELATIVE = _DATA_SAFETY_CORPUS_PIN_RELATIVE
SAFETY_LOGICAL_FREEZE_RELATIVE = _DATA_SAFETY_LOGICAL_FREEZE_RELATIVE
_SAFETY_CORPUS_POSIX = PurePosixPath(SAFETY_CORPUS_RELATIVE.as_posix())
_REGULAR_INDEX_MODE = "100644"
_OBJECT_ID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class CorpusPrivacyError(RuntimeError):
    """The public safety corpus could not earn its narrow privacy exception."""


@dataclass(frozen=True)
class AuthenticatedSafetyCorpus:
    """Exact repository paths and hashes admitted by the corpus contract."""

    sha256_by_path: dict[Path, str]

    @property
    def members(self) -> frozenset[Path]:
        return frozenset(self.sha256_by_path)

    def accepts(self, path: Path, content: bytes) -> bool:
        expected = self.sha256_by_path.get(path)
        return expected is not None and sha256(content).hexdigest() == expected


def is_safety_corpus_path(path: Path) -> bool:
    """Return whether a repository-relative path is inside the exact v1.1 root."""
    if path.is_absolute():
        return False
    try:
        path.relative_to(SAFETY_CORPUS_RELATIVE)
    except ValueError:
        return False
    return path != SAFETY_CORPUS_RELATIVE


def is_safety_corpus_pin_path(path: Path) -> bool:
    """Match only the one external inventory-pin path."""
    return not path.is_absolute() and path == SAFETY_CORPUS_PIN_RELATIVE


def corpus_path_exists(repository_root: Path) -> bool:
    """Check for the corpus root without following a broken redirect."""
    try:
        (repository_root / SAFETY_CORPUS_RELATIVE).lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _is_redirected(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CorpusPrivacyError("corpus path metadata could not be read") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _collect_plain_worktree_files(repository_root: Path) -> dict[Path, bytes]:
    """Read a plain, complete corpus worktree without traversing redirects."""
    corpus_root = repository_root / SAFETY_CORPUS_RELATIVE
    current = repository_root
    for part in SAFETY_CORPUS_RELATIVE.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CorpusPrivacyError("corpus worktree is missing or unreadable") from exc
        if _is_redirected(current) or not stat.S_ISDIR(metadata.st_mode):
            raise CorpusPrivacyError("corpus worktree contains a redirected directory")

    files: dict[Path, bytes] = {}

    def unreadable(_error: OSError) -> None:
        raise CorpusPrivacyError("corpus worktree could not be enumerated")

    for directory, dirnames, filenames in os.walk(
        corpus_root, topdown=True, followlinks=False, onerror=unreadable
    ):
        parent = Path(directory)
        for name in dirnames:
            candidate = parent / name
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise CorpusPrivacyError("corpus directory metadata could not be read") from exc
            if _is_redirected(candidate) or not stat.S_ISDIR(metadata.st_mode):
                raise CorpusPrivacyError("corpus worktree contains a redirected directory")
        for name in filenames:
            candidate = parent / name
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise CorpusPrivacyError("corpus member metadata could not be read") from exc
            if _is_redirected(candidate) or not stat.S_ISREG(metadata.st_mode):
                raise CorpusPrivacyError("corpus worktree contains a redirected member")
            relative = candidate.relative_to(repository_root)
            try:
                files[relative] = candidate.read_bytes()
            except OSError as exc:
                raise CorpusPrivacyError("corpus member could not be read") from exc
    return files


def _read_plain_repository_file(
    repository_root: Path,
    relative: Path,
    *,
    label: str = "external corpus pin",
) -> bytes:
    """Read one regular repository file with no redirected path component."""
    current = repository_root
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CorpusPrivacyError(f"{label} is missing or unreadable") from exc
        if _is_redirected(current):
            raise CorpusPrivacyError(f"{label} path is redirected")
        expected_kind = stat.S_ISREG if index == len(relative.parts) - 1 else stat.S_ISDIR
        if not expected_kind(metadata.st_mode):
            raise CorpusPrivacyError(f"{label} path has an invalid file type")
        if index == len(relative.parts) - 1 and metadata.st_mode & 0o111:
            raise CorpusPrivacyError(f"{label} worktree mode is not a regular 100644 file")
    try:
        return current.read_bytes()
    except OSError as exc:
        raise CorpusPrivacyError(f"{label} could not be read") from exc


def _expected_repository_members(verified: VerifiedSafetyCorpus) -> frozenset[Path]:
    within_corpus = {
        Path(INVENTORY_NAME),
        Path(PROVENANCE_NAME),
        Path("meta.json"),
        Path("manifests", f"{SAFETY_SPLIT}.jsonl"),
        *(Path(*PurePosixPath(entry.image).parts) for entry in verified.split.entries),
        *(Path(*PurePosixPath(entry.gt).parts) for entry in verified.split.entries),
    }
    return frozenset(SAFETY_CORPUS_RELATIVE / member for member in within_corpus)


def _authenticate_files(
    files: dict[Path, bytes],
    validation_root: Path,
    pin_path: Path,
    logical_freeze_path: Path,
) -> AuthenticatedSafetyCorpus:
    try:
        verified = load_verified_safety_corpus(
            validation_root,
            pin_path=pin_path,
            logical_freeze_path=logical_freeze_path,
        )
    except (TierCContractError, OSError, UnicodeError, ValueError) as exc:
        raise CorpusPrivacyError("canonical safety corpus validation failed") from exc
    expected = _expected_repository_members(verified)
    if set(files) != expected:
        raise CorpusPrivacyError("corpus members differ from the authenticated inventory")
    return AuthenticatedSafetyCorpus(
        {path: sha256(content).hexdigest() for path, content in files.items()}
    )


def authenticate_worktree_safety_corpus(repository_root: Path) -> AuthenticatedSafetyCorpus:
    """Authenticate the exact corpus files present in a public worktree."""
    _require_committed_logical_freeze(repository_root)
    _require_committed_inventory_pin(repository_root)
    files = _collect_plain_worktree_files(repository_root)
    return _authenticate_files(
        files,
        repository_root / SAFETY_CORPUS_RELATIVE,
        repository_root / SAFETY_CORPUS_PIN_RELATIVE,
        repository_root / SAFETY_LOGICAL_FREEZE_RELATIVE,
    )


def _portable_index_member(raw_path: bytes) -> tuple[Path, Path]:
    try:
        value = raw_path.decode("utf-8")
    except UnicodeError as exc:
        raise CorpusPrivacyError("corpus index path is not UTF-8") from exc
    if not value or "\\" in value or ":" in value:
        raise CorpusPrivacyError("corpus index path is not portable")
    portable = PurePosixPath(value)
    if (
        portable.is_absolute()
        or portable.as_posix() != value
        or any(part in {"", ".", ".."} for part in portable.parts)
    ):
        raise CorpusPrivacyError("corpus index path is not portable")
    try:
        member = portable.relative_to(_SAFETY_CORPUS_POSIX)
    except ValueError as exc:
        raise CorpusPrivacyError("corpus index member escapes its canonical root") from exc
    if not member.parts:
        raise CorpusPrivacyError("corpus index member is not a file")
    return Path(*portable.parts), Path(*member.parts)


def _index_listing(repository_root: Path) -> bytes:
    try:
        return subprocess.run(
            [
                "git",
                "ls-files",
                "--stage",
                "-z",
                "--",
                SAFETY_CORPUS_RELATIVE.as_posix(),
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CorpusPrivacyError("Git index corpus members could not be enumerated") from exc


def _index_records(repository_root: Path) -> list[tuple[Path, Path]]:
    output = _index_listing(repository_root)
    records: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for raw_record in (record for record in output.split(b"\0") if record):
        try:
            header, raw_path = raw_record.split(b"\t", maxsplit=1)
            mode, object_id, stage = header.decode("ascii").split()
        except (ValueError, UnicodeError) as exc:
            raise CorpusPrivacyError("Git index corpus record is malformed") from exc
        repository_path, member = _portable_index_member(raw_path)
        if (
            mode != _REGULAR_INDEX_MODE
            or stage != "0"
            or _OBJECT_ID_RE.fullmatch(object_id) is None
            or repository_path in seen
        ):
            raise CorpusPrivacyError("Git index corpus member is not a unique regular file")
        seen.add(repository_path)
        records.append((repository_path, member))
    if not records:
        raise CorpusPrivacyError("Git index does not contain the canonical safety corpus")
    return records


def _index_blob(repository_root: Path, path: Path) -> bytes:
    try:
        return subprocess.run(
            ["git", "cat-file", "blob", f":{path.as_posix()}"],
            cwd=repository_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CorpusPrivacyError("Git index corpus blob could not be read") from exc


def _head_blob(repository_root: Path, path: Path, *, label: str = "external corpus pin") -> bytes:
    try:
        return subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{path.as_posix()}"],
            cwd=repository_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CorpusPrivacyError(f"required {label} is not committed in HEAD") from exc


def _head_exists(repository_root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if result.returncode not in {0, 1}:
        raise CorpusPrivacyError("Git HEAD could not be inspected")
    return result.returncode == 0


def _head_path_exists(repository_root: Path, path: Path) -> bool:
    if not _head_exists(repository_root):
        return False
    result = subprocess.run(
        [
            "git",
            "cat-file",
            "-e",
            f"HEAD:{path.as_posix()}",
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if result.returncode not in {0, 1, 128}:
        raise CorpusPrivacyError("external corpus pin history could not be inspected")
    return result.returncode == 0


def _head_pin_exists(repository_root: Path) -> bool:
    return _head_path_exists(repository_root, SAFETY_CORPUS_PIN_RELATIVE)


def _git_path_listing(repository_root: Path, args: list[str], *, label: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repository_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CorpusPrivacyError(f"{label} Git metadata could not be read") from exc


def _index_regular_blob(repository_root: Path, path: Path, *, label: str) -> bytes:
    output = _git_path_listing(
        repository_root,
        ["ls-files", "--stage", "-z", "--", path.as_posix()],
        label=label,
    )
    records = [record for record in output.split(b"\0") if record]
    if len(records) != 1:
        raise CorpusPrivacyError(f"{label} is not a unique regular file in the Git index")
    try:
        header, raw_path = records[0].split(b"\t", maxsplit=1)
        mode, object_id, stage = header.decode("ascii").split()
        indexed_path = raw_path.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise CorpusPrivacyError(f"{label} Git index record is malformed") from exc
    if (
        indexed_path != path.as_posix()
        or mode != _REGULAR_INDEX_MODE
        or stage != "0"
        or _OBJECT_ID_RE.fullmatch(object_id) is None
    ):
        raise CorpusPrivacyError(f"{label} is not a regular 100644 file in the Git index")
    return _index_blob(repository_root, path)


def _head_regular_blob(repository_root: Path, path: Path, *, label: str) -> bytes:
    output = _git_path_listing(
        repository_root,
        ["ls-tree", "-z", "HEAD", "--", path.as_posix()],
        label=label,
    )
    records = [record for record in output.split(b"\0") if record]
    if len(records) != 1:
        raise CorpusPrivacyError(f"required {label} is not committed in HEAD")
    try:
        header, raw_path = records[0].split(b"\t", maxsplit=1)
        mode, object_type, object_id = header.decode("ascii").split()
        committed_path = raw_path.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise CorpusPrivacyError(f"{label} HEAD record is malformed") from exc
    if (
        committed_path != path.as_posix()
        or mode != _REGULAR_INDEX_MODE
        or object_type != "blob"
        or _OBJECT_ID_RE.fullmatch(object_id) is None
    ):
        raise CorpusPrivacyError(f"{label} is not a regular 100644 file in HEAD")
    return _head_blob(repository_root, path, label=label)


def _validate_logical_freeze_content(content: bytes) -> None:
    with TemporaryDirectory(prefix="ssi-logical-freeze-") as temporary:
        freeze_path = Path(temporary) / SAFETY_LOGICAL_FREEZE_RELATIVE.name
        freeze_path.write_bytes(content)
        try:
            entries = parse_logical_freeze(freeze_path, expected_split=SAFETY_SPLIT)
        except TierCContractError as exc:
            raise CorpusPrivacyError("logical safety freeze is not canonical") from exc
    if len(entries) != SAFETY_COUNT:
        raise CorpusPrivacyError(
            f"logical safety freeze has {len(entries)} entries, expected {SAFETY_COUNT}"
        )


def _require_committed_logical_freeze(repository_root: Path) -> bytes:
    label = "logical safety freeze"
    head_content = _head_regular_blob(
        repository_root,
        SAFETY_LOGICAL_FREEZE_RELATIVE,
        label=label,
    )
    index_content = _index_regular_blob(
        repository_root,
        SAFETY_LOGICAL_FREEZE_RELATIVE,
        label=label,
    )
    if index_content != head_content:
        raise CorpusPrivacyError("logical safety freeze index differs from HEAD")
    worktree_content = _read_plain_repository_file(
        repository_root,
        SAFETY_LOGICAL_FREEZE_RELATIVE,
        label=label,
    )
    if worktree_content != head_content:
        raise CorpusPrivacyError("logical safety freeze worktree differs from HEAD")
    _validate_logical_freeze_content(head_content)
    return head_content


def _require_committed_inventory_pin(repository_root: Path) -> bytes:
    label = "external corpus pin"
    head_content = _head_regular_blob(
        repository_root,
        SAFETY_CORPUS_PIN_RELATIVE,
        label=label,
    )
    index_content = _index_regular_blob(
        repository_root,
        SAFETY_CORPUS_PIN_RELATIVE,
        label=label,
    )
    if index_content != head_content:
        raise CorpusPrivacyError("external corpus pin index differs from HEAD")
    worktree_content = _read_plain_repository_file(
        repository_root,
        SAFETY_CORPUS_PIN_RELATIVE,
        label=label,
    )
    if worktree_content != head_content:
        raise CorpusPrivacyError("external corpus pin worktree differs from HEAD")
    try:
        parse_inventory_pin(head_content)
    except TierCContractError as exc:
        raise CorpusPrivacyError("committed external corpus pin is invalid") from exc
    return head_content


def _staged_delta_paths(repository_root: Path) -> frozenset[Path]:
    output = _git_path_listing(
        repository_root,
        ["diff", "--cached", "--name-only", "--no-renames", "-z"],
        label="staged delta",
    )
    paths: set[Path] = set()
    for raw_path in (record for record in output.split(b"\0") if record):
        try:
            value = raw_path.decode("utf-8")
        except UnicodeError as exc:
            raise CorpusPrivacyError("staged delta path is not UTF-8") from exc
        portable = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or ":" in value
            or portable.is_absolute()
            or portable.as_posix() != value
            or any(part in {"", ".", ".."} for part in portable.parts)
        ):
            raise CorpusPrivacyError("staged delta path is not portable")
        paths.add(Path(*portable.parts))
    return frozenset(paths)


def _head_corpus_exists(repository_root: Path) -> bool:
    if not _head_exists(repository_root):
        return False
    output = _git_path_listing(
        repository_root,
        [
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            "HEAD",
            "--",
            SAFETY_CORPUS_RELATIVE.as_posix(),
        ],
        label="safety corpus",
    )
    return bool(output)


def validate_staged_logical_freeze(
    repository_root: Path,
    *,
    pin_changed: bool,
    corpus_changed: bool,
) -> None:
    """Permit one canonical freeze-only commit before both pin and corpus."""
    if _head_path_exists(repository_root, SAFETY_LOGICAL_FREEZE_RELATIVE):
        raise CorpusPrivacyError("logical safety freeze is write-once")
    if pin_changed or corpus_changed:
        raise CorpusPrivacyError("logical safety freeze, pin, and corpus need separate commits")
    if _head_pin_exists(repository_root) or _head_corpus_exists(repository_root):
        raise CorpusPrivacyError("logical safety freeze must precede the pin and corpus")
    if _staged_delta_paths(repository_root) != frozenset({SAFETY_LOGICAL_FREEZE_RELATIVE}):
        raise CorpusPrivacyError("logical safety freeze must be the only staged delta")
    content = _index_regular_blob(
        repository_root,
        SAFETY_LOGICAL_FREEZE_RELATIVE,
        label="logical safety freeze",
    )
    worktree_content = _read_plain_repository_file(
        repository_root,
        SAFETY_LOGICAL_FREEZE_RELATIVE,
        label="logical safety freeze",
    )
    if worktree_content != content:
        raise CorpusPrivacyError("logical safety freeze worktree differs from the Git index")
    _validate_logical_freeze_content(content)


def validate_staged_inventory_pin(
    repository_root: Path,
    *,
    corpus_changed: bool,
    freeze_changed: bool = False,
) -> None:
    """Permit only the first, corpus-free commit of a canonical external pin."""
    if corpus_changed:
        raise CorpusPrivacyError("external corpus pin and corpus must use separate commits")
    if freeze_changed:
        raise CorpusPrivacyError("logical safety freeze and pin must use separate commits")
    if _staged_delta_paths(repository_root) != frozenset({SAFETY_CORPUS_PIN_RELATIVE}):
        raise CorpusPrivacyError("external corpus pin must be the only staged delta")
    _require_committed_logical_freeze(repository_root)
    if _head_pin_exists(repository_root):
        raise CorpusPrivacyError("external corpus pin is write-once")
    try:
        pin_content = _index_blob(repository_root, SAFETY_CORPUS_PIN_RELATIVE)
        parse_inventory_pin(pin_content)
    except (CorpusPrivacyError, TierCContractError) as exc:
        raise CorpusPrivacyError("new external corpus pin is invalid") from exc
    if _index_listing(repository_root):
        raise CorpusPrivacyError("external corpus pin must precede the corpus commit")


def authenticate_index_safety_corpus(repository_root: Path) -> AuthenticatedSafetyCorpus:
    """Authenticate a complete index snapshot and require identical worktree bytes."""
    head_freeze = _require_committed_logical_freeze(repository_root)
    records = _index_records(repository_root)
    worktree_files = _collect_plain_worktree_files(repository_root)
    head_pin = _require_committed_inventory_pin(repository_root)
    index_files: dict[Path, bytes] = {}

    with TemporaryDirectory(prefix="ssi-corpus-index-") as temporary:
        snapshot_root = Path(temporary) / "repository"
        validation_root = snapshot_root / SAFETY_CORPUS_RELATIVE
        pin_path = snapshot_root / SAFETY_CORPUS_PIN_RELATIVE
        logical_freeze_path = snapshot_root / SAFETY_LOGICAL_FREEZE_RELATIVE
        pin_path.parent.mkdir(parents=True, exist_ok=True)
        pin_path.write_bytes(head_pin)
        logical_freeze_path.parent.mkdir(parents=True, exist_ok=True)
        logical_freeze_path.write_bytes(head_freeze)
        for repository_path, member in records:
            content = _index_blob(repository_root, repository_path)
            index_files[repository_path] = content
            destination = validation_root / member
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

        if set(worktree_files) != set(index_files) or any(
            worktree_files[path] != content for path, content in index_files.items()
        ):
            raise CorpusPrivacyError("corpus worktree differs from the Git index snapshot")
        return _authenticate_files(
            index_files,
            validation_root,
            pin_path,
            logical_freeze_path,
        )
