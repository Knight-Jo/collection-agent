"""Score experiment runs and compare model deployments.

The evaluator consumes reviewed, normalized metrics. It deliberately keeps
quality separate from efficiency so cheap runs cannot offset unsupported
claims or other failed hard gates.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

if __package__:
    from .analyze_trajectory import summarize as summarize_trajectory
else:
    from analyze_trajectory import summarize as summarize_trajectory

SCHEMA_VERSION = "1.0"


class StrictModel(BaseModel):
    """Base model for versioned evaluation files."""

    model_config = ConfigDict(extra="forbid")


class Question(StrictModel):
    question_id: str
    text: str
    weight: float = Field(default=1, gt=0)


class MustFindSource(StrictModel):
    source_id: str
    description: str
    url: str | None = None
    required: bool = True


class KeyFact(StrictModel):
    fact_id: str
    question_id: str
    statement: str
    weight: float = Field(default=1, gt=0)
    critical: bool = False
    required_independent_sources: int = Field(default=1, ge=1)


class KnownConflict(StrictModel):
    conflict_id: str
    description: str


class BenchmarkCase(StrictModel):
    case_id: str
    category: str
    topic: str
    questions: list[Question] = Field(min_length=2, max_length=6)
    must_find_sources: list[MustFindSource]
    key_facts: list[KeyFact]
    known_conflicts: list[KnownConflict]
    required_media_types: list[str]


class Benchmark(StrictModel):
    schema_version: Literal["1.0"]
    benchmark_id: str
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Benchmark:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case_id values must be unique")
        return self


class MetricObservation(StrictModel):
    value: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1)
    note: str | None = None


class GateObservation(StrictModel):
    value: float = Field(ge=0)
    evidence: list[str] = Field(min_length=1)
    note: str | None = None


class ModelInfo(StrictModel):
    model_id: str
    provider: str
    name: str
    deployment: Literal["cloud", "local"]
    context_window: int = Field(gt=0)
    thinking: bool
    revision: str | None = None


class ResourceUsage(StrictModel):
    elapsed_seconds: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    model_requests: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)
    monetary_cost: float | None = Field(default=None, ge=0)
    gpu_seconds: float | None = Field(default=None, ge=0)
    energy_kwh: float | None = Field(default=None, ge=0)


def resources_from_trace(path: Path) -> ResourceUsage:
    """Project reproducible resource fields from a structured trajectory."""
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "event_type" in event:
            events.append(event)
    resources = summarize_trajectory(events)["resources"]
    if resources["elapsed_seconds"] is None:
        raise ValueError("trajectory does not contain elapsed time")
    return ResourceUsage.model_validate(resources)


class EvaluationInput(StrictModel):
    schema_version: Literal["1.0"]
    benchmark_id: str
    case_id: str
    run_id: str
    run_dir: str
    repeat: int = Field(ge=1)
    evaluation_mode: Literal["frozen", "live"]
    model: ModelInfo
    metrics: dict[str, MetricObservation]
    gates: dict[str, GateObservation]
    resources: ResourceUsage
    reviewer: str | None = None
    reviewed_at: str | None = None


class MetricGroupPolicy(StrictModel):
    weight: float = Field(gt=0, le=1)
    metrics: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_metric_weights(self) -> MetricGroupPolicy:
        _require_weight_sum(self.metrics.values(), "metric weights")
        return self


class GatePolicy(StrictModel):
    operator: Literal["min", "max", "equal"]
    threshold: float


class SelectionPolicy(StrictModel):
    quality_retention_min: float = Field(ge=0, le=1)
    category_retention_min: float = Field(ge=0, le=1)
    valid_run_rate_min: float = Field(ge=0, le=1)
    efficiency_metric: Literal[
        "elapsed_seconds",
        "input_tokens",
        "output_tokens",
        "model_requests",
        "tool_calls",
        "monetary_cost",
        "gpu_seconds",
        "energy_kwh",
    ]
    efficiency_gain_min: float = Field(ge=0, le=1)


class EvaluationPolicy(StrictModel):
    schema_version: Literal["1.0"]
    mode: Literal["frozen", "live"] = "live"
    groups: dict[str, MetricGroupPolicy] = Field(min_length=1)
    gates: dict[str, GatePolicy] = Field(min_length=1)
    selection: SelectionPolicy

    @model_validator(mode="after")
    def validate_group_weights(self) -> EvaluationPolicy:
        _require_weight_sum(
            (group.weight for group in self.groups.values()),
            "group weights",
        )
        metric_names = [
            name for group in self.groups.values() for name in group.metrics
        ]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("each metric must belong to exactly one group")
        return self


def _require_weight_sum(values, label: str) -> None:
    total = sum(values)
    if not math.isclose(total, 1, abs_tol=1e-6):
        raise ValueError(f"{label} must sum to 1, got {total}")


def load_benchmark(path: Path) -> Benchmark:
    return Benchmark.model_validate(_load_json(path))


def load_evaluation(path: Path) -> EvaluationInput:
    return EvaluationInput.model_validate(_load_json(path))


def load_policy(path: Path) -> EvaluationPolicy:
    with path.open(encoding="utf-8") as stream:
        return EvaluationPolicy.model_validate(yaml.safe_load(stream))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def score_evaluation(
    policy: EvaluationPolicy,
    benchmark: Benchmark,
    evaluation: EvaluationInput,
) -> dict:
    """Calculate quality groups and non-compensable hard gates."""
    if evaluation.benchmark_id != benchmark.benchmark_id:
        raise ValueError("evaluation benchmark_id does not match benchmark")
    if evaluation.evaluation_mode != policy.mode:
        raise ValueError(
            f"evaluation mode {evaluation.evaluation_mode} does not match "
            f"policy mode {policy.mode}"
        )
    cases = {case.case_id: case for case in benchmark.cases}
    if evaluation.case_id not in cases:
        raise ValueError(f"unknown benchmark case: {evaluation.case_id}")

    required_metrics = {
        metric for group in policy.groups.values() for metric in group.metrics
    }
    missing_metrics = sorted(required_metrics - evaluation.metrics.keys())
    if missing_metrics:
        raise ValueError(
            f"missing required metrics: {', '.join(missing_metrics)}"
        )
    missing_gates = sorted(policy.gates.keys() - evaluation.gates.keys())
    if missing_gates:
        raise ValueError(f"missing required gates: {', '.join(missing_gates)}")

    group_scores: dict[str, float] = {}
    quality_score = 0.0
    for name, group in policy.groups.items():
        score = sum(
            evaluation.metrics[metric].value * weight
            for metric, weight in group.metrics.items()
        )
        group_scores[name] = _rounded(score * 100)
        quality_score += score * group.weight

    gate_results = {
        name: _gate_passes(evaluation.gates[name].value, rule)
        for name, rule in policy.gates.items()
    }
    failed_gates = sorted(
        name for name, passed in gate_results.items() if not passed
    )
    hard_gates_passed = not failed_gates
    case = cases[evaluation.case_id]
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": benchmark.benchmark_id,
        "case_id": case.case_id,
        "category": case.category,
        "run_id": evaluation.run_id,
        "run_dir": evaluation.run_dir,
        "repeat": evaluation.repeat,
        "evaluation_mode": evaluation.evaluation_mode,
        "model": evaluation.model.model_dump(),
        "quality_score": _rounded(quality_score * 100),
        "group_scores": group_scores,
        "hard_gates_passed": hard_gates_passed,
        "failed_gates": failed_gates,
        "gate_results": gate_results,
        "valid_run": hard_gates_passed,
        "resources": evaluation.resources.model_dump(),
    }


def _gate_passes(value: float, rule: GatePolicy) -> bool:
    if rule.operator == "min":
        return value >= rule.threshold
    if rule.operator == "max":
        return value <= rule.threshold
    return math.isclose(value, rule.threshold, abs_tol=1e-9)


def _rounded(value: float) -> float:
    return round(value, 4)


def compare_scores(
    policy: EvaluationPolicy,
    scores: list[dict],
    baseline_model_id: str,
) -> dict:
    """Aggregate paired benchmark cases and assess local model retention."""
    modes = {score.get("evaluation_mode") for score in scores}
    if len(modes) > 1:
        raise ValueError(
            "cannot compare scores across evaluation modes: "
            f"{sorted(str(mode) for mode in modes)}"
        )
    if modes and next(iter(modes)) != policy.mode:
        raise ValueError(
            f"score mode {next(iter(modes))} does not match "
            f"policy mode {policy.mode}"
        )
    by_model: dict[str, dict[tuple[str, int], dict]] = defaultdict(dict)
    for score in scores:
        model_id = score["model"]["model_id"]
        run_key = (score["case_id"], score["repeat"])
        if run_key in by_model[model_id]:
            raise ValueError(
                f"duplicate score for {model_id}/{run_key[0]}/r{run_key[1]}"
            )
        by_model[model_id][run_key] = score
    if baseline_model_id not in by_model:
        raise ValueError(f"baseline model not found: {baseline_model_id}")

    baseline = by_model[baseline_model_id]
    summaries: dict[str, dict] = {}
    for model_id, cases in sorted(by_model.items()):
        paired_keys = sorted(cases.keys() & baseline.keys())
        if not paired_keys:
            continue
        quality_retention = _retention(
            [cases[item]["quality_score"] for item in paired_keys],
            [baseline[item]["quality_score"] for item in paired_keys],
        )
        category_retention = _category_retention(cases, baseline, paired_keys)
        valid_run_rate = statistics.fmean(
            1.0 if cases[item]["valid_run"] else 0.0 for item in paired_keys
        )
        efficiency_gain = _efficiency_gain(
            cases,
            baseline,
            paired_keys,
            policy.selection.efficiency_metric,
        )
        summary = {
            "paired_cases": len({case_id for case_id, _ in paired_keys}),
            "paired_runs": len(paired_keys),
            "mean_quality_score": _rounded(
                statistics.fmean(
                    cases[item]["quality_score"] for item in paired_keys
                )
            ),
            "quality_retention": quality_retention,
            "category_retention": category_retention,
            "minimum_category_retention": min(
                category_retention.values(), default=None
            ),
            "valid_run_rate": _rounded(valid_run_rate),
            "efficiency_metric": policy.selection.efficiency_metric,
            "efficiency_gain": efficiency_gain,
        }
        summary["selection_status"] = _selection_status(
            policy.selection,
            summary,
            is_baseline=model_id == baseline_model_id,
        )
        summaries[model_id] = summary

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_model_id": baseline_model_id,
        "evaluation_mode": policy.mode,
        "models": summaries,
    }


def _retention(candidate: list[float], baseline: list[float]) -> float | None:
    baseline_total = sum(baseline)
    if baseline_total == 0:
        return None
    return _rounded(sum(candidate) / baseline_total)


def _category_retention(
    candidate: dict[tuple[str, int], dict],
    baseline: dict[tuple[str, int], dict],
    paired_keys: list[tuple[str, int]],
) -> dict[str, float]:
    by_category: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for run_key in paired_keys:
        by_category[candidate[run_key]["category"]].append(run_key)
    output: dict[str, float] = {}
    for category, case_ids in sorted(by_category.items()):
        retention = _retention(
            [candidate[item]["quality_score"] for item in case_ids],
            [baseline[item]["quality_score"] for item in case_ids],
        )
        if retention is not None:
            output[category] = retention
    return output


def _efficiency_gain(
    candidate: dict[tuple[str, int], dict],
    baseline: dict[tuple[str, int], dict],
    paired_keys: list[tuple[str, int]],
    metric: str,
) -> float | None:
    candidate_values = [
        candidate[item]["resources"].get(metric) for item in paired_keys
    ]
    baseline_values = [
        baseline[item]["resources"].get(metric) for item in paired_keys
    ]
    if any(value is None for value in candidate_values + baseline_values):
        return None
    baseline_mean = statistics.fmean(baseline_values)
    if baseline_mean == 0:
        return None
    candidate_mean = statistics.fmean(candidate_values)
    return _rounded((baseline_mean - candidate_mean) / baseline_mean)


def _selection_status(
    policy: SelectionPolicy,
    summary: dict,
    *,
    is_baseline: bool,
) -> str:
    if is_baseline:
        return "baseline"
    required = (
        summary["quality_retention"],
        summary["minimum_category_retention"],
        summary["efficiency_gain"],
    )
    if any(value is None for value in required):
        return "incomplete"
    passed = (
        summary["quality_retention"] >= policy.quality_retention_min
        and summary["minimum_category_retention"]
        >= policy.category_retention_min
        and summary["valid_run_rate"] >= policy.valid_run_rate_min
        and summary["efficiency_gain"] >= policy.efficiency_gain_min
    )
    return "recommended" if passed else "not_recommended"


def render_comparison_markdown(comparison: dict) -> str:
    """Render a compact management-facing model comparison table."""
    lines = [
        "# 模型评测对比",
        "",
        f"基准模型：`{comparison['baseline_model_id']}`",
        "",
        "| 模型 | 配对任务 | 配对运行 | 平均质量分 | 质量保持率 | 最低分类保持率 | 有效运行率 | 效率提升 | 结论 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for model_id, item in comparison["models"].items():
        lines.append(
            "| {model} | {cases} | {runs} | {quality:.2f} | {retention} | "
            "{category} | {valid} | {efficiency} | {status} |".format(
                model=model_id,
                cases=item["paired_cases"],
                runs=item["paired_runs"],
                quality=item["mean_quality_score"],
                retention=_format_rate(item["quality_retention"]),
                category=_format_rate(item["minimum_category_retention"]),
                valid=_format_rate(item["valid_run_rate"]),
                efficiency=_format_rate(item["efficiency_gain"]),
                status=item["selection_status"],
            )
        )
    lines.extend(
        [
            "",
            "> 质量分只在硬门槛通过后才构成有效运行；效率提升不能抵消证据或安全门槛失败。",
        ]
    )
    return "\n".join(lines)


def _format_rate(value: float | None) -> str:
    return "未测量" if value is None else f"{value:.1%}"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--policy", type=Path, required=True)
    validate.add_argument("--benchmark", type=Path, required=True)

    score = subparsers.add_parser("score")
    score.add_argument("--policy", type=Path, required=True)
    score.add_argument("--benchmark", type=Path, required=True)
    score.add_argument("--input", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--policy", type=Path, required=True)
    compare.add_argument("--baseline-model", required=True)
    compare.add_argument("--scores", type=Path, nargs="+", required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--markdown", type=Path)

    resources = subparsers.add_parser("resources")
    resources.add_argument("--trace", type=Path, required=True)
    resources.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "resources":
            projected = resources_from_trace(args.trace)
            _write_json(args.output, projected.model_dump(mode="json"))
            print(f"resources written: {args.output}")
            return 0
        policy = load_policy(args.policy)
        if args.command == "validate":
            benchmark = load_benchmark(args.benchmark)
            print(
                f"valid: policy={len(policy.groups)} groups, "
                f"benchmark={len(benchmark.cases)} cases"
            )
            return 0
        if args.command == "score":
            result = score_evaluation(
                policy,
                load_benchmark(args.benchmark),
                load_evaluation(args.input),
            )
            _write_json(args.output, result)
            print(f"score written: {args.output}")
            return 0
        scores = [_load_json(path) for path in args.scores]
        comparison = compare_scores(policy, scores, args.baseline_model)
        _write_json(args.output, comparison)
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.markdown.write_text(
                render_comparison_markdown(comparison) + "\n",
                encoding="utf-8",
            )
        print(f"comparison written: {args.output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
