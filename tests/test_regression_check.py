import json

from manuali_rag.regression import Check, build_checks


def test_check_supports_minimum_and_maximum() -> None:
    assert Check("minimum", 9, minimum=9).passed
    assert not Check("minimum", 8, minimum=9).passed
    assert Check("maximum", 19.9, maximum=20).passed
    assert not Check("maximum", 20.1, maximum=20).passed


def test_build_checks_reads_all_reports(tmp_path) -> None:
    (tmp_path / "embedding.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider": "nomic-embed-text-v2-moe",
                        "top1_correct": 9,
                        "top3_correct": 10,
                        "mean_reciprocal_rank": 0.95,
                    }
                ]
            }
        )
    )
    (tmp_path / "hybrid.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider": "nomic-embed-text-v2-moe",
                        "best": {
                            "top1_correct": 9,
                            "top3_correct": 10,
                            "mean_reciprocal_rank": 0.95,
                        },
                    }
                ]
            }
        )
    )
    (tmp_path / "end-to-end.json").write_text(
        json.dumps(
            {
                "summary": {
                    "retrieval_top1": 9,
                    "retrieval_top3": 10,
                    "answers_passed": 10,
                    "median_wall_seconds": 12,
                }
            }
        )
    )
    (tmp_path / "ingestion.json").write_text(
        json.dumps(
            {
                "ingestion": {
                    "page_count": 3,
                    "chunk_count": 3,
                    "stored_markdown_exists": True,
                    "repeat_already_indexed": True,
                },
                "summary": {"retrieval_passed": 3, "answers_passed": 3},
            }
        )
    )
    (tmp_path / "http-smoke.json").write_text(
        json.dumps({"summary": {"checks_passed": 6, "total": 6}})
    )
    (tmp_path / "ui-smoke.json").write_text(
        json.dumps({"summary": {"checks_passed": 7, "total": 7}})
    )

    checks = build_checks(tmp_path)

    assert len(checks) == 20
    assert all(check.passed for check in checks)
