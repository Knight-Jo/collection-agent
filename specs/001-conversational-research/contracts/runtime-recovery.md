# Contract: Runtime Claim, Completion and Recovery

## Single-workspace Runtime

首版只支持一个工作区 Runtime：

- 进程启动先取得工作区级锁；无法取得时拒绝启动第二实例。
- 获得锁意味着旧进程已退出，因此遗留 running/stopping Run 立即转 interrupted。
- 不使用没有 heartbeat 的固定两分钟 lease 证明活性。
- 多 worker 支持属于未来范围，需要 runtime UUID、heartbeat 和 periodic CAS reaper。

## Action Claim

```python
claim = state_store.claim_action(action_id)
```

一个事务 MUST：

1. 要求 Action 为 queued。
2. 校验 `precondition_committed_state_version` 和可选 SearchPlanVersion。
3. 过期时把 Action 转 expired，且不创建 Run。
4. 未过期时把 Action 转 executing，并创建或返回唯一 ResearchRun。
5. 使用 `action_request_id` 唯一约束保证恢复/重复调度不会创建第二个 Run。

Runtime 只有收到 executing claim 才启动 worker；expired claim 发送 `action.expired`，不得回复“进入执行队列”。

## Initial and Retry Claim

- queued initial/retry Run 通过 CAS claim 为 running。
- retry 必须关联 failed/interrupted Run，并使用当前明确 snapshot 创建新 Run。
- retry endpoint 不仅创建 queued record，还必须进入相同持久 scheduler。
- 同一 Run 的第二次 claim 返回已认领/终态，不重复执行。

## Completion

- checkpoint、Run terminal status、Action terminal status 和 durable event 在一个 StateStore 事务完成。
- worker 不自行按顺序调用多个 transition method 模拟原子完成。
- Run 的成功 outcome 为 `committed`、`no_progress`、`sufficient` 或 `with_gaps` 中契约允许的组合；模型正常返回本身不是成功条件。
- 至少满足“有效 staged revision”或“确定性 no-progress/stop reason”之一，Run 才能成功。

## Startup Recovery Matrix

| Persisted state | Startup action |
|---|---|
| accepted/processing message without reply | 原子 claim 后重试；只有一个 Runtime 可处理 |
| reply exists but attempt processing | 在事务中收敛 attempt completed，不生成第二个 reply |
| queued initial Run | 重新调度并 CAS claim |
| queued continuation/report Action | 重新调度并原子 claim |
| queued retry Run | 重新调度并 CAS claim |
| running/stopping Run from old runtime | 转 interrupted；保留旧 committed snapshot |
| executing Action + no committed checkpoint | 转 failed/interrupted并开放显式 retry |
| executing Action + committed checkpoint/terminal Run | 幂等收敛到 succeeded |
| open RunWorkspace for terminal Run | 标 abandoned并排入清理 |

## Cancellation

- queued Action/Run 直接事务性转 cancelled，不等待 ResearchGate。
- 等待工作区执行权的内存 task 必须可取消，并且不会留下 queued orphan Run。
- running Run 先转 stopping并通知 worker；`finish_run` 发现 stopping 时不得 commit staged state。
- report Action 必须具有与 research Action 相同的 queued cancellation 语义。

## Event Contract

- durable state 变化和对应 event/timeline 在同一事务写入。
- transient `answer.delta` 只用于最终已验证答案的展示，不作为恢复依据。
- `/api/runs` 不得维护独立内存状态真相；应迁移到 ResearchRun 或移除。
