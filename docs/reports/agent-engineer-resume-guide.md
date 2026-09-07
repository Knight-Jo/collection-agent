# AI 应用 / Agent 工程师：简历项目经历与面试手册

更新日期：2026-09-06。源码核对基线：`43458e4`。

定位：把项目讲成“围绕证据构建的研究型 Agent 工程”，而不是功能清单或框架演示。本文依据当前源码、定向测试与可定位实验记录；spec 是目标，历史实验是历史版本成果，两者都不自动等于当前实现。

使用方式：投简历选第二节，准备开场读第三节，技术面重点练第四至七节。以下第一人称话术是模板，“负责 / 主导 / 独立实现”必须按本人真实贡献调整，不因仓库存在代码就默认全部为个人成果。

## 一、项目定位：让面试官记住什么

### 1.1 推荐名称

**知证：基于 PydanticAI 的多源研究与多模态证据工作台**

英文：**Evidence-Grounded Research Agent & Multimodal Workbench**

一句话：

> 面向公开信息调研，将多角色模型决策、多源搜索、多模态材料处理和混合检索组合成研究闭环，让回答能够回到具体材料版本和原文位置，并复用这套能力支撑断言核验与媒体分析。

### 1.2 三个有辨识度的卖点

1. **不只组织模型调用，还设计数据生命周期。** 区分原始字节、内容版本、抽取产物、检索分块和引用，解释清楚“同一文件重新解析后，旧引用怎么办”。
2. **不只做固定资料 RAG，还做缺口驱动研究。** 模型规划查询、评估覆盖并决定是否继续取证；系统负责搜索、采集、存储及上下文构建。
3. **不只增加业务页面，还复用研究核心。** 把证据评估与报告生成分开，Monitor、FactCheck 消费同一研究评估，Media 复用材料采集与抽取。

对应的岗位定位是 AI 应用 / Agent 后端工程师，兼具 RAG 与工作台交付能力；不是模型训练、分布式 Agent 平台或已经生产验收的自动事实裁决系统。

### 1.3 当前技术栈

| 方向 | 当前使用 | 面试讲法 |
| --- | --- | --- |
| 模型与编排 | Python 3.12、PydanticAI、Pydantic | 类型化多角色输出 + Python 研究循环 |
| 搜索 | Exa、Brave、Tavily、SearXNG、arXiv、OpenAlex、RSS | 7 类 provider Adapter；实际可用性依赖配置、凭证及网络 |
| 采集与抽取 | httpx2/httpcore2、Playwright、trafilatura/BeautifulSoup、PyMuPDF/pdfplumber、Office 解析库、Tesseract、FFmpeg、faster-whisper | 统一材料契约，按格式路由与回退；部分后端是可选依赖 |
| 检索与存储 | SQLite、内容寻址文件仓、Qdrant、Embedding、tiktoken | 业务真相与派生索引分离，词法/向量融合及降级 |
| 应用交付 | FastAPI、React 19、TypeScript、TanStack Query/Router、Vite、Bun、SSE | Python 应用能力与 HTTP 展示分离，前端位于 frontend/ |
| 工程保障 | pytest、Ruff、Pyright、Vitest、Biome、结构化日志 | 用契约、规则与故障场景验证，不把测试数量冒充效果指标 |

不再沿用旧手册的“百度原生 provider”“未使用向量数据库”“旧 web/ 兼容 API”等描述。当前存在 Qdrant 和 HybridRetriever；词法检索是中文字符/二元组与英文词的匹配，不应写成已经实现 BM25 或 Reranker。

## 二、可直接用于简历的项目描述

### 2.1 一页简历版（推荐）

**知证：多源研究与多模态证据工作台**｜AI 应用 / Agent 后端开发

`Python` `PydanticAI` `FastAPI` `SQLite` `Qdrant` `React`

- 构建基于 PydanticAI 的多角色研究流程，拆分规划、覆盖评估、证据核验、续搜决策与报告撰写，串联多源搜索、材料采集和上下文构建，支持根据证据缺口继续研究。
- 设计 `Resource → Revision → Artifact → Chunk → Citation` 材料链路，以 SHA-256 内容寻址、不可变抽取版本和页码/时间区间定位，支撑原件复用与引用回溯。
- 实现任务范围内的词法与向量混合检索，使用 Qdrant、Embedding 和 RRF 融合；小材料集直接装载，向量路径异常降级至词法，并按 token 预算选择上下文。
- 将研究循环拆出类型化 `ResearchAssessment`，供调研报告、监测和断言核验复用；媒体分析复用抽取链路，通过独立角色将转写归纳为跨分段声明，并保留未核验状态及时间定位。
- 建设 FastAPI + React 工作台及分业务持久化模块，集中管理后台执行与并发，增加模块依赖、材料版本、检索范围、裁决规则和媒体引用等自动化测试。

