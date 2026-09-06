# Tasks: 持续监测 · 事实核验 · 媒体分析

**Input**: [spec.md](spec.md)、[data-model.md](data-model.md)
**Status**: 待实施；本文不是代码完成记录。
**Scope**: 后端应用、FastAPI、测试；前端接入独立后续实施。

## 实施规则

- 先写能复现需求缺口的测试，再修改实现；按 Module 的公开 Interface 测试，不把私有辅助函数作为业务契约。
- 以当前代码为起点；runtime_state 与 provider 替换方法已存在，但配置冻结、恢复、凭证安全需要补齐。
- 不把新逻辑继续塞进 ConversationService、MaterialStore 或 api/app.py，不复制研究循环。
- 任务编号稳定。只有不共享文件且满足依赖的工作才可并行；本清单不使用原有错误的 [P] 标记（原任务多处同时改同一文件）。
- 不引入 Redis/Celery、通用 Repository/工作流框架或前端兼容层。所有新依赖先查现有依赖，仅确有缺口时通过 uv 添加。

## Phase 1 — 明确复用 Interface 与存储所有权

- [ ] **T101** [FR-405] 在 tests/unit/test_module_dependencies.py 用标准库 AST 检查新增 Module 不依赖 conversation/api/bootstrap，业务 Module 不互相导入，SQL 不外泄；补既有研究/会话行为回归用例。建立目标依赖规则，不借此重写无关代码。
- [ ] **T102** [FR-104, FR-205] 在 contracts/research.py 定义 ResearchAssessment；调整 orchestration/orchestrator.py，使已有循环输出类型化评估，普通调研再生成报告。保留原有报告入口及行为但不复制循环；测试无需生成报告即可消费 coverage/evidence/citations。
- [ ] **T103** [FR-202, FR-304] 在现有 context/材料定位能力中集中校验 scope、Citation、BlockSpan 与连续引文；研究评估出口拒绝或标记无效引用。测试伪造 citation_id、跨任务材料、错误 span、同 URL 不同 revision。
- [ ] **T104** [FR-405, FR-408] 从 MaterialStore 提取任务/预算/检查点操作到 storage/tasks.py、runtime_state 操作到 storage/settings.py；各调用方改用唯一实现。SqliteStore 提供明确的共享事务使用方式并更新过时“仅 MaterialStore 调用”的约定；测试复合写入回滚，不嵌套自动 commit。

**依赖**：T101 先行；T102、T103 配合完成后才允许三个业务消费评估。T104 完成后再添加跨记录事务。

## Phase 2 — 契约、持久执行与运行配置

- [ ] **T105** [FR-101, FR-203, FR-301] 分别在 monitoring/models.py、factcheck/models.py、media/models.py 定义 data-model 的模型；跨 Module 共享执行字段放现有 contracts。分别测试枚举、条件必填、时间区间、归属、not_checkable、nullable speaker 与媒体 unverified。
- [ ] **T106** [FR-106, FR-206, FR-305, FR-404] 新增并注册下一序号 SQLite 迁移；新增 storage/monitoring.py、storage/factcheck.py、storage/media.py Adapter，扩展 tasks、评估快照与时间线。验证外键、幂等、计划唯一性、原子入队/完成和版本不可变；使用临时 SQLite 测试，不把多表写入当成若干 CRUD 的顺序调用。
- [ ] **T107** [FR-404, FR-408] 在 application.py 统一后台执行登记、并发限制、取消和关闭；运行调度不再散落在 ConversationService/API。复用 runtime/ 的执行限制，加入工作区执行锁、queued 认领、running→interrupted 恢复和按 kind 分派。resume 保留 task_id、阶段、预算和 deadline；deadline/预算耗尽明确拒绝。
- [ ] **T108** [FR-401, FR-402, FR-406, SC-401] 新增 search/settings.py 并移出 ConversationService 的配置操作；复用已有 KV/构造函数，提供原子配置 revision、只写秘密字段与脱敏投影。入队冻结非敏感策略，禁止运行中全局 provider 热替换；测试新旧运行并存、修改失败回滚、清空 Key/Cookie、当前凭证解析与秘密不入快照。
- [ ] **T109** [FR-405, FR-407] 整理 API 注册与依赖注入：新增路由放 api/routes/，bootstrap.py 组装应用与 Adapter；library.py 只读组合各 Module 摘要，ConversationService 移除跨业务 library 与配置职责。不提前增加返回 mock/空壳的“已实现”端点。

