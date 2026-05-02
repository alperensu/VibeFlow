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
from core.sieve import FunctionInfo, SieveResult, TypeInfo, parse_file
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


@dataclass(slots=True)
class SymbolRef:
    symbol_id: str
    name: str
    kind: str
    relative_path: str
    signature: str
    body: str
    skeleton: str
    calls: set[str]
    start_line: int
    end_line: int
    score: float = 0.0

    @property
    def dynamic_text(self) -> str:
        if self.kind == "function":
            return f"{self.signature}\n{self.body}".rstrip()
        return self.skeleton


@dataclass
class ProjectIndex:
    root: Path
    vector_cache: VectorCache = field(default_factory=VectorCache)
    files: dict[str, IndexedFile] = field(default_factory=dict)
    symbols: dict[str, SymbolRef] = field(default_factory=dict)
    symbols_by_name: dict[str, list[SymbolRef]] = field(default_factory=dict)
    symbol_ids_by_file: dict[str, set[str]] = field(default_factory=dict)

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
        self._remove_symbols_for_file(relative_path)

        text = f"{relative_path}\n{indexed.skeleton}"
        self.vector_cache.upsert(
            doc_id=relative_path,
            text=text,
            metadata={
                "path": relative_path,
                "language": language,
                "parse_ok": sieve.parse_ok,
                "kind": "file",
            },
        )
        self._index_symbols(indexed)
        return True

    def remove_file(self, path: str | Path) -> None:
        file_path = Path(path)
        try:
            relative_path = str(file_path.relative_to(self.root))
        except ValueError:
            relative_path = str(file_path)
        self.files.pop(relative_path, None)
        self.vector_cache.delete(relative_path)
        self._remove_symbols_for_file(relative_path)

    def semantic_matches(self, query: str, top_k: int | None = None) -> list[IndexedFile]:
        documents = self.vector_cache.query(query, top_k=top_k or 20)
        matches: list[IndexedFile] = []
        for document in documents:
            if document.metadata.get("kind") != "file":
                continue
            path = str(document.metadata.get("path", document.doc_id))
            indexed = self.files.get(path)
            if indexed:
                matches.append(indexed)
        return matches

    def semantic_symbols(
        self,
        query: str,
        top_k: int = 12,
        threshold: float | None = None,
    ) -> list[SymbolRef]:
        documents = self.vector_cache.query(
            query,
            top_k=top_k,
            threshold=0.0 if threshold is None else threshold,
        )
        symbols: list[SymbolRef] = []
        for document in documents:
            if document.metadata.get("kind") not in {"function", "type"}:
                continue
            symbol = self.symbols.get(document.doc_id)
            if symbol:
                symbols.append(_with_score(symbol, document.score))
        return symbols

    def symbols_named(self, names: set[str], exclude_path: str | None = None) -> list[SymbolRef]:
        matches: list[SymbolRef] = []
        for name in sorted(names):
            for symbol in self.symbols_by_name.get(name, []):
                if exclude_path and symbol.relative_path == exclude_path:
                    continue
                matches.append(symbol)
        return matches

    def _index_symbols(self, indexed: IndexedFile) -> None:
        if not indexed.sieve.parse_ok:
            return
        for function in indexed.sieve.functions:
            symbol = _function_symbol(indexed.relative_path, function)
            self._store_symbol(symbol)

        for type_info in indexed.sieve.types:
            symbol = _type_symbol(indexed.relative_path, type_info)
            self._store_symbol(symbol)

    def _store_symbol(self, symbol: SymbolRef) -> None:
        self.symbols[symbol.symbol_id] = symbol
        self.symbols_by_name.setdefault(symbol.name, []).append(symbol)
        self.symbol_ids_by_file.setdefault(symbol.relative_path, set()).add(symbol.symbol_id)
        self.vector_cache.upsert(
            doc_id=symbol.symbol_id,
            text=f"{symbol.relative_path}\n{symbol.name}\n{symbol.skeleton}",
            metadata={
                "kind": symbol.kind,
                "name": symbol.name,
                "path": symbol.relative_path,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
            },
        )

    def _remove_symbols_for_file(self, relative_path: str) -> None:
        ids = self.symbol_ids_by_file.pop(relative_path, set())
        for symbol_id in ids:
            symbol = self.symbols.pop(symbol_id, None)
            self.vector_cache.delete(symbol_id)
            if not symbol:
                continue
            bucket = self.symbols_by_name.get(symbol.name, [])
            self.symbols_by_name[symbol.name] = [item for item in bucket if item.symbol_id != symbol_id]
            if not self.symbols_by_name[symbol.name]:
                self.symbols_by_name.pop(symbol.name, None)


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


def _function_symbol(relative_path: str, function: FunctionInfo) -> SymbolRef:
    method_suffix = "method" if function.is_method else "function"
    return SymbolRef(
        symbol_id=f"{relative_path}::{method_suffix}::{function.name}::{function.start_line}",
        name=function.name,
        kind="function",
        relative_path=relative_path,
        signature=function.signature,
        body=function.body,
        skeleton=function.skeleton,
        calls=set(function.calls),
        start_line=function.start_line,
        end_line=function.end_line,
    )


def _type_symbol(relative_path: str, type_info: TypeInfo) -> SymbolRef:
    return SymbolRef(
        symbol_id=f"{relative_path}::type::{type_info.name}::{type_info.start_line}",
        name=type_info.name,
        kind="type",
        relative_path=relative_path,
        signature=type_info.header,
        body=type_info.body,
        skeleton=type_info.skeleton,
        calls=set(),
        start_line=type_info.start_line,
        end_line=type_info.end_line,
    )


def _with_score(symbol: SymbolRef, score: float) -> SymbolRef:
    return SymbolRef(
        symbol_id=symbol.symbol_id,
        name=symbol.name,
        kind=symbol.kind,
        relative_path=symbol.relative_path,
        signature=symbol.signature,
        body=symbol.body,
        skeleton=symbol.skeleton,
        calls=set(symbol.calls),
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        score=score,
    )
