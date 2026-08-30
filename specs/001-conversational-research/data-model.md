# Data Model: 多轮广深情报调研

本特性复用现有业务模型，但当前 committed boundary 需要最小数据库迁移：记录不可变 snapshot/asset revision、保证一个 Action 只创建一个 Run，并让 Run/Checkpoint/Action 原子完成。搜索配置和请求/结果仍是不持久化的 Value Object。

## Existing Domain Entities

### IntelTask

- 一个主题的持久边界。
- 包含目标、范围、2 至 6 个核心问题、预算、覆盖状态和 committed state version。
- 一个 Conversation 最多绑定一个 IntelTask，绑定后不可改绑。

### IntelQuestion

- 属于一个 IntelTask。
- 状态为已回答、部分回答、未回答或冲突。
- 覆盖评估聚合独立来源、时效、冲突和证据充分性。

### Conversation

- 保存多轮用户和助手消息。
- 未绑定时用于 intake；绑定后只访问对应 IntelTask 的已提交资产。
- 实质性新主题必须创建新 Conversation 和 IntelTask。

### ResearchRun

- 属于一个 IntelTask，保存冻结目标、运行类型、预算、状态、失败或停止原因。
- 固定 `input_committed_state_version`、`bound_task_id` 和唯一 Action 关系；执行时不得静默 rebase。
- 状态转换由 StateStore 事务控制。
- 中断运行进入终态；安全重试创建新的 linked run。

### SearchPlanVersion

- 属于一个 ResearchRun。
- 不可变记录问题优先级、来源角色、查询方向和缺口。
- 每次新 run 使用独立版本，避免续研静默改写旧计划。

### ResearchCheckpoint

- 属于一个 ResearchRun。
- 原子提交经过 hash 验证的 snapshot manifest，并在同一事务完成 Run/Action。
- manifest 覆盖 document、fact revision、evidence、review、conflict、coverage、material digest 及影响报告的新鲜度状态。
- 空工作集可以记录 `no_progress` checkpoint/outcome，但不得推进 committed state version。
- start/commit 只允许仍为 running 且输入版本未过期的 ResearchRun。

### IntelDocument / Fact / Evidence / SupportReview

- IntelDocument 保存公开来源内容、来源元数据、抓取时间、完整性和内容 hash。
- Fact 是与核心问题关联的原子声明。
- Evidence 是 IntelDocument 中可定位的精确片段，对 Fact 提供支持或反驳。
- SupportReview 判断片段是否完整支撑 Fact；只有满足规则的事实才能进入正式结论。

### ActionRequest / ReportVersion

- ActionRequest 保存用户明确要求或确认的续研、计划调整、报告生成动作。
- 一个 ActionRequest 最多关联一个执行 ResearchRun；claim 时原子检查状态和 precondition version。
- ReportVersion 绑定生成时固定 snapshot 的 committed version、checkpoint ID、asset fingerprint、内容 hash 和发布状态；新 snapshot 只使旧版本 stale，不改写旧内容。

## Hardening Entities and Value Objects

### CommittedResearchSnapshot

一个任务在指定 committed state version 上的不可变读取视图。

| Field | Type | Rules |
|---|---|---|
| `task_id` | string | 必须与所有 task-scoped revision 同属一个任务 |
| `version` | int | 单调递增；空/no-progress 完成不递增 |
| `checkpoint_id` | string / null | version 0 可为空；其他版本对应一个 committed checkpoint |
| `asset_manifest` | AssetRevisionRef[] | 稳定排序、去重、逐项 hash 验证 |
| `fingerprint` | sha256 | 由 manifest 和报告相关状态确定性计算 |
| `created_at` | timestamp | checkpoint commit 时间 |

普通对话、TaskView、下载、Coverage、ReportPublisher 和恢复后的 Agent context MUST 读取同一个 snapshot Interface，不得自行扫描全局资产目录。

### AssetRevisionRef

