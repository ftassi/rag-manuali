"""Calibra i pesi RRF del retrieval ibrido su un corpus sintetico."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from evaluate_embeddings import DOCUMENTS, QUERIES

from manuali_rag.config import Settings
from manuali_rag.embeddings import HashEmbedder, OpenAIEmbedder
from manuali_rag.retrieval import Retriever
from manuali_rag.store import ChunkInput, Store

LEXICAL_WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]


class CachingEmbedder:
    def __init__(self, wrapped: object, texts: list[str]) -> None:
        self.model_name = wrapped.model_name
        vectors = wrapped.embed(texts)
        self.cache = dict(zip(texts, vectors, strict=True))

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.cache[text] for text in texts]


def prepare_store(root: Path, embedder: CachingEmbedder) -> Store:
    store = Store(root / f"{embedder.model_name.replace(':', '-')}.sqlite3")
    chunks = [
        ChunkInput(page=index, section="Dati tecnici", content=text)
        for index, (_, text) in enumerate(DOCUMENTS, start=1)
    ]
    store.replace_document(
        document_id="synthetic",
        checksum=f"synthetic-{embedder.model_name}",
        source_name="synthetic.md",
        title="Manuale sintetico",
        markdown_path="",
        page_count=len(chunks),
        warnings=[],
        chunks=chunks,
        embeddings=embedder.embed([chunk.content for chunk in chunks]),
        embedding_model=embedder.model_name,
    )
    return store


def evaluate_weights(
    base_settings: Settings,
    store: Store,
    embedder: CachingEmbedder,
    lexical_weight: float,
) -> dict[str, object]:
    settings = replace(base_settings, retrieval_lexical_weight=lexical_weight)
    retriever = Retriever(store, embedder, settings)
    results = []
    reciprocal_ranks = []
    for query, expected in QUERIES:
        hits = retriever.search(query, top_k=len(DOCUMENTS))
        ranked_ids = [DOCUMENTS[(hit.page or 1) - 1][0] for hit in hits]
        rank = ranked_ids.index(expected) + 1
        reciprocal_ranks.append(1 / rank)
        results.append({"query": query, "expected": expected, "rank": rank, "top3": ranked_ids[:3]})
    return {
        "semantic_weight": settings.retrieval_semantic_weight,
        "lexical_weight": lexical_weight,
        "rrf_k": settings.retrieval_rrf_k,
        "top1_correct": sum(result["rank"] == 1 for result in results),
        "top3_correct": sum(result["rank"] <= 3 for result in results),
        "total": len(results),
        "mean_reciprocal_rank": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        "results": results,
    }


def evaluate_provider(
    name: str, wrapped: object, settings: Settings, root: Path
) -> dict[str, object]:
    texts = [text for _, text in DOCUMENTS] + [query for query, _ in QUERIES]
    embedder = CachingEmbedder(wrapped, texts)
    store = prepare_store(root, embedder)
    configurations = [
        evaluate_weights(settings, store, embedder, lexical_weight)
        for lexical_weight in LEXICAL_WEIGHTS
    ]
    best = max(
        configurations,
        key=lambda item: (
            item["top1_correct"],
            item["top3_correct"],
            item["mean_reciprocal_rank"],
            -abs(item["lexical_weight"] - 1.0),
        ),
    )
    return {"provider": name, "best": best, "configurations": configurations}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", default="nomic-embed-text-v2-moe")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    base_settings = Settings.from_env()

    with tempfile.TemporaryDirectory(prefix="manuali-hybrid-eval-") as temporary:
        root = Path(temporary)
        providers = [
            evaluate_provider("hash-dev", HashEmbedder(384), base_settings, root),
            evaluate_provider(
                args.model,
                OpenAIEmbedder(args.base_url, args.model, timeout=120),
                base_settings,
                root,
            ),
        ]
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "method": {
            "kind": "hybrid SQLite FTS5 + vector RRF",
            "documents": len(DOCUMENTS),
            "queries": len(QUERIES),
            "lexical_weights": LEXICAL_WEIGHTS,
            "manuals_real": False,
        },
        "providers": providers,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
