"""
Smart chunking fallback.

Token saving:
- Used only when AST parsing is not trustworthy.
- Keeps chunks near code boundaries so the API can return a preview or a few
  relevant chunks instead of sending an entire complex file.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("vibeflow.chunker")

_BOUNDARY_PATTERNS = re.compile(
    r"^(?:"
    r"def |async def |class |function |const |let |var |export |import |from "
    r"|#{1,3} "
    r"|//\s*-{3,}"
    r"|#\s*-{3,}"
    r")",
    re.MULTILINE,
)


def smart_chunk(
    source: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    from config import CHUNK_OVERLAP, CHUNK_SIZE

    chunk_size = chunk_size or CHUNK_SIZE
    chunk_overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP

    if not source.strip():
        return []
    if len(source) <= chunk_size:
        return [source]

    boundaries = [0]
    boundaries.extend(match.start() for match in _BOUNDARY_PATTERNS.finditer(source) if match.start() > 0)
    boundaries.append(len(source))

    chunks: list[str] = []
    start = 0
    while start < len(source):
        end = min(start + chunk_size, len(source))
        if end >= len(source):
            chunk = source[start:end].rstrip()
            if chunk:
                chunks.append(chunk)
            break

        best = max((pos for pos in boundaries if start < pos <= end), default=start)
        if best <= start:
            newline = source.rfind("\n", start, end)
            best = newline + 1 if newline > start else end

        chunk = source[start:best].rstrip()
        if chunk:
            chunks.append(chunk)
        start = max(best - chunk_overlap, start + 1)

    logger.debug("chunked %d chars into %d chunks", len(source), len(chunks))
    return chunks
