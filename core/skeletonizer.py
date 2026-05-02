"""
Source skeletonization.

Token saving:
- A file skeleton keeps imports, class headers, and function signatures.
- Bodies are omitted from the reusable static context unless explicitly needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.chunker import smart_chunk
from core.sieve import SieveResult, parse_file, parse_source

logger = logging.getLogger("vibeflow.skeletonizer")


def skeletonize_file(file_path: str | Path, language: str = "python") -> str:
    result = parse_file(file_path, language)
    return _result_to_skeleton(result, file_path)


def skeletonize_source(source: str, language: str = "python", file_path: str = "<string>") -> str:
    result = parse_source(source, language, file_path)
    return _result_to_skeleton(result, file_path, source=source)


def _result_to_skeleton(
    result: SieveResult,
    file_path: str | Path,
    source: str | None = None,
) -> str:
    path = Path(file_path)
    if not result.parse_ok:
        logger.warning("AST parse failed for %s; using smart chunking fallback", path)
        if source is None and path.exists():
            source = path.read_text(encoding="utf-8", errors="replace")
        if source:
            chunks = smart_chunk(source)
            preview = chunks[0] if chunks else ""
            return (
                "# FALLBACK: smart chunking (AST unavailable)\n"
                f"# {path.name}: first chunk only; {len(chunks)} chunks total\n\n"
                f"{preview}"
            )
        return "\n".join(f"# {warning}" for warning in result.warnings)

    skeleton = result.skeleton
    original_lines = _count_lines(path, source)
    skeleton_lines = skeleton.count("\n") + 1 if skeleton else 0
    original_tokens = _estimate_tokens(source) if source is not None else _estimate_file_tokens(path)
    skeleton_tokens = _estimate_tokens(skeleton)
    saved = _saving_percent(original_tokens, skeleton_tokens)

    header = (
        f"# skeleton of {path.name}: {original_lines} lines -> {skeleton_lines} lines, "
        f"~{saved:.1f}% token saving"
    )
    warnings = "\n".join(f"# {warning}" for warning in result.warnings)
    body = "\n".join(part for part in (warnings, skeleton) if part.strip())
    return f"{header}\n{body}".rstrip()


def _count_lines(path: Path, source: str | None) -> int:
    if source is not None:
        return source.count("\n") + 1 if source else 0
    try:
        return path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
    except OSError:
        return 0


def _estimate_file_tokens(path: Path) -> int:
    try:
        return _estimate_tokens(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _estimate_tokens(text: str) -> int:
    from config import CHARS_PER_TOKEN

    return max(1, int(len(text) / CHARS_PER_TOKEN)) if text else 0


def _saving_percent(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return max(0.0, (before - after) / before * 100.0)


def skeletonize_directory(
    directory: str | Path,
    language: str = "python",
    extensions: set[str] | None = None,
) -> dict[str, str]:
    from config import IGNORED_DIRS, SUPPORTED_EXTENSIONS

    root = Path(directory)
    if extensions is None:
        extensions = {ext for ext, lang in SUPPORTED_EXTENSIONS.items() if lang == language}

    skeletons: dict[str, str] = {}
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in extensions:
            skeletons[str(path.relative_to(root))] = skeletonize_file(path, language)
    return skeletons
