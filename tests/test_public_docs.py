"""Executable contracts for the active portfolio documentation."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ACTIVE_DOCS = (
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("COMMERCIAL-LICENSE.md"),
    Path("THIRD_PARTY_NOTICES.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/DATASET_CONTRACT.md"),
    Path("docs/EVAL_RELEASE.md"),
    Path("docs/PRIVACY.md"),
    Path("docs/ROADMAP.md"),
    Path("docs/READER_DECISION.md"),
    Path("samples/README.md"),
    Path("assets/fonts/README.md"),
    Path("assets/fonts/FONTS.md"),
)

_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\((?P<target>[^)]+)\)")
_MAKE_LINE = re.compile(r"(?m)^\s*(?:[$>]\s*)?make\s+(?P<target>[A-Za-z0-9_.-]+)\b")
_MAKE_INLINE = re.compile(r"`make\s+(?P<target>[A-Za-z0-9_.-]+)\b[^`]*`")
_PYTHON_MODULE = re.compile(r"uv run --locked python -m (?P<module>[a-zA-Z0-9_.]+)")
_PYTHON_FILE = re.compile(r"(?:uv run --locked )?python\s+(?P<path>[a-zA-Z0-9_./-]+\.py)\b")


def _documents() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in ACTIVE_DOCS}


def _local_link_path(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith("#"):
        return None
    relative = unquote(parsed.path)
    if not relative:
        return None
    return (document.parent / Path(relative)).resolve(strict=False)


def test_every_active_document_exists() -> None:
    missing = [path.as_posix() for path in ACTIVE_DOCS if not path.is_file()]
    assert not missing


def test_active_markdown_has_no_broken_local_link() -> None:
    root = Path.cwd().resolve(strict=True)
    broken: list[str] = []
    escaped: list[str] = []
    for document, text in _documents().items():
        for match in _MARKDOWN_LINK.finditer(text):
            target = _local_link_path(document, match.group("target"))
            if target is None:
                continue
            if not target.is_relative_to(root):
                escaped.append(f"{document.as_posix()} -> {target}")
            elif not target.exists():
                broken.append(f"{document.as_posix()} -> {target.relative_to(root).as_posix()}")
    assert not escaped
    assert not broken


def test_documented_make_commands_name_real_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"(?m)^([A-Za-z0-9_.-]+):(?:\s|$)", makefile))
    missing: list[str] = []
    for document, text in _documents().items():
        referenced = {
            match.group("target")
            for pattern in (_MAKE_LINE, _MAKE_INLINE)
            for match in pattern.finditer(text)
        }
        missing.extend(
            f"{document.as_posix()}: make {target}" for target in sorted(referenced - targets)
        )
    assert not missing


def test_documented_python_entrypoints_exist() -> None:
    missing: list[str] = []
    for document, text in _documents().items():
        for match in _PYTHON_MODULE.finditer(text):
            module = match.group("module")
            candidate = Path(*module.split(".")).with_suffix(".py")
            package = Path(*module.split("."), "__init__.py")
            if not candidate.is_file() and not package.is_file():
                missing.append(f"{document.as_posix()}: {module}")
        for match in _PYTHON_FILE.finditer(text):
            candidate = Path(match.group("path"))
            if not candidate.is_file():
                missing.append(f"{document.as_posix()}: {candidate.as_posix()}")
    assert not missing


def test_active_uv_commands_use_the_lockfile() -> None:
    unlocked: list[str] = []
    for document, text in _documents().items():
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "uv run " in line and "uv run --locked " not in line:
                unlocked.append(f"{document.as_posix()}:{line_number}")
    assert not unlocked


def test_active_docs_do_not_advertise_retired_runtime_names() -> None:
    retired = {
        "Anthropic": re.compile(r"\banthropic\b", re.IGNORECASE),
        "BRESSAY": re.compile(r"\bbressay\b", re.IGNORECASE),
        "HT Micron form": re.compile(r"\bht\s*micron\b|\bhtmicron_security\b", re.IGNORECASE),
        "local VLM": re.compile(r"\blocal_vlm\b|\bvlm\b", re.IGNORECASE),
        "Ollama": re.compile(r"\bollama\b", re.IGNORECASE),
        "Paddle reader": re.compile(r"\bpaddle(?:ocr)?\b", re.IGNORECASE),
        "Qwen reader": re.compile(r"\bqwen[\w.:-]*\b", re.IGNORECASE),
        "scikit-learn": re.compile(r"\bscikit-learn\b|\bsklearn\b", re.IGNORECASE),
    }
    found: list[str] = []
    for document, text in _documents().items():
        found.extend(
            f"{document.as_posix()}: {label}"
            for label, pattern in retired.items()
            if pattern.search(text)
        )
    assert not found


def test_showcase_docs_have_no_internal_ticket_markers_or_two_form_claim() -> None:
    found: list[str] = []
    for document, text in _documents().items():
        if re.search(r"\bSSI-\d+\b", text):
            found.append(f"{document.as_posix()}: internal ticket")
        if re.search(r"\btwo (?:report|form) types?\b", text, re.IGNORECASE):
            found.append(f"{document.as_posix()}: two-form claim")
    assert not found


def test_readme_uses_source_available_language_without_open_source_claim() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "source-available" in readme
    assert re.search(r"\bopen[- ]source\b", readme, re.IGNORECASE) is None
    assert "PENDING" not in readme


def test_current_showcase_asset_is_presented_with_honest_provenance() -> None:
    readme = " ".join(Path("README.md").read_text(encoding="utf-8").split())
    samples = " ".join(Path("samples/README.md").read_text(encoding="utf-8").split())

    assert "current v1.1 capture" in readme.lower()
    assert "real Chromium smoke flow" in readme
    assert "demonstrate product behavior and layout, not OCR accuracy" in samples
    assert "FakeDocumentReader" in samples
