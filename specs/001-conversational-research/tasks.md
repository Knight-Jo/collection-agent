# Tasks: 多轮广深情报调研

**Input**: Design documents from `/specs/001-conversational-research/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: 规格明确要求独立验收、安全回归和中断恢复测试，因此每组行为变更先增加能够复现缺口的测试，再修改实现。

**Organization**: 任务按用户故事组织；P0/P1 中被多个故事共享的状态、安全和运行时不变量放在 Foundational 阶段。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可与同阶段其他标记任务并行，涉及不同文件且不依赖未完成任务
- **[Story]**: 对应 `spec.md` 中的用户故事
- **P0/P1/P2**: 描述漏洞修复优先级，不等同于用户故事优先级

## Phase 1: Setup (Shared Configuration)

**Purpose**: 固定现有技术栈和部署配置形状，不引入新编排框架或厂商 SDK。

- [X] T001 [P] 将 Pydantic AI 约束到当前兼容主版本并刷新锁文件，修改 `pyproject.toml` 和 `uv.lock`
- [X] T002 [P] 在 `src/intel_agent/config.py` 和 `config.example.yaml` 增加 AI-native Provider、关闭默认 httpx fallback、可选 Web bearer token/trusted-host 配置，同时保留开发默认 `web.host: 0.0.0.0`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 修复所有用户故事共同依赖的 P0/P1 安全、committed-state 和生命周期不变量。

**⚠️ CRITICAL**: 本阶段完成前不得接入付费 AI-native 搜索渠道。

- [X] T003 [P] 添加 IPv4-mapped IPv6、DNS rebinding、redirect 和 fallback 回归测试到 `tests/test_security.py` 与 `tests/test_document.py`
- [X] T004 在 `src/intel_agent/security.py` 和 `src/intel_agent/fetch.py` 归一化 `IPv6Address.ipv4_mapped`、要求公网地址，并删除或安全固定 httpx fallback 的实际连接地址，使 T003 通过
- [X] T005 [P] 添加默认 `0.0.0.0`、未认证启动警告、可选 bearer token、SSE/下载认证和 trusted-host 测试到 `tests/test_config.py` 与 `tests/test_web_api.py`
- [X] T006 在 `src/intel_agent/web/app.py` 实施 T005 的认证、Host 校验和开发暴露警告；未配置 token 时保持局域网开发可用
- [X] T007 [P] 添加 document/search 响应字节上限、crawler 唯一链接上限、RunCreate 字段上限和 retained event 上限测试到 `tests/test_document.py`、`tests/test_crawl.py`、`tests/test_search.py` 与 `tests/test_web_runs.py`
- [X] T008 在 `src/intel_agent/fetch.py`、`src/intel_agent/search/__init__.py`、`src/intel_agent/extract.py`、`src/intel_agent/crawl.py`、`src/intel_agent/web/schemas.py` 与 `src/intel_agent/web/runs.py` 实施解析前流式限额和有界集合，使 T007 通过
- [X] T009 添加敏感 URL 查询参数和认证值不进入日志、trace、SSE、文档 metadata 或报告的回归测试到 `tests/test_logging.py`、`tests/test_trajectory.py` 与 `tests/test_web_api.py`
- [X] T010 复用 `src/intel_agent/logging.py` 的脱敏路径并补齐 `src/intel_agent/fetch.py`、`src/intel_agent/trajectory.py`、`src/intel_agent/state_store.py` 与 `src/intel_agent/web/app.py` 的 URL/secret 持久化调用，使 T009 通过
- [ ] T011 [P] 添加旧数据库升级、baseline snapshot、asset revision manifest、run workspace 和 `research_runs(action_request_id)` 唯一约束测试到 `tests/test_state_db.py` 与 `tests/test_state_models.py`
- [X] T012 在 `src/intel_agent/state_db.py` 和 `src/intel_agent/models.py` 实施 T011 所需的最小向前迁移及 `CommittedResearchSnapshot`、`AssetRevisionRef`、`RunWorkspace`、`ResearchOutcome` 模型
- [ ] T013 添加固定版本 snapshot、hash 验证、未提交/abandoned workspace 不可见和幂等读取测试到 `tests/test_state_store.py`
- [X] T014 在 `src/intel_agent/state_store.py` 和 `src/intel_agent/storage.py` 实施 `committed_snapshot(task_id, version)`、`run_view(run_id)`、staged revision 和确定性 fingerprint，使 T013 通过
- [ ] T015 将 Document、Fact、Evidence 和 MaterialDigest 的运行中写入改为 append-only revision staging，修改 `src/intel_agent/fetch.py`、`src/intel_agent/fact.py`、`src/intel_agent/evidence.py` 与 `src/intel_agent/materials.py`
- [ ] T016 将 SupportReview、Conflict、Coverage 和 Task 更新改为当前 Run workspace 中的新 revision，修改 `src/intel_agent/audit.py`、`src/intel_agent/conflicts.py`、`src/intel_agent/coverage.py` 与 `src/intel_agent/task.py`
- [ ] T017 让 Agent context、TaskView、资源下载和通用任务读取只使用 committed snapshot 或当前 run view，修改 `src/intel_agent/context.py`、`src/intel_agent/web/views.py` 与 `src/intel_agent/storage.py`
- [X] T018 添加 Action 原子 claim、唯一 Run、checkpoint 状态守卫、expected-version CAS、原子 finish 和幂等重放测试到 `tests/test_state_store.py`
- [X] T019 在 `src/intel_agent/state_store.py` 实施 `claim_action`、queued Run claim 和 `finish_run` 事务，使 checkpoint、Run、Action、workspace 与 durable event 原子收敛并通过 T018
- [ ] T020 [P] 添加工作区单实例锁、旧 active Run 中断、queued initial/action/report/retry 恢复及 executing 状态收敛测试到 `tests/test_conversation_recovery.py`
- [ ] T021 在 `src/intel_agent/conversation.py` 和 `src/intel_agent/web/app.py` 实施工作区锁与完整启动恢复矩阵，移除无 heartbeat 的固定两分钟 lease 作为活性依据
- [ ] T022 添加 Agent 绑定 Task/Run 后拒绝跨任务 Fact、Evidence、Document、Plan、Checkpoint 和 Report 读写的测试到 `tests/test_runner.py` 与 `tests/test_continuation.py`
- [ ] T023 在 `src/intel_agent/agent.py` 的 `AgentDeps` 注入 `bound_task_id`/`run_id`，让 task-scoped 工具从依赖派生归属或拒绝不匹配 ID，并停止把全局 active-task 指针当授权
- [X] T024 添加零 staged revision 的 `no_progress`、queued cancellation、stopping 禁止 commit、失败/取消 workspace abandoned 测试到 `tests/test_continuation.py`
- [ ] T025 在 `src/intel_agent/continuation.py` 中先取得执行权再 claim Run，只通过 `run_view` 执行并调用原子 `finish_run`；正常模型返回但无有效 revision 时不推进版本

**Checkpoint**: SSRF、任务隔离、committed snapshot、原子完成和恢复门禁可独立通过；所有用户故事可在此基础上开发。

---

## Phase 3: User Story 1 - 通过对话启动调研 (Priority: P1) 🎯 MVP

**Goal**: 用户通过自然语言澄清并启动一个绑定当前对话、范围冻结且可恢复的首轮调研。

**Independent Test**: 分别提交完整主题、歧义主题和能力咨询；验证直接启动、必要澄清和不创建空任务三条路径，并在启动后重启进程确认只存在一条消息、一个任务和一个 initial Run。

### Tests for User Story 1

- [ ] T026 [P] [US1] 添加完整主题、歧义主题、能力咨询、2 至 6 个核心问题和对话单次绑定测试到 `tests/test_intake.py`
- [ ] T027 [P] [US1] 添加 processing attempt 原子 claim、已有 reply 幂等完成和并发重复处理测试到 `tests/test_state_store.py`
- [ ] T028 [P] [US1] 添加创建对话、提交消息、澄清后启动和重启恢复的 API 集成测试到 `tests/test_web_conversation.py`

### Implementation for User Story 1

- [ ] T029 [US1] 在 `src/intel_agent/intake.py` 和 `src/intel_agent/conversation.py` 固化能力咨询/澄清/启动分支、ResearchScope 验证及一次性 Conversation-to-Task 绑定，使 T026 通过
- [ ] T030 [US1] 在 `src/intel_agent/state_store.py` 将 message attempt claim、assistant reply、citation、attempt completion 和 durable event 收敛为幂等事务，使 T027 通过
- [ ] T031 [US1] 在 `src/intel_agent/conversation.py` 和 `src/intel_agent/web/conversation.py` 使用原子 message claim 并只调度 queued initial Run，使 T028 通过

**Checkpoint**: User Story 1 可单独创建、澄清、启动和恢复一个任务，不需要 AI-native Provider 即可验收。

---

## Phase 4: User Story 2 - 广泛且深入地搜集公开情报 (Priority: P1)

**Goal**: 围绕核心问题执行可追踪计划，覆盖国内外、多语言和独立来源，并通过可替换 AI-native Provider 扩展发现范围。

**Independent Test**: 用包含官网、新闻、论文、附件及中外来源的固定基准主题运行一次受限调研；验证计划存在、渠道可降级、结果跨渠道去重、原始材料被归档，搜索摘要从未直接成为 Evidence。

### Tests for User Story 2

- [X] T032 [P] [US2] 添加 initial/continuation Run 各有不可变 SearchPlanVersion、active plan endpoint 可读及旧计划前置条件过期测试到 `tests/test_state_store.py` 与 `tests/test_web_conversation.py`
- [X] T033 [P] [US2] 添加 AI-native 配置约束、缺密钥 degraded、disabled 不调用和 credentialed admission 测试到 `tests/test_config.py` 与 `tests/test_search_providers.py`
- [X] T034 [P] [US2] 添加 Exa、Brave、Tavily 官方响应映射、认证头、超限响应、无效 schema 和 secret 不泄漏契约测试到 `tests/test_search_providers.py`
- [ ] T035 [P] [US2] 添加现有国内外渠道与 AI-native Provider 并发、URL 去重、单点失败降级、总预算和“摘要不是证据”组合测试到 `tests/test_search.py`
- [ ] T036 [P] [US2] 添加站内深挖、附件发现、有界唯一链接、来源上游去重和中外来源覆盖测试到 `tests/test_deep_crawl_workflow.py`
- [ ] T037 [P] [US2] 添加只有 `supports` Evidence 计入独立交叉验证、官方单源例外不接受 contradiction 的测试到 `tests/test_audit.py` 与 `tests/test_coverage.py`
- [ ] T038 [P] [US2] 添加 Judge 调用计入运行总预算且共享 AsyncClient 在成功、失败和取消后关闭的测试到 `tests/test_runner.py`

### Implementation for User Story 2

- [X] T039 [US2] 在 `src/intel_agent/continuation.py` 和 `src/intel_agent/state_store.py` 为每个 initial/continuation Run 创建并绑定 SearchPlanVersion，执行时读取冻结计划并使 T032 通过
- [X] T040 [US2] 扩展 `src/intel_agent/search/provider.py` 的显式 credentialed admission，并从 `src/intel_agent/config.py` 构建 enabled 且密钥存在的 Provider 集合，使 T033 通过
- [X] T041 [P] [US2] 使用现有 `SearchProvider` 与调用方 AsyncClient 实现 Exa Adapter 于 `src/intel_agent/search/providers/exa.py`
- [X] T042 [P] [US2] 使用现有 `SearchProvider` 与调用方 AsyncClient 实现 Brave Adapter 于 `src/intel_agent/search/providers/brave.py`
- [X] T043 [P] [US2] 使用现有 `SearchProvider` 与调用方 AsyncClient 实现 Tavily Adapter 于 `src/intel_agent/search/providers/tavily.py`
- [X] T044 [US2] 让 `src/intel_agent/search/__init__.py` 的 `web_search` 统一调用现有及 AI-native Provider，复用 `src/intel_agent/search/provider.py` 的缓存、限流、规范化和去重，并通过 T034/T035
- [ ] T045 [US2] 在 `src/intel_agent/extract.py` 与 `src/intel_agent/crawl.py` 用 set 和提取上限处理链接，并保留附件/动态材料的预算内深挖，使 T036 通过
- [ ] T046 [US2] 在 `src/intel_agent/agent.py`、`src/intel_agent/audit.py` 与 `src/intel_agent/coverage.py` 仅按独立 `supports` 来源解除交叉验证，正确处理官方归属例外，使 T037 通过
- [ ] T047 [US2] 在 `src/intel_agent/runner.py`、`src/intel_agent/agent.py` 与 `src/intel_agent/audit.py` 共享运行级请求/Token 预算和 AsyncClient 生命周期，使 T038 通过
- [ ] T048 [US2] 增加覆盖发现、一手来源、独立佐证、附件、反向证据和 Provider 降级的固定基准验收到 `tests/test_deep_crawl_workflow.py`

**Checkpoint**: User Story 2 可通过直接构造 IntelTask/Run 独立验收；任一 AI-native Provider 失败不影响其他渠道，候选摘要不进入 Evidence。

---

## Phase 5: User Story 4 - 获得可核验的调研报告 (Priority: P1)

**Goal**: 报告只引用一次固定 committed snapshot 中经过完整审核的证据，并以不可变版本发布。

**Independent Test**: 对同时包含 full support、单源、冲突和缺口的固定 snapshot 生成报告，并在渲染与落库间并发提交新 checkpoint；验证旧内容不会绑定新版本，历史报告保持不变且正确标 stale。

### Tests for User Story 4

- [ ] T049 [P] [US4] 添加报告渲染期间 committed version 改变、expected-version/fingerprint CAS 失败和重试测试到 `tests/test_report_versions.py`
- [ ] T050 [P] [US4] 添加 Fact ID 不变但 Evidence/Review/Conflict/Coverage revision 改变时报告 stale，以及未审核/contradicts Evidence 不可引用测试到 `tests/test_report.py`
- [ ] T051 [P] [US4] 添加旧报告可读、新报告版本递增、显式发布和 stale 状态 API 测试到 `tests/test_web_conversation.py`

### Implementation for User Story 4

- [X] T052 [US4] 在 `src/intel_agent/state_store.py` 为 ReportVersion 保存 snapshot fingerprint，并用 expected committed version/fingerprint CAS 原子创建草稿
- [ ] T053 [US4] 在 `src/intel_agent/report_versions.py` 中一次取得固定 committed snapshot、基于其 manifest 渲染并处理 `STALE_REPORT`，不得再次读取 current version
- [ ] T054 [US4] 在 `src/intel_agent/report.py` 与 `src/intel_agent/audit.py` 保留完整 asset revision coverage fingerprint，并只允许 active Fact、supports Evidence、full Review 和 hash-valid Document 进入正式引用，使 T049/T050 通过
- [ ] T055 [US4] 在 `src/intel_agent/web/conversation.py` 和 `src/intel_agent/web/views.py` 返回不可变报告版本、stale 标记和固定 snapshot 资源，使 T051 通过

**Checkpoint**: User Story 4 可使用预置 snapshot 独立生成、发布、查看和核验报告，不依赖正在运行的搜索。

---

## Phase 6: User Story 3 - 在对话中追问与续研 (Priority: P2)

**Goal**: 用户只基于已提交证据问答，并可显式发起、取消、恢复或重试不会污染旧结果的续研。

**Independent Test**: 对预置 committed snapshot 分别执行证据问答、建议确认、补充搜索、取消、崩溃恢复、重试及实质性新主题输入；验证引用、Action/Run 数量、版本推进和新主题隔离。

### Tests for User Story 3

- [X] T056 [P] [US3] 添加 committed + active Fact + supports + full Review + valid Document 才标为 verified_evidence 的检索测试到 `tests/test_retrieval.py`
- [ ] T057 [P] [US3] 添加 DialogueDecision 在结构/引用/action 校验完成前不发送答案、material clue 最多 partial 的测试到 `tests/test_dialogue.py`
- [ ] T058 [P] [US3] 添加已绑定对话中的实质性新主题返回“新建对话/任务”且不创建 Action 或资产的测试到 `tests/test_dialogue.py` 与 `tests/test_conversation.py`
- [ ] T059 [P] [US3] 添加 expired confirm 不发送 queued、一个 Action 一个 Run、queued cancel、report cancel、retry 调度和崩溃恢复测试到 `tests/test_continuation.py` 与 `tests/test_conversation_recovery.py`
- [X] T060 [P] [US3] 添加极端 history cap 下保持总字节上限及 ToolCall/ToolReturn 配对的测试到 `tests/test_context.py`

### Implementation for User Story 3

- [X] T061 [US3] 在 `src/intel_agent/retrieval.py` 只从 committed snapshot 构建 passage，并按 T056 的五项条件设置 verified_evidence
- [X] T062 [US3] 在 `src/intel_agent/dialogue.py` 先完成 DialogueDecision 解析、repair、引用和 action 校验再发布可见答案，使 T057 通过
- [ ] T063 [US3] 在 `src/intel_agent/models.py`、`src/intel_agent/dialogue.py` 与 `src/intel_agent/conversation.py` 增加确定性 new-topic 分流且不改绑现有 Conversation，使 T058 通过
- [ ] T064 [US3] 在 `src/intel_agent/conversation.py`、`src/intel_agent/continuation.py` 与 `src/intel_agent/web/conversation.py` 依据原子 claim 结果发送事件，并接通 continuation/report/retry 的恢复和取消，使 T059 通过
- [X] T065 [US3] 在 `src/intel_agent/context.py` 实施有界 fallback，必要时丢弃完整旧工具交换而不留下孤立 ToolReturn，使 T060 通过

**Checkpoint**: 四类续研生命周期和证据问答均可对预置任务独立验收；失败、取消、新主题不会改变旧 committed snapshot。

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 删除第二状态真相，完成文档、兼容性和全栈门禁。

- [ ] T066 添加 `/api/runs` 在重启后仍读取持久 ResearchRun、不会保留无界终态内存记录的测试到 `tests/test_web_runs.py`
- [ ] T067 将 `src/intel_agent/web/app.py` 的旧 `/api/runs` 路由迁移到 `StateStore` ResearchRun/event，删除或缩减 `src/intel_agent/web/runs.py` 的 `RunRegistry` 第二状态真相，使 T066 通过
- [X] T068 [P] 更新开发默认 `0.0.0.0`、未认证警告、生产认证、Provider 配置、密钥、费用、降级和证据边界文档于 `README.md`、`config.example.yaml` 与 `specs/001-conversational-research/quickstart.md`
- [ ] T069 执行并修复 `ruff format --check .`、`ruff check .`、`pyright`、`pytest` 与 `uv build` 发现的问题，必要修改限定在对应失败文件和 `tests/`
- [ ] T070 执行并修复 `web/` 下 `bun run test`、`bun run typecheck`、`bun run check`、`bun run build`，随后按 `specs/001-conversational-research/quickstart.md` 完成 P0/P1 故障注入和 AI-native smoke 验收

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: 无依赖；T001 与 T002 可并行。
- **Phase 2 Foundational**: 依赖 Setup；T003→T004、T005→T006、T007→T008、T009→T010、T011→T012→T013→T014→T015/T016→T017、T018→T019、T020→T021、T022→T023、T024→T025。
- **User Stories**: 全部依赖 Foundational。可用固定数据库 fixture 独立验收，因此不强制故事间依赖；集成交付建议 US1 → US2 → US4 → US3。
- **Polish**: T066/T067 依赖 Foundational runtime；T068 可在故事实现后并行；T069/T070 依赖本次计划纳入的所有故事完成。

### User Story Dependencies

```text
Setup → Foundational ─┬→ US1 对话启动 (MVP)
                     ├→ US2 广深搜集
                     ├→ US4 可核验报告
                     └→ US3 问答与续研

