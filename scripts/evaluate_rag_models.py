"""Valuta retrieval e risposte Ollama su fonti tecniche sintetiche."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from manuali_rag.config import Settings
from manuali_rag.embeddings import HashEmbedder
from manuali_rag.llm import LLMClient
from manuali_rag.retrieval import AnswerService, Retriever
from manuali_rag.store import ChunkInput, Store

CASES = [
    {
        "id": "error-code",
        "source": "L'errore E104 indica una pressione insufficiente nel circuito.",
        "question": "Cosa indica l'errore E104?",
        "expected": ["pressione insufficiente"],
        "forbidden": ["temperatura"],
    },
    {
        "id": "torque",
        "source": "Serrare il dado della flangia a 12 Nm.",
        "question": "Qual è la coppia di serraggio del dado della flangia?",
        "expected": ["12 nm"],
        "forbidden": [],
    },
    {
        "id": "maintenance",
        "source": "Pulire il filtro dell'aria ogni sei mesi.",
        "question": "Ogni quanto va pulito il filtro dell'aria?",
        "expected": ["sei mesi"],
        "forbidden": ["garantire", "prevenire", "problemi di funzionamento"],
    },
    {
        "id": "temperature",
        "source": "La temperatura massima di esercizio è 65 °C.",
        "question": "Qual è la temperatura massima di esercizio?",
        "expected": ["65"],
        "forbidden": ["75"],
    },
    {
        "id": "safety-order",
        "source": "Prima di rimuovere il coperchio, scollegare l'alimentazione elettrica.",
        "question": "Cosa bisogna fare prima di rimuovere il coperchio?",
        "expected": ["scollegare", "alimentazione"],
        "forbidden": ["riavviare"],
    },
    {
        "id": "pressure",
        "source": "Regolare la pressione nominale a 2,5 bar.",
        "question": "A quale pressione nominale va regolato il dispositivo?",
        "expected": ["2,5 bar"],
        "forbidden": ["3,5"],
    },
    {
        "id": "exact-name",
        "source": "Il kit di ricambio compatibile è denominato KX-17B.",
        "question": "Qual è il nome esatto del kit di ricambio compatibile?",
        "expected": ["kx-17b"],
        "forbidden": ["kx-17a"],
    },
    {
        "id": "irrelevant-neighbor",
        "source": "Il codice A7 segnala lo scarico ostruito. Dopo la manutenzione ordinaria si può riavviare il pannello.",
        "question": "Cosa segnala il codice A7?",
        "expected": ["scarico ostruito"],
        "forbidden": ["riavviare", "manutenzione ordinaria"],
    },
]


def prepare_store(root: Path, settings: Settings) -> tuple[Store, HashEmbedder]:
    store = Store(root / "synthetic.sqlite3")
    embedder = HashEmbedder(settings.hash_embedding_dimensions)
    for page, case in enumerate(CASES, start=1):
        chunk = ChunkInput(page=page, section="Dati tecnici", content=case["source"])
        store.replace_document(
            document_id=case["id"],
            checksum=f"synthetic-{case['id']}",
            source_name=f"{case['id']}.md",
            title=f"Manuale sintetico {case['id']}",
            markdown_path="",
            page_count=1,
            warnings=[],
            chunks=[chunk],
            embeddings=embedder.embed([chunk.content]),
            embedding_model=embedder.model_name,
        )
    return store, embedder


def evaluate_model(model: str, settings: Settings, store: Store, embedder: HashEmbedder) -> dict:
    model_settings = replace(settings, llm_model=model)
    service = AnswerService(
        Retriever(store, embedder, model_settings), LLMClient(model_settings), model_settings
    )
    results = []
    for case in CASES:
        started = time.perf_counter()
        answer = service.answer(
            case["question"], document_id=case["id"], top_k=1, include_images=False
        )
        elapsed = time.perf_counter() - started
        normalized = answer.text.casefold()
        facts_ok = all(term in normalized for term in case["expected"])
        forbidden_ok = not any(term in normalized for term in case["forbidden"])
        citation_ok = "[s1]" in normalized
        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "answer": answer.text,
                "retrieved_expected_source": bool(answer.sources)
                and answer.sources[0].document_id == case["id"],
                "facts_ok": facts_ok,
                "forbidden_ok": forbidden_ok,
                "citation_ok": citation_ok,
                "passed": facts_ok and forbidden_ok and citation_ok,
                "wall_seconds": round(elapsed, 3),
            }
        )
    return {
        "model": model,
        "passed": sum(bool(result["passed"]) for result in results),
        "total": len(results),
        "median_wall_seconds": round(
            statistics.median(float(result["wall_seconds"]) for result in results), 3
        ),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["llama3.2:3b", "qwen2.5:1.5b"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base_settings = Settings.from_env()
    with tempfile.TemporaryDirectory(prefix="manuali-rag-eval-") as temporary:
        root = Path(temporary)
        settings = replace(
            base_settings,
            data_dir=root,
            database_path=root / "synthetic.sqlite3",
            embedding_provider="hash",
            caption_mode="off",
            max_images_per_question=0,
        )
        store, embedder = prepare_store(root, settings)
        models = [evaluate_model(model, settings, store, embedder) for model in args.models]

    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "method": {
            "kind": "end-to-end synthetic RAG",
            "cases": len(CASES),
            "retrieval": "SQLite FTS5 + hash embeddings, document-scoped",
            "manuals_real": False,
        },
        "models": models,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
