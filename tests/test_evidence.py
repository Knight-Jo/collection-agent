"""Fact/evidence CRUD, supersession, tamper detection tests."""

import pytest

from intel_agent.evidence import list_evidence_for_fact, save_evidence
from intel_agent.fact import load_fact, save_fact, supersede_fact
from intel_agent.models import IntelError
from intel_agent.storage import read_json_object, write_json_atomic
from tests.conftest import make_document, new_task


def test_fact_save_is_idempotent(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    f1 = save_fact(cwd, task.id, q.id, "  测试主题  现状是 A  ")
    f2 = save_fact(cwd, task.id, q.id, "测试主题 现状是 A")
    assert f1.id == f2.id
    assert f1.statement == "测试主题 现状是 A"
    assert f1.id.startswith("fact-")


def test_fact_save_validates_question(cwd):
    task = new_task(cwd)
    with pytest.raises(IntelError) as e:
        save_fact(cwd, task.id, "q-does-not-exist", "事实")
    assert e.value.code == "INVALID_INPUT"


def test_supersede_fact(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    compound = save_fact(cwd, task.id, q.id, "测试主题现状是 A 且进展为 B")
    atomic1 = save_fact(cwd, task.id, q.id, "测试主题现状是 A")
    atomic2 = save_fact(cwd, task.id, q.id, "测试主题进展为 B")
    superseded = supersede_fact(
        cwd, compound.id, [atomic1.id, atomic2.id], "复合事实拆分为原子事实"
    )
    assert superseded.status == "superseded"
    assert superseded.superseded_by == [atomic1.id, atomic2.id]
    # 循环检测
    with pytest.raises(IntelError):
        supersede_fact(cwd, atomic1.id, [compound.id], "cycle")


def test_supersede_requires_same_task_question(cwd):
    task = new_task(cwd)
    q1, q2 = task.questions[0], task.questions[1]
    f1 = save_fact(cwd, task.id, q1.id, "事实甲")
    f2 = save_fact(cwd, task.id, q2.id, "事实乙")
    with pytest.raises(IntelError) as e:
        supersede_fact(cwd, f1.id, [f2.id], "不该跨问题")
    assert e.value.code == "INVALID_INPUT"


def test_evidence_save_locates_quote(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(
        cwd, "第一行内容\n关于测试主题的关键句子在此。\n第三行"
    )
    fact = save_fact(cwd, task.id, q.id, "测试主题的关键句子存在")
    evidence = save_evidence(
        cwd, fact.id, doc.id, "supports", "关于测试主题的关键句子在此。"
    )
    assert evidence.line_start == 2
    assert evidence.line_end == 2
    assert evidence.id.startswith("ev-")
    # 幂等
    evidence2 = save_evidence(
        cwd, fact.id, doc.id, "supports", "关于测试主题的关键句子在此。"
    )
    assert evidence2.id == evidence.id
    assert len(list_evidence_for_fact(cwd, fact.id)) == 1


def test_evidence_quote_not_found(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(cwd, "正文内容")
    fact = save_fact(cwd, task.id, q.id, "某事实")
    with pytest.raises(IntelError) as e:
        save_evidence(cwd, fact.id, doc.id, "supports", "不存在的引文")
    assert e.value.code == "QUOTE_NOT_FOUND"


@pytest.mark.parametrize("extraction_status", ["unavailable", "failed"])
def test_evidence_rejects_document_without_successful_extraction(
    cwd, extraction_status
):
    task = new_task(cwd)
    question = task.questions[0]
    document = make_document(cwd, "archived but not extracted")
    record = read_json_object(cwd, f"documents/{document.id}.json")
    record["extraction_status"] = extraction_status
    write_json_atomic(cwd, f"documents/{document.id}.json", record)
    fact = save_fact(cwd, task.id, question.id, "某事实")

    with pytest.raises(IntelError) as error:
        save_evidence(
            cwd,
            fact.id,
            document.id,
            "supports",
            "archived but not extracted",
        )

    assert error.value.code == "EXTRACTION_UNAVAILABLE"


def test_existing_evidence_becomes_unusable_if_extraction_is_not_successful(
    cwd,
):
    task = new_task(cwd)
    question = task.questions[0]
    document = make_document(cwd, "successfully extracted quote")
    fact = save_fact(cwd, task.id, question.id, "某事实")
    save_evidence(
        cwd,
        fact.id,
        document.id,
        "supports",
        "successfully extracted quote",
    )
    record = read_json_object(cwd, f"documents/{document.id}.json")
    record["extraction_status"] = "failed"
    write_json_atomic(cwd, f"documents/{document.id}.json", record)

    with pytest.raises(IntelError) as error:
        list_evidence_for_fact(cwd, fact.id)

    assert error.value.code == "EXTRACTION_UNAVAILABLE"


def test_document_tamper_detected(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(cwd, "原始正文内容")
    fact = save_fact(cwd, task.id, q.id, "某事实")
    save_evidence(cwd, fact.id, doc.id, "supports", "原始正文内容")
    # 篡改正文文件
    (cwd / doc.text_path).write_text("被篡改的内容", encoding="utf-8")
    with pytest.raises(IntelError) as e:
        list_evidence_for_fact(cwd, fact.id)
    assert e.value.code == "DOCUMENT_TAMPERED"


def test_fact_metadata_corruption_detected(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    fact = save_fact(cwd, task.id, q.id, "某事实")
    data = read_json_object(cwd, f"facts/{fact.id}.json")
    data["statement"] = "被篡改的陈述"
    write_json_atomic(cwd, f"facts/{fact.id}.json", data)
    with pytest.raises(IntelError) as e:
        load_fact(cwd, fact.id)
    assert e.value.code == "STORAGE_CORRUPT"
