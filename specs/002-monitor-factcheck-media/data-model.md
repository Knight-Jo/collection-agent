# Data Model: 持续监测 · 事实核验 · 媒体分析

**Status**: Draft — revised 2026-09-06
**Authority**: 行为以 [spec.md](spec.md) 为准；本文件定义字段、不变量与事务，实施顺序见 [tasks.md](tasks.md)。
所有新增模型均为待实现，不把当前 UI 字典视为领域实体。

## 1. 复用与所有权

| 数据 | 模型归属 | 持久化 Adapter |
|---|---|---|
| ResearchTask、Checkpoint、预算与 work item 归属 | 现有 contracts/research.py | storage/tasks.py（从 MaterialStore 提取任务相关操作；材料操作仍在原处） |
| Resource、artifact、EvidenceBlock、Chunk、Citation、MaterialScope | 现有 contracts/ 与 extraction/ | 现有 MaterialStore / ResourceStore |
| ResearchAssessment（新增类型化评估结果） | contracts/research.py | 与 task 关联的评估快照，由研究循环提交 |
| Monitor、MonitorRun、FactVersion、MonitorChange | monitoring/models.py | storage/monitoring.py |
| FactCheck、FactEvidence、Verdict | factcheck/models.py | storage/factcheck.py |
| MediaJob、MediaSegment、MediaFact、MediaEvidence | media/models.py | storage/media.py |
| 搜索配置及版本 | search/settings.py | storage/settings.py，复用 runtime_state |

存储 Adapter 复用同一个 SqliteStore 连接与事务设施；复合写操作显式共享事务，不调用各自自动 commit 的 CRUD 拼装“原子提交”。SQL 只在 storage/ 内。只有数据库组装所有者负责关闭连接。没有第二数据库、通用实体仓库或新增全文/向量真相源。

## 2. 共享执行与证据契约

### 2.1 task 关联与状态

每个 MonitorRun、FactCheck、MediaJob 有唯一、不可变的 task_id，关联现有 tasks 表，材料和预算均以此归属。不创建虚假的 conversation；Media 使用 task 支撑执行、预算和 work items，但不调用研究循环。

扩展 tasks 的 kind 为 research/monitor/factcheck/media，供应用层恢复分派；既有任务回填 research。task 状态为唯一执行状态源，业务查询通过关联读取，不另存互相独立的 status。业务结果提交与 task 状态转换同一事务完成。

状态沿用 queued/running/completed/partial/failed/cancelled/interrupted：

- queued → running 或 cancelled。
- running → completed/partial/failed/cancelled/interrupted。
- interrupted 或可恢复 failed → queued，必须显式 resume；复用 task_id、输入快照、已用预算与原 deadline。
- interrupted/failed 也可显式转 cancelled，以结束恢复意图并释放监测占用；重复 cancel 不改变已有终态。
- completed/partial/cancelled 不原地重跑。需要新工作时使用新幂等键创建新记录。
- task 保存 cancel_requested；终态提交必须校验它，避免取消与成功提交竞争。
- 业务 phase 与状态不同：FactCheck 为 understanding/researching/adjudicating；Media 为 transcribing/analyzing；Monitor 为 researching/comparing。
- 错误保存 code/message/stage/retryable（对应 DomainError 的安全投影），另有 limitations；用户内容、秘密或内部路径不得拼入未脱敏错误。
- queued 时 started_at 为空；终态 finished_at 必填，时间统一 UTC aware datetime。恢复保存 attempt 编号与既有时间线，不擦除历史。

task 新增的 phase、cancel_requested、error、输入快照和阶段完成记录应类型化，不能依靠自由文本或内存 Task 推导。ResearchTask/Checkpoint 的既有材料、预算语义保留。

### 2.2 幂等与时间线

- 提交请求身份为 (operation, idempotency_key)，保存规范化 input_hash 与结果引用。monitor_create、monitor_run、factcheck_submit、media_submit 分属不同 operation。
- 同 key 同 input_hash 返回原对象；不同 input_hash 返回冲突，不覆盖旧输入。MonitorRun 的计划触发额外具有 (monitor_id, scheduled_for) 唯一约束。
- 媒体 input_hash 由内容 hash、媒体分析参数构成，展示文件名不影响分析身份；字节复用不等于任务自动去重。
- TimelineEntry：task_id、sequence、attempt、phase、state、summary、created_at；(task_id, sequence) 唯一，按序稳定分页。记录公开进度与依据，不记录模型内部推理链。
- 状态转换/阶段产物与对应时间线同事务写入；EventBus 通知在提交后发送，消息丢失不影响查询与恢复。

### 2.3 ResearchAssessment 与引用

