"""Tests for model-neutral experiment scoring and comparison."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.evaluate_runs import (
    Benchmark,
    EvaluationInput,
    EvaluationPolicy,
    compare_scores,
    main,
    score_evaluation,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _policy() -> EvaluationPolicy:
    return EvaluationPolicy.model_validate(
        {
            "schema_version": "1.0",
            "groups": {
                "coverage": {
                    "weight": 0.6,
                    "metrics": {
                        "question_coverage": 0.5,
                        "key_fact_recall": 0.5,
                    },
                },
                "evidence": {
                    "weight": 0.4,
                    "metrics": {"citation_precision": 1.0},
                },
            },
            "gates": {
                "unsupported_major_claims": {
                    "operator": "max",
                    "threshold": 0,
                },
                "traceability_rate": {
                    "operator": "min",
                    "threshold": 1,
                },
                "valid_completion": {
                    "operator": "min",
                    "threshold": 1,
                },
            },
            "selection": {
                "quality_retention_min": 0.9,
                "category_retention_min": 0.85,
                "valid_run_rate_min": 0.9,
                "efficiency_metric": "monetary_cost",
                "efficiency_gain_min": 0.3,
            },
        }
    )


def _benchmark() -> Benchmark:
    return Benchmark.model_validate(
        {
            "schema_version": "1.0",
            "benchmark_id": "test-benchmark",
            "cases": [
                {
                    "case_id": "policy-001",
                    "category": "policy",
                    "topic": "测试主题",
                    "questions": [
                        {"question_id": "q1", "text": "问题一", "weight": 1}
                    ],
                    "must_find_sources": [],
                    "key_facts": [],
                    "known_conflicts": [],
                    "required_media_types": [],
                }
            ],
        }
    )


def _evaluation(
    *,
    run_id: str = "run-cloud",
    model_id: str = "cloud",
    repeat: int = 1,
    metric_value: float = 1.0,
    unsupported_claims: float = 0,
    cost: float = 10,
    evaluation_mode: str = "live",
) -> EvaluationInput:
    return EvaluationInput.model_validate(
        {
            "schema_version": "1.0",
            "benchmark_id": "test-benchmark",
            "case_id": "policy-001",
            "run_id": run_id,
            "run_dir": f"experiments/runs/{run_id}",
            "repeat": repeat,
            "evaluation_mode": evaluation_mode,
            "model": {
                "model_id": model_id,
                "provider": "test",
                "name": model_id,
                "deployment": "cloud" if model_id == "cloud" else "local",
                "context_window": 32768,
                "thinking": False,
            },
            "metrics": {
                "question_coverage": {
                    "value": metric_value,
                    "evidence": ["review:q1"],
                },
                "key_fact_recall": {
                    "value": metric_value,
                    "evidence": ["review:facts"],
                },
                "citation_precision": {
                    "value": metric_value,
                    "evidence": ["review:citations"],
                },
            },
            "gates": {
                "unsupported_major_claims": {
                    "value": unsupported_claims,
                    "evidence": ["review:claims"],
                },
                "traceability_rate": {
                    "value": 1,
                    "evidence": ["review:traceability"],
                },
                "valid_completion": {
                    "value": 1,
                    "evidence": ["manifest:stage"],
                },
            },
            "resources": {
                "elapsed_seconds": 600,
                "input_tokens": 1000,
                "output_tokens": 100,
                "model_requests": 10,
                "tool_calls": 20,
                "monetary_cost": cost,
            },
        }
    )


def test_score_calculates_weighted_quality_and_gates():
    result = score_evaluation(_policy(), _benchmark(), _evaluation())

    assert result["quality_score"] == 100
    assert result["group_scores"] == {"coverage": 100, "evidence": 100}
    assert result["hard_gates_passed"] is True
    assert result["valid_run"] is True


def test_score_rejects_missing_required_metric():
    evaluation = _evaluation()
    del evaluation.metrics["citation_precision"]

    with pytest.raises(ValueError, match="citation_precision"):
        score_evaluation(_policy(), _benchmark(), evaluation)


def test_failed_gate_cannot_be_offset_by_quality():
    result = score_evaluation(
        _policy(),
        _benchmark(),
        _evaluation(unsupported_claims=1),
    )

    assert result["quality_score"] == 100
    assert result["hard_gates_passed"] is False
    assert result["valid_run"] is False
    assert result["failed_gates"] == ["unsupported_major_claims"]


def test_compare_uses_paired_cases_and_reports_small_model_decision():
    policy = _policy()
    benchmark = _benchmark()
    cloud = score_evaluation(policy, benchmark, _evaluation())
    local = score_evaluation(
        policy,
        benchmark,
        _evaluation(
            run_id="run-local",
            model_id="local",
            metric_value=0.9,
            cost=5,
        ),
    )

    comparison = compare_scores(policy, [cloud, local], "cloud")
    local_summary = comparison["models"]["local"]

    assert local_summary["paired_cases"] == 1
    assert local_summary["paired_runs"] == 1
    assert local_summary["quality_retention"] == 0.9
    assert local_summary["minimum_category_retention"] == 0.9
    assert local_summary["valid_run_rate"] == 1
    assert local_summary["efficiency_gain"] == 0.5
    assert local_summary["selection_status"] == "recommended"


def test_compare_marks_missing_cost_as_incomplete():
    policy = _policy()
    benchmark = _benchmark()
    cloud = score_evaluation(policy, benchmark, _evaluation())
    local_input = _evaluation(
        run_id="run-local",
        model_id="local",
        metric_value=0.95,
    )
    local_input.resources.monetary_cost = None
    local = score_evaluation(policy, benchmark, local_input)

    comparison = compare_scores(policy, [cloud, local], "cloud")

    assert comparison["models"]["local"]["efficiency_gain"] is None
    assert comparison["models"]["local"]["selection_status"] == "incomplete"


def test_compare_accepts_repeated_runs_for_the_same_case():
    policy = _policy()
    benchmark = _benchmark()
    scores = [
        score_evaluation(
            policy,
            benchmark,
            _evaluation(run_id="cloud-r1", repeat=1),
        ),
        score_evaluation(
            policy,
            benchmark,
            _evaluation(run_id="cloud-r2", repeat=2),
        ),
        score_evaluation(
            policy,
            benchmark,
            _evaluation(
                run_id="local-r1",
                model_id="local",
                repeat=1,
                metric_value=0.9,
                cost=5,
            ),
        ),
        score_evaluation(
            policy,
            benchmark,
            _evaluation(
                run_id="local-r2",
                model_id="local",
                repeat=2,
                metric_value=0.9,
                cost=5,
            ),
        ),
    ]

    local = compare_scores(policy, scores, "cloud")["models"]["local"]

    assert local["paired_cases"] == 1
    assert local["paired_runs"] == 2
    assert local["valid_run_rate"] == 1


def _frozen_policy() -> EvaluationPolicy:
    return EvaluationPolicy.model_validate(
        {
            "schema_version": "1.0",
            "mode": "frozen",
            "groups": {
                "coverage": {
                    "weight": 0.5,
                    "metrics": {
                        "question_coverage": 0.5,
                        "key_fact_recall": 0.5,
                    },
                },
                "evidence": {
                    "weight": 0.5,
                    "metrics": {"citation_precision": 1.0},
                },
            },
            "gates": {
                "unsupported_major_claims": {
                    "operator": "max",
                    "threshold": 0,
                },
                "traceability_rate": {
                    "operator": "min",
                    "threshold": 1,
                },
                "valid_completion": {
                    "operator": "min",
                    "threshold": 1,
                },
            },
            "selection": {
                "quality_retention_min": 0.9,
                "category_retention_min": 0.85,
                "valid_run_rate_min": 0.9,
                "efficiency_metric": "monetary_cost",
                "efficiency_gain_min": 0.3,
            },
        }
    )


def test_frozen_policy_rejects_live_evaluation():
    with pytest.raises(ValueError, match="evaluation mode"):
        score_evaluation(
            _frozen_policy(),
            _benchmark(),
            _evaluation(evaluation_mode="live"),
        )


def test_live_policy_rejects_frozen_evaluation():
    with pytest.raises(ValueError, match="evaluation mode"):
        score_evaluation(
            _policy(),
            _benchmark(),
            _evaluation(evaluation_mode="frozen"),
        )


def test_frozen_policy_scores_without_search_metrics():
    result = score_evaluation(
        _frozen_policy(),
        _benchmark(),
        _evaluation(evaluation_mode="frozen"),
    )

    assert result["evaluation_mode"] == "frozen"
    assert result["quality_score"] == 100
    assert result["hard_gates_passed"] is True


def test_compare_rejects_mixed_evaluation_modes():
    policy = _policy()
    benchmark = _benchmark()
    live = score_evaluation(policy, benchmark, _evaluation())
    frozen = score_evaluation(
        _frozen_policy(),
        benchmark,
        _evaluation(
            run_id="run-frozen",
            evaluation_mode="frozen",
        ),
    )

    with pytest.raises(ValueError, match="evaluation modes"):
        compare_scores(_frozen_policy(), [live, frozen], "cloud")


def test_repo_frozen_policy_has_no_search_metrics_and_sums_to_one():
    policy = EvaluationPolicy.model_validate(
        __import__("yaml").safe_load(
            (
                PROJECT_ROOT / "experiments/evaluation/policy.frozen.yaml"
            ).read_text(encoding="utf-8")
        )
    )

    assert policy.mode == "frozen"
    metric_names = {
        name for group in policy.groups.values() for name in group.metrics
    }
    assert "precision_at_10" not in metric_names
    assert "must_find_recall_at_50" not in metric_names


def test_cli_validates_scores_and_compares_examples(monkeypatch, tmp_path):
    evaluation_dir = PROJECT_ROOT / "experiments" / "evaluation"
    policy = evaluation_dir / "policy.yaml"
    benchmark = evaluation_dir / "benchmark.example.json"
    cloud_score = tmp_path / "cloud.json"
    local_score = tmp_path / "local.json"
    comparison = tmp_path / "comparison.json"
    markdown = tmp_path / "comparison.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_runs.py",
            "validate",
            "--policy",
            str(policy),
            "--benchmark",
            str(benchmark),
        ],
    )
    assert main() == 0

    for evaluation_name, output in (
        ("evaluation.cloud.example.json", cloud_score),
        ("evaluation.local.example.json", local_score),
    ):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "evaluate_runs.py",
                "score",
                "--policy",
                str(policy),
                "--benchmark",
                str(benchmark),
                "--input",
                str(evaluation_dir / evaluation_name),
                "--output",
                str(output),
            ],
        )
        assert main() == 0

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_runs.py",
            "compare",
            "--policy",
            str(policy),
            "--baseline-model",
            "cloud-large",
            "--scores",
            str(cloud_score),
            str(local_score),
            "--output",
            str(comparison),
            "--markdown",
            str(markdown),
        ],
    )
    assert main() == 0

    result = json.loads(comparison.read_text(encoding="utf-8"))
    assert result["models"]["qwen-local-27b"]["selection_status"] == (
        "recommended"
    )
    assert "模型评测对比" in markdown.read_text(encoding="utf-8")
