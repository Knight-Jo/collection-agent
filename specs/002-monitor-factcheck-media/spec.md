# Feature Specification: 持续监测 · 事实核验 · 媒体分析

**Created**: 2026-09-06
**Status**: Draft — architecture review revised 2026-09-06
**Review baseline**: 当前实现 `3fccc60`；本目录描述待实现行为，不代表代码已经具备这些保证。
**Related documents**: [数据模型](data-model.md) · [实施任务](tasks.md)

## 1. 目标与范围

在现有研究能力上增加持续监测（Monitor）、单条断言核验（FactCheck）和本地音视频分析（Media）。采用模块化单体：复用研究循环和材料能力，分别拥有业务规则与持久状态，不复制检索/抓取/抽取流水线。

本期交付 Python 应用层、FastAPI 端点及自动化测试；前端页面与 mock 替换不作为本期验收条件。现有 `frontend/` 仅是展示需求参考，不反向决定领域模型；不要求兼容 mock 的字段、枚举或模拟事件。CLI 与未来 Web 客户端都能调用同一应用能力，业务不得依赖 HTTP 或会话存在。

### 1.1 基线与需求优先级

- 实际可复用的是 `ResearchTask / Checkpoint / ResearchResult`、`EvidenceReview / EvidenceItem`、`Resource / NormalizedDocument / EvidenceBlock / Citation / MaterialScope`。
- spec 001 中的 `IntelTask / ResearchRun / ResearchCheckpoint / Fact / Evidence / SupportReview / StateStore` 不是当前可直接调用的实现，不能作为“已完成”的前置条件。
- `runtime_state`、`build_search_providers`、`SearchService.replace_providers` 已存在，但尚不等于具备本 spec 要求的配置快照、秘密脱敏及恢复保证；缺口必须纳入实施任务。
- 本 spec 对新增能力的状态、事务、恢复、凭证规则以本文为准；不隐式引入 spec 001 的 Action、RunWorkspace、committed manifest 等整套旧模型。
- 本期允许本地搜索 Key/Cookie 写入受限状态库，明确替代 spec 001“搜索密钥只读环境变量”的限制；模型密钥仍由部署配置管理。安全规则不能以“本地单用户”为由省略。

## 2. 架构约束（必须通过测试验收）

### 2.1 Module 与职责

| Module / 位置 | 对外 Interface 与职责 | 不得承担 |
|---|---|---|
| `monitoring/` | 创建、修改状态、触发、查询；调度规则、事实版本及基线比较 | 自建搜索循环、核验裁决、媒体解码 |
| `factcheck/` | 提交、查询、恢复；断言理解、证据评估与六级裁决 | 调度监测、把媒体陈述当作真值 |
| `media/` | 提交资源、查询、恢复；转写投影、声明提取与摘要 | 直接调用 ffmpeg/Whisper、自动联网核验 |
| `orchestration/` | 现有研究循环；提供带 scope、coverage、evidence、citations 的类型化评估结果 | 感知 Monitor/FactCheck/Media 或生成工作台投影 |
| `acquisition.py`、`extraction/`、`indexing/`、`context/` | 原始资源到可定位材料、索引及限定范围检索 | 业务裁决、监测基线 |
| `search/settings.py` | 类型化搜索配置读写、脱敏与运行快照 | 依赖 ConversationService，或在运行中替换其快照 |
| `storage/` | 分业务 SQLite Adapter；约束、事务、幂等提交 | 模型推理、搜索与调度策略 |
| `application.py` | 组合各业务 Interface；后台任务所有权、并发限制、恢复与关闭 | 实现差异算法、裁决、转写或 HTTP 投影 |
| `api/routes/` | 请求校验、HTTP 状态与响应映射 | SQL、模型调用、后台任务所有权 |
| `library.py` | 组合各业务只读摘要用于资料库展示 | 调度、写入、重新推导事实真伪 |
| `bootstrap.py` | 唯一组装点；构造并注入依赖、管理资源释放 | 业务规则 |

特性内模型放各自 `models.py`；`contracts/` 只放实际跨 Module 使用的契约，不是所有模型的集中仓库。复用现有具体实现，不预建通用 Repository、插件系统、工作流 DSL 或微服务。

依赖方向：`API/CLI → application → 业务 Module → 共享研究/材料能力与 storage Adapter`。存储可导入纯模型，但不能导入业务执行代码；模型不导入存储、HTTP 或组装代码。业务 Module 不互相调用；例如媒体声明的独立核验由调用方显式提交给 FactCheck，不由 Media 自动触发。

