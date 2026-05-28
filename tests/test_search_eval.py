from __future__ import annotations

import json
from pathlib import Path

from erfairy.indexer import InMemoryTfIdfIndex
from erfairy.sample_data import SAMPLE_DOCUMENTS
from erfairy.store import SQLiteDocumentStore


def test_sample_search_eval_set(tmp_path, request):
    store = SQLiteDocumentStore(tmp_path / "eval.sqlite3")
    documents = store.bulk_upsert(SAMPLE_DOCUMENTS)
    index = InMemoryTfIdfIndex()
    index.rebuild(documents)

    eval_path = Path(__file__).parent / "fixtures" / "search_eval.json"
    cases = json.loads(eval_path.read_text(encoding="utf-8"))

    top1_hits = 0
    top3_hits = 0
    zero_results = 0

    for case in cases:
        results, total = index.search(case["query"], category=None, limit=3)
        urls = [document.url for document, _score in results]

        if total == 0:
            zero_results += 1
            continue
        if urls and urls[0] == case["expected_top1"]:
            top1_hits += 1
        if any(expected in urls for expected in case["expected_top3_contains"]):
            top3_hits += 1

    total_cases = len(cases)
    top1_accuracy = top1_hits / total_cases
    top3_accuracy = top3_hits / total_cases
    zero_result_rate = zero_results / total_cases

    request.config._search_eval_summary = {
        "total_cases": total_cases,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "zero_results": zero_results,
        "top1_accuracy": top1_accuracy,
        "top3_accuracy": top3_accuracy,
        "zero_result_rate": zero_result_rate,
    }

    assert top1_accuracy >= 0.8
    assert top3_accuracy >= 0.95
    assert zero_result_rate == 0
