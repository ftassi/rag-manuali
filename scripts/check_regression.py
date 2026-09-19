"""Verifica soglie minime sui report di regressione del Raspberry Pi."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from manuali_rag.regression import build_checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir", type=Path)
    args = parser.parse_args()
    try:
        checks = build_checks(args.report_dir)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL report di regressione non valido: {exc}") from exc

    for check in checks:
        print(check.render())
    failures = [check for check in checks if not check.passed]
    if failures:
        raise SystemExit(f"Regressione fallita: {len(failures)} soglie non rispettate")
    print(f"Regressione superata: {len(checks)}/{len(checks)} soglie rispettate")


if __name__ == "__main__":
    main()
