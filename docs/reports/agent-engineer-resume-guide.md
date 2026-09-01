# AI 应用 / Agent 工程师项目经历与面试手册

本文用于将“情报调研智能体”整理为 AI 应用 / Agent 工程师方向的简历项目经历，并提供自我介绍、面试问答、扩展规划和学习路线。

文中的“已实现”均以当前仓库代码和实验记录为依据；代表性性能数据来自特定对照实验，不等同于所有主题下的生产 SLA。尚未落地的能力统一标为“规划”，面试时不要表述为已经上线。

---

## 一、项目定位

### 1.1 推荐项目名称

**基于 PydanticAI 的多轮深度情报调研智能体**

英文名称可写为：

**Evidence-Grounded Deep Research Agent with PydanticAI**

### 1.2 一句话介绍

面向公开互联网信息调研，构建能够围绕用户主题自主规划、多源检索、深度采集、证据核验并持续对话的 Agent 系统，最终生成带可追溯引用、覆盖评估和明确局限的结构化调研报告。

### 1.3 技术栈

```text
Python 3.12 / PydanticAI / Pydantic / FastAPI / SQLite / httpx
React / TypeScript / SSE / Bun
Exa / Brave / Tavily / SearXNG / 百度 / 新闻与学术搜索
PyMuPDF / Playwright / Tesseract / FFmpeg / faster-whisper
JSONL Trajectory / pytest / pyright / Ruff / Biome
```

### 1.4 适合强调的岗位能力

- Agent 工作流设计，而不仅是调用一次大模型 API；
- 多轮对话、长期任务状态和上下文窗口管理；
- Search、Crawl、RAG 与证据治理的完整链路；
- Pydantic 结构化输出和确定性业务门控；
- 异步任务、取消、恢复、幂等和版本化报告；
- LLM 应用可观测性、评测、安全和工程化交付。

---

## 二、可直接放入简历的项目描述

### 2.1 精简版：适合一页简历

**基于 PydanticAI 的多轮深度情报调研智能体**｜核心开发

`Python` `PydanticAI` `FastAPI` `SQLite` `React` `SSE` `Playwright`

- 设计并实现面向公开信息调研的 Agent 工作流，将主题规划、多源搜索、网页及附件采集、事实抽取、证据审核、覆盖评估和报告生成串联为可恢复的完整闭环。
- 建立 `Document → Fact → Evidence → SupportReview → Coverage → Report` 证据链，通过精确引文、内容哈希、独立来源组和确定性质量门控，降低模型幻觉进入正式结论的风险。
- 实现多轮对话与长期任务状态管理，以 SQLite 持久状态作为事实来源，通过增量摘要、Top-K 检索、有界消息历史和动态 `CONTEXT_SNAPSHOT` 支撑 16K—256K 上下文配置。
- 将 PydanticAI 流式事件和业务状态更新映射为统一 JSONL 轨迹，形成 L1 技术、L2 决策、L3 结果三层可观测体系，支持 Tool Call 因果回放、Token/耗时分析和失败定位。
- 针对深层链接噪声和单源结论设计相关性及交叉验证门控；代表性实验中无关深层资源由 48 条降至 0，任务耗时下降 74%、Token 消耗下降 53%，双源率最高由 0 提升至 86.7%。

### 2.2 标准版：适合两页简历或项目主页

**项目背景：** 通用联网问答通常直接基于搜索摘要生成答案，缺少原文归档、证据定位、交叉验证和长任务恢复能力。本项目将大模型定位为调研组织者，把事实可信度、状态提交和报告完整性交给确定性系统约束。

**个人职责与成果：**

1. 基于 PydanticAI 设计工具型 Research Agent，支持多轮自主决策，并通过结构化工具参数和 Pydantic 模型约束 Agent 与业务系统之间的交互。
2. 设计 Conversation、IntelTask、ResearchRun、RunWorkspace、Checkpoint、CommittedResearchSnapshot 和 ReportVersion 等领域对象，实现“运行暂存—原子提交—固定快照—版本报告”的生命周期。
3. 接入 Exa、Brave、Tavily、SearXNG、百度及新闻、学术、开源软件等检索来源；构建查询矩阵、来源角色、URL 规范化、域名公平性和缺口驱动补源策略。
4. 实现 HTML、PDF、Office、图片 OCR、音视频转写与 JavaScript 动态页面处理，并加入 robots.txt、SSRF 防护、DNS pinning、逐跳重定向校验、并发及下载预算。
5. 构建证据治理链路：搜索结果仅作为线索，材料归档后提取原子事实和逐字引文，再由隔离审核模型判断 `full / partial / irrelevant / contradicts`，最后计算问题覆盖和停止条件。
6. 实现对话与研究两类记忆：完整消息和研究资产持久化，模型侧仅注入增量摘要、最近消息、已提交证据检索结果及有界状态快照，避免上下文无限增长和半成品证据泄漏。
7. 建设 FastAPI + React 本地工作台，使用 SSE 展示调研阶段、工具动作和覆盖进度；保留 `/api/runs` 作为 ResearchRun 兼容适配器，避免维护第二套运行状态机。
8. 建立 append-only JSONL 调研轨迹和自动分析脚本，统一记录模型调用、决策、动作、观察、状态变化与运行结果；后端累计 600+ 项自动化测试，前端 29 项测试，并接入类型、格式和构建门禁。