| Field | Type | Rules |
|---|---|---|
| `asset_type` | enum | document、fact、evidence、review、conflict、coverage、material_digest、task_revision |
| `logical_id` | string | 业务实体稳定 ID |
| `revision_id` | string | 内容/修订稳定 ID，不得被原地覆盖 |
| `content_sha256` | string | 提升可见性前验证 |
| `task_id` | string | document cache 可跨任务复用内容，但 manifest 归属必须是当前 task |

Fact supersession 和 Conflict resolution 使用新 revision 表达，不覆盖旧 snapshot 引用的文件。

### RunWorkspace

ResearchRun 的持久工作集，不是第二个业务状态源。

| Field | Type | Rules |
|---|---|---|
| `run_id` | string | 唯一对应一个非终态或待清理 Run |
| `task_id` | string | 等于 Run.bound task |
| `base_version` | int | 等于 Run.input committed version |
| `staged_revisions` | AssetRevisionRef[] | 只对当前 Run 可见 |
| `status` | open/committed/abandoned | committed 只能随 checkpoint 原子完成 |

活动 Agent 的读取视图是 `CommittedResearchSnapshot(base_version) + RunWorkspace`；失败、取消或 interrupted 后 workspace 变为 abandoned，普通读取永不可见，后台可安全清理 orphan 内容文件。

### RuntimeOwnership

首版不实现分布式 lease；使用一个工作区级单实例锁。

- 新 Runtime 获得锁后，数据库中遗留的 running/stopping Run 都属于旧进程并转 interrupted。
- 若以后支持多 worker，再引入 runtime UUID、heartbeat 和 periodic CAS reaper。

### ResearchOutcome

| Value | Meaning | Version effect |
|---|---|---|
| `committed` | 有有效 staged revision 提升可见性 | version + 1 |
| `no_progress` | 完成搜索但没有新增可提交状态 | version 不变 |
| `failed` | 执行错误 | version 不变 |
| `cancelled` / `stopped` / `interrupted` | 未完成 | version 不变 |

## Persistence Mapping

优先扩展现有 checkpoint schema，不创建独立“第二状态库”：

- `checkpoint_assets` 增加或迁移为 revision manifest，保存 `asset_type`、`logical_id`、`revision_id`、`content_sha256`。
- `run_workspace_assets` 保存每个 Run 的 staged revision；terminal 后标 committed/abandoned。
- `research_runs(action_request_id)` 在非空时唯一，保证一个 Action 最多一个 Run。
- `research_checkpoints` 记录 `snapshot_fingerprint`；no-progress checkpoint 的 output version 等于 input version。
- `report_versions` 使用已有 committed version/checkpoint 字段并增加/复用 snapshot fingerprint；创建时执行 expected-version CAS。
- 现有 legacy 资产通过一次 baseline snapshot 导入；迁移不得把未归属任务的全局文件自动标 committed。

## Search Integration Value Objects

### AiNativeProviderConfig

部署配置，不持久化到业务数据库。

| Field | Type | Rules |
|---|---|---|
| `enabled` | bool | 默认 false；只有显式启用才允许调用 |
| `base_url` | URL / null | 可选覆盖；必须为 `https`，测试或本地代理可显式使用 `http` |
| `api_key_env` | string | 环境变量名，不是密钥值；不得为空白 |
| `rate_limit` | float | 大于等于 0，单位秒 |
| `max_results` | int | 1 至 50 |
| `cache_ttl` | int | 大于等于 0，单位秒 |
| `timeout_seconds` | float | 大于 0；单供应商超时 |

三个首版实例为 `exa`、`brave`、`tavily`，共享同一配置形状并允许不同默认 URL 和环境变量名。

### ProviderMetadata

复用现有模型，并为显式 credentialed stack 接受对应 access mode。

| Field | Meaning |
|---|---|
| `name` | 稳定供应商标识，写入 SearchResult provenance |
| `access_mode` | 匿名、自托管、Web fallback 或显式 credentialed |
| `requires_credentials` | AI-native Adapter 为 true |
| `requires_payment` | 描述服务是否可能计费，不代表自动启用 |
| `supports_anonymous` | AI-native Adapter 通常为 false |

### SearchRequest

复用现有模型：