US1 + US2 + US4 + US3 → Polish / Full acceptance
```

- **US1**: 直接依赖 shared message/run transactions，无其他故事依赖。
- **US2**: 通过预置 Task/Run 独立测试；完整用户旅程使用 US1 创建的任务。
- **US4**: 通过预置 committed snapshot 独立测试；真实报告内容来自 US2。
- **US3**: 通过预置 committed snapshot 独立测试；完整旅程建立在 US1/US2/US4 之上。

### Parallel Opportunities

- T001/T002、T003/T005/T007/T011/T020 可在各自文件不冲突时并行编写。
- US2 的 T041/T042/T043 三个 Provider Adapter 可并行；共享组合层 T044 等三者接口稳定后执行。
- US4 的 T049/T050/T051 可并行编写后再实现 T052-T055。
- US3 的检索、Dialogue、Action recovery 和 context 测试可按 T056/T057/T059/T060 并行。
- 不并行修改 `state_store.py`、`conversation.py` 或 `agent.py`；这些深 Module 的任务按编号串行，避免迁移和状态机冲突。

## Parallel Execution Examples

### User Story 2

```text
T041: Implement Exa Adapter in src/intel_agent/search/providers/exa.py
T042: Implement Brave Adapter in src/intel_agent/search/providers/brave.py
T043: Implement Tavily Adapter in src/intel_agent/search/providers/tavily.py
```

### User Story 4

```text
T049: Report snapshot race tests in tests/test_report_versions.py
T050: Evidence/revision freshness tests in tests/test_report.py
T051: Report version API tests in tests/test_web_conversation.py
```

### User Story 3

```text
T056: Verified evidence tests in tests/test_retrieval.py
T057: Validated answer visibility tests in tests/test_dialogue.py
T059: Continuation recovery tests in tests/test_continuation.py and tests/test_conversation_recovery.py
T060: History compaction tests in tests/test_context.py
```

## Implementation Strategy

### MVP First

1. 完成 T001-T025，建立可信安全和状态基础。
2. 完成 T026-T031，独立验收 User Story 1。
3. 停止并验证：自然语言主题可澄清、启动、重启恢复且不重复。

此范围是交互入口 MVP；可交付调研产品还需要 US2 和 US4。

### Incremental Delivery

1. **Security/state foundation**: 先封闭 SSRF、跨任务、未提交资产和 crash window。
2. **US1**: 可靠创建和启动任务。
3. **US2**: 先统一现有 Provider，再并行增加 Exa/Brave/Tavily。
4. **US4**: 对固定 snapshot 生成可核验版本报告。
5. **US3**: 补齐对话问答、续研、取消、恢复和重试。
6. **Polish**: 删除内存 Run 真相并执行全栈门禁。

## Notes

- 每个测试任务必须先证明当前缺口，再实现紧随其后的修复任务。
- 搜索 answer、summary、snippet、highlight 始终只是候选线索。
- 开发默认 `0.0.0.0` 是明确产品决定；生产或外网暴露仍必须认证并限制 Host。
- 不新增 LangChain、LangGraph、厂商 SDK、第二数据库或单实现抽象层。
- 每个任务完成后运行最小相关测试；T069/T070 才运行完整门禁。
