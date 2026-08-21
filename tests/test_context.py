"""Bounded model history backed by durable research state."""

from pydantic_ai import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from intel_agent.agent import build_agent, build_deps
from intel_agent.config import Settings
from intel_agent.context import (
    CONTEXT_SNAPSHOT_PREFIX,
    build_context_snapshot,
    compact_message_history,
)
from intel_agent.coverage import eval_coverage
from intel_agent.evidence import save_evidence
from intel_agent.fact import save_fact
from intel_agent.materials import generate_material_digest, register_material
from intel_agent.task import create_task, load_task, save_task
from tests.conftest import DEFAULT_CRITERIA, make_document


def _tool_exchange(number: int, content: str):
    call_id = f"call-{number}"
    return [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="web_search",
                    args={"query": f"query-{number}"},
                    tool_call_id=call_id,
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="web_search",
                    content=content,
                    tool_call_id=call_id,
                )
            ]
        ),
    ]


def test_compaction_keeps_initial_request_and_recent_complete_exchanges():
    initial = ModelRequest(parts=[UserPromptPart(content="original task")])
    messages: list[ModelMessage] = [initial]
    for number in range(5):
        messages.extend(_tool_exchange(number, "x" * 600))

    compacted = compact_message_history(
        messages,
        max_bytes=2_500,
        snapshot='{"stage":"collect"}',
    )

    assert compacted[0] is initial
    assert len(ModelMessagesTypeAdapter.dump_json(compacted)) <= 2_500
    assert len(compacted) < len(messages)
    assert isinstance(compacted[-2], ModelResponse)
    assert isinstance(compacted[-1], ModelRequest)
    call = compacted[-2].parts[0]
    result = compacted[-1].parts[0]
    assert isinstance(call, ToolCallPart)
    assert isinstance(result, ToolReturnPart)
    assert call.tool_call_id == result.tool_call_id == "call-4"
    assert any(
        isinstance(part, UserPromptPart)
        and str(part.content).startswith(CONTEXT_SNAPSHOT_PREFIX)
        for part in compacted[-1].parts
    )


def test_context_snapshot_restores_task_fact_and_coverage(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "测试主题已有一个待验证事实",
        "reported",
    )
    eval_coverage(cwd, task.id)

    snapshot = build_context_snapshot(cwd)

    assert task.id in snapshot
    assert fact.id in snapshot
    assert "测试主题已有一个待验证事实" in snapshot
    assert '"level": "insufficient"' in snapshot


def test_context_snapshot_directs_small_model_to_archived_document(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    document = make_document(cwd, "可引用的归档正文")
    register_material(
        cwd,
        task.id,
        document.canonical_url,
        document_id=document.id,
    )

    snapshot = build_context_snapshot(cwd)

    assert document.id in snapshot
    assert document.title in snapshot
    assert "停止继续搜索或抓取" in snapshot
    assert "document_read" in snapshot

    resumed = build_context_snapshot(cwd, read_document_ids={document.id})

    assert "不要再次读取" in resumed
    assert "fact_save" in resumed


def test_context_snapshot_directs_pending_evidence_to_audit(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    document = make_document(cwd, "测试主题已有可核验进展")
    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "测试主题已有可核验进展",
    )
    evidence = save_evidence(
        cwd,
        fact.id,
        document.id,
        "supports",
        "测试主题已有可核验进展",
    )

    snapshot = build_context_snapshot(cwd)

    assert evidence.id in snapshot
    assert "停止搜索、抓取和覆盖评估" in snapshot
    assert "evidence_audit" in snapshot


def test_context_snapshot_does_not_reenter_assess(cwd):
    task = create_task(
        cwd,
        "测试主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    for _ in range(3):
        eval_coverage(cwd, task.id)
    task = load_task(cwd, task.id)
    save_task(cwd, task.model_copy(update={"stage": "assess"}))

    snapshot = build_context_snapshot(cwd)

    assert "material_digest" in snapshot
    assert "stage='assess'" not in snapshot

    document = make_document(cwd, "测试主题材料")
    register_material(
        cwd,
        task.id,
        document.canonical_url,
        document_id=document.id,
    )
    generate_material_digest(cwd, task.id)

    with_digest = build_context_snapshot(cwd)

    assert "generate_research_report" in with_digest
    assert "不要重复调用 material_digest" in with_digest


def test_main_and_audit_models_have_separate_output_limits(cwd):
    settings = Settings.model_validate(
        {
            "model": {
                "name": "Qwen3.5-9B",
                "base_url": "http://127.0.0.1:9876/v1",
                "api_key_env": None,
            },
            "context": {
                "main_output_tokens": 1_024,
                "audit_output_tokens": 384,
                "disable_thinking": True,
            },
        }
    )

    agent = build_agent(settings)
    deps = build_deps(cwd, settings)

    assert agent.model_settings == {
        "max_tokens": 1_024,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    assert deps.judge is not None
    assert deps.judge.agent.model_settings == {
        "max_tokens": 384,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