**依赖**：T105 → T106 → T107；T104 → T108；T107、T108 → T109。Phase 3–5 在共享 Interface 稳定后按需分开实现，不同时改共享契约。

**Checkpoint**：临时数据库验证持久入队、幂等、重启中断、取消竞争及秘密脱敏；通过类型化应用 Interface 使用能力，不要求 HTTP 存在。

## Phase 3 — Monitor：调度与原子增量基线（US1–US2）

- [ ] **T201** [FR-101, FR-102] 在 monitoring/service.py 实现创建与显式配置/status 更新；配置版本递增不改变既有运行快照。测试空输入、站点校验、daily/weekly 时区结构、暂停幂等及暂停后手动运行。
- [ ] **T202** [FR-103, FR-408] 在 monitoring/scheduler.py 实现可注入时钟的到期检查与下一时刻计算；向应用提交持久工作，不拥有独立 worker。测试 DST 重复/缺失时刻、漏跑合并、暂停恢复、单监测 active_run_id 认领、重复计划及手动请求，手动运行不改计划时间。
- [ ] **T203** [FR-104] 用冻结输入驱动现有研究循环并保存 ResearchAssessment；复用 task 材料 scope 和预算。测试不会创建 Conversation，不调用报告展示投影，不混入其他任务材料。
- [ ] **T204** [FR-105] 在 monitoring/ 内实现事实身份/版本匹配与来源 hostname 去重；比较输入输出均为类型化数据。测试首轮空基线、同义改写、value 修订、scope 改变、匹配不确定、未命中不删除、同站不同 URL、重要性理由及空变化。
- [ ] **T205** [FR-106, FR-404] 完成变化集、累积事实/来源成员、task 终态、基线指针的原子条件提交。测试 partial/失败不推进基线、提交前后崩溃、取消竞争、恢复同运行及基线失配；有新活动运行/基线已变化时禁止旧失败运行强行 resume。
- [ ] **T206** [FR-407] 新增 api/routes/monitors.py：创建/显式更新、分页读取、提交/查询运行。测试 201/202、Idempotency-Key、重复输入冲突、run 归属与有界历史；library 通过只读摘要接入，不在会话模块实现。

**依赖**：T201 → T202；T203 → T204 → T205；T202、T205 → T206。

**Checkpoint**：创建→自动/手动触发→评估→变化→基线→查询闭环，无重复活动运行、无失败基线污染。

## Phase 4 — FactCheck：引用验证与独立裁决（US3）

- [ ] **T301** [FR-201, FR-206] 在 factcheck/service.py 实现持久异步提交、断言理解与 checkability；先返回 queued，再执行模型。测试观点/含糊输入正常 completed + not_checkable + verdict=null，执行故障不会伪装 insufficient。
- [ ] **T302** [FR-202, FR-205] 基于理解结果生成正反方向研究输入，调用同一研究循环消费 ResearchAssessment；验证并保存 FactEvidence，保留当前 scope。测试没有反证时不伪造、跨任务/错误引用不入有效证据。
- [ ] **T303** [FR-203, FR-204] 在 factcheck/verdict.py 实现六级裁决及证据充分度的类型化输出验证与证据归组计数；需要的模型步骤复用现有 agent/模型执行与预算能力。测试支持/反驳/部分限定、实质冲突、证据不足、重复转载与未知独立性；禁止 relation→accepted/disputed 映射。
- [ ] **T304** [FR-206, FR-404] 原子提交证据、裁决、终态与时间线；测试 partial、failed、cancelled、interrupted 及恢复保留阶段，不重置预算/deadline。
- [ ] **T305** [FR-407] 新增 api/routes/factchecks.py：提交及分页列表/详情/证据/时间线。验证 202 返回快于执行完成、轮询可恢复全部持久状态、library 仅组合真实摘要；不增加必需 SSE 依赖。

**依赖**：T301 → T302 → T303 → T304 → T305。

**Checkpoint**：断言→理解→正反取证→引用校验→裁决→查询闭环，不依赖会话或前端模拟。

## Phase 5 — Media：资源复用与未核验声明（US4）