### 2.3 招聘平台短描述

独立设计并实现基于 PydanticAI 的深度调研 Agent。系统支持围绕主题自主规划、多搜索源检索、网页/PDF/Office/音视频采集、事实与引文审核、问题覆盖判断、多轮续研和版本化报告；使用 SQLite 持久状态、有界上下文和 JSONL 轨迹解决长任务记忆、恢复与可观测问题，并通过相关性及双源门控显著降低无效采集和单源结论。

### 2.4 英文简历版本

**Evidence-Grounded Deep Research Agent | Core Developer**

- Built a multi-turn research agent with PydanticAI, covering planning, multi-provider search, recursive collection, evidence review, coverage evaluation, and versioned report generation.
- Designed a durable lifecycle around Conversation, ResearchRun, staging workspace, atomic checkpoints, and committed snapshots, enabling cancellation, recovery, and consistent report publication.
- Implemented bounded agent memory using incremental conversation summaries, committed-state retrieval, compact message history, and deterministic context snapshots for configurable 16K–256K context windows.
- Introduced an evidence pipeline from archived documents to atomic facts, exact quotations, semantic support reviews, source independence checks, and coverage gates to prevent unsupported claims from entering reports.
- Added a three-layer JSONL trajectory for model/tool telemetry, business decisions, and outcome evaluation; representative experiments reduced irrelevant deep links from 48 to 0, runtime by 74%, token usage by 53%, and increased dual-source coverage up to 86.7%.

---

## 三、项目成果应如何表达

### 3.1 建议使用的成果口径

| 类别 | 推荐表达 | 依据与边界 |
| --- | --- | --- |
| 完整链路 | 完成从主题输入到证据化报告的端到端闭环 | 已有 CLI、API、Web 和真实任务产物 |
| 测试规模 | 建立 600+ 后端测试和 29 项前端测试 | 表示工程保障规模，不等于测试覆盖率 |
| 采集质量 | 代表性实验中无关深层资源 48→0 | 仅指深层链接相关性门控实验 |
| 效率 | 代表性实验中耗时下降 74%、Token 下降 53% | 是优化前后对照结果，不是所有任务平均值 |
| 证据质量 | 双源率最高由 0 提升至 86.7% | 是交叉验证门控专项实验结果 |
| 来源多样性 | 有效域数量由 5.73 提升至 7.89，政府来源 2→7 | 是指定实验指标，不是全局累计量 |
| 产品状态 | 已达到内部演示和受控试用条件 | 尚未完成生产级大样本验收 |

### 3.2 不建议使用的表述

以下说法虽然听起来更强，但没有当前证据支撑：

- “已服务大量企业用户”或“已在生产环境大规模运行”；
- “消除模型幻觉”或“结论准确率达到 99%”；
- “所有任务耗时降低 74%”；
- “实现了分布式多 Agent 平台”；
- “使用 LangGraph、向量数据库、OpenTelemetry”，当前项目并未使用这些组件；
- “实现 256K 有效记忆”，实际是支持对应上下文配置，并不代表模型能无损利用全部信息。

### 3.3 面试时的稳妥说法

> 这是一个完成了真实联网实验和内部工作台的工程项目，目前达到受控试用阶段。我的指标来自固定实验的前后对照，所以我会说明实验条件，不把它外推成生产 SLA。生产化还需要补充跨主题基准、故障注入、统一资源预算和多用户隔离。

这段话不会削弱项目，反而能够体现对评测边界和工程成熟度的理解。

---

## 四、自我介绍中的项目讲述

### 4.1 30 秒电梯版

> 我主要做了一个基于 PydanticAI 的深度情报调研 Agent。它不是搜索后直接生成答案，而是把主题拆成调查方向，通过多个国内外搜索源采集网页、PDF 和多媒体材料，再把原文转成事实、精确引文和审核记录，只有满足覆盖与来源规则的内容才能进入报告。项目中我重点解决了长任务状态恢复、上下文压缩、证据可信度和可观测性问题，并完成了 FastAPI、React 工作台和真实联网实验。

