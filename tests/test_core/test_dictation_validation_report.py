import json

import pytest

from tools.dictation_validation_report import load_jsonl, percentile, summarize


def test_percentile_uses_nearest_rank_and_handles_empty_values():
    assert percentile([], 0.95) is None
    assert percentile([1, 2, 3, 4, 5], 0.95) == 5.0
    assert percentile([5, 1, 4, 2, 3], 0.50) == 3.0


def test_summary_preserves_missing_insertion_measurements():
    result = summarize([
        {
            "activation_to_listening_ms": 10,
            "activation_to_first_commit_ms": 100,
            "activation_to_first_insert_ms": None,
            "finalization_ms": 50,
            "max_queue_wait_ms": 0,
        },
        {
            "activation_to_listening_ms": 20,
            "activation_to_first_commit_ms": 200,
            "activation_to_first_insert_ms": 250,
            "finalization_ms": 70,
            "max_queue_wait_ms": 30,
        },
    ])

    insert = result["metrics"]["activation_to_first_insert_ms"]
    assert insert["count"] == 1
    assert insert["missing"] == 1
    assert insert["median"] == 250.0
    assert insert["p95"] == 250.0


def test_load_jsonl_rejects_non_object_rows(tmp_path):
    path = tmp_path / "metrics.jsonl"
    path.write_text(json.dumps({"max_queue_wait_ms": 1}) + "\n[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="riga 2"):
        load_jsonl(path)