ResearchAssessment 是研究循环向普通报告、Monitor、FactCheck 暴露的类型化结果，至少含 task_id、scope_id、coverage、evidence_review、citations、accepted_artifact_ids、limitations、stop_reason、usage。它不是新的执行引擎；报告生成消费同一结果。

EvidenceItem.citation_id 只在所属评估上下文中有意义，跨运行持久化必须保存可独立解析的完整 Citation：

- Citation 含 chunk_id、artifact_id、document_id、revision_id、resource_id、block_spans、locators；source_url 对本地材料可空。
- 入库前校验引用属于该 task 的固定 MaterialScope，chunk/blocks 属于同一 artifact，quote 为对应 block span 的原文；模型返回的 URL 和 citation_id 本身不是验证结果。
- 多 span 引文按结构存储，不能把不连续原文拼接后声称是连续引述；最小实现每个连续引述一条 Evidence。
- 同一 artifact 被重抽取产生新 artifact，不修改旧引用。显示标题/URL 是投影字段，不是引用主键。

## 3. Monitor

### Monitor

| Field | Type | Rules |
|---|---|---|
| monitor_id | string | 主键 |
| name / subject / strategy | string | 非空且有长度上限 |
| questions / websites | string[] | 有界列表；站点按现有 URL/域名校验规则验证 |
| schedule | MonitorSchedule | daily 或 weekly；local_time=HH:MM、timezone=IANA、weekly 另含 weekday=0..6 |
| status | active / paused | 显式设置；重复暂停不变成恢复 |
| config_version | int | 从 1 递增；改变业务配置才递增 |
| baseline_run_id | string / null | 最近完整提交运行；必须属于同一监测 |
| active_run_id | string / null | 唯一占用运行；queued/running/interrupted 期间持有 |
| next_run_at | timestamp / null | paused 为空；active 为未来计划时间或待处理漏跑时刻 |
| last_run_at | timestamp / null | 最近一次实际开始执行时间 |
| created_at / updated_at | timestamp | UTC |

调度采用 spec 第 5 节的时区、漏跑与暂停规则；禁用自由文本 frequency，不需要 cron 引擎。

### MonitorRun

| Field | Type | Rules |
|---|---|---|
| run_id / monitor_id | string | 主键 / 归属监测 |
| task_id | string | 唯一外键到 tasks；状态/时间/错误从 task 读取 |
| trigger | scheduled / manual | 显式区分 |
| scheduled_for | timestamp / null | scheduled 必填，manual 为空 |
| input_snapshot | object | Monitor 配置、config_version、搜索非敏感配置及版本、预算/抽取配置；无明文凭证 |
| baseline_run_id | string / null | 入队时冻结；不能在执行中改读最新值 |
| initial_baseline | bool | baseline_run_id 为空时为 true |
| summary / limitations | string / string[] | 空变化不等于失败 |

一个监测持有 active_run_id（可空），创建运行时原子占用，completed/partial/failed/cancelled 时释放；interrupted 保留占用直到恢复或取消。使用监测行上的占用字段和条件更新保证互斥。baseline_run_id/active_run_id 必须引用同一监测，事务中验证。resume 必须在同一事务重新认领占用并校验当前基线等于冻结基线；有其他活动运行或基线变化时拒绝，不覆盖新运行。

### FactVersion 与基线成员

这里是监测内部事实观察版本，不是全局“已证实事实”。

| Field | Type | Rules |
|---|---|---|
| fact_version_id | string | 不可变版本主键 |
| monitor_id / created_run_id | string | 归属与首次观察运行 |
| fact_key | string | 规范化 subject、predicate、scope 组成的结构化身份；不含可变 value，不用全文 hash 判断身份 |
| subject / predicate / scope / value | typed JSON | scope 保留时间、地域等限定；value 保留单位与类型 |
| statement | string | 便于阅读的声明 |
| previous_version_id | string / null | 同 monitor + fact_key 的旧版本；新增为空 |
| citations | Citation[] | 非空、校验通过的本运行证据 |

模型可提出身份匹配候选，但领域代码验证归属、结构和旧版本引用；身份不能确认则 new_fact 并记录 uncertainty，不能随意链接旧版本。只有同一 scope 下的值修订构成 changed_fact；不同观察日期的独立测量一般是不同 scope。格式化、同义改写和单位等价不能单凭字符串差异触发 changed_fact。

每个完整 MonitorRun 保存累积基线成员 (run_id, fact_key, fact_version_id) 与来源成员 (run_id, source_key)。新完整快照继承旧成员并合入经过验证的变化；未命中历史事实不移除成员。partial 的候选材料保留，但不发布成基线/正式变化。

source_key 首版使用规范化 hostname（小写、IDNA、去末尾点）；同域路径变化不新增来源，子域可不同。它表示站点，不声称代表独立出版机构。

### MonitorChange