### 4.2 1 分钟面试版

> 我做的项目是一个面向公开信息调研的多轮 Agent。最初的问题是，普通联网问答容易把搜索摘要直接当事实，而且长任务一旦中断就无法恢复。我的方案是把 PydanticAI 作为推理和工具编排层，同时用确定性系统管理事实、状态和质量门槛。
>
> 整条链路包括主题规划、多源搜索、网页及附件抓取、事实和精确引文抽取、独立审核、覆盖评估以及版本化报告。运行过程中，新资产先进入 RunWorkspace，只有 checkpoint 校验通过后才提交到 SQLite 和文件资产，因此取消或失败不会污染已确认结果。模型上下文也不是无限重放聊天历史，而是由增量摘要、最近消息、已提交证据检索和状态快照组成。
>
> 在代表性实验里，深层链接门控将无关资源从 48 条降到 0，同时耗时下降 74%、Token 下降 53%；交叉验证门控把双源率最高提升到 86.7%。项目目前达到内部试用阶段，下一步会补生产级基准、统一预算和 OTel 性能链路。

### 4.3 3 分钟深度版

> 这个项目的背景是，情报调研和普通问答的目标不同。普通问答追求快速给出一个看起来合理的答案，正式调研则要求说明信息从哪里来、是否读过原文、有没有独立验证、哪些问题还没查清。所以我把系统设计成 Agent 编排加确定性质量门控，而不是让模型独自控制全部流程。
>
> 第一层是信息发现与采集。系统同时支持 Exa、Brave、Tavily、SearXNG、百度，以及新闻、学术和开源软件等垂直入口。搜索结果只作为候选线索，后续还要抓取并归档原文。采集层支持普通 HTML、PDF、Office、OCR、音视频转写和 JavaScript 动态页面，并加入 SSRF、防重定向绕过、robots、并发和下载预算。
>
> 第二层是证据治理。每条结论先拆成原子 Fact，再绑定原文逐字 Evidence 和行号或时间戳，之后由隔离的审核模型判断支持程度。Coverage 会综合问题覆盖、独立来源、冲突和无进展轮次，决定继续补源、带缺口生成报告，还是正常停止。报告还绑定 coverage fingerprint 和文档哈希，底层证据变化后旧报告不能被误当成当前结果。
>
> 第三层是多轮状态和记忆。Conversation 是交互入口，IntelTask 是业务核心，一次续研对应一个 ResearchRun。新资产先暂存在 RunWorkspace，通过 Checkpoint 原子提交形成 CommittedResearchSnapshot。对话只能读取已提交资产，避免运行中的半成品泄漏。模型侧则使用增量摘要、有界历史和动态状态快照，进程重启后从持久状态重新构造上下文。
>
> 最后是可观测性。我把 PydanticAI 的流式工具事件和业务状态变化映射到统一 JSONL，按 L1 技术执行、L2 决策原因、L3 结果评测三个层次分析。这样不仅知道工具是否失败，还能回答为什么发起第 17 次搜索、它解决了哪个问题、覆盖度是否真的提升。
>
> 这个项目让我形成的主要认识是：Agent 工程的难点不是多写几个 Prompt，而是让概率模型运行在可验证、可恢复、可评测的确定性系统里。当前项目已能真实运行，但生产化还需要跨主题基准、故障注入、多用户隔离以及更完整的资源预算。

### 4.4 用 STAR 结构回答“你做了什么”

**Situation：** 联网大模型能够快速回答，但难以满足正式调研的原文留存、证据复核、覆盖判断和任务恢复要求。

**Task：** 构建一个能够持续调研、保存证据、披露缺口并生成可审计报告的本地 Agent 系统。

**Action：** 使用 PydanticAI 实现工具编排；设计持久化 ResearchRun 和 checkpoint；建立多源搜索、递归采集、证据审核、Coverage 门控、有界上下文和三层运行轨迹。

**Result：** 打通端到端真实任务链路；代表性实验中降低无效采集和资源消耗，并显著提升独立来源覆盖；形成 CLI、API、Web 工作台、自动化测试和实验评测体系。

---

## 五、项目架构的面试讲法

### 5.1 一张图讲清主流程

```text
用户主题 / 多轮指令
        │
        ▼
Conversation ── Task ── ResearchRun
                        │
                        ▼
              PydanticAI Agent 编排
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       多源搜索       安全采集       内容提取
          │             │             │
          └─────────────┴─────────────┘
                        ▼
Document → Fact → Evidence → Review → Coverage
                        │
                        ▼
          Checkpoint / Committed Snapshot
                        │
                        ▼
              Versioned Research Report

旁路：PydanticAI Events + Business Events → trace.jsonl
```

