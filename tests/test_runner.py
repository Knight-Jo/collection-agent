"""Shared CLI/Web agent runner tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ToolCallPart,
    ToolReturnPart,
)

from intel_agent import runner as runner_module
from intel_agent import trajectory
from intel_agent.agent import (
    _resolve_bound_task_id,
    build_agent,
    build_deps,
)
from intel_agent.config import BudgetConfig, Settings
from intel_agent.models import IntelError, ResearchScope, SufficiencyCriteria
from intel_agent.runner import (
    TaskRunSpec,
    _result_summary,
    build_task_prompt,
    run_agent_task,
)
from intel_agent.task import (
    create_task,
    load_task,
    parse_time_range,
    save_task,
)
from intel_agent.trajectory import JsonlTrajectoryRecorder, emit, make_event


def make_spec() -> TaskRunSpec:
    return TaskRunSpec(
        topic="低空经济",
        questions=["投资进展如何？", "商业化进展如何？"],
        criteria=SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
    )


def test_agent_deps_reject_cross_task_binding(cwd):
    deps = build_deps(cwd, Settings(), task_id="task-a", run_id="run-a")

    assert _resolve_bound_task_id(deps, None) == "task-a"
    with pytest.raises(IntelError, match="不匹配"):
        _resolve_bound_task_id(deps, "task-b")


def test_parse_time_range_recognizes_single_year_and_ranges():
    assert parse_time_range("2026年低空经济投资与融资趋势") == "2026"
    assert parse_time_range("低空经济 2024-2026 发展情况") == "2024-2026"
    assert parse_time_range("低空经济 2024年至2026年 发展情况") == "2024-2026"
    assert parse_time_range("低空经济投资与融资趋势") == ""
    assert parse_time_range("") == ""


def test_translate_stream_event_emits_decision_and_action(tmp_path):
    recorder = JsonlTrajectoryRecorder(tmp_path / "trace.jsonl")
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)
    trajectory.set_task_id("task-1")
    event = FunctionToolCallEvent(
        part=ToolCallPart(tool_name="web_search", args={"q": "低空经济"})
    )
    runner_module._translate_stream_event(event, tmp_path)
    recorder.close()

    lines = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert [line["event_type"] for line in lines] == ["decision", "action"]
    assert lines[0]["origin"] == "model"
    assert lines[0]["payload"]["decision"] == "web_search"
    assert lines[0]["payload"]["reason_source"] == "derived"
    assert lines[1]["payload"]["action_id"] is not None
    assert lines[1]["payload"]["tool"] == "web_search"


def test_translate_stream_event_links_bounded_observation(tmp_path):
    recorder = JsonlTrajectoryRecorder(tmp_path / "trace.jsonl")
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)
    actions: dict[str, runner_module.ActionTrace] = {}
    call = FunctionToolCallEvent(
        part=ToolCallPart(
            tool_name="web_search",
            tool_call_id="call-1",
            args={
                "query": "低空经济",
                "question_id": "question-1",
                "investigation_item_id": "item-1",
            },
        )
    )
    result = FunctionToolResultEvent(
        ToolReturnPart(
            tool_name="web_search",
            tool_call_id="call-1",
            content={"count": 2, "results": ["a" * 2000, "b" * 2000]},
        )
    )

    runner_module._translate_stream_event(call, tmp_path, actions)
    runner_module._translate_stream_event(result, tmp_path, actions)
    recorder.close()

    decision, action, observation = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text().splitlines()
    ]
    assert action["parent_event_id"] == decision["event_id"]
    assert observation["parent_event_id"] == action["event_id"]
    assert action["question_id"] == "question-1"
    assert action["investigation_item_id"] == "item-1"
    assert observation["payload"]["status"] == "succeeded"
    assert observation["payload"]["duration_ms"] >= 0
    assert observation["payload"]["result"]["count"] == 2
    assert observation["payload"]["result"]["item_count"] == 2
    assert "results" not in observation["payload"]["result"]
    assert len(json.dumps(observation, ensure_ascii=False)) < 2000


def test_translate_stream_event_marks_business_failure(tmp_path):
    recorder = JsonlTrajectoryRecorder(tmp_path / "trace.jsonl")
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)
    actions: dict[str, runner_module.ActionTrace] = {}
    call = FunctionToolCallEvent(
        part=ToolCallPart(
            tool_name="fact_save",
            tool_call_id="call-1",
            args={"task_id": "task-1", "question_id": "question-1"},
        )
    )
    result = FunctionToolResultEvent(
        ToolReturnPart(
            tool_name="fact_save",
            tool_call_id="call-1",
            content={
                "ok": False,
                "error": {
                    "code": "CROSS_VERIFY_BACKLOG",
                    "message": "需要补证",
                },
            },
        )
    )

    runner_module._translate_stream_event(call, tmp_path, actions)
    runner_module._translate_stream_event(result, tmp_path, actions)
    recorder.close()

    observation = json.loads(
        (tmp_path / "trace.jsonl").read_text().splitlines()[-1]
    )
    assert observation["payload"]["status"] == "failed"
    assert observation["payload"]["result"]["error_code"] == (
        "CROSS_VERIFY_BACKLOG"
    )


def test_result_summary_keeps_first_validation_error():
    summary = _result_summary(
        {
            "ok": False,
            "errors": [
                {
                    "code": "REPORT_INVALID",
                    "message": "报告缺少有效引用",
                }
            ],
        }
    )

    assert summary["error_code"] == "REPORT_INVALID"
    assert summary["error_message"] == "报告缺少有效引用"


def test_close_pending_actions_records_interrupted_observation(tmp_path):
    recorder = JsonlTrajectoryRecorder(tmp_path / "trace.jsonl")
    binding = trajectory.bind_context("run-1", recorder, task_id="task-1")
    actions: dict[str, runner_module.ActionTrace] = {}
    call = FunctionToolCallEvent(
        part=ToolCallPart(
            tool_name="web_search",
            tool_call_id="call-1",
            args={
                "query": "低空经济",
                "question_id": "question-1",
                "investigation_item_id": "item-1",
            },
        )
    )

    runner_module._translate_stream_event(call, tmp_path, actions)
    runner_module._close_pending_actions(actions)
    trajectory.restore_context(binding)
    recorder.close()

    records = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text().splitlines()
    ]
    action, observation = records[-2:]
    assert actions == {}
    assert observation["parent_event_id"] == action["event_id"]
    assert observation["question_id"] == "question-1"
    assert observation["investigation_item_id"] == "item-1"
    assert observation["payload"]["action_id"] == "call-1"
    assert observation["payload"]["status"] == "interrupted"


@pytest.mark.asyncio
async def test_run_agent_task_records_failed_terminal_and_restores_context(
    monkeypatch, cwd, tmp_path
):
    outer = JsonlTrajectoryRecorder(tmp_path / "outer.jsonl")
    failed_path = tmp_path / "failed.jsonl"
    seed = JsonlTrajectoryRecorder(failed_path)
    seed_binding = trajectory.bind_context("failed-run", seed)
    emit(make_event("run_started", "system", {}, layer="evaluation"))
    trajectory.restore_context(seed_binding)
    seed.close()
    failed = JsonlTrajectoryRecorder(failed_path)
    trajectory.bind_run("outer-run")
    trajectory.set_recorder(outer)

    class FakeEvents:
        result = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError("provider secret should not leak")

    class FakeAgent:
        def run_stream_events(self, _prompt, **_kwargs):
            return FakeEvents()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _settings: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda *_args, **_kwargs: SimpleNamespace(crawl_event_callback=None),
    )

    with pytest.raises(RuntimeError, match="provider secret"):
        await run_agent_task(
            cwd,
            Settings(),
            make_spec(),
            recorder=failed,
            run_id="failed-run",
        )
    emit(make_event("action", "model", {}, layer="technical"))
    failed.close()
    outer.close()

    records = [
        json.loads(line)
        for line in (tmp_path / "failed.jsonl").read_text().splitlines()
    ]
    assert [record["event_type"] for record in records] == [
        "run_started",
        "run_finished",
    ]
    terminal = records[-1]["payload"]
    assert terminal["status"] == "failed"
    assert terminal["error_code"] == "RuntimeError"
    assert "secret" not in json.dumps(terminal)
    assert json.loads((tmp_path / "outer.jsonl").read_text())["run_id"] == (
        "outer-run"
    )


def test_create_task_copies_explicit_scope_time_range_to_every_question(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["2026年测试主题的现状如何", "测试主题的进展如何"],
        SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
        scope=ResearchScope(time_range="2024-2026"),
    )

    assert [q.time_range for q in task.questions] == [
        "2024-2026",
        "2024-2026",
    ]


def test_create_task_parses_year_per_question_without_scope(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["2026年测试主题的现状如何", "测试主题的进展如何"],
        SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
    )

    assert [q.time_range for q in task.questions] == ["2026", ""]
    persisted = load_task(cwd, task.id)
    assert [q.time_range for q in persisted.questions] == ["2026", ""]


def test_task_run_spec_validates_run_limits():
    spec = make_spec().model_copy(
        update={"max_requests": 40, "max_tool_calls": 12}
    )

    assert TaskRunSpec.model_validate(spec.model_dump()).max_requests == 40
    assert TaskRunSpec.model_validate(spec.model_dump()).max_tool_calls == 12

    with pytest.raises(ValidationError):
        TaskRunSpec.model_validate(
            {**make_spec().model_dump(), "max_requests": 0}
        )


def test_task_run_spec_normalizes_and_validates_questions():
    spec = TaskRunSpec(
        topic="  测试主题  ",
        questions=[" 问题甲 ", "问题甲", " 问题乙 "],
        criteria=SufficiencyCriteria(
            min_independent_sources=2,
            min_high_quality_sources=1,
            recency_days=90,
            require_recency=False,
        ),
    )

    assert spec.topic == "测试主题"
    assert spec.questions == ["问题甲", "问题乙"]

    one_question = TaskRunSpec(
        topic="测试",
        questions=["只有一个问题"],
        criteria=spec.criteria,
    )
    assert one_question.questions == ["只有一个问题"]


def test_task_run_spec_accepts_topic_without_questions():
    spec = TaskRunSpec(topic=" 低空经济 ")

    assert spec.topic == "低空经济"
    assert spec.questions == []
    assert spec.objective == ""
    assert spec.scope.model_dump() == {
        "time_range": "",
        "geography": [],
        "languages": [],
    }
    assert spec.report_depth == "standard"


def test_topic_only_prompt_asks_agent_to_generate_questions():
    prompt = build_task_prompt(TaskRunSpec(topic="低空经济"))

    assert "生成 3–6 个" in prompt
    assert "低空经济" in prompt


def test_prompt_preserves_optional_research_brief():
    spec = TaskRunSpec.model_validate(
        {
            "topic": "低空经济",
            "objective": "了解产业现状",
            "questions": ["政策如何变化？"],
            "scope": {
                "time_range": "2024-2026",
                "geography": ["中国"],
                "languages": ["zh-CN", "en"],
            },
            "report_depth": "deep",
        }
    )

    prompt = build_task_prompt(spec)
    assert "了解产业现状" in prompt
    assert "政策如何变化？" in prompt
    assert "不得新增" in prompt
    assert "补充必要问题" not in prompt
    assert "2024-2026" in prompt
    assert "中国" in prompt
    assert "zh-CN、en" in prompt


def test_explicit_questions_are_frozen_not_extended():
    prompt = build_task_prompt(make_spec())

    assert "必须且只能使用以下问题" in prompt
    assert "不得新增、删除、合并或改写" in prompt
    assert "补充必要问题" not in prompt
    assert "投资进展如何？；商业化进展如何？" in prompt


def test_build_task_prompt_preserves_user_input_and_criteria():
    prompt = build_task_prompt(make_spec())

    assert "低空经济" in prompt
    assert "投资进展如何？；商业化进展如何？" in prompt
    assert "min_independent_sources=2" in prompt
    assert "require_recency=false" in prompt


def test_prompt_is_generic_and_report_first():
    prompt = build_task_prompt(TaskRunSpec(topic="量子计算"))

    assert "material_digest" in prompt
    assert "generate_research_report" in prompt
    assert "亿航" not in prompt
    assert "caixin.com" not in prompt


def test_deep_crawl_defaults_off():
    assert Settings().crawl.enabled_by_default is False


@pytest.mark.asyncio
async def test_run_agent_task_streams_events(monkeypatch, cwd):
    received: list[object] = []
    result = SimpleNamespace(output="完成")
    deps = SimpleNamespace(crawl_event_callback=None)

    class FakeEvents:
        def __init__(self):
            self.result = result
            self._events = iter(["tool-started", "tool-completed"])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration as error:
                raise StopAsyncIteration from error

    class FakeContext:
        async def __aenter__(self):
            return FakeEvents()

        async def __aexit__(self, *_args):
            return False

    class FakeAgent:
        def run_stream_events(self, prompt, **kwargs):
            assert "低空经济" in prompt
            assert kwargs["deps"] is deps
            assert deps.crawl_event_callback is on_event
            assert kwargs["usage_limits"].request_limit == 100
            return FakeContext()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: deps,
    )

    async def on_event(event: object) -> None:
        received.append(event)

    actual = await run_agent_task(
        cwd, Settings(), make_spec(), on_event=on_event
    )

    assert actual is result
    assert received == ["tool-started", "tool-completed"]


@pytest.mark.asyncio
async def test_run_agent_task_stops_same_target_business_failure_loop(
    monkeypatch, cwd
):
    deps = SimpleNamespace(crawl_event_callback=None)
    events: list[object] = []
    for index in range(3):
        call_id = f"call-{index}"
        events.extend(
            [
                FunctionToolCallEvent(
                    part=ToolCallPart(
                        tool_name="evidence_save",
                        tool_call_id=call_id,
                        args={
                            "fact_id": "fact-1",
                            "document_id": "doc-1",
                            "quote": f"错误引文 {index}",
                        },
                    )
                ),
                FunctionToolResultEvent(
                    ToolReturnPart(
                        tool_name="evidence_save",
                        tool_call_id=call_id,
                        content={
                            "ok": False,
                            "error": {
                                "code": "QUOTE_NOT_FOUND",
                                "message": "引文不存在",
                            },
                        },
                    )
                ),
            ]
        )

    class FakeEvents:
        result = SimpleNamespace(output="未完成")

        def __init__(self):
            self._events = iter(events)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration as error:
                raise StopAsyncIteration from error

    class FakeAgent:
        def run_stream_events(self, _prompt, **_kwargs):
            return FakeEvents()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _settings: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: deps,
    )

    with pytest.raises(IntelError, match="连续失败") as captured:
        await run_agent_task(cwd, Settings(), make_spec())

    assert captured.value.code == "TOOL_FAILURE_LOOP"


@pytest.mark.asyncio
async def test_done_task_replaces_untrusted_model_summary(monkeypatch, cwd):
    task = create_task(
        cwd, "低空经济", ["问题甲", "问题乙"], make_spec().criteria
    )
    save_task(
        cwd,
        task.model_copy(
            update={"stage": "done", "completion_status": "with_gaps"}
        ),
    )
    result = SimpleNamespace(output="模型声称有未验证的第二条事实")

    class FakeEvents:
        def __init__(self):
            self.result = result

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeAgent:
        def run_stream_events(self, _prompt, **_kwargs):
            return FakeEvents()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: SimpleNamespace(
            crawl_event_callback=None
        ),
    )

    actual = await run_agent_task(cwd, Settings(), make_spec())

    assert "模型声称" not in actual.output
    assert "completion_status=with_gaps" in actual.output
    assert "已验证事实数=0" in actual.output


@pytest.mark.asyncio
async def test_run_agent_task_applies_tighter_task_limits(monkeypatch, cwd):
    result = SimpleNamespace(output="完成")
    captured = None

    class FakeEvents:
        def __init__(self):
            self.result = result

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeAgent:
        def run_stream_events(self, _prompt, **kwargs):
            nonlocal captured
            captured = kwargs["usage_limits"]
            return FakeEvents()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: SimpleNamespace(
            crawl_event_callback=None
        ),
    )
    settings = Settings(budgets=BudgetConfig(request_limit=200))

    await run_agent_task(
        cwd,
        settings,
        make_spec().model_copy(
            update={"max_requests": 40, "max_tool_calls": 12}
        ),
    )

    assert captured is not None
    assert captured.request_limit == 40
    assert captured.tool_calls_limit == 12


@pytest.mark.asyncio
async def test_deep_report_enables_recursive_collection(monkeypatch, cwd):
    result = SimpleNamespace(output="完成")
    captured: dict[str, object] = {}

    class FakeEvents:
        def __init__(self):
            self.result = result

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeAgent:
        def run_stream_events(self, prompt, **_kwargs):
            captured["prompt"] = prompt
            return FakeEvents()

    monkeypatch.setattr(
        "intel_agent.runner.build_agent", lambda _s: FakeAgent()
    )
    monkeypatch.setattr(
        "intel_agent.runner.build_deps",
        lambda _cwd, _settings, *, deep_crawl: (
            captured.update({"deep_crawl": deep_crawl})
            or SimpleNamespace(crawl_event_callback=None)
        ),
    )

    await run_agent_task(
        cwd,
        Settings(),
        TaskRunSpec(topic="量子计算", report_depth="deep", deep_crawl=False),
    )

    assert captured["deep_crawl"] is True
    assert "deep_crawl=true" in str(captured["prompt"])


def test_build_agent_conversation_capture_invoked(monkeypatch, cwd):
    from pydantic_ai.models.test import TestModel

    captured: list[tuple[list, list]] = []
    monkeypatch.setattr(
        "intel_agent.agent._build_chat_model",
        lambda _cfg, _key: TestModel(custom_output_text="回答", call_tools=[]),
    )
    agent = build_agent(
        Settings(),
        conversation_capture=lambda msgs, specs: captured.append(
            (msgs, specs)
        ),
    )
    agent.run_sync("测试问题", deps=build_deps(cwd, Settings()))

    assert captured
    assert any(msgs for msgs, _specs in captured), "捕获的消息历史不应为空"
    assert any(specs for _msgs, specs in captured), "捕获的工具清单不应为空"


@pytest.mark.asyncio
async def test_run_agent_task_captures_final_response(
    monkeypatch, cwd, tmp_path
):
    from pydantic_ai.models.test import TestModel

    monkeypatch.setattr(
        "intel_agent.agent._build_chat_model",
        lambda _cfg, _key: TestModel(
            custom_output_text="最终回答", call_tools=[]
        ),
    )
    conv = tmp_path / "conversation.json"
    await run_agent_task(cwd, Settings(), make_spec(), conversation_path=conv)

    assert conv.exists()
    messages = json.loads(conv.read_text())
    kinds = [m["kind"] for m in messages]
    assert kinds.count("response") == kinds.count("request")
    final = messages[-1]
    assert final["kind"] == "response"
    assert any(
        p.get("part_kind") == "text" and "最终回答" in str(p.get("content"))
        for p in final["parts"]
    )

    specs_path = tmp_path / "tool-specs.json"
    assert specs_path.exists()
    specs = json.loads(specs_path.read_text())
    names = {spec["name"] for spec in specs}
    assert "web_search" in names


def test_result_summary_keeps_failure_error_fields():
    # Run 059: 65 audit failures were only recoverable from run.log greps
    # because tool results were hashed and the error dict was dropped.
    summary = _result_summary(
        {
            "ok": False,
            "error": {
                "code": "SEMANTIC_AUDIT_FAILED",
                "message": "语义审核返回了无法解析的 JSON: broken",
            },
        }
    )

    assert summary["ok"] is False
    assert summary["error_code"] == "SEMANTIC_AUDIT_FAILED"
    assert "无法解析的 JSON" in str(summary["error_message"])


def test_result_summary_keeps_scalar_keys_and_hashes_content():
    summary = _result_summary(
        {
            "query": "人形机器人",
            "count": 3,
            "results": [{"document_id": "doc-1"}],
        }
    )

    assert summary["count"] == 3
    assert summary["item_count"] == 1
    assert summary["content_sha256"]
    assert "results" not in summary