| Field | Type | Rules |
|---|---|---|
| change_id / run_id | string | 稳定主键及所属运行 |
| kind | new_fact / changed_fact / new_source | 唯一枚举 |
| previous_version_id / current_version_id | string / null | new_fact 仅 current；changed_fact 两者均有且属于同一 fact_key |
| source_key | string / null | new_source 必填；另附至少一个定位到本运行材料的 Citation |
| importance / importance_reason | high / normal；string | high 必须说明与监测策略的关联 |
| summary / created_at | string / timestamp | 公开描述与 UTC 时间 |

同一 run + kind + 被变更对象只生成一条变化。完整运行的事实版本、基线成员、变化、task 完成状态、时间线、Monitor.baseline_run_id 与 active_run_id 更新必须原子提交；以冻结基线做条件更新，条件失配返回冲突，不覆盖新基线。

## 4. FactCheck

### FactCheck

| Field | Type | Rules |
|---|---|---|
| fact_check_id / task_id | string | 主键 / 唯一 task 外键 |
| claim | string | 非空单条断言，有长度上限 |
| input_snapshot | object | 非敏感搜索、模型/抽取、预算配置与版本；凭证只引用 |
| understanding / questions | string / string[] | 形成后持久化 |
| checkability | pending / checkable / not_checkable | not_checkable 必须有 reason |
| checkability_reason | string / null | 无法核验的公开说明 |
| verdict | Verdict / null | 完成可核验评估时必填；其他情形按下方规则 |
| evidence_sufficiency | high / medium / low / null | not_checkable 或尚未评估为空 |
| rationale / limitations | string / string[] | 公开证据依据，不是内部推理链 |
| independent_sources / primary_sources / counter_evidence | int >= 0 | 从有效去重证据导出，不采信模型直接填写的计数 |

状态和阶段从 task 获取。completed + checkable 必须有 verdict；completed + not_checkable 的 verdict/sufficiency 为空；partial 可保留裁决但必须标注部分覆盖与原因；failed/cancelled/interrupted 不新增正式最终裁决，可保留已提交阶段证据供恢复。

### Verdict（唯一六级枚举）

| 值 | 判定含义 |
|---|---|
| supported | 核心断言及其限定均有充分有效支持，无未解决的实质反证 |
| mostly_supported | 核心得到支持，次要限定仍有缺口；必须指出缺口 |
| insufficient | 有效证据不足以判断核心断言，包括只有无法追源的二手转述 |
| disputed | 核心断言存在有效且无法消解的实质正反冲突 |
| mostly_refuted | 核心受到有力反驳，次要限定仍未解决 |
| refuted | 核心断言及关键限定有充分有效反驳，无未解决的实质支持 |

裁决消费同一 scope 的正反证据及覆盖评估。先剔除无效引用，再判断证据不足/实质冲突，最后形成方向与限定；不能仅按证据票数、来源域名数或 relation 映射。high/medium/low 描述评估充分度，不是断言为真的概率。

### FactEvidence

| Field | Type | Rules |
|---|---|---|
| evidence_id / fact_check_id | string | 主键 / 所属核验 |
| relation | supports / contradicts | 相对经过理解与限定的 claim |
| quote / citation | string / Citation | 校验过的连续引文及完整定位 |
| publisher_key | string / null | 来源出版者归组，不等同 hostname |
| independence_group | string / null | 共同原始报道/数据归为一组；无法判定独立性为空 |
| source_nature | primary / secondary / unknown | 相对被核验主张判断 |
| attribution_basis | string | 可追溯的归组/一手性依据，不能无依据猜测 |
| source_title | string | 展示名；URL 从 citation 获取 |

同一核验的相同 artifact + block span + relation 去重。independent_sources 为有依据的不同 independence_group 数，primary_sources 为其中存在 primary 证据的组数（不超过 independent_sources）；counter_evidence 为去重后的 contradicts 证据条数，不等于反方机构数。未知来源保留展示但不增加确认独立计数。

## 5. Media

### MediaJob

| Field | Type | Rules |
|---|---|---|
| media_job_id / task_id | string | 主键 / 唯一 task 外键 |
| resource_id | string | 上传原始资源，沿用 ResourceStore；不得只存 filename |
| artifact_id | string / null | 抽取成功后绑定不可变 artifact |
| filename | string | 仅安全展示名，不决定落盘路径 |
| kind / media_type / size_bytes | audio 或 video / string / int > 0 | 实际探测类型与上传字节数 |
| duration_ms | int > 0 / null | 探测成功后保存；用于时长限额及区间校验 |
| input_snapshot | object | 抽取/分析配置与版本，预算、deadline；无需搜索配置 |
| summary / limitations | string / string[] | 空语音/低质量/部分覆盖要明确 |
| coverage | CoverageUnit[] | 复用抽取覆盖信息，分页或有界摘要 |