### 5.2 最值得讲的四个设计点

#### 设计点一：模型负责决策，系统负责约束

模型适合根据当前证据缺口选择下一步搜索或阅读动作，但不适合独自判断事务提交、资源预算和报告有效性。因此工具参数使用 Pydantic 校验，关键阶段转换、coverage gate、哈希校验和提交规则由普通 Python 代码执行。

#### 设计点二：把模型上下文和业务事实分开

模型消息历史只是本轮推理材料；SQLite、原始文件、Fact 和 Evidence 才是长期事实。上下文丢失可以从持久状态重建，模型产生过的错误描述也不会自动成为系统事实。

#### 设计点三：Run 暂存和已提交快照隔离

运行中的资产先写入工作区，checkpoint 通过后才形成新版本。研究 Agent 可以看到自己的暂存内容，对话 Agent 只能读取 committed snapshot。这个边界解决失败污染、并发可见性和报告一致性问题。

#### 设计点四：轨迹是旁路审计，不是第二套状态源

JSONL 只记录发生过什么，不能重建业务真相。业务状态仍由 SQLite 和文件资产管理，避免引入完整 Event Sourcing 的一致性成本。

---

## 六、高频面试问题与参考回答

### 6.1 为什么使用 PydanticAI，而不是 LangChain 或 LangGraph？

当前系统的核心需求是类型安全的工具调用、结构化输出、依赖注入、消息历史处理和流式事件，PydanticAI 已经能够覆盖，而且与现有 Pydantic 领域模型结合自然。任务流程虽然长，但主要状态机由业务代码和 SQLite 明确维护，没有必须使用图框架才能表达的复杂分支。

LangGraph 的优势是显式图节点、checkpoint、人工中断和复杂多 Agent 编排。如果未来出现大量可视化分支、跨 Agent 协作和节点级重放，迁移才有收益。现在迁移会同时保留现有业务状态机和框架状态机，形成双重状态源，成本大于价值。

### 6.2 Agent 和普通工作流有什么区别？

确定性工作流预先固定每一步，Agent 会根据当前任务状态和工具结果动态选择下一动作。本项目采用混合方式：查询、阅读和补源由 Agent 决策；安全、预算、证据准入、阶段转换和停止条件由确定性代码控制。这样保留灵活性，又不把可靠性完全交给模型。

### 6.3 如何控制模型幻觉？

不是只靠 Prompt，而是设置数据和流程门控：搜索摘要不能成为正式证据；报告结论必须关联 Fact、逐字 Evidence、原文 locator 和审核结果；重大事实需要独立来源组；冲突必须披露；coverage 不足时输出 `with_gaps`，不能用自然语言补齐。模型仍可能犯错，但错误进入正式报告的路径被显著收窄。

### 6.4 为什么要把主题拆成关键问题？这种方法有什么局限？

拆解能够建立覆盖基线、分配来源角色并判断停止，但如果一开始的问题过细或方向错误，系统会机械地为错误问题补证。当前改进是把固定问题视为调查框架而不是报告目录，再增加 investigation item 和缺口驱动发现；找到新事实、冲突或关键实体后可以扩展调查项，但用户确认的核心问题仍保持稳定，便于验收。

### 6.5 系统的“记忆”是如何实现的？

记忆不是一个单独的 Memory 类，而是五类状态：SQLite 中的业务长期记忆、Conversation 消息与增量摘要、单次 Run 的 PydanticAI 历史、已提交研究快照，以及进程内临时任务。每次调用只构建有界上下文，事实从已提交状态检索，进程重启后由持久状态重建运行，而不是依赖模型记住全部历史。

### 6.6 如何避免上下文窗口无限增长？

对话侧使用“增量摘要 + 最近 10 条消息 + Top 8 检索结果”；研究侧使用 `ProcessHistory` 删除旧快照、保留必要工具交换，并注入最大 16 KB 的确定性 `CONTEXT_SNAPSHOT`。历史预算使用保守字节估算，为系统提示、工具定义和输出保留空间。

### 6.7 为什么当前没有使用向量数据库？

当前是单机、单任务规模，已提交证据和文档数量有限，词法 Top-K 检索实现更简单、可解释、部署成本低。只有当单任务达到数千文档、P95 延迟超标，或标注集证明 Recall@8 不足时，才会在现有 `TaskRetriever` seam 后增加 hybrid retrieval，而不是让向量库成为新的事实来源。

### 6.8 多轮对话和 ResearchRun 是什么关系？

