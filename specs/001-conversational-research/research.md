# Phase 0 Research: 架构与实现缺口审计

## 结论

架构方向仍然合理：Pydantic AI 只承担模型与工具循环，StateStore、证据审核和报告 Module 掌握业务规则，因此不需要迁移 LangChain/LangGraph。但是当前 Implementation 还不能把 `committed_state_version`、任务隔离和网络安全当成可靠保证。AI-native 搜索会放大外部输入、调用次数和长期运行风险，必须先完成 P0/P1 修复。

## Audit Method

- 端到端追踪 intake、ConversationRuntime、ContinuationRunner、Agent 工具、StateStore、文件资产、Retriever、ReportPublisher、FastAPI 和 crawler。
- 交叉检查规格 FR-004、FR-005、FR-008、FR-013、FR-015、FR-017、FR-018、FR-020、FR-021。
- 使用当前 Python 3.12 / Pydantic AI 2.27.0 环境执行两个最小探针。
- `resolve_public_url("http://[::ffff:127.0.0.1]:6780/api/tasks")` 被放行，确认 SSRF 表示法绕过。
- 500-byte history cap 返回 10,649 bytes，并留下孤立 ToolReturn，确认极端压缩失效。
- 默认测试环境的 editable install 指向旧 benchmark worktree，首次收集出现 12 个 import error；显式 `PYTHONPATH=src` 后全量套件长时间无输出。本结论不把未完成测试当作通过证据。

## Priority Definitions

- **P0**: 可能访问内网、未经授权读取/修改数据，或让失败运行改变已提交结论；新增搜索前必须修复。
- **P1**: 可能永久卡住、重复执行、错误成功或违反规格的审计/恢复语义；功能验收前必须修复。
- **P2**: 质量、成本、可观测性和维护性缺口；在核心不变量稳定后修复。

## Confirmed Findings

