"""Soglie e validazione dei report di regressione."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    actual: float
    minimum: float | None = None
    maximum: float | None = None

    @property
    def passed(self) -> bool:
        if self.minimum is not None and self.actual < self.minimum:
            return False
        return not (self.maximum is not None and self.actual > self.maximum)

    def render(self) -> str:
        if self.minimum is not None:
            requirement = f">= {self.minimum:g}"
        else:
            requirement = f"<= {self.maximum:g}"
        status = "PASS" if self.passed else "FAIL"
        return f"{status} {self.name}: {self.actual:g} (richiesto {requirement})"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _model_provider(report: dict[str, Any], model: str) -> dict[str, Any]:
    for provider in report["providers"]:
        if provider["provider"] == model:
            return provider
    raise ValueError(f"Provider {model} assente dal report")


def build_checks(report_dir: Path) -> list[Check]:
    embedding = _model_provider(_load(report_dir / "embedding.json"), "nomic-embed-text-v2-moe")
    hybrid = _model_provider(_load(report_dir / "hybrid.json"), "nomic-embed-text-v2-moe")["best"]
    end_to_end_report = _load(report_dir / "end-to-end.json")
    end_to_end = end_to_end_report["summary"]
    negation_case = next(
        result
        for result in end_to_end_report["results"]
        if result["expected_document"] == "inactive-state"
    )
    ingestion_report = _load(report_dir / "ingestion.json")
    ingestion = ingestion_report["ingestion"]
    ingestion_summary = ingestion_report["summary"]
    http_smoke = _load(report_dir / "http-smoke.json")["summary"]
    ui_smoke = _load(report_dir / "ui-smoke.json")["summary"]
    return [
        Check("embedding top-1", embedding["top1_correct"], minimum=10),
        Check("embedding top-3", embedding["top3_correct"], minimum=11),
        Check("embedding MRR", embedding["mean_reciprocal_rank"], minimum=0.9545),
        Check("hybrid top-1", hybrid["top1_correct"], minimum=10),
        Check("hybrid top-3", hybrid["top3_correct"], minimum=11),
        Check("hybrid MRR", hybrid["mean_reciprocal_rank"], minimum=0.9545),
        Check("end-to-end retrieval top-1", end_to_end["retrieval_top1"], minimum=10),
        Check("end-to-end retrieval top-3", end_to_end["retrieval_top3"], minimum=11),
        Check("end-to-end risposte", end_to_end["answers_passed"], minimum=11),
        Check("end-to-end casi", end_to_end["total"], minimum=11),
        Check("end-to-end negazione", float(negation_case["passed"]), minimum=1),
        Check(
            "end-to-end latenza mediana",
            end_to_end["median_wall_seconds"],
            maximum=20,
        ),
        Check("ingestion pagine", ingestion["page_count"], minimum=3),
        Check("ingestion chunk", ingestion["chunk_count"], minimum=3),
        Check(
            "ingestion Markdown salvato",
            float(ingestion["stored_markdown_exists"]),
            minimum=1,
        ),
        Check(
            "ingestion idempotente",
            float(ingestion["repeat_already_indexed"]),
            minimum=1,
        ),
        Check("ingestion retrieval", ingestion_summary["retrieval_passed"], minimum=3),
        Check("ingestion risposte", ingestion_summary["answers_passed"], minimum=3),
        Check("HTTP smoke controlli previsti", http_smoke["total"], minimum=6),
        Check("HTTP smoke controlli superati", http_smoke["checks_passed"], minimum=6),
        Check("UI smoke controlli previsti", ui_smoke["total"], minimum=7),
        Check("UI smoke controlli superati", ui_smoke["checks_passed"], minimum=7),
    ]