- [ ] **T401** [FR-301, FR-403] 实现媒体上传入队：流式字节限额、内容探测、受控资源仓、内容 hash 幂等及元数据/任务事务。复用 ResourceStore.write_stream，不用 filename 拼路径。测试伪造 MIME、超限、损坏输入、路径穿越、重复 key 与上传中断；若使用 FastAPI multipart 且环境缺依赖，通过 uv 明确添加所需解析依赖。
- [ ] **T402** [FR-302, FR-306] media/service.py 经 AcquisitionPipeline 处理已上传 Resource 并投影 MediaSegment；不另写 ASR/转码封装。测试阶段恢复、原始媒体时间偏移、speaker/confidence=null、无语音、部分转写、后端不可用、时长/超时限制；不自动联网抓取。
- [ ] **T403** [FR-303, FR-304] 从已提交 blocks 提取 MediaFact 与 MediaEvidence，并验证跨分段关联、原文 span、时间区间和 job 归属。测试默认 unverified/mentions、材料内反驳不会生成外部裁决、提示注入无效，媒体模型调用计入现有执行预算。
- [ ] **T404** [FR-305, FR-404] 生成摘要并原子提交分析结果/终态/时间线。恢复复用已提交 artifact，不覆盖旧转写；测试空结果、partial、失败、取消竞争与重复完成。
- [ ] **T405** [FR-407] 新增 api/routes/media.py：上传、分页读取任务/分段/声明/出处/时间线；不允许读取任意服务端路径。通过真实小媒体 fixture + 受控抽取替身完成 API 集成测试，并提供标记的真实 ffmpeg/Whisper 检查。

**依赖**：T401 → T402 → T403 → T404 → T405。

**Checkpoint**：上传→转写→声明与出处→摘要→查询闭环，媒体陈述不被冒充为已经核实的事实。

## Phase 6 — 跨能力验收与交付

- [ ] **T501** [FR-404, FR-407, FR-408] 实现并验证 api/routes/tasks.py 的 resume/cancel：按持久 kind 分派，不新建重复 task；整合三种能力的状态/错误映射及分页集合路由。HTTP 查询不可启动工作。
- [ ] **T502** [FR-403, FR-406, FR-407] 安全测试覆盖上传/设置/控制/下载的一致访问保护、Host/Origin 校验、SSRF 既有约束、秘密不回显、不进日志/时间线/模型上下文；默认本地绑定，非 loopback 显式保护。不把 CORS 当认证。
- [ ] **T503** [SC-101, SC-402, SC-403] 在 tests/integration/、tests/api/、tests/e2e/ 注入入队/阶段/完成崩溃，覆盖多业务并发、单工作区第二执行进程拒绝、幂等重试、取消及配置变更；无前端即可验收三条链路。
- [ ] **T504** [SC-102, SC-201, SC-202, SC-301] 在 tests/fixtures/ 固定人工标注变化对、六级核验断言与清晰/低质媒体样本；提供单独的质量评估入口，报告固定分母、版本、方向准确率、六级混淆矩阵、声明召回率及定位完整性。CI 不以实时网络或付费模型调用为硬断言。
- [ ] **T505** 更新 README.md、根 CONTEXT.md 和必要开发文档，说明 Module 所有权、启动/安全、配置生效点、单执行进程限制、恢复和前端延期；文档按已完成实现更新，不能提前声称全部支持。
- [ ] **T506** 使用 Python 3.12 的 collection-agent-pydantic conda 环境与 uv，执行 ruff format --check、ruff check、pyright、pytest、uv build；真实媒体依赖不可用时明确列出跳过，不把替身测试说成真实后端通过。

**依赖**：三条业务闭环及 T501–T504 完成后执行 T505–T506。新增三项特性不应破坏既有研究/会话测试；前端构建不作为本期完成门槛，因为本期不修改前端。

## 后续独立范围（不计本期完成）

- frontend/ 按新后端契约移除对应 mock、接入列表/轮询/错误展示；不反向要求领域恢复 accepted/disputed 媒体假裁决。
- 需要实时推送时基于既有 EventBus 增加通知；只有明确需要跨重连事件回放时才设计持久事件协议。
- 真实自定义站点检索、Cookie 注入、说话人分离、分布式执行分别提出独立需求。
