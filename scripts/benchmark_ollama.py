"""Benchmark ripetibile di un modello Ollama usando le metriche native dell'API."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

CASES = [
    {
        "prompt": "Rispondi in italiano in una frase: il manuale dice che E104 indica pressione insufficiente. Cosa indica E104?",
        "expected": ["pressione insufficiente"],
    },
    {
        "prompt": "Estrai solo il valore: 'Serrare il dado a 12 Nm'. Qual e la coppia di serraggio?",
        "expected": ["12 nm"],
    },
    {
        "prompt": "Usa solo la fonte. Fonte: pulire il filtro ogni sei mesi. Domanda: ogni quanto va pulito il filtro?",
        "expected": ["sei mesi"],
    },
]


def generate(base_url: str, model: str, prompt: str, num_predict: int) -> dict[str, object]:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "seed": 42, "num_predict": num_predict},
            "keep_alive": "5m",
        }
    ).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.load(response)
    result["wall_duration_seconds"] = time.perf_counter() - started
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="llama3.2:3b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--num-predict", type=int, default=96)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    generate(args.base_url, args.model, "Rispondi soltanto: pronto", 8)
    runs = []
    for case in CASES:
        prompt = case["prompt"]
        raw = generate(args.base_url, args.model, prompt, args.num_predict)
        eval_count = int(raw.get("eval_count", 0))
        eval_duration = int(raw.get("eval_duration", 0))
        prompt_count = int(raw.get("prompt_eval_count", 0))
        prompt_duration = int(raw.get("prompt_eval_duration", 0))
        response = str(raw.get("response", "")).strip()
        expected = list(case["expected"])
        runs.append(
            {
                "prompt": prompt,
                "response": response,
                "expected": expected,
                "fact_check_passed": all(term in response.casefold() for term in expected),
                "wall_seconds": round(float(raw["wall_duration_seconds"]), 3),
                "prompt_tokens": prompt_count,
                "prompt_tokens_per_second": round(prompt_count / (prompt_duration / 1e9), 3)
                if prompt_duration
                else None,
                "generated_tokens": eval_count,
                "generated_tokens_per_second": round(eval_count / (eval_duration / 1e9), 3)
                if eval_duration
                else None,
                "load_seconds": round(int(raw.get("load_duration", 0)) / 1e9, 3),
            }
        )

    speeds = [
        float(run["generated_tokens_per_second"])
        for run in runs
        if run["generated_tokens_per_second"]
    ]
    passed = sum(bool(run["fact_check_passed"]) for run in runs)
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "host": {
            "node": platform.node(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "ollama": {"base_url": args.base_url, "model": args.model},
        "method": {
            "warmup_runs": 1,
            "measured_runs": len(runs),
            "temperature": 0,
            "seed": 42,
            "num_predict": args.num_predict,
        },
        "summary": {
            "median_generated_tokens_per_second": round(statistics.median(speeds), 3),
            "min_generated_tokens_per_second": round(min(speeds), 3),
            "max_generated_tokens_per_second": round(max(speeds), 3),
            "median_wall_seconds": round(
                statistics.median(float(run["wall_seconds"]) for run in runs), 3
            ),
            "fact_checks_passed": passed,
            "fact_checks_total": len(runs),
        },
        "runs": runs,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