### MediaSegment

MediaSegment 是 artifact 中语音/字幕 EvidenceBlock 的只读投影，不另存第二份可变转写正文。

| Field | Type | Rules |
|---|---|---|
| segment_id | string | 对 media_job_id + artifact_id + block_id 稳定 |
| media_job_id / artifact_id / block_id | string | 必须属于同一任务资源 |
| locator | Locator | start_ms/end_ms 成对存在，0 <= start < end <= 原始 duration_ms |
| text | string | 原始 block.text，不被摘要覆盖 |
| speaker | string / null | 仅采信后端元数据；当前 WhisperBackend 无说话人输出时为空 |
| confidence | float 0..1 / null | 后端未提供则空，不推算伪置信度 |

有重叠语音时允许时间区间重叠，排序按起始时刻和稳定 ID。所有视频转音频与切片偏移必须还原原始媒体时间；不把转码片段的局部时间直接暴露。

### MediaFact 与 MediaEvidence

| Entity | Fields | Rules |
|---|---|---|
| MediaFact | fact_id、media_job_id、statement、segment_ids[]、verification_status=unverified | segment_ids 非空，支持跨分段；不提供 accepted/disputed 假裁决 |
| MediaEvidence | evidence_id、media_job_id、fact_id、segment_id、artifact_id、block_span、locator、quote、relation | fact/segment 必须同属 job；block_span 用既有 BlockSpan 类型并对应 segment.block_id |

relation 为 mentions/supports/contradicts，仅表达材料内出处或关系。每条 MediaEvidence 对应一个连续引述；跨分段声明可有多条出处，不伪造一个连续大时间区间。quote 校验对应 block_span 原文，locator 落在该 segment 内；原始 Resource 经 job/artifact 可追溯，不要求先生成搜索用 Chunk 才能证明出处。

独立外部核验在本期由调用方另外提交 FactCheck。MediaFact 不存伪造 FactCheck verdict，也不自动产生跨业务调用或预算消耗。

## 6. 配置、SQLite 与事务清单

### 搜索配置

继续使用已有 runtime_state 表；search/settings.py 提供校验过的类型化操作，HTTP 不暴露任意 KV 写入。

- 保留现有 search_source:<id>、ai_tool:<id>、custom_sources 数据，增加递增配置 revision；单次配置更新和 revision 在一个事务内。
- provider 展示分组与执行注册分离，自定义仅配置记录含 executable=false。
- effective snapshot 包含启用 provider、查询限制、配置 revision 与凭证引用；不含 api_key/cookies 明文。
- API 对 Key/Cookie 仅返回 configured 布尔值。写入支持替换/清空；未填写不误清空，掩码文本不得当秘密写回。
- 构造失败时不发布无效配置；工作入队读取已提交 revision 的一致快照。运行前获取凭证当前值，恢复不保存旧秘密历史。

### 迁移与约束

新增下一序号迁移（当前预计 005_workspace_extensions.sql），并更新 storage/sqlite.py 的显式 MIGRATIONS 注册。不能只创建文件而遗漏注册，已有 004_runtime_state.sql 不重复创建。

需要的持久化集合：monitors、monitor_runs、monitor_fact_versions、monitor_baseline_facts、monitor_baseline_sources、monitor_changes、fact_checks、fact_evidence、media_jobs、media_facts、media_evidence、task_timeline、提交幂等记录，以及现有 tasks/research_results 的必要扩展。MediaSegment 从既有 blocks 投影，不另建转写副本表。

主键、外键、计划触发唯一性、同 key 输入一致性和版本不可变由约束与事务保障；JSON 仅用于经过模型验证的快照、限定结构与覆盖信息，不能用一个任意 payload 替代所有归属/唯一约束。跨表同任务归属不能只靠 UUID 难猜，Adapter 的写入 Interface 必须验证。

必须覆盖的事务：

1. 注册提交幂等身份 + 创建 task + 创建业务记录 + 入队时间线；MonitorRun 同时认领 active_run_id，只有计划触发推进计划时刻。创建 Monitor 配置本身不创建执行 task。
2. 阶段产物 + task phase + 时间线；恢复只复用已提交且与快照一致的阶段。
3. 终态结果 + task 状态 + 时间线；Monitor 完整成功另提交变化、累积基线及指针。
4. 配置多项修改 + revision；原子发布新运行可见版本。
5. 取消请求与终态提交条件竞争；取消不能晚于成功被悄悄覆盖。

上传 blob 先写盘，之后事务关联 job；崩溃可留下没有 job 引用的资源，不对用户可见为成功任务。只清理明确属于未提交上传的临时文件，不删除共享内容仓。迁移不得删除既有资源、研究结果或本地配置。