| Priority | Finding | Code evidence | Impact |
|---|---|---|---|
| P0 | committed checkpoint 只跟踪 document/fact/evidence ID，工具却原地修改 Fact/Review/Conflict/Coverage | `continuation.py:217-308`, `fact.py:168-215`, `audit.py:193-250`, `conflicts.py:111-143` | 失败、取消或崩溃运行可以改变已提交事实，而 state version 不变 |
| P0 | Agent context、TaskView 和部分报告路径直接读取全部文件资产 | `context.py:52-80`, `web/views.py:168-244`, `report_versions.py:20-47` | 未提交或孤儿资产污染下一次 Agent、界面和报告 |
| P0 | ReportPublisher 只 allowlist Fact，未同步约束 Evidence/Review/Document | `report_versions.py:28-35`, `audit.py:268-285` | 失败运行给已提交 Fact 增加的 Evidence 可能进入报告 |
| P0 | 报告渲染与落库之间没有 expected-version CAS，coverage fingerprint 条件被 allowlist 分支覆盖 | `report_versions.py:20-47`, `report.py:246-269`, `state_store.py:1687-1748` | 旧内容可能被记录成基于最新 committed version |
| P0 | IPv4-mapped IPv6 未归一化 | `security.py:23-60`, `security.py:88-112`, `fetch.py:141-156` | `::ffff:127.0.0.1`、私网和 metadata IPv4 可绕过 SSRF blocklist |
| P0 | Web 默认 `0.0.0.0` 且无认证/Host 校验 | `config.py:138-140`, `web/app.py:49-219`, `web/conversation.py:38-251` | 同网段或暴露端口的客户端可读取原件、烧额度、取消/确认/发布 |
| P0 | 默认 httpx fallback 忽略已验证 IP并在限额后才检查完整 body | `config.py:107-108`, `fetch.py:381-407`, `agent.py:1785-1806` | DNS rebinding 和内存 DoS |
| P0 | AgentDeps 未绑定当前 Task/Run，多数工具信任模型提供 ID或全局 active-task | `agent.py:230-253`, `agent.py:1645-2110`, `continuation.py:217-244` | 模型幻觉或提示注入可跨任务读写 |
| P1 | Action claim、Run 创建、checkpoint、Run/Action 完成分属多个事务 | `continuation.py:183-276`, `state_store.py:1080-1285`, `state_store.py:1535-1679` | crash window 产生 executing Action、running Run 或已提交 checkpoint 的不一致组合 |
| P1 | 过期 proposal 仍被 Runtime 宣告 queued 并调度 | `state_store.py:1160-1205`, `conversation.py:283-302` | 产生错误用户反馈和永久 queued 孤儿 Run |
| P1 | 恢复只处理 pending message 和 queued initial Run | `conversation.py:249-271`, `web/app.py:80-83` | queued continuation/report/retry 永久不执行，executing Action 不收敛 |
| P1 | 固定两分钟 lease 无 heartbeat，且 reaper 只在启动运行一次 | `continuation.py:121-129`, `continuation.py:208-216`, `state_store.py:1474-1495` | 快速重启遗留 ghost Run；长健康 Run 可被另一实例误判 interrupted |
| P1 | 多个 continuation 在取得 gate 前创建 Run，执行时不复核 Action/input version | `continuation.py:183-217`, `state_store.py:1180-1205` | 排队运行的审计输入版本与实际 checkpoint 基线漂移 |
| P1 | start/commit checkpoint 未要求 Run 正处于 running | `state_store.py:1535-1604` | queued、failed 或 succeeded Run 可以提交资产 |
| P1 | 空 `agent.run()` 返回仍提交空 checkpoint 并标成功 | `continuation.py:249-276` | 零工具、零进展续研错误成功并使报告 stale |
| P1 | TaskRetriever 把未审核、partial、contradicts 或 superseded Fact 的 Evidence 标成 verified | `retrieval.py:109-172` | 对话可把未核验证据当正式引用 |
| P1 | 对话允许只有 material clue 的事实回答为 answered，且流式文本在结构校验前发送 | `dialogue.py:192-266` | 用户可能看到未核验或最终被 repair 替换的答案 |
| P1 | 交叉验证 backlog 统计所有 relation，未只统计 supports | `agent.py:1145-1197` | 一个支持来源加一个反证来源可能错误解除补证要求 |
| P1 | message processing attempt 无原子 claim；reply 与 attempt completed 分事务 | `state_store.py:689-727`, `state_store.py:787-942`, `conversation.py:432-533` | 多 Runtime 重复回答或留下永久 processing attempt |
| P1 | crawler HTML 链接 list 去重近 O(n²) 且无提取上限 | `extract.py:200-220`, `extract.py:948-974`, `crawl.py:834-855` | 恶意 5 MiB 页面造成 CPU/内存和超大 crawl snapshot |
| P1 | 外部搜索和 Run API 输入/事件在完整缓冲前缺少总量上限 | `search/__init__.py:150-300`, `web/schemas.py:55-90`, `web/runs.py:54-124` | 错误搜索端、超大请求或大量终态 Run 可耗尽内存 |
| P2 | SearchPlanVersion 只有存储和测试，生产未调用 | `state_store.py:1392-1455`, `continuation.py:149`, `continuation.py:261` | search-plan endpoint 通常 404，modify-plan 前置条件无法成立 |
| P2 | 新主题没有明确 intent/Action，search_specific_topic 可污染当前任务 | `dialogue.py:20-67`, `models.py:52-63` | FR-004 的新对话分流依赖模型自由发挥 |
| P2 | history compaction 极端 fallback 超 cap 且破坏 tool call/return 配对 | `context.py:207-243` | provider 拒绝消息或上下文继续超限 |
| P2 | JudgeAgent 使用独立 usage，未计入注释声称的统一 request budget | `config.py:73-79`, `agent.py:275-313`, `audit.py:177-229` | 审核请求可超过运行预算和成本上限 |
| P2 | 每次 build_deps 创建 AsyncClient，runner/continuation 未关闭 | `agent.py:230-253`, `runner.py:333`, `continuation.py:240` | 长期运行积累连接与资源 |
| P2 | 通用 web_search 绕过已有 SearchProvider | `search/__init__.py:317-427`, `search/provider.py:42-90` | AI-native Adapter 会复制缓存、限流、准入和降级逻辑 |
| P2 | 旧 `/api/runs` 使用纯内存 RunRegistry | `web/app.py:53-78`, `web/runs.py:54-239` | 与 SQLite ResearchRun 形成第二套状态真相，重启丢失 |
| P2 | Pydantic AI 依赖没有主版本上限 | `pyproject.toml:7-18` | 非 lockfile 安装可能静默进入破坏性主版本 |

## Decision 1: 先建立可信 committed snapshot

**Decision**: 普通读取只能通过一个 committed-state Module 获得固定 snapshot；活动 Agent 只能看到该 snapshot 加当前 Run 工作集。Fact supersession、Review、Conflict resolution、Coverage 和 MaterialDigest 不再原地改变已提交版本，而使用不可变修订或 run-scoped staging。checkpoint 是唯一提升可见性的动作。

