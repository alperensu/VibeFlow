"""
VibeFlow Core configuration.

Token saving model:
- Static project structure is cached and reused.
- Dynamic request context stays small: current intent, cursor location, and
  only the bodies that are likely to matter.
"""

from __future__ import annotations

import os
from pathlib import Path


HOST: str = os.getenv("VIBEFLOW_HOST", "127.0.0.1")
PORT: int = int(os.getenv("VIBEFLOW_PORT", "7400"))
AUTO_PROJECT_ROOT: str | None = os.getenv("VIBEFLOW_PROJECT_ROOT")
AUTO_INDEX: bool = os.getenv("VIBEFLOW_AUTO_INDEX", "1").lower() not in {"0", "false", "no"}
AUTO_WATCH: bool = os.getenv("VIBEFLOW_AUTO_WATCH", "1").lower() not in {"0", "false", "no"}

DATA_DIR: Path = Path(os.getenv("VIBEFLOW_DATA", ".vibeflow"))
VECTOR_DB_DIR: Path = DATA_DIR / "cache"

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
}

MAX_FILE_SIZE: int = int(os.getenv("VIBEFLOW_MAX_FILE_SIZE", str(2 * 1024 * 1024)))

SIMILARITY_THRESHOLD: float = float(os.getenv("VIBEFLOW_SIM_THRESHOLD", "0.18"))
TOP_K_RESULTS: int = int(os.getenv("VIBEFLOW_TOP_K", "20"))

WATCHER_DEBOUNCE_MS: int = int(os.getenv("VIBEFLOW_DEBOUNCE_MS", "300"))

IGNORED_DIRS: set[str] = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".vibeflow",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}

CHUNK_SIZE: int = int(os.getenv("VIBEFLOW_CHUNK_SIZE", "1500"))
CHUNK_OVERLAP: int = int(os.getenv("VIBEFLOW_CHUNK_OVERLAP", "200"))
CHARS_PER_TOKEN: float = 3.5

# Context budget defaults are deliberately modest so the sidecar stays useful
# below the 100ms target on warm cache.
MAX_STATIC_CHARS: int = int(os.getenv("VIBEFLOW_MAX_STATIC_CHARS", "24000"))
MAX_DYNAMIC_CHARS: int = int(os.getenv("VIBEFLOW_MAX_DYNAMIC_CHARS", "12000"))
