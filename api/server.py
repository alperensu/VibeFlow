"""
FastAPI unified API for VibeFlow Core.

Token saving:
- /context returns cache-friendly static skeletons plus compact dynamic context.
- /sieve/signatures exposes the first core sieve primitive directly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

import config
from core.context_builder import ContextBuilder, ContextRequest
from core.indexer import ProjectIndex
from core.sieve import parse_file
from core.watcher import WatcherEngine

_indexes: dict[str, ProjectIndex] = {}
_watchers: dict[str, WatcherEngine] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.AUTO_PROJECT_ROOT and config.AUTO_INDEX:
        index = _get_index(Path(config.AUTO_PROJECT_ROOT))
        count = index.index_project()
        watching = False
        if config.AUTO_WATCH:
            watcher = WatcherEngine(index)
            watcher.start()
            _watchers[str(index.root)] = watcher
            watching = watcher.running
        app.state.auto_bootstrap = {
            "project_root": str(index.root),
            "indexed_files": count,
            "total_files": len(index.files),
            "watching": watching,
            "vector_backend": index.vector_cache.backend,
        }
    else:
        app.state.auto_bootstrap = None

    yield

    for watcher in list(_watchers.values()):
        watcher.stop()


app = FastAPI(title="VibeFlow Core", version="0.1.0", lifespan=lifespan)


class IndexRequest(BaseModel):
    project_root: str = Field(default=".", description="Project root to index")
    watch: bool = Field(default=True, description="Start watchdog incremental indexing")


class ContextRequestModel(BaseModel):
    project_root: str = "."
    current_file: str | None = None
    cursor_line: int | None = Field(default=None, ge=1)
    intent: str = ""
    max_files: int = Field(default=8, ge=1, le=32)


class SieveRequest(BaseModel):
    file_path: str
    language: str = "python"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "auto_bootstrap": getattr(app.state, "auto_bootstrap", None),
        "indexes": list(_indexes.keys()),
        "watchers": {root: watcher.running for root, watcher in _watchers.items()},
    }


@app.post("/index")
def index_project(payload: IndexRequest) -> dict[str, Any]:
    index = _get_index(Path(payload.project_root))
    count = index.index_project()
    if payload.watch:
        watcher = _watchers.get(str(index.root))
        if watcher is None:
            watcher = WatcherEngine(index)
            _watchers[str(index.root)] = watcher
        watcher.start()
    return {
        "project_root": str(index.root),
        "indexed_files": count,
        "total_files": len(index.files),
        "vector_backend": index.vector_cache.backend,
        "watching": _watchers.get(str(index.root)).running if str(index.root) in _watchers else False,
    }


@app.post("/context")
def build_context(payload: ContextRequestModel) -> dict[str, Any]:
    root = Path(payload.project_root).resolve()
    index = _get_index(root)
    if not index.files:
        index.index_project()

    current_file = Path(payload.current_file) if payload.current_file else None
    request = ContextRequest(
        project_root=root,
        current_file=current_file,
        cursor_line=payload.cursor_line,
        intent=payload.intent,
        max_files=payload.max_files,
    )
    package = ContextBuilder(index).build(request)
    return {
        "context_string": package.context_string,
        "prompt": package.prompt,
        "stats": package.stats,
        "warnings": package.warnings,
    }


@app.post("/sieve/signatures")
def sieve_signatures(payload: SieveRequest) -> dict[str, Any]:
    result = parse_file(payload.file_path, payload.language)
    return {
        "file_path": result.file_path,
        "language": result.language,
        "parse_ok": result.parse_ok,
        "warnings": result.warnings,
        "imports": result.imports,
        "signatures": [function.skeleton for function in result.functions if not function.is_method],
        "types": [type_info.skeleton for type_info in result.types],
        "skeleton": result.skeleton,
    }


def _get_index(root: Path) -> ProjectIndex:
    resolved = root.resolve()
    key = str(resolved)
    if key not in _indexes:
        _indexes[key] = ProjectIndex(root=resolved)
    return _indexes[key]
