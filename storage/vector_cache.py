"""
Local vector cache.

Token saving:
- Semantic pruning asks the cache for only the top matching files/chunks.
- The API never has to paste the full repository when a few skeletons match.

ChromaDB is used when installed. A tiny in-memory fallback keeps development
usable without blocking the sidecar startup.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import SIMILARITY_THRESHOLD, TOP_K_RESULTS, VECTOR_DB_DIR

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DIMENSIONS = 384


@dataclass(slots=True)
class VectorDocument:
    doc_id: str
    text: str
    metadata: dict[str, Any]
    score: float = 0.0


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _embed(text: str) -> list[float]:
    vector = [0.0] * _DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % _DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class VectorCache:
    def __init__(self, path: str | Path = VECTOR_DB_DIR, collection_name: str = "vibeflow") -> None:
        self.path = Path(path)
        self.collection_name = collection_name
        self._memory: dict[str, VectorDocument] = {}
        self._chroma = None

        try:
            import chromadb

            self.path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self.path))
            self._chroma = client.get_or_create_collection(collection_name)
        except Exception:
            self._chroma = None

    @property
    def backend(self) -> str:
        return "chromadb" if self._chroma is not None else "memory"

    def upsert(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        metadata = metadata or {}
        embedding = _embed(text)
        if self._chroma is not None:
            self._chroma.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata],
                embeddings=[embedding],
            )
            return

        self._memory[doc_id] = VectorDocument(doc_id=doc_id, text=text, metadata=metadata)

    def delete(self, doc_id: str) -> None:
        if self._chroma is not None:
            self._chroma.delete(ids=[doc_id])
            return
        self._memory.pop(doc_id, None)

    def query(
        self,
        text: str,
        top_k: int = TOP_K_RESULTS,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> list[VectorDocument]:
        embedding = _embed(text)
        if self._chroma is not None:
            result = self._chroma.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
            documents: list[VectorDocument] = []
            ids = result.get("ids", [[]])[0]
            texts = result.get("documents", [[]])[0]
            metadatas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]
            for doc_id, doc_text, metadata, distance in zip(ids, texts, metadatas, distances):
                score = 1.0 - float(distance)
                if score >= threshold:
                    documents.append(VectorDocument(doc_id, doc_text or "", metadata or {}, score))
            return documents

        scored: list[VectorDocument] = []
        for doc in self._memory.values():
            score = _cosine(embedding, _embed(doc.text))
            if score >= threshold:
                scored.append(VectorDocument(doc.doc_id, doc.text, doc.metadata, score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]
