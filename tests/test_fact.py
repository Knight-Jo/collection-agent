"""Claim type persistence and backward compatibility."""

import pytest

from intel_agent.fact import save_fact
from intel_agent.models import Fact, IntelError, SufficiencyCriteria
from intel_agent.task import create_task
from tests.conftest import new_task


def test_fact_claim_type_defaults_for_historical_record(cwd):
    task = new_task(cwd)
    fact = save_fact(cwd, task.id, task.questions[0].id, "测试主题事实")
    historical = fact.model_dump()
    historical.pop("claim_type", None)

    loaded = Fact.model_validate(historical)

    assert loaded.claim_type == "corroborated"


def test_fact_save_persists_claim_type(cwd):
    task = new_task(cwd)

    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "政府发布测试主题政策",
        claim_type="primary",
    )

    assert fact.claim_type == "primary"


def test_fact_save_validates_and_persists_investigation_item(cwd):
    task = create_task(
        cwd,
        "主题",
        ["问题甲", "问题乙"],
        SufficiencyCriteria(),
        investigation_items={"问题甲": ["指标水平", "代表厂商"]},
    )
    question = task.questions[0]
    item = question.investigation_items[0]

    fact = save_fact(
        cwd,
        task.id,
        question.id,
        "指标水平达到 A",
        investigation_item_id=item.id,
    )

    assert fact.investigation_item_id == item.id
    with pytest.raises(IntelError, match="调研项不属于问题"):
        save_fact(
            cwd,
            task.id,
            question.id,
            "错误归属",
            investigation_item_id="item-missing",
        )
