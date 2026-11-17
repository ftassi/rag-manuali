"""Collaudo ripetibile con domande e criteri locali, esclusi dal repository."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import httpx

from manuali_rag.cli import _components
from manuali_rag.config import Settings
from manuali_rag.retrieval import CLARIFICATION_TEXT, AnswerService, Retriever


def write_html_report(path: Path, report: dict, images: list[list[tuple[str, str]]]) -> None:
    sections = []
    for case, previews in zip(report["cases"], images, strict=True):
        status = "Superato" if case["passed"] else "Da verificare"
        checks = {
            "Testo": case["facts_ok"] and not case["extraneous"],
            "Fonti": case["sources_ok"],
            "Citazioni": case["citations_ok"],
            "Immagini": case["images_ok"],
        }
        details = " · ".join(f"{label}: {'OK' if ok else 'da verificare'}"
                             for label, ok in checks.items())
        figures = "".join(
            f'<figure><figcaption>{escape(label)}</figcaption>'
            f'<img alt="{escape(label)}" src="{escape(url)}"></figure>'
            for label, url in previews
        )
        sections.append(
            f'<section><h2>{escape(case["question"])}</h2>'
            f'<p><strong>{status}</strong> · {details}</p>'
            f'<p class="answer">{escape(case["answer"])}</p>{figures}</section>'
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<!doctype html><html lang="it"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Collaudo RAG</title><style>body{font:1rem system-ui;max-width:64rem;'
        'margin:2rem auto;padding:0 1rem}section{border-top:1px solid #999}'
        '.answer{white-space:pre-wrap}img{max-width:100%;height:auto}</style>'
        f'<h1>Collaudo RAG: {report["passed"]}/{report["total"]}</h1>'
        f'<p>{escape(report["timestamp_utc"])} · Checkout {escape(report["code_commit"][:7])}</p>'
        '<p>Gli esiti automatici non valutano la naturalezza della risposta o la pertinenza visiva.</p>'
        + "".join(sections) + '</html>',
        encoding="utf-8",
    )


def documents_match(
    selected: list[str], expected: list[str], required: list[str] | tuple[str, ...] = (),
) -> bool:
    """La stessa pagina di un altro manuale non è una fonte valida."""
    return (not expected or bool(selected) and set(selected) <= set(expected)) and set(required) <= set(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--api-url", help="Collauda il servizio HTTP, incluse le pagine citate")
    parser.add_argument("--html", type=Path, help="Salva anche un report HTML con immagini incorporate")
    parser.add_argument("--model", help="Confronta un modello locale nella modalità CLI")
    args = parser.parse_args()
    if args.model and args.api_url:
        parser.error("--model si usa senza --api-url")
    if args.html and not args.api_url:
        parser.error("--html richiede --api-url")
    if args.html and args.html.resolve() == args.output.resolve():
        parser.error("--html e --output devono indicare due file distinti")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    if not cases:
        raise ValueError("Il file non contiene casi di collaudo")
    settings = Settings.from_env()
    if args.model:
        settings = replace(settings, llm_model=args.model)
    service = None
    if not args.api_url:
        store, embedder, llm = _components(settings)
        service = AnswerService(Retriever(store, embedder, settings), llm, settings)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    results = []
    previews = []
    for case in cases:
        expected_pages = case.get("expected_pdf_pages", [])
        expected_documents = case.get("expected_document_ids", [])
        if not expected_pages and not case.get("expect_abstention", False):
            raise ValueError(f"Specificare pagine attese o astensione per {case['id']}")
        started = time.perf_counter()
        images_ok = None
        case_previews = []
        if args.api_url:
            with httpx.Client(base_url=args.api_url, timeout=settings.llm_timeout + 120,
                              trust_env=False) as client:
                response = client.post("/api/questions", json={
                    "question": case["question"],
                    "document_id": case.get("document_id"),
                    "include_images": True,
                })
                response.raise_for_status()
                payload = response.json()
                answer_text = payload["answer"]
                pages = [source["page"] for source in payload["sources"]]
                documents = [source["document_id"] for source in payload["sources"]]
                source_count = len(payload["sources"])
                images_ok = bool(source_count) or case.get("expect_abstention", False)
                for index, source in enumerate(payload["sources"], start=1):
                    if not source.get("page_url"):
                        images_ok = False
                        continue
                    image = client.get(source["page_url"])
                    mime = image.headers.get("content-type", "").split(";")[0].strip().lower()
                    image_ok = image.is_success and mime.startswith("image/")
                    images_ok = images_ok and image_ok
                    if args.html and image_ok and mime in {"image/png", "image/jpeg", "image/webp"}:
                        label = f'[S{index}] {source["manual_title"]}, pagina {source["page"]}'
                        encoded = base64.b64encode(image.content).decode("ascii")
                        case_previews.append((label, f"data:{mime};base64,{encoded}"))
        else:
            assert service is not None
            answer = service.answer(
                case["question"], document_id=case.get("document_id"), include_images=False
            )
            answer_text = answer.text
            pages = [source.page for source in answer.sources]
            documents = [source.document_id for source in answer.sources]
            source_count = len(answer.sources)
        normalized = answer_text.casefold()
        if case.get("expect_abstention", False):
            expected_texts = {
                "Le fonti fornite non contengono questa informazione.",
                "Non ho trovato informazioni pertinenti nei manuali indicizzati.",
            }
            if case.get("expect_clarification", False):
                expected_texts = {case.get("clarification_text", CLARIFICATION_TEXT)}
            facts_ok = answer_text in expected_texts
            sources_ok = not source_count
            citations_ok = True
        else:
            facts_ok = all(term.casefold() in normalized for term in case["required_terms"])
            sources_ok = bool(set(pages) & set(expected_pages)) and all(
                page in expected_pages for page in pages
            ) and documents_match(documents, expected_documents, case.get("required_document_ids", []))
            citations_ok = bool(source_count) and all(
                f"[S{index}]" in answer_text for index in range(1, source_count + 1)
            )
        extra = [
            term for term in case.get("forbidden_terms", []) if term.casefold() in normalized
        ]
        result = {
            "id": case["id"],
            "question": case["question"],
            "expected_pdf_pages": expected_pages,
            "expected_document_ids": expected_documents,
            "required_document_ids": case.get("required_document_ids", []),
            "required_terms": case.get("required_terms", []),
            "forbidden_terms": case.get("forbidden_terms", []),
            "expect_abstention": case.get("expect_abstention", False),
            "expect_clarification": case.get("expect_clarification", False),
            "answer": answer_text,
            "selected_pdf_pages": pages,
            "selected_document_ids": documents,
            "facts_ok": facts_ok,
            "sources_ok": sources_ok,
            "citations_ok": citations_ok,
            "extraneous": extra,
            "images_ok": images_ok,
            "passed": facts_ok and sources_ok and citations_ok and not extra and images_ok is not False,
            "wall_seconds": round(time.perf_counter() - started, 3),
        }
        results.append(result)
        previews.append(case_previews)
        if args.html:
            status = "OK" if result["passed"] else "DA VERIFICARE"
            print(f'{len(results)}/{len(cases)} {status} — {case["id"]}', flush=True)
        else:
            print(json.dumps(result, ensure_ascii=False), flush=True)
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "code_commit": commit,
        "cases_file": str(args.cases.resolve()),
        "api_url": args.api_url,
        "llm_model": settings.llm_model,
        "cases": results,
        "passed": sum(result["passed"] for result in results),
        "total": len(results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.html:
        write_html_report(args.html, report, previews)
        print(f"Report da aprire nel browser: {args.html.resolve()}", flush=True)
    print(f"Collaudo: {report['passed']}/{report['total']}; report: {args.output}", flush=True)
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