`ConversationService` 只保留会话相关行为；搜索配置和跨业务 library 投影必须移出。新增数据不得继续追加到 `MaterialStore`：按 `storage/monitoring.py`、`storage/factcheck.py`、`storage/media.py` 拆分。现有任务/预算/检查点操作提取到 `storage/tasks.py`，运行配置提取到 `storage/settings.py`；复用同一 SQLite 事务设施，不保留两套实现。无需为此重写无关会话存储。

### 2.2 复用方式与执行所有权

- Monitor 与 FactCheck 调用同一个研究循环获得类型化证据评估结果。把现有循环与报告生成之间的 Interface 明确化；普通调研继续生成报告，两个新调用方不必先生成无用报告。
- 禁止读取 `ConversationService._facts_from_evidence` 等展示辅助函数作为领域输入，也不解析报告自然语言或裸 JSON 来恢复事实。
- Media 直接复用接收本地 `Resource` 的 `AcquisitionPipeline`；不调用研究循环，不经过远程 fetch。新增声明抽取步骤使用已有模型调用、预算与执行限制。
- 一个后台执行所有者：应用层统一登记、限制并发、取消并等待执行结束。API 与调度器只提交已持久化的工作，不分别创建无人管理的后台任务。
- 沿用 `ResearchTask.task_id` 支撑材料归属、预算和 work item 检查点；每个 MonitorRun、FactCheck、MediaJob 绑定一个独立 task_id。Media 复用此执行记录并不意味着运行研究循环。
- 阶段状态与业务结果单独建模；若与 task 状态重复存储，须在同一事务转换并具有明确映射，不能形成两个互相矛盾的状态真相。

## 3. 用户场景与验收

### US1 — 创建、调度与暂停监测（P1）

用户设置主题、关注策略、核心问题、重点网站和结构化频率后创建 active 监测。

1. 创建成功后持久化配置及下一触发时间；非法频率明确拒绝，不静默回退。
2. 到点或手动触发先持久化独立 MonitorRun、task_id、配置快照，再执行。
3. 同一监测最多一个 queued/running/interrupted 运行；重复计划触发不创建新运行，重复手动请求返回原运行。其他监测与研究任务可以在全局并发限额内执行。
4. 暂停后不再创建计划运行；已运行工作继续。暂停状态下允许显式手动触发，且不改变计划状态。
5. 重启不能丢失 queued 运行；旧 running 转 interrupted，显式 resume 复用原运行。不得把“恢复”实现为创建第二个 task。

### US2 — 识别可追溯的增量变化（P1）

1. 首次完整运行以空基线生成 new_fact/new_source，并标记 initial baseline。
2. 后续运行只与启动时冻结的 baseline_run_id 比较。新增声明产生 new_fact；同一事实身份的值发生可证明变化才产生 changed_fact，并引用新旧不可变版本。
3. 文本改写不自动视为事实变化；无法确定身份时保守记录新增并披露匹配不确定性。本轮未检索到历史事实不代表删除或反驳。
4. new_source 以规范化站点 hostname 去重，不把同站不同 URL 或多个搜索 provider 当成新来源机构。
5. 变更集、累积事实/来源快照、运行完成状态及基线指针原子提交。partial/failed/cancelled/interrupted 不推进基线。
6. 没有实质变化时完成并记录空变化集，不生成虚构变化；重要性默认为 normal，high 必须带与关注策略相关的理由。

### US3 — 独立核验一条断言（P1）

1. 提交断言先创建 queued 记录并立即返回；理解、检索和裁决均在后台执行。
2. 明确理解、适用时间/范围及核验问题。含糊、不可证伪或纯观点可正常完成，但标记 not_checkable、原因与空 verdict。
3. 对可核验断言同时设计支持与反驳方向，不要求无反证时伪造反证。证据必须映射到本次任务 scope 内的 Citation 与原文片段。
4. 输出 supported / mostly_supported / insufficient / disputed / mostly_refuted / refuted 六级裁决之一，以及 high/medium/low 证据充分度、公开理由与限制。
5. 裁决不是把 supports/contradicts 机械映射为 accepted/disputed。重复转载不能提高独立来源数；证据不足、仅有无法追源的二手陈述或无法消解的实质冲突必须披露。
6. 查询可看到持久化步骤时间线。执行失败和用户取消不是“证据不足”的同义词；partial 结果不能伪装 completed。

### US4 — 分析上传的本地音视频（P1）

