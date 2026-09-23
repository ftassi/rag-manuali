"""Collaudo browser headless dell'interfaccia web con dati sintetici temporanei."""

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

import httpx
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

MANUAL = """<!-- pagina: 3 -->
## Arresto
Per arrestare l'unità tenere premuto il tasto LK-4 per quattro secondi.

<!-- pagina: 9 -->
## Diagnostica
Il codice R17 indica che la valvola di ritorno è bloccata.
"""


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_server(url: str, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError("Il server si è arrestato durante l'avvio")
        try:
            response = httpx.get(f"{url}/api/health", timeout=1)
            response.raise_for_status()
            return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise TimeoutError("Il server non ha risposto entro 30 secondi")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    started = time.perf_counter()
    checks: dict[str, bool] = {}
    answer_text = ""
    source_text = ""

    with tempfile.TemporaryDirectory(prefix="manuali-ui-") as temporary:
        root = Path(temporary)
        source = root / "manuale-ui-sintetico.md"
        source.write_text(MANUAL, encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "MANUALI_DATA_DIR": str(root / "data"),
                "MANUALI_CAPTION_MODE": "off",
                "MANUALI_MAX_IMAGES_PER_QUESTION": "0",
            }
        )
        server_log = (root / "server.log").open("w+", encoding="utf-8")
        driver_log = (root / "geckodriver.log").open("w+", encoding="utf-8")
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
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        driver: webdriver.Firefox | None = None
        try:
            _wait_for_server(url, server)
            options = Options()
            options.add_argument("-headless")
            options.set_preference("network.proxy.type", 0)
            driver = webdriver.Firefox(options=options, service=Service(log_output=driver_log))
            driver.set_window_size(1280, 900)
            wait = WebDriverWait(driver, 120)

            driver.get(url)
            checks["page_loaded"] = (
                driver.title == "Manuali locali"
                and driver.find_element(By.TAG_NAME, "h1").text == "Manuali locali"
            )

            driver.find_element(By.ID, "file").send_keys(str(source))
            driver.find_element(By.ID, "upload").click()
            wait.until(
                lambda browser: (
                    "2 pagine, 2 sezioni indicizzate"
                    in browser.find_element(By.ID, "upload-status").text
                )
            )
            upload_status = driver.find_element(By.ID, "upload-status").text
            checks["upload_feedback"] = "Manuale Ui Sintetico" in upload_status

            driver.find_element(By.ID, "question").send_keys("Che cosa indica il codice R17?")
            driver.find_element(By.ID, "ask").click()
            wait.until(lambda browser: bool(browser.find_element(By.ID, "answer").text.strip()))
            wait.until(lambda browser: browser.find_element(By.ID, "ask").is_enabled())

            answer_text = driver.find_element(By.ID, "answer").text
            source_text = driver.find_element(By.ID, "sources").text
            normalized = answer_text.casefold()
            checks["answer_rendered"] = all(
                term in normalized for term in ("r17", "valvola di ritorno", "bloccata", "[s1]")
            )
            checks["source_rendered"] = all(
                term in source_text
                for term in ("[S1] Manuale Ui Sintetico", "Diagnostica", "pagina 9")
            )
            checks["no_broken_page_link"] = not driver.find_elements(By.CSS_SELECTOR, "#sources a")
            checks["controls_reenabled"] = (
                driver.find_element(By.ID, "upload").is_enabled()
                and driver.find_element(By.ID, "ask").is_enabled()
            )
            checks["no_visible_error"] = not driver.find_elements(By.CSS_SELECTOR, ".error")

            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                driver.save_screenshot(str(args.screenshot.resolve()))
        except Exception as exc:
            server_log.seek(0)
            driver_log.seek(0)
            raise RuntimeError(
                f"Smoke test UI fallito: {exc}\n"
                f"Log server:\n{server_log.read()}\n"
                f"Log WebDriver:\n{driver_log.read()}"
            ) from exc
        finally:
            if driver is not None:
                driver.quit()
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)
            server_log.close()
            driver_log.close()

    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "method": {
            "kind": "Firefox headless synthetic UI smoke test",
            "manuals_real": False,
            "browser": "Firefox",
        },
        "summary": {
            "checks_passed": sum(checks.values()),
            "total": len(checks),
            "wall_seconds": round(time.perf_counter() - started, 3),
        },
        "checks": checks,
        "answer": answer_text,
        "sources": source_text,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not checks or not all(checks.values()):
        raise SystemExit("Smoke test UI fallito: una o più verifiche non sono state superate")


if __name__ == "__main__":
    main()