如本人只负责后端，将最后一条改为“提供 FastAPI 契约并配合前端接入”；不要默认写“独立完成全栈”。

### 2.2 强调后端与架构的版本

**背景：** 联网回答很容易停留在搜索摘要与自然语言拼接，难以维护原始材料、重新解析后的引用、任务内检索范围，以及不同业务间的复用关系。

**职责：** 围绕研究核心进行模块化重构，区分跨模块契约、搜索与采集、材料存储、检索上下文、模型角色和应用入口；将搜索设置、资料库投影和新业务持久化从会话职责中拆出。

**落地：**

1. 把来源身份、字节版本、抽取版本分别建模，避免“URL 等于文档”“更新索引等于覆盖证据”的混淆。
2. 将 SQLite/文件仓作为事实来源，Qdrant 作为可重建索引；检索在固定 MaterialScope 内执行。
3. 用 ResearchAssessment 隔开“取得证据”与“撰写报告”，新增业务无需复制完整研究循环或先生成一份无用报告。
4. 以应用层管理后台任务，业务模块提供执行入口；通过 SQLite 保存任务、材料与时间线，提供恢复相关操作。
5. 以 AST 依赖检查、临时数据库测试和受控模型替身检查关键契约；把真实联网/媒体后端验收与确定性单测分开。

**结果表达：** 形成可复用研究与材料核心，并接入调研、监测、核验、媒体等业务入口。当前是持续迭代的本地工作台，不包装成高并发生产平台；新增业务的调度、恢复、安全与质量门槛仍需继续收敛。

### 2.3 招聘平台短描述

基于 PydanticAI 构建多源研究与多模态证据工作台，采用类型化角色编排、版本化材料链、任务范围混合检索与 FastAPI 应用层。通过 SQLite、内容寻址资源仓和 Qdrant 分离业务真相与检索索引，支撑原文回溯、音视频声明定位及研究能力复用；提供 React 工作台、规则回归与历史真实实验记录。

### 2.4 英文版

**Evidence-Grounded Research Agent & Multimodal Workbench | AI Application Engineer**

- Built a typed research workflow with PydanticAI roles for planning, coverage assessment, evidence review, continuation decisions, and report writing.
- Designed a versioned material pipeline with content-addressed resources, immutable extraction artifacts, structured chunks, and page/time-based citation locators.
- Implemented task-scoped lexical and vector retrieval with Qdrant, rank fusion, lexical fallback, and token-budgeted context selection.
- Separated research assessment from report generation to reuse the same loop for monitoring and fact-checking; added transcript-based claim extraction with source-segment references.
- Delivered FastAPI endpoints and a React workbench, with focused tests for module dependencies, retrieval scope, material identity, verdict rules, and media provenance.

不在英文版额外加入“production-grade”“exactly-once”“hallucination-free”等中文版没有证据支持的承诺。

## 三、开场与追问：由短到长

### 3.1 30 秒版

> 我做的是一个研究型 Agent 工作台，核心不是让模型直接联网回答，而是把找到的网页、PDF 和音视频变成可定位、可检索、可追溯的材料。模型分角色负责规划、核验和决定是否继续搜索，系统负责采集、版本化存储和上下文选择。我重点做的是材料证据链、任务范围混合检索，以及把研究核心复用到核验和媒体分析。

### 3.2 1 分钟版

> 这个项目解决的是公开信息调研中“找到信息”和“能解释答案依据”之间的缺口。我把它拆成研究决策和材料处理两部分：PydanticAI 的角色输出结构化研究计划、覆盖评估、证据关系和下一步决策；Python 编排执行搜索、抓取、抽取、入库、索引和上下文构建。
>
> 数据上，我没有把一段文本直接丢进向量库就结束，而是区分原始 Resource、内容 Revision、抽取 Artifact、Chunk 和 Citation。这样同一材料重新解析时，旧引用仍然有明确版本。检索先固定任务的材料范围，小集合直接装载，大集合使用词法与向量融合，向量不可用时能降级。
>
> 后面又把证据评估从报告生成中拆出来，复用到核验和监测；媒体分析则复用抽取链路。当前已经有后端与 React 工作台，我会把已落地的数据链路和仍需加强的调度、幂等、核验质量分开说明。

