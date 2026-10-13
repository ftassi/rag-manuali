"""Verifica il servizio locale dalla slice systemd priva di accesso alla rete esterna."""

from __future__ import annotations

import argparse
import errno
import json
import socket
import subprocess
import sys
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    args = parser.parse_args()

    # Indirizzo riservato alla documentazione: basta il rifiuto locale del kernel.
    # Un timeout o una rete irraggiungibile non provano l'isolamento del servizio.
    with socket.socket() as probe:
        probe.settimeout(3)
        try:
            probe.connect(("198.51.100.1", 443))
        except OSError as exc:
            if exc.errno not in {errno.EPERM, errno.EACCES}:
                raise RuntimeError("Filtro IP non dimostrato: atteso EPERM/EACCES") from exc
        else:
            raise RuntimeError("La connessione esterna non è stata bloccata")
    print("Accesso esterno: bloccato dal kernel", flush=True)

    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    case = next(case for case in cases if not case.get("expect_abstention", False))
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=300) as client:
        home = client.get("/")
        home.raise_for_status()
        assert "Manuali locali" in home.text
        health = client.get("/api/health")
        health.raise_for_status()
        assert health.json()["status"] == "ok"
        response = client.post(
            "/api/questions",
            json={
                "question": case["question"],
                "document_id": case.get("document_id"),
                "include_images": True,
            },
        )
        response.raise_for_status()
        answer = response.json()
        assert all(term.casefold() in answer["answer"].casefold() for term in case["required_terms"])
        assert answer["sources"]
        assert all(source["page"] in case["expected_pdf_pages"] for source in answer["sources"])
        assert all(f"[S{i}]" in answer["answer"] for i in range(1, len(answer["sources"]) + 1))
        page = client.get(next(source["page_url"] for source in answer["sources"] if source["page_url"]))
        page.raise_for_status()
        assert page.headers["content-type"].startswith("image/")
    print("Interfaccia, domanda su manuale locale e pagina citata: OK", flush=True)

    # Importazione via HTTP in un indice temporaneo, senza aggiungere dati al QARA.
    subprocess.run([sys.executable, "scripts/smoke_http.py"], check=True)
    print("Importazione e interrogazione HTTP con indice temporaneo: OK", flush=True)


if __name__ == "__main__":
    main()