**Rationale**:

- 只在 Retriever 增加 allowlist 无法阻止 Report、Coverage、Agent context 和 TaskView 读取孤儿资产。
- 删除失败运行的新文件也无法回滚已提交 Fact 的原地 supersede。
- 内容寻址文件可以在数据库事务前写入；崩溃只留下不可见 orphan，数据库 committed manifest 仍是事实源。

**Alternatives considered**:

- **失败时按 ID 删除新增文件**: 拒绝，无法恢复原地修改，也无法覆盖进程硬崩溃。
- **复制整个 workspace 并在失败时恢复**: 拒绝，文档可能很大，恢复与并发语义脆弱。
- **只依赖提示词要求 Agent 不修改旧资产**: 拒绝，提示词不是事务或授权控制。

## Decision 2: 生命周期在 StateStore 内原子收敛

**Decision**: 增加窄的 StateStore Interface：原子 claim Action 并创建/复用唯一 Run；原子提交 checkpoint manifest、完成 Run 和完成 Action；原子 claim/complete message attempt。Runtime 只负责调度，不再手工拼装状态转换顺序。

**Rationale**:

- 事务应该放在拥有 SQLite 状态机的深 Module，而不是分散在 ConversationRuntime 和 ContinuationRunner。
- `action_request_id` 唯一性和 expected-version CAS 能在重启和重复调度下提供一次执行保证。
- 空工作集应记录 `no_progress` outcome，但不推进 committed version。

**Alternatives considered**:

- **在 Runtime 增加更多 if/try/finally**: 拒绝，crash window 仍跨事务存在。
- **迁移 LangGraph checkpoint**: 拒绝，它不会自动把本项目的 SQLite 与文件资产提交为一个业务事务。

## Decision 3: 保持单进程产品范围并真正执行它

**Decision**: 首版通过工作区级单实例锁保证只有一个 Runtime；新进程持锁启动后，将遗留 running/stopping Run 收敛为 interrupted。无需保留没有 heartbeat 的两分钟租约。恢复器重新调度 queued initial/action/report/retry，并对 executing 状态按 Run/checkpoint 结果收敛。

**Rationale**:

- 规格明确本地单机单用户，单实例锁比伪分布式 lease 更简单可靠。
- 当前全局 active-task pointer 和文件资产也不支持多进程；先诚实约束比半支持并发安全。

**Alternatives considered**:

- **runtime UUID + heartbeat + periodic reaper**: 多 worker 成为真实需求时再采用。
- **等待旧 lease 自然过期**: 拒绝，当前没有周期 reaper，可能永久卡住。

## Decision 4: 安全默认拒绝

**Decision**: 公网地址判断先归一化 IPv4-mapped IPv6 并要求 `ip.is_global`；删除或默认关闭会重新解析 DNS 的 httpx fallback；所有外部 body 流式限额。为方便开发，Web 保持默认 `0.0.0.0`；无认证启动时输出醒目警告，生产或外网暴露必须配置 bearer token 和可信 Host。

**Rationale**:

- 外部 URL 来自模型、搜索结果和恶意网页，属于真实 trust boundary。
- CORS 不能阻止同网段直接 HTTP 请求或 DNS rebinding。
- 在 `response.content` 之后检查大小不能防内存 DoS。

**Alternatives considered**:

- **继续维护显式 IP blocklist**: 拒绝作为唯一判断，特殊表示法容易遗漏。
- **保留不固定 IP 的 fallback 并标注 low risk**: 拒绝，URL 由不可信输入控制。
- **默认改为 127.0.0.1**: 未采用；用户明确要求保留局域网开发便利，风险通过运行时警告和生产配置门禁管理。

## Decision 5: Task/Run binding 是工具授权条件

**Decision**: `AgentDeps` 持有固定 `task_id` 和 `run_id`。Task-scoped 工具不让模型选择 Task，或在兼容期统一拒绝不匹配参数；文档、Fact、Evidence、Plan、Checkpoint 和 Report 关联均在 StateStore 事务中验证同属 Task。

**Rationale**:

- 系统提示中的“使用工具返回 ID”不是授权控制。
- 绑定后可移除执行路径对全局 active-task pointer 的依赖，为以后并发留下正确升级点。

**Alternatives considered**:

- **依赖 UUID 难猜**: 拒绝，模型上下文、日志和 Web 接口都会暴露 ID。
- **只加数据库单列 foreign key**: 拒绝，它只验证对象存在，不验证同属 Task。

## Decision 6: 对话与报告使用相同证据定义