### 3.3 3 分钟版：按四个问题讲，不背目录

**第一，为什么需要 Agent？**

> 一次搜索很难覆盖完整主题。系统先生成问题和搜索方向，再根据已取得的材料评估覆盖、识别支持或冲突，决定继续搜什么。这里的动态性在“下一轮信息需求”，不是让模型任意修改数据库或执行系统命令。

**第二，最核心的数据设计是什么？**

> 我把材料分成多个身份层次。相同字节可以复用存储，但不同来源仍保留来源记录；同一来源的内容变化生成新 Revision；抽取方式变化生成新 Artifact。正文以 EvidenceBlock 为依据，Chunk 保留 block span，引用再指回原件及页码、表格或时间区间。这个设计解决的是证据生命周期，不只是给回答加几个 URL。

**第三，如何解决上下文与检索？**

> 每次构建上下文先冻结任务材料范围，所有召回使用同一个 scope，避免全库搜完再事后过滤。能装下就直接用；装不下再通过中文感知词法与向量结果融合挑选，按 token 预算裁剪。Qdrant 是检索加速层，不接管业务状态。下一步要用固定数据集验证召回收益，而不是因为用了向量库就声称答案更准确。

**第四，架构如何支撑产品扩展？**

> 研究循环输出 ResearchAssessment，报告撰写只是一个消费者，监测和核验可以直接复用评估。媒体分析复用 Resource 与抽取产物，再用模型把跨段语音归纳为声明；声明默认 unverified，证明“说过什么”不等于证明“说得对”。这让我把业务模块分开，又没有复制搜索和解析栈。

收尾：

> 我最重视的是模型与确定性代码的分工，以及每个能力能拿出什么验证证据。当前已有规则测试和历史真实运行记录，但不把原型能力、历史指标和生产保证混在一起。

## 四、白板架构：一张图、三个不变量

### 4.1 当前主流程

```text
React 工作台 / FastAPI / CLI
              │
      应用组合与后台执行管理
              │
     ┌────────┼─────────────┐
   研究报告  Monitor / FactCheck  Media
     │          │               │
     └── ResearchAssessment     │
           研究循环              │
              │                 │
           多源搜索              │
              └── AcquisitionPipeline ◀── 上传 Resource
                       │
              Fetch → Extract → Normalize
                       │
              SQLite + 不可变资源仓
                       │
               Chunk / 词法索引
                       ├── Embedding → Qdrant
                       │
               MaterialScope → Context
                       │
               Coverage / Verifier / Decider
                       └── 继续搜索或输出评估
```

Media 不自动进入联网研究循环；Monitor/FactCheck 不必生成普通研究报告。图是职责与数据流，不表示各分支都由独立进程执行。

### 4.2 三个最值得展开的不变量

| 不变量 | 解决的问题 | 当前源码入口 |
| --- | --- | --- |
| 原件、抽取产物和索引身份分开 | 去重、重抽取、重建索引不应混为覆盖同一对象 | [资源仓](../../src/intel_agent/storage/resources.py)、[归一化](../../src/intel_agent/normalization.py) |
| 召回先确定任务材料范围 | 同库多任务材料不能随意进入当前上下文 | [上下文管理](../../src/intel_agent/context/manager.py)、[Qdrant 过滤](../../src/intel_agent/indexing/qdrant.py) |
| 材料中的声明不等于外部事实 | 转写准确与事实正确属于不同问题 | [媒体分析](../../src/intel_agent/media/service.py)、[媒体模型](../../src/intel_agent/media/models.py) |

注意：“结构化引用可解析”只证明位置与身份可追溯，不自动证明该片段在语义上支持结论。完整引文、归属和语义支持验证仍需分别检查。

### 4.3 模块化重构怎么讲出价值

不要只说“拆了很多文件”。可以这样说：

> 我按变化原因拆模块：provider 变化留在 search，解析器变化留在 extraction，业务裁决留在 factcheck，展示聚合留在 library。真正共享的是 ResearchAssessment、材料契约和任务执行设施，而不是把所有模型放进一个大文件，或者每个业务再写一套工作流。

