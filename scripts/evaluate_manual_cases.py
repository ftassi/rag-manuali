"""Collaudo ripetibile con domande e criteri locali, esclusi dal repository."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from manuali_rag.cli import _components
from manuali_rag.config import Settings
from manuali_rag.retrieval import AnswerService, Retriever


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    if not cases:
        raise ValueError("Il file non contiene casi di collaudo")
    settings = Settings.from_env()
    store, embedder, llm = _components(settings)
    service = AnswerService(Retriever(store, embedder, settings), llm, settings)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    results = []
    for case in cases:
        expected_pages = case.get("expected_pdf_pages", [])
        if not expected_pages and not case.get("expect_abstention", False):
            raise ValueError(f"Specificare pagine attese o astensione per {case['id']}")
        started = time.perf_counter()
        answer = service.answer(
            case["question"], document_id=case.get("document_id"), include_images=False
        )
        normalized = answer.text.casefold()
        pages = [source.page for source in answer.sources]
        if case.get("expect_abstention", False):
            facts_ok = answer.text in {
                "Le fonti fornite non contengono questa informazione.",
                "Non ho trovato informazioni pertinenti nei manuali indicizzati.",
            }
            sources_ok = not answer.sources
            citations_ok = True
        else:
            facts_ok = all(term.casefold() in normalized for term in case["required_terms"])
            sources_ok = bool(set(pages) & set(expected_pages)) and all(
                page in expected_pages for page in pages
            )
            citations_ok = bool(answer.sources) and all(
                f"[S{index}]" in answer.text for index in range(1, len(answer.sources) + 1)
            )
        extra = [
            term for term in case.get("forbidden_terms", []) if term.casefold() in normalized
        ]
        result = {
            "id": case["id"],
            "question": case["question"],
            "expected_pdf_pages": expected_pages,
            "required_terms": case.get("required_terms", []),
            "forbidden_terms": case.get("forbidden_terms", []),
            "expect_abstention": case.get("expect_abstention", False),
            "answer": answer.text,
            "selected_pdf_pages": pages,
            "facts_ok": facts_ok,
            "sources_ok": sources_ok,
            "citations_ok": citations_ok,
            "extraneous": extra,
            "passed": facts_ok and sources_ok and citations_ok and not extra,
            "wall_seconds": round(time.perf_counter() - started, 3),
        }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "code_commit": commit,
        "cases_file": str(args.cases.resolve()),
        "cases": results,
        "passed": sum(result["passed"] for result in results),
        "total": len(results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collaudo: {report['passed']}/{report['total']}; report: {args.output}", flush=True)
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
