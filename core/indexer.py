"""
Project indexing.

Token saving:
- The index stores skeletons, not full source, for the static cache.
- Semantic search works over compact structural text plus path metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from config import IGNORED_DIRS, SUPPORTED_EXTENSIONS
from core.chunker import smart_chunk
from core.sieve import SieveResult, parse_file
from storage.vector_cache import VectorCache


@dataclass(slots=True)
class IndexedFile:
    path: Path
    relative_path: str
    language: str
    sieve: SieveResult
    compact_text: str
    indexed_at: float

    @property
    def skeleton(self) -> str:
        return self.compact_text


@dataclass
class ProjectIndex:
    root: Path
    vector_cache: VectorCache = field(default_factory=VectorCache)
    files: dict[str, IndexedFile] = field(default_factory=dict)

    def index_project(self) -> int:
        count = 0
        for path in self.root.rglob("*"):
            if _ignored(path):
                continue
            if path.is_file() and path.suffix in SUPPORTED_EXTENSIONS:
                if self.index_file(path):
                    count += 1
        return count

    def index_file(self, path: str | Path) -> bool:
        file_path = Path(path)
        if _ignored(file_path) or not file_path.exists() or not file_path.is_file():
            return False
        language = SUPPORTED_EXTENSIONS.get(file_path.suffix)
        if language is None:
            return False

        sieve = parse_file(file_path, language)
        compact_text = _compact_text(file_path, sieve)
        try:
            relative_path = str(file_path.relative_to(self.root))
        except ValueError:
            relative_path = str(file_path)

        indexed = IndexedFile(
            path=file_path,
            relative_path=relative_path,
            language=language,
            sieve=sieve,
            compact_text=compact_text,
            indexed_at=perf_counter(),
        )
        self.files[relative_path] = indexed

        text = f"{relative_path}\n{indexed.skeleton}"
        self.vector_cache.upsert(
            doc_id=relative_path,
            text=text,
            metadata={
                "path": relative_path,
                "language": language,
                "parse_ok": sieve.parse_ok,
            },
        )
        return True

    def remove_file(self, path: str | Path) -> None:
        file_path = Path(path)
        try:
            relative_path = str(file_path.relative_to(self.root))
        except ValueError:
            relative_path = str(file_path)
        self.files.pop(relative_path, None)
        self.vector_cache.delete(relative_path)

    def semantic_matches(self, query: str, top_k: int | None = None) -> list[IndexedFile]:
        documents = self.vector_cache.query(query, top_k=top_k or 20)
        matches: list[IndexedFile] = []
        for document in documents:
            path = str(document.metadata.get("path", document.doc_id))
            indexed = self.files.get(path)
            if indexed:
                matches.append(indexed)
        return matches


def _ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _compact_text(path: Path, sieve: SieveResult) -> str:
    if sieve.parse_ok:
        return sieve.skeleton

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "\n".join(sieve.warnings)

    chunks = smart_chunk(source)
    preview = chunks[0] if chunks else ""
    warnings = "\n".join(sieve.warnings)
    return (
        "# FALLBACK: smart chunking (AST unavailable)\n"
        f"{warnings}\n"
        f"{preview}"
    ).strip()