当前已存在分业务 storage、独立 search/settings 和 library，并有依赖测试；但组装仍使用部分动态属性，旧 MaterialStore 仍保留部分重叠职责。可说“完成关键职责拆分”，不要说“彻底实现零耦合架构”。

## 五、六个技术深挖题

### 5.1 这是 Multi-Agent、工作流，还是 Agentic RAG？

推荐回答：

> 更准确地说，是类型化多角色研究工作流，具有根据证据缺口反复检索的 Agentic RAG 特征。planner、coverage、verifier、decider、writer 各有结构化输出，媒体还有 fact_extractor。它们由同一 Python 编排管理，不是彼此自治通信的分布式多 Agent 集群。

追问“为什么选 PydanticAI”：本项目已经以 Pydantic 契约组织数据，角色输出可以直接进入类型化评估；当前研究循环用普通 Python 表达清楚，没有为框架迁移制造第二套状态体系。

不要把“6 个角色”说成“6 个独立模型”或“天然提高准确率”；它们可以共享同一模型配置，收益需要评测。

### 5.2 为什么已经用 Qdrant，还保留 SQLite 和词法检索？

推荐回答：

> 三者负责不同问题。SQLite 保存业务与材料元数据，文件仓保存原始字节，Qdrant 保存可重建向量。中文词法基线用于实体和字面匹配，向量用于语义候选；通过 RRF 按名次融合，避免直接相加不同分数。向量故障时返回词法结果并记录降级，而不是整条研究链路不可用。

当前词法使用 CJK unigram/bigram 与英文词，SQL 匹配计数，不是 BM25；当前没有单独 Reranker。小材料集能装入上下文时直接使用，不强制走向量召回。

若被问“提升多少”：目前有检索机制与历史真实后端 roundtrip 证据，不能据此推断 Recall@K 或答案质量提升。应准备固定 query—相关 chunk 标注集，再比较词法、向量和融合。

### 5.3 为什么要有 Revision 和 Artifact 两种版本？

推荐回答：

> Revision 回答原始内容有没有变，Artifact 回答同一原件经过什么处理得到了什么结果。扫描 PDF 从原生文本提取切到 OCR，或者更换解析后端，即使原始字节没变，抽取结果也可能变。把两种版本分开，才知道历史引用对应哪一次处理。

沿链解释：

```text
Resource（原始字节与来源）
  → DocumentIdentity / Revision（来源身份与内容版本）
  → Artifact / EvidenceBlock（版本化抽取结果与定位）
  → Chunk / BlockSpan（检索分块）
  → Citation（答案回溯入口）
```

不要把所有内容 hash 称为同一个 document_id，也不要把哈希完整性等同于事实真实性。

### 5.4 上下文管理与“长期记忆”到底是什么？

推荐回答：

> 当前的核心是持久材料加按需构建上下文，而不是无限保存模型聊天历史。ContextManager 固定 scope，判断材料是否装得下，再选择直接装载或混合召回，使用 tokenizer 计数和 chunk 预算挑选内容；进程外的材料不依赖模型记住。

必须讲清两个边界：

- 证据预算不等于整次模型请求预算，系统提示、角色说明和输出额度仍需单独考虑。
- 当前裁剪包含每 chunk 固定开销估计，不能宣称所有格式下最终 prompt 都经过精确硬上限验证；也不能继续宣称旧版“最近 10 条消息 + Top 8 + 16 KB 快照”就是当前实现。

来源：[ContextManager](../../src/intel_agent/context/manager.py)、[TokenCounter](../../src/intel_agent/indexing/tokenize.py)、[上下文格式化](../../src/intel_agent/context/formatter.py)。

### 5.5 事实核验如何避免“有引用就是真的”？

推荐回答：

> 我区分三件事：引用能定位、片段与断言的支持关系、来源是否独立。当前核验模块复用研究证据，并提供六级裁决和来源计数规则；但自动独立来源识别和复杂断言判断还没有达到可靠验收，不能拿规则通过率代替真实核验准确率。

具体边界：

- 当前 `_checkable` 仍固定返回 checkable，不能声称已自动识别观点、含糊或不可核验断言。
- 证据转换目前没有充分填充 independence_group，一手性默认 unknown；不能声称已完成转载溯源和一手来源识别。
- `adjudicate` 是基于方向与计数的简化规则，不是经过校准的事实真值模型。
- 原文片段引用、任务归属、语义支持和最终报告引用覆盖必须分别验证，不能用 Pydantic 字段合法性替代。