1. 用户上传文件字节；系统限制体积、验证实际媒体类型，存入现有资源仓并创建 queued MediaJob。不接受客户端指定任意服务端路径或远程 URL。
2. 转写生成带原始媒体毫秒半开区间的分段；说话人仅在后端真实提供时记录，否则为 null。首版不强制增加说话人分离模型。
3. 从材料提取可独立核验的声明，每条关联一个或多个分段。默认 verification_status=unverified，绝不因“说话人说了”而标为 accepted。
4. 媒体片段证明陈述出处，默认 relation=mentions；只有材料内确有支持/反驳内容时才用 supports/contradicts，且不表示已完成外部核验。
5. 结果包含摘要、分段、声明、出处和转写覆盖限制。无可用语音正常返回空结果及原因；解码/后端故障为 failed；部分可用结果为 partial。
6. 转码/切片的偏移还原到原始媒体，原始 Resource、artifact 和 block 引用不能丢失。Media 不自动读取监测/核验材料，也不自动联网。

## 4. Functional Requirements

### 持续监测

- **FR-101**: MUST 持久化名称、主题、策略、结构化频率、问题、重点网站、配置版本与 active/paused 状态。
- **FR-102**: MUST 用显式状态更新支持暂停/恢复；相同请求重复执行不反转状态。
- **FR-103**: MUST 支持计划与手动触发，冻结每次运行输入并满足单监测单活动运行及触发幂等。
- **FR-104**: MUST 复用研究循环，遵守既有网络安全、材料 scope、预算和并发限制。
- **FR-105**: MUST 按 US2 生成带版本引用的 new_fact/changed_fact/new_source 与重要性理由。
- **FR-106**: MUST 原子提交完成结果及基线；保留累积历史，失败/部分结果不得污染基线。

### 事实核验

- **FR-201**: MUST 接收非空单条断言，持久化理解、可核验性、原因与核验问题。
- **FR-202**: MUST 寻找正反方向证据，并校验 scope、引文与稳定来源定位。
- **FR-203**: MUST 使用唯一六级 Verdict 定义及三档充分度；not_checkable 的 verdict 必须为空。
- **FR-204**: MUST 从去重后的证据及来源分组计算独立来源数、一手来源数、反证数，未知归属不当作已确认独立。
- **FR-205**: MUST 复用研究证据评估，裁决由 FactCheck Module 负责，禁止复制研究循环或复用展示层二级映射。
- **FR-206**: MUST 持久化进度、时间线、终态、结论及错误；失败、部分完成、取消、中断可区分。

### 媒体分析

- **FR-301**: MUST 流式接收并限制上传文件，复用 ResourceStore，校验实际类型与解码能力。
- **FR-302**: MUST 返回有效时间区间，speaker 可空；不得虚构说话人或转写置信度。
- **FR-303**: MUST 提取未核验声明并关联一个或多个原始分段；不自动赋予真假裁决。
- **FR-304**: MUST 保留可验证的原文及 artifact/block/Locator 关联，区分材料内关系与独立核验结果。
- **FR-305**: MUST 按阶段持久化转写、声明、出处与摘要，并表达空结果、部分覆盖与失败。
- **FR-306**: MUST 通过现有 AcquisitionPipeline/ExtractionService 复用媒体后端，不新增平行媒体栈。

### 跨能力

- **FR-401**: MUST 复用现有 runtime_state 持久化运行配置，经校验后对后续新运行生效；运行中快照不热切换。
- **FR-402**: MUST 区分 provider 类型与界面分组；Exa/Brave/Tavily 的展示分组不派生第二套 provider 注册或调度机制。自定义站点只存配置时 MUST 标明不可执行。
- **FR-403**: MUST 将所有网页、转写、文件名与模型输出视为不可信输入；模型不能突破任务归属或执行材料内指令。
- **FR-404**: MUST 遵循第 5 节恢复规则，保留已提交状态；不承诺外部调用 exactly-once。
- **FR-405**: MUST 执行第 2 节依赖约束；新增业务不依赖 ConversationService，不向 MaterialStore/app.py 追加业务实现。
- **FR-406**: MUST 对 Key 与 Cookie 均只写不回显；响应、时间线、日志、配置快照和模型上下文不得出现明文。
- **FR-407**: MUST 提供第 6 节的类型化 FastAPI Interface、稳定错误码与有界列表；查询不触发工作。
- **FR-408**: MUST 由一个应用执行所有者管理工作区锁、任务并发及关闭；新增模型步骤纳入相同预算、deadline 与取消机制。

