# Contract: Committed Research State

## Purpose

定义一个任务的普通读取、活动 Run 工作态和 checkpoint 提交规则。该 Interface 必须被 Agent context、Retriever、TaskView、资源下载、Coverage、ReportPublisher 和恢复逻辑共同使用。

## Read Interface

```python
snapshot = state_store.committed_snapshot(task_id, version=None)
working_view = state_store.run_view(run_id)
```

`committed_snapshot` MUST：

1. 返回一个固定 committed version、checkpoint ID、asset manifest 和 fingerprint。
2. 只包含 manifest 引用且 hash 验证成功的 revision。
3. 不扫描文件目录推断可见性。
4. 对同一 version 重复调用产生相同逻辑结果。

`run_view` MUST：

1. 返回 Run 的固定 base snapshot 加该 Run 的 staged revisions。
2. 拒绝 task_id 与 Run 绑定不一致的读取。
3. 在 Run 终止后不再把 abandoned workspace 暴露为工作态。

## Evidence Visibility

只有同时满足以下条件的 Evidence 才能标记为 `verified_evidence`：

- Evidence revision 在 snapshot manifest 中。
- 关联 Fact revision 在同一 snapshot 中且 active。
- 关联 Document 在同一 snapshot 中且完整性 hash 有效。
- Evidence relation 为 `supports`。
- 对应 SupportReview revision 在同一 snapshot 中且 verdict 为 `full`。

`partial`、`irrelevant`、`contradicts`、未审核 Evidence 和 superseded Fact 可以在审计视图展示，但不能作为 verified citation 或 covered conclusion。

## Mutation Rules

- 新 Document、Fact、Evidence、Review、Conflict、Coverage、MaterialDigest 和 Task revision 写入 RunWorkspace。
- 已被任意 committed snapshot 引用的 revision 不得原地覆盖。
- Fact supersession 和 Conflict resolution 创建新 revision。
- 内容文件可以在数据库提交前按 hash 写入全局内容仓；没有 manifest 引用的文件是不可见 orphan。
- 普通 API 不得通过 `get_task_view` 或直接文件扫描绕过 committed snapshot。

## Commit Interface

```python
result = state_store.finish_run(
    run_id=run_id,
    expected_input_version=base_version,
    staged_manifest=manifest,
    outcome="committed" | "no_progress",
)
```

同一 SQLite 事务 MUST：

1. 验证 Run 为 running，Action/Run/所有 revision 同属 Task。
2. 验证当前 committed version 等于 expected input version。
3. 验证 staged manifest ID、hash 和引用依赖。
4. `committed` 且存在新 revision 时创建 committed checkpoint、推进 version、使旧报告 stale。
5. `no_progress` 或无新 revision 时记录终态但不推进 version、不使报告 stale。
6. 完成 ResearchRun 和关联 Action，并追加对应 event/timeline。
7. 重复调用返回同一终态，不创建第二个 checkpoint 或 version。

queued、failed、succeeded、cancelled、stopped 或 interrupted Run MUST NOT 开始或提交 checkpoint。

## Report Snapshot

ReportPublisher MUST：

1. 一次读取固定 snapshot。
2. 仅使用该 snapshot 的 Fact/Evidence/Review/Document/Coverage。
3. 在渲染前后保持 snapshot fingerprint 不变。
4. 以 expected committed version 和 fingerprint CAS 创建 ReportVersion。
5. CAS 失败时删除/保留为不可见临时输出并返回 `STALE_REPORT`，不得把旧内容绑定到新版本。

## Failure Semantics

- failed/cancelled/stopped/interrupted Run 将 workspace 标为 abandoned。
- abandoned revision 永不进入普通读取；可异步清理，不影响正确性。
- 已 committed snapshot 和 ReportVersion 永不回滚或改写。
- started checkpoint 必须最终为 committed、cancelled 或 failed，不得永久悬挂。
