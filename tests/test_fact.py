"""Claim type persistence and backward compatibility."""

from intel_agent.fact import save_fact
from intel_agent.models import Fact
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