**Decision**: `verified_evidence` 必须同时满足 committed、Fact active、relation supports、SupportReview verdict full、Document hash valid。只有 material clue 时事实回答最多为 partial。对话只在完整 decision 通过结构、引用和 action 校验后发送最终文本；报告针对固定 snapshot 渲染并以 expected-version CAS 落库。

**Rationale**:

- 当前 Retriever 的标签与 coverage/report 的 full-support 定义不一致。
- “先流后验”会让用户看到最终系统并不接受的答案。
- 报告内容与版本必须来自同一次 snapshot，而不是两次独立读 current version。

**Alternatives considered**:

- **继续让模型自行区分 material_clue**: 拒绝，模型输出不能替代服务端状态标签。
- **渲染后无条件绑定最新版本**: 拒绝，存在明确 TOCTOU。

## Decision 7: 保留 Pydantic AI，不迁移 LangChain/LangGraph

**Decision**: Pydantic AI 2.x 继续作为模型、工具、结构化输出、历史和流事件的 Implementation；依赖约束到兼容主版本。当前不引入 LangChain/LangGraph。

**Rationale**:

- 已确认问题位于业务可见性、网络、安全、生命周期和资源上限，不是 Agent loop 能力缺失。
- LangGraph 执行 checkpoint 与 ResearchCheckpoint 语义不同，叠加会增加第二套恢复状态。
- Pydantic AI 已支持 toolsets、多 Agent、MCP、图、OpenTelemetry 和 durable execution integrations。

**Alternatives considered**:

- **LangChain Agent**: 拒绝；其 Agent 底层同样使用 LangGraph，主要替换已有能力。
- **全量 LangGraph**: 拒绝；不能替代 committed evidence transaction。
- **局部 LangGraph**: 仅在跨进程节点级恢复、稳定 fan-out/fan-in 或长时间 HITL 成为已测需求后 spike。

**Official references**:

- [Pydantic AI agents](https://pydantic.dev/docs/ai/core-concepts/agent/)
- [Pydantic AI durable execution](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

## Decision 8: P0/P1 后深化 SearchProvider Seam

**Decision**: Exa、Brave、Tavily 实现现有 `SearchProvider` Interface，使用已安装的 httpx 和官方 REST；Agent 继续只看到一个 `web_search` 工具。credentialed Adapter 显式 opt-in，配置只存环境变量名。

**Rationale**:

- `search/provider.py` 已有 metadata、request、result、缓存、限流和去重。
- 通用 `web_search` 当前绕过此 Seam，才是搜索扩展的根因。
- 一个工具能保持统一预算、降级和“摘要不是证据”规则。

**Alternatives considered**:

- **每个供应商一个 Agent 工具**: 拒绝，复制预算与错误处理并扩大工具选择空间。
- **厂商 SDK**: 当前不需要；简单 REST 不值得增加三个依赖。
- **直接 MCP 搜索**: 不作为核心搜索路径，避免绕过归档和 committed-state Interface。

**Official references**:

- [Exa Search API](https://exa.ai/docs/reference/search)
- [Brave Search API](https://api-dashboard.search.brave.com/app/documentation/web-search)
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)

## Existing Protections That Should Be Preserved

- `storage._safe_path()` 在 resolve 后拒绝路径逃逸和外部 symlink。
- pinned HTTP fetch 校验 scheme、userinfo、DNS、实际连接 IP 和每个 redirect hop；修复 mapped IPv6 后继续复用。
- 文档、证据和报告都有内容 hash/精确引文验证。
- 浏览器默认关闭；启用时使用独立 context、sandbox、禁下载/WebSocket/iframe/popup，并有时间、请求和字节限制。
- SQLite mutator 普遍使用 `BEGIN IMMEDIATE`，状态转换和单任务 running 约束应保留并深化。
- 搜索摘要不能直接保存为 Evidence，报告生成具有 active Fact、full review 和引用生成门禁。

## Re-evaluation Triggers

只有以下事实之一成立才启动 LangGraph 限时 spike：

1. 产品要求小时级运行跨进程从最后完成节点原位恢复，而不是 interrupted + new retry Run。
2. 至少三个独立专家需要稳定 fan-out/fan-in，且单 Agent 工具选择失败已由基准确认。
3. 一次运行内部需要跨重启、长时间等待的人机审批点。
4. 多进程 worker 或同任务并行分支进入已批准范围。

即使触发，StateStore 和 committed snapshot 仍是业务事实源；图只保存执行游标，副作用节点必须使用稳定幂等键。
