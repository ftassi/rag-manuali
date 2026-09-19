"""Confronta embedding hash e Ollama su retrieval semantico italiano sintetico."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from manuali_rag.embeddings import HashEmbedder, OpenAIEmbedder

DOCUMENTS = [
    ("power", "Prima di aprire il pannello, scollegare l'alimentazione elettrica."),
    ("filter", "Pulire il filtro dell'aria ogni sei mesi."),
    ("torque", "Serrare il dado della flangia a 12 Nm."),
    ("temperature", "La temperatura massima di esercizio è 65 °C."),
    ("pressure", "L'errore E104 indica una pressione insufficiente nel circuito."),
    ("drain", "Il codice A7 segnala lo scarico ostruito."),
    ("replacement", "Il kit di ricambio compatibile è denominato KX-17B."),
    ("battery", "Sostituire la batteria quando l'indicatore lampeggia in rosso."),
    ("lubrication", "Applicare grasso al silicone sulle guarnizioni una volta all'anno."),
    ("storage", "Conservare il dispositivo in un luogo asciutto e ventilato."),
]

QUERIES = [
    ("Come tolgo la corrente prima di accedere all'interno?", "power"),
    ("Qual è l'intervallo per detergere l'elemento filtrante?", "filter"),
    ("Quale forza di rotazione va applicata al fissaggio?", "torque"),
    ("Qual è il limite termico consentito durante l'uso?", "temperature"),
    ("Che cosa significa E104 quando il circuito ha poca pressione?", "pressure"),
    ("Quale anomalia segnala A7 nel condotto di uscita?", "drain"),
    ("Qual è il codice del pezzo sostitutivo ammesso?", "replacement"),
    ("Cosa fare quando la spia rossa pulsa?", "battery"),
    ("Con cosa vanno ingrassate annualmente le tenute?", "lubrication"),
    ("In quale ambiente va riposto l'apparecchio?", "storage"),
]


def evaluate(name: str, embedder: object) -> dict[str, object]:
    started = time.perf_counter()
    document_vectors = embedder.embed([text for _, text in DOCUMENTS])
    query_vectors = embedder.embed([query for query, _ in QUERIES])
    elapsed = time.perf_counter() - started
    results = []
    reciprocal_ranks = []
    for (query, expected), query_vector in zip(QUERIES, query_vectors, strict=True):
        scores = [
            sum(a * b for a, b in zip(query_vector, vector, strict=True))
            for vector in document_vectors
        ]
        ranking = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
        ranked_ids = [DOCUMENTS[index][0] for index in ranking]
        rank = ranked_ids.index(expected) + 1
        reciprocal_ranks.append(1 / rank)
        results.append(
            {
                "query": query,
                "expected": expected,
                "rank": rank,
                "top3": ranked_ids[:3],
                "top1_score": round(scores[ranking[0]], 4),
            }
        )
    return {
        "provider": name,
        "dimensions": len(document_vectors[0]),
        "top1_correct": sum(result["rank"] == 1 for result in results),
        "top3_correct": sum(result["rank"] <= 3 for result in results),
        "total": len(results),
        "mean_reciprocal_rank": round(statistics.mean(reciprocal_ranks), 4),
        "total_embedding_seconds": round(elapsed, 3),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", default="nomic-embed-text-v2-moe")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    providers = [
        evaluate("hash-dev", HashEmbedder(384)),
        evaluate(
            args.model,
            OpenAIEmbedder(args.base_url, args.model, timeout=120),
        ),
    ]
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "method": {
            "kind": "synthetic semantic retrieval",
            "documents": len(DOCUMENTS),
            "queries": len(QUERIES),
            "language": "it",
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