## 5. 调度、配置与恢复语义

### 调度

频率采用 daily/weekly + 本地时刻 + IANA 时区，不存自由文本 cron。时间戳统一存 UTC；本地日历计算下一次触发。重复本地时刻只运行一次，不存在的本地时刻顺延到当日首个有效时刻。最小周期为每日一次，不支持任意秒级调度。

计划运行以 (monitor_id, scheduled_for) 唯一；漏跑多期合并为最近一期的一次补跑，不无限追赶。创建运行与推进 next_run_at 在同一事务。运行占用期间不排无限队列；暂停/恢复从当前时间计算未来计划，不补暂停期间任务。手动触发不推进 next_run_at。

### 配置与凭证

搜索配置由独立 Module 管理：验证 → 构造可用配置 → 事务持久化版本 → 发布供新运行读取。失败不能留下“数据库已改、运行侧仍旧”的混合状态。新运行在入队时冻结非敏感有效配置及版本；不通过全局 replace_providers 改变运行中任务。对象可共享 HTTP 连接池，不要求每运行建立新连接池。

Key/Cookie 不进入快照，只引用配置中的凭证标识；内存中的已启动调用使用其原凭证，排队执行及重启后的恢复使用该标识当前值，记录实际配置版本但不保留秘密历史。因此冻结策略可复现，外部世界及凭证字节不承诺完全复现。

API 只返回 api_key_configured/cookie_configured 等布尔字段；支持明确替换/清空。SQLite 与备份按秘密文件保护，禁止提交，POSIX 限制文件及目录权限并在其他平台采取等价保护；首版不声称具备加密凭证保险库。Cookie 只存储、不注入请求。未实现的自定义搜索源不得显示为运行生效。

### 持久执行与恢复

单工作区仅允许一个执行进程持有工作区锁；多个 HTTP worker/实例共同调度不在本期范围，第二执行实例应拒绝启动。进程内 tick 可用标准库实现，可靠性来自 SQLite 约束与事务，而不是定时器。

- 入队：业务记录、task、幂等键与首条时间线原子写入；上传资源字节先成功写入，资源本身复用既有仓库提交机制。
- 执行：queued 原子认领为 running；状态、阶段与已完成阶段产物持久化。事务不得跨网络、模型或转码等待。
- 完成：结果、终态与时间线原子提交；Monitor 再包含基线推进。
- 重启：queued 重新登记；旧 running 转 interrupted；已完成不重跑。用户 resume 原 interrupted/可恢复 failed 记录，复用 task_id、快照、产物、已用预算与原绝对 deadline；不能恢复时明确拒绝，重新执行须显式新建。
- Monitor 恢复还必须原子认领 active_run_id，并确认当前基线仍等于冻结基线；已有其他活动运行或基线变化时返回冲突。可取消 interrupted 运行释放占用，不能让无法恢复的运行永久阻塞监测。
- 取消：queued 直接取消；running 发出取消请求，终态提交必须检查取消标记，取消后不得提交成功结果或监测基线。
- 数据库约束保证已提交业务记录不重复；外部请求和未提交模型调用可能重试，不承诺计费或网络副作用 exactly-once。

## 6. FastAPI Interface

API 模块使用 APIRouter 与类型化请求/响应；app.py 仅负责注册和 lifespan。读端点返回持久状态，默认轮询足够；现有 EventBus 可发 refetch 提示，但不作为数据真相，本期不新增持久 SSE 回放系统。

| 操作 | Interface | 语义 |
|---|---|---|
| 监测配置 | POST /api/monitors；PATCH /api/monitors/{id} | 创建 201；更新显式 status/配置，新配置只影响新运行 |
| 监测读取 | GET /api/monitors；GET /api/monitors/{id} | 详情不内嵌无限历史 |
| 监测运行 | POST /api/monitors/{id}/runs；GET /api/monitors/{id}/runs；GET /api/monitors/{id}/runs/{run_id} | 提交 202，返回稳定运行与 task_id；验证运行归属 |
| 事实核验 | POST /api/fact-checks；GET /api/fact-checks；GET /api/fact-checks/{id} | 提交 202；处理过程不占用提交请求 |
| 媒体分析 | POST /api/media；GET /api/media；GET /api/media/{id} | 上传成功后 202；multipart 文件字节，不接收服务器路径 |
| 执行控制 | POST /api/tasks/{task_id}/resume；POST /api/tasks/{task_id}/cancel | 应用层按持久 kind 分派，不能恢复已完成任务 |
| 资料库 | GET /api/library | 只读组合各 Module 摘要；各集合分页，不重复保存结果 |

