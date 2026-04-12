"""Swappable embedding abstraction: Voyage API, Noop (testing), Cached wrapper."""

import hashlib
import struct
from datetime import datetime, timezone
from typing import Protocol, Any

from . import config


class EmbeddingProvider(Protocol):
    """Interface for embedding providers."""

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        ...

    @property
    def dimensions(self) -> int:
        ...

    @property
    def model_name(self) -> str:
        ...


class VoyageEmbedding:
    """Production: Voyage API embeddings."""

    def __init__(self, model: str = "", dimensions: int = 0):
        self._model = model or config.EMBEDDING_MODEL
        self._dimensions = dimensions or config.EMBEDDING_DIMENSIONS

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        import voyageai

        client = voyageai.Client()
        result = client.embed(texts, model=self._model, input_type=input_type)
        return result.embeddings

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return self._model


class NoopEmbedding:
    """Testing: returns zero vectors. No API calls."""

    def __init__(self, dimensions: int = 0):
        self._dimensions = dimensions or config.EMBEDDING_DIMENSIONS

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        return [[0.0] * self._dimensions for _ in texts]

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return "noop"


class CachedEmbedding:
    """Wrapper: checks embedding_cache before calling inner provider."""

    def __init__(self, inner: EmbeddingProvider, conn: Any):
        self._inner = inner
        self._conn = conn

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # Check cache
        for i, text in enumerate(texts):
            content_hash = hashlib.md5(text.encode()).hexdigest()
            row = self._conn.execute(
                "SELECT embedding, dimensions FROM embedding_cache WHERE content_hash = ? AND model = ?",
                (content_hash, self._inner.model_name),
            ).fetchone()
            if row:
                results[i] = _deserialize_embedding(row["embedding"], row["dimensions"])
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Embed uncached texts
        if uncached_texts:
            new_embeddings = self._inner.embed(uncached_texts, input_type=input_type)
            now = datetime.now(timezone.utc).isoformat()

            for idx, emb in zip(uncached_indices, new_embeddings):
                results[idx] = emb
                content_hash = hashlib.md5(texts[idx].encode()).hexdigest()
                self._conn.execute(
                    "INSERT OR REPLACE INTO embedding_cache (content_hash, model, embedding, dimensions, created_at) VALUES (?, ?, ?, ?, ?)",
                    (content_hash, self._inner.model_name, _serialize_embedding(emb), len(emb), now),
                )
            self._conn.commit()

        return results  # type: ignore[return-value]

    @property
    def dimensions(self) -> int:
        return self._inner.dimensions

    @property
    def model_name(self) -> str:
        return self._inner.model_name


def get_provider(provider_name: str = "", conn: Any | None = None) -> EmbeddingProvider:
    """Factory: return the configured embedding provider, optionally wrapped with caching."""
    provider_name = provider_name or config.EMBEDDING_PROVIDER
    if provider_name == "voyage":
        inner = VoyageEmbedding()
    elif provider_name == "noop":
        inner = NoopEmbedding()
    else:
        raise ValueError(f"Unknown embedding provider: {provider_name}")

    if conn is not None:
        return CachedEmbedding(inner, conn)
    return inner


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Pack a float list into a compact binary blob."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(blob: bytes, dimensions: int) -> list[float]:
    """Unpack a binary blob back to a float list."""
    return list(struct.unpack(f"{dimensions}f", blob))


def content_hash(text: str) -> str:
    """MD5 hash of text, used for embedding cache keys."""
    return hashlib.md5(text.encode()).hexdigest()