Conversation 负责用户交互，IntelTask 保存长期调研目标，一次初始调研或续研对应一个 ResearchRun。对话可以查询已有证据，也可以产生 Continue Research 等 ActionRequest。ResearchRun 完成并提交 checkpoint 后，新资产才对后续对话可见。

### 6.9 为什么保留 `/api/runs`？

它用于兼容旧前端和无界面单主题调用，但内部只是创建 Conversation、Task 和 ResearchRun 的 Adapter。它不拥有独立 RunRegistry、事件状态和恢复逻辑，避免两套运行生命周期长期漂移。

### 6.10 如何保证任务取消和恢复的一致性？

权威状态持久化到 SQLite，进程内只保存 asyncio Task、取消令牌和订阅者。取消或失败时未提交工作区不会改变 committed state；重启后 runtime 根据 Message attempt、ActionRequest 和 ResearchRun 状态重新调度允许恢复的工作。不会尝试从模型生成到一半的 token 继续，而是从最近持久边界重新执行。

### 6.11 如何防止重复执行？

用户消息可以通过 client message ID 幂等；ActionRequest、ResearchRun 和 checkpoint 都有独立身份及状态转换；工具输出和 URL 做任务内去重；提交时校验前置版本。对于失败重试，创建可追踪的新尝试，而不是悄悄覆盖旧运行记录。

### 6.12 Coverage 是怎么计算的？

Coverage 以核心问题为单位，综合有效 Fact 数、审核通过 Evidence、独立来源组、来源质量、时效、冲突和待审核项，输出 covered、partial、gap 或 conflict 等状态。同时记录 gap score 和 no-progress rounds，用于继续补源或停止。它是由权威证据派生的快照，不是模型自由生成的分数。

### 6.13 为什么生成报告前必须运行 `coverage_eval`？

报告必须绑定当前 coverage fingerprint。否则新证据或审核结果变化后，报告可能引用已经失效的状态。前端可以自动继续调研并触发覆盖评估，但后端门禁不能取消，因为它保护的是报告与证据快照的一致性。

### 6.14 搜索广度如何控制？

通过“问题 × 来源角色 × 查询变体”的矩阵产生候选查询，覆盖官网限定、附件、中英文、结构化数据和反证；再结合新闻、学术、软件等垂直 Provider。结果侧做 URL 规范化、同任务去重、单域限额和一手来源优先，避免把更多 URL 误认为更高覆盖。

### 6.15 如何处理动态网页和非 HTML 材料？

静态提取不足时按需使用隔离 Chromium，不默认让全部网页经过浏览器。PDF 使用 PyMuPDF，Office 使用对应解析库或 LibreOffice，图片使用 Tesseract，音视频使用 FFmpeg 和 faster-whisper。处理器缺失时保留原件并标记正文不可用，不允许空内容进入证据链。

### 6.16 抓取公开互联网有哪些安全问题？

主要风险是 SSRF、DNS rebinding、恶意重定向、超大文件、压缩炸弹、无限递归和敏感参数泄漏。系统对目标进行地址校验和 DNS pinning，逐跳检查重定向，遵守 robots.txt，并设置内容类型、文件大小、总下载量、深度、并发和域名速率限制；日志和轨迹对 URL 密钥及敏感字段脱敏。

### 6.17 可观测性为什么分成三层？

L1 回答模型和工具实际执行了什么，L2 回答为什么搜索、抓取或停止，L3 回答资源投入是否带来覆盖提升。只记录 Tool Call 无法解释业务目的，只记录最终报告又无法定位中间问题。三层都从同一 JSONL 事件流派生，避免维护多个统计真相。

### 6.18 为什么没有直接使用 Logfire 或 OpenTelemetry？

当前最需要解决的是业务轨迹，而不是跨服务调用树。PydanticAI 流式事件加自有 Recorder 已经能回答模型、工具、决策和覆盖变化问题，因此首版不增加外部后端。出现多服务部署和跨进程性能定位需求后，再接标准 OTel exporter；Logfire 只能作为可选展示后端。

### 6.19 性能优化是怎么做的？

主要不是换更快模型，而是减少无价值动作：深层链接相关性门控、搜索转抓取门禁、URL 去重、按域并发、增量摘要、上下文裁剪和结果摘要化。代表性实验中，相关性门控在提升有效语料比例的同时降低了 74% 耗时和 53% Token，说明 Agent 性能优化首先要减少无效上下文和无效工具调用。

### 6.20 如何评估一个 Research Agent？

不能只评估最终文风。至少包含问题覆盖率、来源角色覆盖、独立来源比例、证据支持率、冲突披露、关键来源召回、报告引用完整性、上下文稳定性、恢复成功率、耗时、Token 和工具成功率。模型对比应固定主题、预算、Provider 和材料集，多次运行并结合盲审。

