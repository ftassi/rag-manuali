from __future__ import annotations

import hashlib
import math
import re
import struct
from collections.abc import Sequence
from itertools import pairwise
from typing import Protocol

import httpx

from .config import Settings

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return [0.0 for _ in vector]
    return [float(value / norm) for value in vector]


def vector_to_blob(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def blob_to_vector(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(blob) // 4}f", blob)


class HashEmbedder:
    """Fallback deterministico per demo e test; non sostituisce un modello semantico."""

    model_name = "hash-dev"

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = TOKEN_RE.findall(text.casefold())
        features = tokens + [f"{a}_{b}" for a, b in pairwise(tokens)]
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dimensions
            vector[index] += 1.0 if value & 1 else -1.0
        return normalize(vector)


class OpenAIEmbedder:
    """Client per un llama-server locale avviato con --embedding."""

    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.client = httpx.Client(timeout=timeout)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model_name, "input": list(texts)},
        )
        response.raise_for_status()
        payload = response.json()
        ordered = sorted(payload["data"], key=lambda item: item["index"])
        return [normalize(item["embedding"]) for item in ordered]


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hash":
        return HashEmbedder(settings.hash_embedding_dimensions)
    return OpenAIEmbedder(
        settings.embedding_base_url,
        settings.embedding_model,
        settings.embedding_timeout,
    )
