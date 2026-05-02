"""
Unified context builder.

Token saving:
- Static block: cache-friendly file skeletons and symbol skeletons.
- Dynamic block: intent, active function body, and selected local/cross-file bodies.
- Settings report: each optimization switch exposes its estimated token impact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from core.diff_streamer import diff_contract
from core.indexer import IndexedFile, ProjectIndex, SymbolRef
from core.settings import OptimizationSettings, resolve_settings
from core.sieve import FunctionInfo


@dataclass(slots=True)
class ContextRequest:
    project_root: Path
    current_file: Path | None = None
    cursor_line: int | None = None
    intent: str = ""
    max_files: int | None = None
    settings: OptimizationSettings = field(default_factory=OptimizationSettings)


@dataclass(slots=True)
class ContextPackage:
    context_string: str
    prompt: dict[str, Any]
    stats: dict[str, Any]
    warnings: list[str]


class ContextBuilder:
    def __init__(self, index: ProjectIndex) -> None:
        self.index = index

    def build(self, request: ContextRequest) -> ContextPackage:
        started = perf_counter()
        settings = request.settings or resolve_settings()
        warnings: list[str] = []

        current_indexed = self._ensure_current_file(request.current_file)
        if current_indexed and current_indexed.sieve.warnings:
            warnings.extend(current_indexed.sieve.warnings)

        active = self._active_function(request, current_indexed)
        query = self._query_text(request, current_indexed, active)
        max_files = request.max_files or settings.max_files
        matches = self._matches(query, current_indexed, max_files, settings)
        symbols = self._symbols(query, current_indexed, active, settings)

        static_context = self._static_context(matches, symbols, settings)
        dynamic_context = self._dynamic_context(request, current_indexed, active, symbols, warnings, settings)
        context_string = self._join_context(static_context, dynamic_context, settings)

        project_tokens = sum(_estimate_tokens(_read_text(indexed.path)) for indexed in self.index.files.values())
        selected_raw_tokens = sum(_estimate_tokens(_read_text(indexed.path)) for indexed in matches)
        static_tokens = _estimate_tokens(static_context)
        dynamic_tokens = _estimate_tokens(dynamic_context)
        after_tokens = static_tokens + dynamic_tokens
        elapsed_ms = round((perf_counter() - started) * 1000, 3)

        prompt = self._prompt(static_context, dynamic_context, settings)
        stats = {
            "latency_ms": elapsed_ms,
            "vector_backend": self.index.vector_cache.backend,
            "settings": settings.to_dict(),
            "files_considered": len(self.index.files),
            "files_selected": len(matches),
            "symbols_indexed": len(self.index.symbols),
            "symbols_selected": len(symbols),
            "estimated_project_tokens": project_tokens,
            "estimated_selected_raw_tokens": selected_raw_tokens,
            "estimated_context_tokens": after_tokens,
            "estimated_static_tokens": static_tokens,
            "estimated_dynamic_tokens": dynamic_tokens,
            "estimated_total_token_saving_percent": _saving_percent(project_tokens, after_tokens),
            "optimization_effects": self._optimization_effects(
                settings=settings,
                project_tokens=project_tokens,
                selected_raw_tokens=selected_raw_tokens,
                static_tokens=static_tokens,
                dynamic_tokens=dynamic_tokens,
                matches=matches,
                symbols=symbols,
            ),
        }
        return ContextPackage(context_string, prompt, stats, warnings)

    def _ensure_current_file(self, current_file: Path | None) -> IndexedFile | None:
        if current_file is None:
            return None
        path = current_file if current_file.is_absolute() else self.index.root / current_file
        self.index.index_file(path)
        try:
            relative = str(path.relative_to(self.index.root))
        except ValueError:
            relative = str(path)
        return self.index.files.get(relative)

    def _query_text(
        self,
        request: ContextRequest,
        current: IndexedFile | None,
        active: FunctionInfo | None,
    ) -> str:
        parts = [request.intent]
        if request.current_file:
            parts.append(str(request.current_file))
        if current:
            parts.append(current.relative_path)
        if active:
            parts.append(active.signature)
            parts.extend(sorted(active.calls))
        return "\n".join(part for part in parts if part)

    def _matches(
        self,
        query: str,
        current: IndexedFile | None,
        max_files: int,
        settings: OptimizationSettings,
    ) -> list[IndexedFile]:
        selected: list[IndexedFile] = []
        seen: set[str] = set()
        if current:
            selected.append(current)
            seen.add(current.relative_path)

        if settings.semantic_pruning:
            candidates = self.index.semantic_matches(query, top_k=max_files * 3)
        else:
            candidates = list(self.index.files.values())

        for match in candidates:
            if match.relative_path in seen:
                continue
            selected.append(match)
            seen.add(match.relative_path)
            if len(selected) >= max_files:
                break

        if not selected:
            selected = list(self.index.files.values())[:max_files]
        return selected

    def _symbols(
        self,
        query: str,
        current: IndexedFile | None,
        active: FunctionInfo | None,
        settings: OptimizationSettings,
    ) -> list[SymbolRef]:
        if not settings.function_level_retrieval:
            return []

        selected: list[SymbolRef] = []
        seen: set[str] = set()

        if settings.semantic_pruning:
            for symbol in self.index.semantic_symbols(
                query,
                top_k=settings.max_symbols,
                threshold=settings.similarity_threshold,
            ):
                if symbol.symbol_id not in seen:
                    selected.append(symbol)
                    seen.add(symbol.symbol_id)

        if active and settings.include_cross_file_callees:
            exclude = current.relative_path if current else None
            for symbol in self.index.symbols_named(active.calls, exclude_path=exclude):
                if symbol.kind == "function" and symbol.symbol_id not in seen:
                    selected.append(symbol)
                    seen.add(symbol.symbol_id)
                if len(selected) >= settings.max_symbols:
                    break

        return selected[: settings.max_symbols]

    def _static_context(
        self,
        matches: list[IndexedFile],
        symbols: list[SymbolRef],
        settings: OptimizationSettings,
    ) -> str:
        sections: list[str] = []
        remaining = settings.max_static_chars

        for indexed in matches:
            text = self._file_static_text(indexed, settings)
            if not text.strip():
                continue
            section = f"### file: {indexed.relative_path}\n{text}".strip()
            if len(section) > remaining:
                break
            sections.append(section)
            remaining -= len(section)

        symbol_sections: list[str] = []
        for symbol in symbols:
            if symbol.kind == "type" and not settings.include_type_skeletons:
                continue
            text = symbol.skeleton if settings.skeletonization else symbol.dynamic_text
            section = (
                f"### symbol: {symbol.name} ({symbol.kind})\n"
                f"path: {symbol.relative_path}:{symbol.start_line + 1}\n"
                f"{text}"
            ).strip()
            if len(section) > remaining:
                break
            symbol_sections.append(section)
            remaining -= len(section)

        if symbol_sections:
            sections.append("## symbol-level matches\n" + "\n\n".join(symbol_sections))

        return "\n\n".join(sections)

    def _file_static_text(self, indexed: IndexedFile, settings: OptimizationSettings) -> str:
        if not settings.skeletonization:
            return _read_text(indexed.path)

        sieve = indexed.sieve
        if not sieve.parse_ok:
            if settings.fallback_chunking:
                return indexed.compact_text
            return "\n".join(sieve.warnings)

        sections: list[str] = []
        if settings.include_imports and sieve.imports:
            sections.append("\n".join(sieve.imports))
        if settings.include_type_skeletons:
            sections.extend(type_info.skeleton for type_info in sieve.types)

        method_ranges = {(m.start_line, m.end_line) for t in sieve.types for m in t.methods}
        for function in sieve.functions:
            if (function.start_line, function.end_line) not in method_ranges:
                sections.append(function.skeleton)
        return "\n\n".join(section for section in sections if section.strip())

    def _dynamic_context(
        self,
        request: ContextRequest,
        current: IndexedFile | None,
        active: FunctionInfo | None,
        symbols: list[SymbolRef],
        warnings: list[str],
        settings: OptimizationSettings,
    ) -> str:
        lines: list[str] = ["### task", request.intent or "(no intent supplied)"]

        if settings.diff_only_output:
            lines.extend(["", "### output contract", diff_contract()["instruction"]])

        if current:
            lines.extend(["", "### current file", current.relative_path])

        if active and settings.include_active_body:
            lines.extend(["", "### active function body", _format_function(active)])

            if current and settings.include_same_file_callees:
                called = current.sieve.functions_called_by(active)
                if called:
                    lines.extend(["", "### same-file called bodies"])
                    lines.extend(_format_function(function) for function in called)

        if active and settings.include_cross_file_callees:
            cross_file = [
                symbol
                for symbol in symbols
                if symbol.kind == "function"
                and symbol.name in active.calls
                and (current is None or symbol.relative_path != current.relative_path)
            ]
            if cross_file:
                lines.extend(["", "### cross-file called bodies"])
                lines.extend(_format_symbol_body(symbol) for symbol in cross_file)

        if warnings:
            lines.extend(["", "### warnings"])
            lines.extend(warnings)

        value = "\n".join(lines)
        if len(value) > settings.max_dynamic_chars:
            return value[: settings.max_dynamic_chars] + "\n# truncated dynamic context"
        return value

    def _active_function(self, request: ContextRequest, current: IndexedFile | None) -> FunctionInfo | None:
        if current is None or request.cursor_line is None:
            return None
        zero_indexed = max(0, request.cursor_line - 1)
        return current.sieve.get_function_at_line(zero_indexed)

    def _join_context(
        self,
        static_context: str,
        dynamic_context: str,
        settings: OptimizationSettings,
    ) -> str:
        if settings.prompt_caching:
            return (
                "<static_project_context cache_control='ephemeral'>\n"
                f"{static_context}\n"
                "</static_project_context>\n\n"
                "<dynamic_task_context>\n"
                f"{dynamic_context}\n"
                "</dynamic_task_context>"
            )
        return f"{static_context}\n\n{dynamic_context}".strip()

    def _prompt(
        self,
        static_context: str,
        dynamic_context: str,
        settings: OptimizationSettings,
    ) -> dict[str, Any]:
        static_part: dict[str, Any] = {
            "type": "text",
            "name": "static_project_context",
            "text": static_context,
        }
        if settings.prompt_caching:
            static_part["cache_control"] = {"type": "ephemeral"}

        prompt: dict[str, Any] = {
            "headers": {"content-type": "application/json"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        static_part,
                        {
                            "type": "text",
                            "name": "dynamic_task_context",
                            "text": dynamic_context,
                        },
                    ],
                }
            ],
        }
        if settings.prompt_caching:
            prompt["headers"]["anthropic-beta"] = "prompt-caching"
        if settings.diff_only_output:
            prompt["response_contract"] = diff_contract()
        return prompt

    def _optimization_effects(
        self,
        settings: OptimizationSettings,
        project_tokens: int,
        selected_raw_tokens: int,
        static_tokens: int,
        dynamic_tokens: int,
        matches: list[IndexedFile],
        symbols: list[SymbolRef],
    ) -> list[dict[str, Any]]:
        skeleton_tokens = sum(_estimate_tokens(self._file_static_text(indexed, settings)) for indexed in matches)
        symbol_raw_tokens = sum(_estimate_tokens(symbol.dynamic_text) for symbol in symbols)
        symbol_skeleton_tokens = sum(_estimate_tokens(symbol.skeleton) for symbol in symbols)
        cacheable_tokens = static_tokens if settings.prompt_caching else 0

        return [
            {
                "key": "semantic_pruning",
                "enabled": settings.semantic_pruning,
                "estimated_saved_tokens": max(0, project_tokens - selected_raw_tokens) if settings.semantic_pruning else 0,
                "basis": "project raw tokens minus selected raw file tokens",
            },
            {
                "key": "skeletonization",
                "enabled": settings.skeletonization,
                "estimated_saved_tokens": max(0, selected_raw_tokens - skeleton_tokens) if settings.skeletonization else 0,
                "basis": "selected raw file tokens minus static skeleton tokens",
            },
            {
                "key": "function_level_retrieval",
                "enabled": settings.function_level_retrieval,
                "estimated_saved_tokens": max(0, symbol_raw_tokens - symbol_skeleton_tokens)
                if settings.function_level_retrieval and settings.skeletonization
                else 0,
                "basis": "selected symbol bodies minus symbol skeletons",
            },
            {
                "key": "prompt_caching",
                "enabled": settings.prompt_caching,
                "estimated_cacheable_tokens": cacheable_tokens,
                "basis": "static context tokens eligible for provider prompt caching",
            },
            {
                "key": "diff_only_output",
                "enabled": settings.diff_only_output,
                "estimated_response_token_reduction": "high",
                "basis": "response-side saving; depends on model output size and is not counted in prompt tokens",
            },
            {
                "key": "budget_caps",
                "enabled": True,
                "max_static_chars": settings.max_static_chars,
                "max_dynamic_chars": settings.max_dynamic_chars,
                "estimated_context_tokens": static_tokens + dynamic_tokens,
            },
        ]


def _format_function(function: FunctionInfo) -> str:
    return f"{function.signature}\n{function.body}".rstrip()


def _format_symbol_body(symbol: SymbolRef) -> str:
    return f"# {symbol.relative_path}:{symbol.start_line + 1}\n{symbol.dynamic_text}".rstrip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _estimate_tokens(text: str) -> int:
    from config import CHARS_PER_TOKEN

    return max(1, int(len(text) / CHARS_PER_TOKEN)) if text else 0


def _saving_percent(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return round(max(0.0, (before - after) / before * 100.0), 2)
