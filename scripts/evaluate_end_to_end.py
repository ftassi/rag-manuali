"""Valutazione end-to-end senza document scope su corpus tecnico sintetico."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from evaluate_embeddings import DOCUMENTS, QUERIES

from manuali_rag.config import Settings
from manuali_rag.embeddings import OpenAIEmbedder
from manuali_rag.llm import LLMClient
from manuali_rag.retrieval import AnswerService, Retriever
from manuali_rag.store import ChunkInput, Store

EXPECTED = {
    "power": ["scollegare", "alimentazione"],
    "filter": ["sei mesi"],
    "torque": ["12 nm"],
    "temperature": ["65"],
    "pressure": ["e104", "pressione insufficiente"],
    "drain": ["a7", "scarico ostruito"],
    "replacement": ["kx-17b"],
    "battery": ["sostitu", "batteria"],
    "lubrication": ["grasso al silicone"],
    "storage": ["asciutto", "ventilato"],
    "inactive-state": ["inattivo"],
}

DISTINCTIVE_TERMS = {
    "power": ["alimentazione elettrica"],
    "filter": ["sei mesi"],
    "torque": ["12 nm"],
    "temperature": ["65 °c", "65 c"],
    "pressure": ["e104"],
    "drain": ["a7"],
    "replacement": ["kx-17b"],
    "battery": ["lampeggia in rosso"],
    "lubrication": ["grasso al silicone"],
    "storage": ["asciutto e ventilato"],
    "inactive-state": ["stato inattivo"],
}


def prepare_store(root: Path, embedder: OpenAIEmbedder) -> Store:
    store = Store(root / "end-to-end.sqlite3")
    vectors = embedder.embed([text for _, text in DOCUMENTS])
    for page, ((document_id, text), vector) in enumerate(
        zip(DOCUMENTS, vectors, strict=True), start=1
    ):
        store.replace_document(
            document_id=document_id,
            checksum=f"e2e-{document_id}",
            source_name=f"{document_id}.md",
            title=f"Manuale sintetico {document_id}",
            markdown_path="",
            page_count=1,
            warnings=[],
            chunks=[ChunkInput(page=page, section="Dati tecnici", content=text)],
            embeddings=[vector],
            embedding_model=embedder.model_name,
        )
    return store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base_settings = Settings.from_env()
    with tempfile.TemporaryDirectory(prefix="manuali-e2e-") as temporary:
        root = Path(temporary)
        settings = replace(base_settings, data_dir=root, database_path=root / "end-to-end.sqlite3")
        embedder = OpenAIEmbedder(
            settings.embedding_base_url,
            settings.embedding_model,
            settings.embedding_timeout,
        )
        store = prepare_store(root, embedder)
        service = AnswerService(Retriever(store, embedder, settings), LLMClient(settings), settings)
        results = []
        for question, expected_document in QUERIES:
            started = time.perf_counter()
            answer = service.answer(question, top_k=args.top_k, include_images=False)
            elapsed = time.perf_counter() - started
            ranked_ids = [source.document_id for source in answer.sources]
            retrieval_rank = (
                ranked_ids.index(expected_document) + 1 if expected_document in ranked_ids else None
            )
            normalized = answer.text.casefold()
            facts_ok = all(term in normalized for term in EXPECTED[expected_document])
            expected_citation = f"[s{retrieval_rank}]" if retrieval_rank else None
            citation_ok = bool(expected_citation and expected_citation in normalized)
            forbidden = [
                term
                for document_id, terms in DISTINCTIVE_TERMS.items()
                if document_id != expected_document
                for term in terms
            ]
            contamination = [term for term in forbidden if term in normalized]
            passed = retrieval_rank is not None and facts_ok and citation_ok and not contamination
            results.append(
                {
                    "question": question,
                    "expected_document": expected_document,
                    "retrieved_documents": ranked_ids,
                    "retrieval_rank": retrieval_rank,
                    "answer": answer.text,
                    "facts_ok": facts_ok,
                    "citation_ok": citation_ok,
                    "contamination": contamination,
                    "passed": passed,
                    "wall_seconds": round(elapsed, 3),
                }
            )

    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "method": {
            "kind": "unscoped end-to-end synthetic RAG",
            "documents": len(DOCUMENTS),
            "queries": len(QUERIES),
            "top_k": args.top_k,
            "embedding_model": base_settings.embedding_model,
            "llm_model": base_settings.llm_model,
            "manuals_real": False,
        },
        "summary": {
            "retrieval_top1": sum(result["retrieval_rank"] == 1 for result in results),
            "retrieval_top3": sum(result["retrieval_rank"] is not None for result in results),
            "answers_passed": sum(bool(result["passed"]) for result in results),
            "total": len(results),
            "median_wall_seconds": round(
                statistics.median(float(result["wall_seconds"]) for result in results), 3
            ),
        },
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
