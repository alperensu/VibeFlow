"""
Unified context builder.

Token saving:
- Static block: reusable file skeletons, marked cache-friendly.
- Dynamic block: intent, active function body, and directly called bodies.
- Semantic pruning: vector cache selects relevant skeletons before assembly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from config import MAX_DYNAMIC_CHARS, MAX_STATIC_CHARS
from core.diff_streamer import diff_contract
from core.indexer import IndexedFile, ProjectIndex
from core.sieve import FunctionInfo


@dataclass(slots=True)
class ContextRequest:
    project_root: Path
    current_file: Path | None = None
    cursor_line: int | None = None
    intent: str = ""
    max_files: int = 8


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
        warnings: list[str] = []
        current_indexed = self._ensure_current_file(request.current_file)
        if current_indexed and current_indexed.sieve.warnings:
            warnings.extend(current_indexed.sieve.warnings)

        query = self._query_text(request, current_indexed)
        matches = self._matches(query, current_indexed, request.max_files)

        static_context = self._static_context(matches)
        dynamic_context = self._dynamic_context(request, current_indexed, warnings)
        context_string = self._join_context(static_context, dynamic_context)

        before_tokens = sum(_estimate_tokens(_read_text(indexed.path)) for indexed in matches)
        after_tokens = _estimate_tokens(static_context) + _estimate_tokens(dynamic_context)
        elapsed_ms = round((perf_counter() - started) * 1000, 3)

        prompt = {
            "headers": {
                "anthropic-beta": "prompt-caching",
                "content-type": "application/json",
            },
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "name": "static_project_context",
                            "cache_control": {"type": "ephemeral"},
                            "text": static_context,
                        },
                        {
                            "type": "text",
                            "name": "dynamic_task_context",
                            "text": dynamic_context,
                        },
                    ],
                }
            ],
            "response_contract": diff_contract(),
        }

        stats = {
            "latency_ms": elapsed_ms,
            "vector_backend": self.index.vector_cache.backend,
            "files_considered": len(self.index.files),
            "files_selected": len(matches),
            "estimated_tokens_before": before_tokens,
            "estimated_tokens_after": after_tokens,
            "estimated_token_saving_percent": _saving_percent(before_tokens, after_tokens),
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

    def _query_text(self, request: ContextRequest, current: IndexedFile | None) -> str:
        parts = [request.intent]
        if request.current_file:
            parts.append(str(request.current_file))
        active = self._active_function(request, current)
        if active:
            parts.append(active.signature)
            parts.extend(sorted(active.calls))
        return "\n".join(part for part in parts if part)

    def _matches(self, query: str, current: IndexedFile | None, max_files: int) -> list[IndexedFile]:
        selected: list[IndexedFile] = []
        if current:
            selected.append(current)

        for match in self.index.semantic_matches(query, top_k=max_files):
            if match.relative_path not in {item.relative_path for item in selected}:
                selected.append(match)
            if len(selected) >= max_files:
                break

        if not selected:
            selected = list(self.index.files.values())[:max_files]
        return selected

    def _static_context(self, matches: list[IndexedFile]) -> str:
        sections: list[str] = []
        remaining = MAX_STATIC_CHARS
        for indexed in matches:
            skeleton = indexed.skeleton or "# empty skeleton"
            section = f"### {indexed.relative_path}\n{skeleton}".strip()
            if len(section) > remaining:
                break
            sections.append(section)
            remaining -= len(section)
        return "\n\n".join(sections)

    def _dynamic_context(
        self,
        request: ContextRequest,
        current: IndexedFile | None,
        warnings: list[str],
    ) -> str:
        lines: list[str] = [
            "### task",
            request.intent or "(no intent supplied)",
            "",
            "### output contract",
            diff_contract()["instruction"],
        ]
        if current:
            lines.extend(["", "### current file", current.relative_path])

        active = self._active_function(request, current)
        if active:
            lines.extend(["", "### active function body", _format_function(active)])
            called = current.sieve.functions_called_by(active) if current else []
            if called:
                lines.extend(["", "### directly called local bodies"])
                for function in called:
                    lines.append(_format_function(function))

        if warnings:
            lines.extend(["", "### warnings"])
            lines.extend(warnings)

        value = "\n".join(lines)
        if len(value) > MAX_DYNAMIC_CHARS:
            return value[:MAX_DYNAMIC_CHARS] + "\n# truncated dynamic context"
        return value

    def _active_function(self, request: ContextRequest, current: IndexedFile | None) -> FunctionInfo | None:
        if current is None or request.cursor_line is None:
            return None
        zero_indexed = max(0, request.cursor_line - 1)
        return current.sieve.get_function_at_line(zero_indexed)

    def _join_context(self, static_context: str, dynamic_context: str) -> str:
        return (
            "<static_project_context cache_control='ephemeral'>\n"
            f"{static_context}\n"
            "</static_project_context>\n\n"
            "<dynamic_task_context>\n"
            f"{dynamic_context}\n"
            "</dynamic_task_context>"
        )


def _format_function(function: FunctionInfo) -> str:
    return f"{function.signature}\n{function.body}".rstrip()


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