### 6.21 当前最大不足是什么？

第一，跨主题和不同模型下的量化样本仍不足；第二，审核模型调用与主 Agent 的统一预算尚需加强；第三，真实 JS、Office、音视频和冲突样本还需扩充；第四，当前是本地单用户架构，没有认证、租户隔离和分布式执行。这些都是从受控试用走向生产验收的主要工作。

### 6.22 如果让你重新做一次，会改什么？

会更早定义一套小而稳定的 Benchmark 和轨迹 schema，再迭代 Agent 策略。早期如果只看最终报告，很难判断问题来自搜索召回、材料提取、证据审核还是模型决策。另一方面，我仍会保留当前“PydanticAI + 明确业务状态机”的轻量架构，不会一开始就引入 LangGraph、向量数据库和分布式队列。

### 6.23 你在项目中的核心贡献是什么？

回答时不要罗列所有文件，建议概括成三点：

1. 将一次性搜索 Agent 重构为 Conversation-first、可持续续研的任务系统；
2. 建立从原始材料到审核证据再到固定报告快照的可信链路；
3. 通过上下文管理、生命周期恢复和三层轨迹把长任务变成可运行、可解释、可评测的工程系统。

如果某部分由团队其他成员负责，应按真实分工调整，避免把团队成果全部描述为个人独立实现。

---

## 七、可扩展方向

以下内容均是合理规划，不应在简历中写成已经完成。

### 7.1 近期：生产可靠性与量化验收

1. **统一资源预算**：将主 Agent、审核模型、检索和抓取纳入同一 Run 预算，统一统计请求数、Token、时间和外部调用额度。
2. **生命周期故障注入**：覆盖排队、执行、checkpoint、报告生成、发布、取消和进程崩溃等阶段，验证幂等及恢复矩阵。
3. **搜索质量基准**：建立跨政策、行业、企业、技术和事件主题的关键来源召回集，持续测量 Recall、来源独立性和证据增益。
4. **多格式真实样本集**：补齐 JS 动态站、复杂 PDF、Office 表格、扫描件、音视频和互相矛盾来源。
5. **模型对比**：固定输入、预算和材料，比较云端与本地模型的工具遵从、覆盖、耗时、Token 和报告质量。

### 7.2 中期：检索、可观测和执行平台

1. **Hybrid Retrieval**：在 `TaskRetriever` 后增加 BM25 + Embedding + Reranker，保留关键词检索作为可解释基线。
2. **OpenTelemetry**：将 Agent Run、模型请求、HTTP 搜索、抓取和文档处理映射到标准 span，接入 Tempo、Jaeger 或 SigNoz。
3. **后台任务执行**：当单机 asyncio 无法满足吞吐和可靠性时，引入持久任务队列和独立 worker；业务状态仍由 ResearchRun 管理。
4. **Provider 质量路由**：根据主题、地区、语言、时效和历史命中率动态选择 Exa、Brave、Tavily 或本地搜索入口。
5. **成本感知规划**：根据每个动作的预期证据增益、延迟和调用成本选择下一步，而不是只按固定预算执行。

### 7.3 长期：产品化和更复杂 Agent 能力

1. **多用户与租户隔离**：认证、RBAC、任务归属、配额、审计和敏感资料隔离。
2. **跨任务知识库**：将已审核证据沉淀为可版本化知识资产，支持主题更新和来源过期检测；不能直接复用未经重新验证的旧结论。
3. **多 Agent 协作**：按来源或问题划分研究子 Agent，由统一 Evidence Governor 合并事实、消解冲突并控制预算。
4. **Human-in-the-loop**：对高风险结论、冲突证据、搜索范围变更和报告发布设置人工审批点。
5. **增量情报监控**：保存主题查询和来源状态，定期发现新增、修改或撤回材料，生成差异报告。
6. **LangGraph 评估**：只有当显式图分支、多 Agent 协作、人工中断和节点重放成为主需求时，才评估迁移；领域状态和轨迹格式保持框架无关。

### 7.4 扩展优先级原则

```text
先补评测证据
  → 再解决已测量的可靠性或召回问题
  → 再扩展吞吐和多用户
  → 最后考虑框架迁移与复杂多 Agent
```

不要为了简历关键词提前引入 LangGraph、Kafka、向量数据库或 Kubernetes。面试中能解释“什么时候不该使用某项技术”，通常比堆叠技术名更有说服力。

---

## 八、AI 应用 / Agent 工程师学习路线

下面以 12 周、每周 10—15 小时为例。已有基础时可以压缩，但建议按依赖顺序学习。

### 阶段一：Python 与后端基础，第 1—2 周

**学习内容：**

