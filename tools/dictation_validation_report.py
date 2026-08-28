#!/usr/bin/env python3
"""Summarize JSONL dictation latency samples."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

METRICS = (
    "activation_to_listening_ms",
    "activation_to_first_commit_ms",
    "activation_to_first_insert_ms",
    "finalization_ms",
    "max_queue_wait_ms",
)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return float(ordered[index])


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"samples": len(samples), "metrics": {}}
    for name in METRICS:
        values: list[float] = []
        missing = 0
        for sample in samples:
            value = sample.get(name)
            if value is None:
                missing += 1
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                missing += 1
        result["metrics"][name] = {
            "count": len(values),
            "missing": missing,
            "median": median(values) if values else None,
            "p95": percentile(values, 0.95),
            "max": max(values) if values else None,
        }
    return result


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            if not isinstance(item, dict):
                raise ValueError(f"riga {line_number}: oggetto JSON atteso")
            samples.append(item)
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(load_jsonl(args.path)), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