- `query`: 非空自然语言或搜索表达式。
- `max_results`: 1 至 50。
- `time_range`: 可选时间范围，Adapter 映射到厂商支持的字段。
- `language`: 默认随查询语言；不支持时由 Adapter 忽略而不伪造过滤结果。
- `filters`: 可选域名、排除域名或其他已支持条件；未知过滤项不得未经验证直传。

### SearchResult

复用现有归一化结果：

- 标题、URL 和 snippet。
- `provider`/`engine` 来源标识。
- source kind、source type、evidence role。
- 发布时间、作者、rank/score 和安全的 provider-specific extra。

Adapter 不得将 API key、认证头或完整原始响应放入 `extra`。

### SearchOutcome

通用 `web_search` 的现有字典契约，逻辑上包含：

| Field | Type | Meaning |
|---|---|---|
| `results` | SearchResult[] | 跨渠道归一化、去重和排序后的候选 |
| `engineUsed` | string | 实际产生结果的渠道列表 |
| `degraded` | string[] | 被跳过、超时、限流或失败的渠道及安全原因 |
| `error` | string / null | 所有渠道均无结果时的人类可读建议 |

为保持当前公开行为，Implementation 可继续返回 dict；无需为单个调用新增持久模型或数据库表。

## Relationships

```text
Conversation ──binds once──> IntelTask ──contains──> IntelQuestion
                                 │
                                 ├──has many──> ResearchRun ──uses──> SearchPlanVersion
                                 │                    ├──writes──> RunWorkspace
                                 │                    └──commits──> ResearchCheckpoint
                                 │                                       │
                                 ├──versions──> CommittedResearchSnapshot <┘
                                 │                    └──references──> AssetRevisionRef
                                 └──versions──> ReportVersion

AiNativeProviderConfig ──enables──> SearchProvider Adapter
SearchProvider Adapter ──maps──> SearchResult ──candidate only──> IntelDocument
```

## Transient Provider Lifecycle

```text
disabled -> skipped
enabled + missing key -> degraded
enabled + key -> ready -> searching -> success
                               └──────> timeout/error/rate-limited -> degraded
```

Provider 状态是一次运行的观测信息，不是新的业务状态机。失败事件可进入现有运行事件流，但不得推进或回滚 committed state。

## Action and Run State Transitions

```text
Action: proposed -> queued -> executing -> succeeded
                    │           ├───────> failed/cancelled
                    └──────────> expired/cancelled

Run: queued -> running -> succeeded
              │   ├────> failed/interrupted
              │   └────> stopping -> stopped
              └────────> cancelled
```

- `queued Action -> executing Action + unique queued/running Run` 是一个原子 claim。
- `running Run + open RunWorkspace -> committed Checkpoint + terminal Run + terminal Action` 是一个事务。
- 恢复器只可重调度 queued work；executing/active 遗留状态必须按已持久 checkpoint 收敛，不能盲目重放副作用。
- proposed Action 过期后不得发 queued 事件或创建 Run。

## Validation and Invariants

1. YAML 只保存环境变量名；运行时密钥不得被序列化、记录或传给 Agent。
2. 至少一个 AI-native Adapter 在部署验收时必须实际可用；运行时单点故障允许降级。
3. 跨 Provider 按规范化 URL 去重；多个转载 URL 的独立性仍由既有来源评估处理。
4. SearchResult、answer、summary 和 highlight 都是候选，不是 Evidence。
5. `verified_evidence` 必须 committed、supports、Fact active、Review full 且 Document hash 有效。
6. Agent 的 Task/Run 绑定由服务器注入；工具不得用模型参数切换归属。
7. 新结果只通过 ResearchCheckpoint 进入 committed state；失败或取消不改变旧 snapshot。
8. 报告落库必须对渲染时 expected version 做 CAS；版本变化时失败或重试，不能绑定新版本。
9. Action、Run、Plan、Checkpoint 和 Report 的关联必须在 StateStore 事务中验证同属 Task。
10. 每个 Action 最多创建一个非迁移 Run；重复恢复或调度返回同一 claim 结果。
11. 开发默认监听 `0.0.0.0` 并在无认证时警告；生产或外网暴露必须认证并限制可信 Host。
