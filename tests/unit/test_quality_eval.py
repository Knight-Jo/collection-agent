"""Quality-eval harness over the fixed labeled cases (spec 002 SC-102/201)."""

from __future__ import annotations

from intel_agent.contracts.documents import Citation
from intel_agent.factcheck.models import FactEvidence
from intel_agent.factcheck.verdict import adjudicate
from intel_agent.monitoring.diff import diff_baseline
from tests.fixtures import (
    MONITOR_DIFF_CASES,
    VERDICT_CASES,
    verdict_direction,
)


def _evidence(spec) -> FactEvidence:
    relation, group, nature = spec
    return FactEvidence(
        evidence_id=f"{relation}-{group}",
        fact_check_id="fc",
        relation=relation,
        quote="q",
        citation=Citation(
            citation_id="C1",
            chunk_id="c",
            artifact_id="a",
            document_id="d",
            revision_id="r",
            resource_id="res",
        ),
        independence_group=group,
        source_nature=nature,
    )


def run_monitor_diff_eval() -> dict:
    total = len(MONITOR_DIFF_CASES)
    correct = 0
    for baseline, current, exp_new, exp_changed in MONITOR_DIFF_CASES:
        new, changed, _matched = diff_baseline(current, baseline)
        if new == exp_new and changed == exp_changed:
            correct += 1
    return {
        "name": "monitor_diff",
        "total": total,
        "correct": correct,
        "accuracy": correct / total,
    }


def run_verdict_eval() -> dict:
    total = len(VERDICT_CASES)
    exact = 0
    direction_correct = 0
    confusion: dict[str, dict[str, int]] = {}
    for specs, expected in VERDICT_CASES:
        verdict, _suff, _counts = adjudicate([_evidence(s) for s in specs])
        if verdict == expected:
            exact += 1
        if verdict_direction(verdict) == verdict_direction(expected):
            direction_correct += 1
        confusion.setdefault(expected, {}).setdefault(verdict, 0)
        confusion[expected][verdict] += 1
    return {
        "name": "verdict",
        "total": total,
        "exact": exact,
        "exact_accuracy": exact / total,
        "direction_correct": direction_correct,
        "direction_accuracy": direction_correct / total,
        "confusion": confusion,
    }


def test_monitor_diff_accuracy_above_80():
    result = run_monitor_diff_eval()
    assert result["accuracy"] >= 0.80, result


def test_verdict_direction_accuracy_above_80():
    result = run_verdict_eval()
    assert result["direction_accuracy"] >= 0.80, result


def test_verdict_exact_accuracy_reported():
    result = run_verdict_eval()
    assert result["total"] == 30
    assert result["exact_accuracy"] > 0.5, result
