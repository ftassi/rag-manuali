"""Smoke test dell'API HTTP reale con un manuale sintetico temporaneo."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

MANUAL = """<!-- pagina: 4 -->
## Procedura di arresto
Per arrestare l'unità premere il pulsante VX-8 per tre secondi.

<!-- pagina: 9 -->
## Diagnostica
Il codice R17 indica che la valvola di ritorno è bloccata.
"""


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(client: httpx.Client, server: subprocess.Popen[str]) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError("Il server si è arrestato durante l'avvio")
        try:
            response = client.get("/api/health")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            time.sleep(0.25)
    raise TimeoutError("L'endpoint /api/health non ha risposto entro 30 secondi")


def _request_json(response: httpx.Response) -> Any:
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    port = _free_port()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="manuali-http-") as temporary:
        root = Path(temporary)
        source = root / "manuale-http-sintetico.md"
        source.write_text(MANUAL, encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "MANUALI_DATA_DIR": str(root / "data"),
                "MANUALI_CAPTION_MODE": "off",
                "MANUALI_MAX_IMAGES_PER_QUESTION": "0",
            }
        )
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "manuali_rag.cli",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=90) as client:
                health_before = _wait_for_health(client, server)
                with source.open("rb") as handle:
                    upload = _request_json(
                        client.post(
                            "/api/documents",
                            files={"file": (source.name, handle, "text/markdown")},
                        )
                    )
                documents = _request_json(client.get("/api/documents"))
                search = _request_json(
                    client.post(
                        "/api/search",
                        json={"question": "Che cosa indica R17?", "top_k": 3},
                    )
                )
                answer = _request_json(
                    client.post(
                        "/api/questions",
                        json={
                            "question": "Che cosa indica R17?",
                            "top_k": 3,
                            "include_images": False,
                        },
                    )
                )
                health_after = _request_json(client.get("/api/health"))
        except Exception as exc:
            server.terminate()
            output, _ = server.communicate(timeout=10)
            raise RuntimeError(f"Smoke test HTTP fallito: {exc}\nLog server:\n{output}") from exc
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)

    normalized_answer = answer["answer"].casefold()
    results = {
        "health_before_empty": health_before["index"] == {"documents": 0, "chunks": 0},
        "upload_ok": upload["pages"] == 2 and upload["chunks"] == 2,
        "documents_ok": len(documents) == 1 and documents[0]["id"] == upload["document_id"],
        "search_ok": bool(search["results"] and search["results"][0]["page"] == 9),
        "answer_ok": (
            "r17" in normalized_answer
            and "valvola di ritorno" in normalized_answer
            and "bloccata" in normalized_answer
            and "[s1]" in normalized_answer
        ),
        "health_after_ok": health_after["index"] == {"documents": 1, "chunks": 2},
    }
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "method": {
            "kind": "real HTTP synthetic smoke test",
            "manuals_real": False,
            "host": "127.0.0.1",
        },
        "summary": {
            "checks_passed": sum(results.values()),
            "total": len(results),
            "wall_seconds": round(time.perf_counter() - started, 3),
        },
        "checks": results,
        "answer": answer,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not all(results.values()):
        raise SystemExit("Smoke test HTTP fallito: una o più verifiche non sono state superate")


if __name__ == "__main__":
    main()