创建监测、提交运行/核验/媒体要求客户端 Idempotency-Key（CLI 生成）；相同操作+key+输入返回原记录，不同输入同 key 返回 409。媒体用流式内容 hash 与分析参数比较输入；仅相同文件但不同 key 可以显式新建分析。分页集合（含证据、分段、事实、运行、时间线）使用 limit（1–100，默认 20）及稳定游标，按需提供嵌套集合读取路由，禁止详情无限嵌入大数组。

错误体统一包含 code/message/stage/retryable：422 输入校验、404 不存在、409 状态/幂等冲突、413 上传超限、415 不支持媒体类型；后台故障记录到任务，不伪装请求成功后的 completed。绑定 loopback 的单用户本地部署为本期安全基线；非 loopback 部署须有显式认证及可信 Host/Origin 保护，不新增账户体系。这明确收紧 spec 001 默认无认证监听所有地址的开发约定。设置、上传、取消和下载遵守同一保护，CORS 不能代替认证。

## 7. 边界与非目标

- 来源失效：保留成功材料并披露失败；执行是否 partial 由覆盖缺口决定，不因一个 provider 失败就丢弃全部结果。
- 无可核验证据：可核验断言返回 insufficient，而不可核验输入返回 not_checkable；两者不同。
- 媒体超大/损坏：拒绝或 failed；只清理本次未提交临时文件，不删除用户资源或共享 blob。限制媒体时长、转码超时及执行并发，不能只限制上传字节。
- 引用失效或越权：不纳入有效证据和来源计数，记录限制；不可仅凭 URL、列表序号或模型生成 ID 通过校验。
- 本期不做前端实现、推送通知渠道、分布式队列、任意 cron、自动网上音视频抓取、Cookie 注入、自定义站点真实检索、说话人身份识别或自动批量核验媒体声明。
- 不做细粒度数值置信度、内部推理链展示、多用户权限体系、授权绕过或高风险专业决策替代。
- 不迁移旧 mock 数据，不引入兼容层，不要求重写无关模块。

## 8. Success Criteria

- **SC-101**: 自动时钟测试覆盖创建、计划触发、手动触发、暂停/恢复、时区边界、漏跑合并；同监测不出现重复活动运行。
- **SC-102**: 预先固定至少 20 对人工标注基线/新增材料，变化分类正确率至少 80%；无变化样本不生成变化。指标按样本计，不按线上运行次数猜测。
- **SC-201**: 预先固定至少 30 条覆盖六级裁决和不可核验输入的人工标注断言，可核验样本裁决方向（支持/反驳/不足/冲突）正确率至少 80%；报告六级混淆矩阵，不声称六级准确率等同方向准确率。
- **SC-202**: 100% 有效核验证据通过 scope、引文与完整 Citation 定位校验；重复转载不增加确认独立来源数，无证据时不产生确定性结论。
- **SC-301**: 预先固定至少 5 段含清晰可核验陈述的音/视频，人工标注声明召回率至少 90%；100% 输出声明可定位到原始时间区间。低质量/无语音另列边界集，不从清晰样本分母中事后剔除失败。
- **SC-401**: 配置改动无需重启即影响新运行，已启动运行的非敏感策略快照不变；响应/日志/时间线/快照中秘密泄漏为零。
- **SC-402**: 在入队、阶段提交、完成提交前后注入崩溃，已提交业务结果无丢失/重复，恢复不重置预算/deadline，不污染监测基线。
- **SC-403**: 静态依赖测试验证第 2 节；三条流程既可经 Python Interface 测试，也可经 FastAPI 测试，无需创建会话或启动前端。

模型质量验收使用固定材料与记录的模型/配置版本，可独立运行；网络实时结果不作为确定性 CI 断言。结构、幂等、权限与引用完整性由离线自动化测试强制验证。

## 9. 本轮修订决策

1. 以实际代码为基线，撤销不存在的旧实体前置假设。
2. 三个业务 Module 自有模型与规则；拆开会话、搜索设置、资料库及新增存储职责。
3. 六级核验结论为唯一裁决体系；媒体声明保持未核验，speaker 可空。
4. 补充事实身份、不可变版本、原子基线、配置冻结、幂等与中断恢复契约。
5. Key 与 Cookie 一并脱敏；运行策略快照与秘密凭证分离。
6. 本期后端/FastAPI 可独立验收；前端接入和新增 SSE 实现延后。
