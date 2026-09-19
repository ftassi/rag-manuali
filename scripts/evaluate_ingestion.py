"""Prova live dell'intero flusso su un manuale Markdown sintetico."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from manuali_rag.config import Settings
from manuali_rag.embeddings import build_embedder
from manuali_rag.ingest import Ingestor
from manuali_rag.llm import LLMClient
from manuali_rag.retrieval import AnswerService, Retriever
from manuali_rag.store import Store

MANUAL = """<!-- pagina: 2 -->
## Avvio controllato
Prima dell'avvio impostare il selettore sulla posizione ZR-42 e attendere due secondi.

<!-- pagina: 7 -->
## Manutenzione del filtro
Pulire il filtro ogni 180 ore usando esclusivamente acqua tiepida.

<!-- pagina: 11 -->
## Diagnostica
Il codice Q9 indica che il sensore di flusso non risponde.
"""

CASES = [
    {
        "question": "In quale posizione va messo il selettore prima dell'avvio?",
        "page": 2,
        "terms": ["zr-42"],
    },
    {
        "question": "Ogni quanto bisogna pulire il filtro e con cosa?",
        "page": 7,
        "terms": ["180 ore", "acqua tiepida"],
    },
    {
        "question": "Che cosa significa il codice Q9?",
        "page": 11,
        "terms": ["sensore di flusso", "non risponde"],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base_settings = Settings.from_env()
    with tempfile.TemporaryDirectory(prefix="manuali-ingestion-") as temporary:
        root = Path(temporary)
        settings = replace(
            base_settings,
            data_dir=root / "data",
            database_path=root / "data" / "manuali.sqlite3",
            caption_mode="off",
            max_images_per_question=0,
        )
        settings.ensure_directories()
        source = root / "manuale-collaudo-sintetico.md"
        source.write_text(MANUAL, encoding="utf-8")

        store = Store(settings.database_path)
        embedder = build_embedder(settings)
        llm = LLMClient(settings)
        ingestor = Ingestor(settings, store, embedder, llm)

        ingest_started = time.perf_counter()
        ingestion = ingestor.ingest(source)
        ingest_seconds = time.perf_counter() - ingest_started
        repeated = ingestor.ingest(source)

        service = AnswerService(Retriever(store, embedder, settings), llm, settings)
        results = []
        for case in CASES:
            started = time.perf_counter()
            answer = service.answer(case["question"], top_k=3, include_images=False)
            elapsed = time.perf_counter() - started
            normalized = answer.text.casefold()
            retrieved_pages = [source.page for source in answer.sources]
            facts_ok = all(term in normalized for term in case["terms"])
            citation_ok = "[s1]" in normalized
            retrieval_ok = bool(retrieved_pages and retrieved_pages[0] == case["page"])
            results.append(
                {
                    **case,
                    "retrieved_pages": retrieved_pages,
                    "answer": answer.text,
                    "facts_ok": facts_ok,
                    "citation_ok": citation_ok,
                    "retrieval_ok": retrieval_ok,
                    "passed": facts_ok and citation_ok and retrieval_ok,
                    "wall_seconds": round(elapsed, 3),
                }
            )

        stored_document = store.list_documents()[0]
        stored_markdown_exists = (settings.data_dir / stored_document["markdown_path"]).is_file()

    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "method": {
            "kind": "synthetic Markdown ingestion end-to-end",
            "manuals_real": False,
            "embedding_model": base_settings.embedding_model,
            "llm_model": base_settings.llm_model,
            "queries": len(CASES),
        },
        "ingestion": {
            **asdict(ingestion),
            "wall_seconds": round(ingest_seconds, 3),
            "stored_markdown_exists": stored_markdown_exists,
            "repeat_already_indexed": repeated.already_indexed,
        },
        "summary": {
            "retrieval_passed": sum(result["retrieval_ok"] for result in results),
            "answers_passed": sum(result["passed"] for result in results),
            "total": len(results),
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