来源：[核验执行](../../src/intel_agent/factcheck/service.py)、[裁决规则](../../src/intel_agent/factcheck/verdict.py)。

这些是面试追问时应主动说明的实现边界，不必塞进简历正文。

### 5.6 取消、恢复、幂等是不是都已完成？

推荐回答：

> 已有集中执行登记、并发限制、任务状态、取消/恢复方法，以及任务存储的认领和幂等相关操作。但“有方法”不等于所有入口都满足端到端保证。我会分别验证入队事务、执行认领、阶段复用、完成提交和重启接线，再判断可以承诺哪一级恢复。

当前需要保留的事实边界：

- application 有 recover 方法，但 bootstrap 尚未显式调用它；不能说服务启动已自动恢复所有队列。
- scheduler 目前主要是下一运行时间计算，尚未看到接入启动生命周期的周期 tick；“监测配置与手动运行已接入”比“无人值守持续调度已稳定运行”准确。
- 部分提交路径分别创建 task 和业务记录，API 尚未贯通完整 Idempotency-Key 语义。
- 已有预算/尝试账本与用量记录，不代表所有 planner、核验、媒体调用都被统一硬限额约束。
- 外部模型/网络调用可能重试；即使数据库提交幂等，也不能承诺调用与计费 exactly-once。

来源：[应用层](../../src/intel_agent/application.py)、[组装](../../src/intel_agent/bootstrap.py)、[任务存储](../../src/intel_agent/storage/tasks.py)、[调度计算](../../src/intel_agent/monitoring/scheduler.py)。

## 六、怎样讲“我解决过难题”

### 6.1 当前架构故事：把研究评估与报告拆开

**问题：** Monitor/FactCheck 需要证据评估，但并不需要先生成普通研究报告。如果复制流程，搜索策略、引用和错误处理会各自演进。

**行动：** 提取类型化 ResearchAssessment，让研究循环输出 scope、coverage、evidence、citations、limitations 等结果；报告只是下游消费者，新业务消费相同评估。

**结果：** 当前 Monitor/FactCheck 调用 `run_assessment`，普通研究仍可调用 `run_task` 生成报告。价值在复用同一逻辑与明确结果契约，不虚构代码减少比例。

**追问准备：** 如何处理模型输出变化？哪些信息必须进入评估对象？为什么不做万能 workflow 插件系统？

源码：[研究编排](../../src/intel_agent/orchestration/orchestrator.py)。

### 6.2 当前媒体故事：从逐段复述到跨段声明

**问题：** 一条声明可能跨多个语音片段，逐段复制转写会产生重复、语义不完整的“事实”。

**行动：** fact_extractor 返回独立声明与 segment_indices；服务端映射回真实分段，丢弃无有效分段引用的输出，保存摘要、未核验声明及 mentions 出处。

**结果：** 已有跨分段声明、无效索引过滤、无语音跳过与用量记录测试。输出仍是 unverified；没有真实说话人信息时 speaker=null，不虚构身份。

**下一步：** 长音频的分批抽取、覆盖率与事实召回评测。当前把分段全文交给抽取角色，不宣称无限长度媒体已支持。

源码及检查：[媒体执行](../../src/intel_agent/media/service.py)、[语义声明测试](../../tests/unit/test_media_facts.py)。

### 6.3 历史优化故事：先消除无价值动作

这段可以展示优化思路，但必须先说“在重构前的一次低空经济专项实验中”。

- **现象：** 深层链接带来大量与主题无关的导航材料，增加调用和上下文成本。
- **行动：** 在深度入队位置增加相关性门槛，对比 run 009 与 run 010。
- **记录结果：** rel-0 深层条目从 48/50 变为 0/9；耗时从 1433s 到 377s，记录 token 从 6.2M 到 2.9M，约减少 74% 与 53%。
- **复盘：** 输入质量同时影响成本和产出。不能归因为当前混合检索重构，也不能外推为所有主题平均提升。

来源：[run 010 原始报告](../../experiments/runs/010-relevance-gate/REPORT.md)。历史报告未注明精确执行日期；本文于 2026-09-06 核对，不补造实验日期。

### 6.4 历史取舍故事：证据门槛也会增加成本

run 015 → 016 中，关键事实双源率从 0 到 13/15（86.7%），但同时提高搜索预算至 60、放宽执行轮次。结果仍是 with_gaps，独立来源组只有 7/8，双源目标 100% 未达成。

正确话术：