- Python 类型标注、dataclass、Pydantic、异常和上下文管理器；
- asyncio、任务取消、Semaphore、Queue 和 ContextVar；
- FastAPI、REST、SSE、SQLite 事务和 WAL；
- pytest、异步测试、mock、Ruff 和 pyright。

**结合项目实践：**

- 阅读 [`conversation.py`](../../src/intel_agent/conversation.py) 的后台运行与取消；
- 阅读 [`state_store.py`](../../src/intel_agent/state_store.py) 的事务和状态转换；
- 能解释为什么业务状态不能只存在 Python 字典中。

**阶段产出：** 实现一个可取消、可重启恢复、状态持久化的异步任务 API。

### 阶段二：LLM 应用基础，第 3—4 周

**学习内容：**

- Chat Completion、消息角色、上下文窗口和采样参数；
- Tool Calling、结构化输出、Prompt injection 和不可信工具结果；
- Token、延迟、并发、重试和模型供应商兼容接口；
- PydanticAI Agent、RunContext、deps、history processor 和 stream events。

**结合项目实践：**

- 阅读 [`agent.py`](../../src/intel_agent/agent.py) 和 [`runner.py`](../../src/intel_agent/runner.py)；
- 为一个简单工具增加类型安全参数和结果模型；
- 比较 Agent 决策与普通确定性函数的适用边界。

**阶段产出：** 实现一个带 3—5 个工具、结构化输出和错误处理的小型 Agent。

### 阶段三：搜索、抓取与 RAG，第 5—6 周

**学习内容：**

- 查询改写、垂直检索、召回率、精确率、去重和 rerank；
- robots.txt、URL 规范化、HTML 正文抽取和动态页面；
- 文档分块、BM25、Embedding、向量检索和 Hybrid Search；
- RAG 的来源引用、上下文排序和检索评测。

**结合项目实践：**

- 阅读 [`search/`](../../src/intel_agent/search/) 和 [`crawl.py`](../../src/intel_agent/crawl.py)；
- 阅读 [`retrieval.py`](../../src/intel_agent/retrieval.py) 的轻量词法检索；
- 设计一个 20—50 条问题的 Recall@K 小型评测集。

**阶段产出：** 对同一资料集比较关键词、Embedding 和 Hybrid Retrieval。

### 阶段四：Agent 状态、记忆与可靠性，第 7—8 周

**学习内容：**

- 短期上下文、长期记忆、语义记忆和工作记忆的区别；
- 状态机、幂等、checkpoint、乐观并发和固定快照；
- 摘要漂移、上下文压缩、检索注入和任务恢复；
- PydanticAI、LangGraph 与自定义工作流的架构取舍。

**结合项目实践：**

- 精读[记忆与上下文管理](../architecture/intelligence-agent-memory-management.md)；
- 画出 Conversation、Task、ResearchRun 和 Checkpoint 的状态关系；
- 为取消、失败、重试和重启各设计一个故障测试。

**阶段产出：** 能从零设计一个不依赖完整聊天历史的长任务 Agent。

### 阶段五：证据、评测与安全，第 9—10 周

**学习内容：**

- Groundedness、Faithfulness、Answer Relevance 和 Retrieval Recall；
- LLM-as-a-Judge 的偏差、隔离、重复评审和人工盲审；
- Prompt injection、SSRF、DNS rebinding、路径穿越和日志脱敏；
- 离线数据集、在线实验、回归基准和成本质量权衡。

**结合项目实践：**

- 阅读 [`evidence.py`](../../src/intel_agent/evidence.py)、[`audit.py`](../../src/intel_agent/audit.py) 和 [`coverage.py`](../../src/intel_agent/coverage.py)；
- 阅读 [`security.py`](../../src/intel_agent/security.py) 与 [`fetch.py`](../../src/intel_agent/fetch.py)；
- 选三个主题手工审查结论、引文和独立来源。

**阶段产出：** 建立一个同时衡量质量、成本和稳定性的 Agent Benchmark。

### 阶段六：可观测性与生产化，第 11—12 周

**学习内容：**

- 结构化日志、metrics、trace 和 OpenTelemetry；
- 模型调用、工具调用和业务决策的关联；
- 任务队列、worker、限流、背压、熔断和降级；
- Docker、CI/CD、配置、密钥管理和部署健康检查。

**结合项目实践：**

- 精读[可观测性技术报告](../architecture/intelligence-agent-observability.md)；
- 使用 `scripts/analyze_trajectory.py` 回放一次完整运行；
- 将一次模型请求和 HTTP 工具调用接入本地 OTel Demo。

**阶段产出：** 能解释并展示一个 Agent 从用户请求到工具和模型服务的完整调用链。

