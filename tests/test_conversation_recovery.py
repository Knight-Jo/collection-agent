from intel_agent.state_store import StateStore


def test_interrupted_run_keeps_working_assets_out_and_retries_as_new_run(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(
        run.id,
        "running",
        lease_owner="dead-runtime",
        lease_expires_at="2026-08-25T00:00:00+00:00",
    )
    store.start_checkpoint(run.id, reason="unfinished batch")

    recovered = store.recover_expired_runs("2026-08-25T00:00:01+00:00")
    retry = store.retry_run(run.id)

    assert recovered[0].status == "interrupted"
    assert store.committed_state_version("task-1") == 0
    assert store.committed_asset_ids("task-1", "document") == set()
    assert retry.id != run.id
    assert retry.retry_of_run_id == run.id


def test_startup_recovery_interrupts_all_active_runs_without_lease(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    run = store.create_run("task-1", "initial", 0, {})
    store.transition_run(
        run.id,
        "running",
        lease_owner="old-runtime",
        lease_expires_at="2999-01-01T00:00:00+00:00",
    )

    recovered = store.recover_expired_runs()

    assert [item.id for item in recovered] == [run.id]
    assert recovered[0].status == "interrupted"


def test_recovery_converges_executing_action_when_run_is_interrupted(cwd):
    store = StateStore(cwd)
    task_id = "task-1"
    store.register_task(task_id)
    trigger = store.add_user_message(task_id, "继续搜索", "recover-action")
    action = store.create_action(
        task_id, trigger.id, "continue_research", {"topic": "恢复"}
    )
    run = store.create_run(
        task_id,
        "continue_research",
        0,
        {},
        action_request_id=action.id,
    )
    store.transition_action(
        action.id, "executing", created_research_run_id=run.id
    )
    store.transition_run(
        run.id,
        "running",
        lease_owner="dead-runtime",
        lease_expires_at="2999-01-01T00:00:00+00:00",
    )

    store.recover_expired_runs()

    assert store.get_run(run.id).status == "interrupted"
    assert store.get_action(action.id).status == "failed"