> 当时发现提供更多候选不等于模型会完成交叉验证，所以在登记事实时增加补源约束，并重新分配预算。双源率改善了，但成本和预算也变化，我不会把它说成同成本下单一算法带来的提升。它验证的是约束与预算协同，而不是系统已经完全解决事实核验。

来源：[run 016 原始报告](../../experiments/runs/016-verification-gate/REPORT.md)。精确执行日期未注明；核对日期为 2026-09-06。

## 七、证据与成熟度：面试时哪些话可以说

### 7.1 当前能力口径

| 能力 | 可陈述事实 | 不应扩大的承诺 |
| --- | --- | --- |
| 多角色研究 | 五类研究角色、结构化输出、循环研究与报告分离 | 自治分布式 Multi-Agent、已经消除幻觉 |
| 多模态材料 | 多格式后端、资源归档、页码/表格/时间定位 | 所有格式和故障场景都已真实验收 |
| 混合检索 | Qdrant + 词法 + RRF + 降级，task scope | 已有 BM25/Reranker、召回显著提高 |
| Monitor | 配置、下一时间计算、手动运行、基线差异代码 | 稳定自动调度、完整语义变化识别 |
| FactCheck | 独立入口、研究复用、六级裁决规则 | 已可靠识别不可核验输入或独立来源 |
| Media | 转写投影、语义声明、分段引用、摘要 | 自动外部核验、说话人身份识别 |
| 生命周期 | 后台执行所有权、状态/恢复方法和局部事务测试 | 全入口 crash-safe/exactly-once |
| 工作台 | frontend/ 已调用后端研究、监测、核验及媒体接口 | 页面存在即等于全部业务验收通过 |
| 日志与事件 | stdlib 分级日志、StructuredLogger、EventBus、时间线及研究 SSE | 旧版 Recorder/三层完整轨迹仍已全部接入 |
| 安全 | HTTP 公网地址/重定向校验、受控传输、设置读取脱敏 | 浏览器出口、上传限制、认证已全面生产加固 |

当前上传路由未显式传入 max_bytes，媒体类型还依赖请求类型/文件名；浏览器出口隔离另有未验证记录。面试可以说明已有安全措施，也要说明尚不能直接开放成公共上传服务。

### 7.2 哪些数字可以用

**本次定向回归：** 2026-09-06，源码基线 `43458e4`，下列 9 个测试文件运行结果为 **30 passed**。这是选定功能的回归结果，不是全仓库总测试数、覆盖率或端到端成功率。

在 Python 3.12 的 collection-agent-pydantic conda 环境中，从仓库根运行：

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run --no-sync pytest -q \
  tests/unit/test_context.py \
  tests/unit/test_lexical_retrieval.py \
  tests/unit/test_normalization.py \
  tests/unit/test_resource_store.py \
  tests/unit/test_module_dependencies.py \
  tests/unit/test_monitoring.py \
  tests/unit/test_verdict.py \
  tests/unit/test_media_facts.py \
  tests/unit/test_workspace.py