### 8.1 学习优先级

如果时间有限，按以下顺序投入：

```text
Python 异步与类型系统
  → Tool Calling 与结构化输出
  → RAG 和检索评测
  → 状态机、记忆与恢复
  → 证据治理和安全
  → 可观测性与生产化
  → 多 Agent 和框架迁移
```

---

## 九、面试准备清单

### 9.1 必须能够现场讲清楚

- 为什么该项目不是普通 RAG 或搜索问答；
- 一次用户主题如何变成 ResearchRun 和最终报告；
- Fact、Evidence、Review、Coverage 各自解决什么问题；
- 模型上下文与持久事实为什么必须分开；
- 取消、失败和重启后哪些状态可以恢复；
- 为什么当前选择 PydanticAI，什么条件下考虑 LangGraph；
- 74%、53% 和 86.7% 分别来自什么实验，不能如何外推；
- 当前系统的真实边界和下一阶段优先级。

### 9.2 建议准备的现场材料

1. 一张端到端架构图；
2. 一份包含原文引用、局限和来源目录的示例报告；
3. 一段 `trace.jsonl` 及其分析输出；
4. 一个任务取消或重启恢复演示；
5. 一组优化前后实验对比；
6. 一页“已实现 / 规划中 / 不做”的边界表。

### 9.3 回答问题的结构

技术问题可以统一按下面顺序回答：

```text
先说明业务问题
  → 给出当前设计
  → 解释关键不变量
  → 提供测试或实验结果
  → 承认局限
  → 说明达到什么条件才升级
```

这种讲法比直接背诵框架 API 更能体现 Agent 工程能力。

---

## 十、源码复习索引

| 面试主题 | 主要代码或文档 |
| --- | --- |
| Agent 与工具编排 | [`agent.py`](../../src/intel_agent/agent.py)、[`runner.py`](../../src/intel_agent/runner.py) |
| 多轮对话与运行生命周期 | [`conversation.py`](../../src/intel_agent/conversation.py)、[`continuation.py`](../../src/intel_agent/continuation.py) |
| 领域模型 | [`models.py`](../../src/intel_agent/models.py)、[领域术语](../development/domain.md) |
| 持久状态与恢复 | [`state_store.py`](../../src/intel_agent/state_store.py)、[`state_db.py`](../../src/intel_agent/state_db.py) |
| 上下文与记忆 | [`context.py`](../../src/intel_agent/context.py)、[`dialogue.py`](../../src/intel_agent/dialogue.py)、[技术报告](../architecture/intelligence-agent-memory-management.md) |
| 搜索与来源策略 | [`search/`](../../src/intel_agent/search/)、[`search_queries.py`](../../src/intel_agent/search_queries.py)、[搜索策略](../architecture/search-policy.md) |
| 抓取与安全 | [`crawl.py`](../../src/intel_agent/crawl.py)、[`fetch.py`](../../src/intel_agent/fetch.py)、[`security.py`](../../src/intel_agent/security.py) |
| 文档与多媒体提取 | [`document_extract.py`](../../src/intel_agent/document_extract.py)、[`extract.py`](../../src/intel_agent/extract.py)、[`browser.py`](../../src/intel_agent/browser.py) |
| 事实、证据与审核 | [`fact.py`](../../src/intel_agent/fact.py)、[`evidence.py`](../../src/intel_agent/evidence.py)、[`audit.py`](../../src/intel_agent/audit.py) |
| 冲突、覆盖与报告 | [`conflicts.py`](../../src/intel_agent/conflicts.py)、[`coverage.py`](../../src/intel_agent/coverage.py)、[`report.py`](../../src/intel_agent/report.py) |
| 可观测性 | [`trajectory.py`](../../src/intel_agent/trajectory.py)、[技术报告](../architecture/intelligence-agent-observability.md) |
| Web 与兼容 API | [`web/`](../../src/intel_agent/web/)、[`web/runs.py`](../../src/intel_agent/web/runs.py) |
| 项目进展与实验指标 | [项目建设进展汇报](intelligence-research-agent-progress-report.md) |

---

## 十一、最终推荐话术

如果简历只能保留一句最有辨识度的描述，建议使用：

> 将 PydanticAI 的概率型工具决策放入可验证的工程闭环：以持久化状态和 checkpoint 管理长任务，以原文证据和 coverage gate 约束报告质量，以有界上下文和三层轨迹解决记忆、恢复与可观测问题。

如果面试结束前只能补充一句，建议使用：

> 我认为 Agent 工程的核心不是让模型拥有更多自由，而是明确哪些事情由模型判断、哪些事情必须由确定性系统保证，并且让每次决策都能被复核和评测。