```

**历史真实后端验收：** [2026-09-05 E2E 记录](../../experiments/e2e-acceptance-2026-09-05.md)记载真实 LLM/学术搜索两轮、Embedding→Qdrant roundtrip、音视频 ASR 等结果。可讲“有真实后端验收记录”，不要把当时 77 项测试或角色调用次数当成当前版本数据。该记录与重构状态报告对引用数存在 10/11 的差异，未复测前不在简历使用精确引用数。

**质量规则测试：** [固定测试样例](../../tests/fixtures/__init__.py)含 20 组字典差异和 30 组结构化证据组合；[评估测试](../../tests/unit/test_quality_eval.py)检查规则输出。这不是 30 条真实断言的联网事实核验 Benchmark，不能转换成“事实核验准确率超过 80%”。

**历史优化：** 74%、53%、86.7% 只按第六节的 run、主题、分母和预算条件使用，不写进当前版本默认能力指标。

### 7.3 如果面试官问“还有什么不足”

建议只选最熟悉的两点，并给出验证方案：

> 第一是恢复的端到端一致性：我会围绕入队、认领和提交注入崩溃，检查同一工作有没有重复记录、取消会不会晚于成功提交，以及预算有没有重置。第二是核验质量：需要补充来源归组、不可核验输入和真实断言标注集，把规则测试与端到端效果分开。

这比“后续接微服务、上 Kubernetes、做大规模多 Agent”更贴近当前项目真实问题。

## 八、按岗位调整表达

| 岗位 | 优先讲 | 准备一个现场证据 |
| --- | --- | --- |
| Agent / AI 应用 | 角色输出、缺口驱动循环、评估与报告分离 | planner → assessment → decision 的一次调用流程 |
| RAG / 检索工程 | scope、分块定位、词法/向量融合、token 选择 | 相同问题在词法与融合路径下的命中材料 |
| Python 后端 | 依赖方向、存储事务、后台任务、失败语义 | 一个临时 SQLite 状态或恢复测试 |
| AI 全栈 | HTTP 契约、任务进度、资料库投影、前端缓存更新 | 上传音频→查看分段与声明，或一次研究 SSE |
| 工程优化 | 实验设计、浪费定位、质量—成本取舍 | run 010/016 的前后条件和未达指标 |

“主导架构”需要能回答替代方案与取舍，“实现核心模块”需要能现场定位执行链路。若使用了 AI 编程工具，可据实说明工具参与编码与测试生成，自己的贡献是需求定义、设计判断、验收和审查；不要虚构手写全部代码或团队管理经历。

## 九、复习路线与源码索引

不再按旧架构背 agent.py、runner.py、state_store.py 等已删除路径。用下面六步，每一步都能展示代码或运行检查。

| 顺序 | 复习目标 | 当前入口 |
| --- | --- | --- |
| 1 | 角色如何输出类型化计划/评估/报告 | [角色](../../src/intel_agent/agent/roles.py)、[研究契约](../../src/intel_agent/contracts/research.py) |
| 2 | 搜索候选如何成为版本化材料 | [搜索](../../src/intel_agent/search/service.py)、[采集](../../src/intel_agent/acquisition.py)、[抽取](../../src/intel_agent/extraction/service.py)、[材料契约](../../src/intel_agent/contracts/documents.py) |
| 3 | 范围、召回、token 与引用如何关联 | [ContextManager](../../src/intel_agent/context/manager.py)、[召回](../../src/intel_agent/context/retrieval.py)、[索引](../../src/intel_agent/indexing/service.py) |
| 4 | 三种业务如何复用核心且保持不同语义 | [Monitor](../../src/intel_agent/monitoring/service.py)、[FactCheck](../../src/intel_agent/factcheck/service.py)、[Media](../../src/intel_agent/media/service.py) |
| 5 | 状态在哪里，启动/恢复究竟接到哪里 | [应用层](../../src/intel_agent/application.py)、[TaskStore](../../src/intel_agent/storage/tasks.py)、[Bootstrap](../../src/intel_agent/bootstrap.py)、[故障测试](../../tests/integration/test_crash_recovery.py) |
| 6 | UI、事件、设置与持久数据如何衔接 | [API](../../src/intel_agent/api/app.py)、[业务路由](../../src/intel_agent/api/routes/workspace.py)、[前端 client](../../frontend/src/api/client.ts)、[日志](../../src/intel_agent/runtime/logging.py) |

练习要求：每一步回答“输入、输出、状态归属、失败行为、验证方式”，不要只复述类名。实现与文档冲突时，回到源码/测试；旧架构报告和旧图索引只用于解释历史演进。

## 十、面试前的最后检查

- [ ] 简历每条“我做了”都与真实个人贡献匹配。
- [ ] 能画出研究循环和材料生命周期，并说明两者不是同一个状态机。
- [ ] 能解释 RRF、scope、Artifact 与 Citation，不把词法匹配叫 BM25。
- [ ] 能展示一条媒体声明如何关联多个分段，解释 unverified 与 mentions。
- [ ] 能区分代码存在、局部测试通过、真实后端验收和生产效果四种证据等级。
- [ ] 所有性能数字带 run、条件和分母；历史结果不归到新版本。
- [ ] 现场演示前重新确认服务、凭证、样本和启动链路；不展示真实密钥或内部地址。
- [ ] 不声称当前已实现旧版完整报告快照、三层 Recorder、自动调度或全链路幂等。
- [ ] 准备一个“未解决问题→最小修复→可失败测试”的回答，而不是承诺没有缺陷。

最终推荐话术：

> 我的核心工作是把模型的研究判断接到一套可追溯的材料和检索系统上：模型负责提出信息需求，材料链负责保留出处，应用层组织执行。对每一项能力，我都区分已经实现什么、测试证明了什么，以及还有什么不能保证。
