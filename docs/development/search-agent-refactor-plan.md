# Search Agent v0.1 Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 经用户选择，也可使用 superpowers:subagent-driven-development。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目重构为满足 v0.1 全部能力与 A01–A27 验收的单一模块化后端，提供 Python、CLI 和 FastAPI 入口；Web 前端独立部署，当前不实现页面。

**Architecture:** 在 `src/intel_agent/` 内按公共契约拆开 Search、Fetch、Extraction、Normalization、Storage、Indexing、Context 和 Orchestration，最终只交付一套引擎。CLI 与 FastAPI 共用 application 的任务控制和 bootstrap 的依赖组装；业务模块不依赖 HTTP。SQLite 是材料、任务和索引状态的权威来源，文件系统保存不可变资源，Qdrant 是可重建索引；Agent 仅生成研究决策。

**Tech Stack:** FastAPI / Uvicorn、Python 3.12、Pydantic 2 / Pydantic AI、HTTPX / HTTPCore、SQLite / FTS5、Qdrant、Playwright、Trafilatura / BeautifulSoup、PyMuPDF / pdfplumber、Tesseract、python-docx / python-pptx / openpyxl、FFmpeg / FFprobe、faster-whisper、目标模型 tokenizer；uv、pytest、Ruff、Pyright。

**Spec:** [搜集与研究智能体实现规格 v0.1](../../specs/2026-09-05-search-agent-design.md)，日期 2026-09-05。实施者必须同时阅读该 spec；本计划中的示例是实现锚点，不替代完整契约。

## Global Constraints

- “音频、视频、OCR、多种解析后端都是 v0.1 的必需能力，不得以 MVP 简化为由删除或仅留下空接口。”
- spec 原始范围：“首先交付可调用的 Python 接口和最小 CLI，不要求 Web UI。”用户最新补充要求 FastAPI 后端支持未来 Web，当前仍不实现 Web 页面。
- 用户最新决策（2026-09-05）：不考虑旧版本兼容性；删除双引擎目标、兼容入口和旧数据转换任务。现有文件仅作为能力复用依据；本轮仍只修改计划，不执行代码或用户数据删除。
- “单用户、本地或单机服务部署；Windows 为首要运行环境。必须记录实际测试的 Python、依赖和外部工具版本。”
- “模型、解析库、Provider 凭据通过配置注入，禁止业务层硬编码。”
- “禁止导入模块时自动联网、加载大型模型或注册全局可变实例。”
- “取消信号必须向上传播，不能转换为可重试普通失败。”
- “默认不自动下载模型；下载由配置或安装步骤显式启用。”
- HTML 至少两个真实后端；PDF 至少两个真实文本/结构后端；图片 OCR、音频 ASR、视频媒体处理各至少一个真实后端。
- DOCX、PPTX、XLSX、PNG、JPEG、WAV、MP3、MP4、WebM 均纳入真实样本验收；不得用 mock 记录代替真实后端验收。
- 时间为带时区 UTC；位置序号从 1 开始；字符和毫秒区间为半开区间；bbox 使用原始页面/图像归一化坐标。
- 默认切块：目标 600 tokens、硬上限 900 tokens、重叠最多 80 tokens。Hybrid：`Σ 1/(60 + rank)`，rank 从 1 开始，各路及融合后 top_k 默认 30。
- §14 全部资源限制进入一套配置；重试计数含首次且恢复不重置。完整配置与低资源配置必须明确区分。
- 遵循根目录 `AGENTS.md`：生产代码仍在 `src/intel_agent/`；Python 3.12 conda 环境，依赖只通过 uv 管理；保留 `uv.lock`；英文文件名和代码注释；变更行为必须有针对性的回归测试。

---

## 1. 本次交付、工作树与基线

本文件是实施计划，任务均未开始实现。工作分支为 `refactor/search-agent-v01`，隔离目录为仓库根目录下 `.worktrees/search-agent-v01`，起点为 `84e6437`。后续命令必须在该工作树执行。

原 `main` 的未提交内容没有移入新代码基线：`config.example.yaml` 的模型名变更、`src/intel_agent/logging.py` 的日志格式变更，以及 `extract.py → extract/` 拆分。spec 已按原内容复制到新工作树。实施抽取任务前，应检查这些改动是否已提交，再按功能选择复用；不可覆盖原工作区，不可复制其 `ModuleType.__setattr__` 测试兼容技巧作为新模块结构。

计划阶段使用已有 conda 环境，通过 `PYTHONPATH=src` 和 `uv run --no-sync` 确认导入的是本工作树，避免重装 editable package 改变其他工作树的环境绑定。已确认 Python 为 3.12.3，收集到 680 个既有测试。首次全量检查受当前 SOCKS 代理环境影响：出现缺少 `socksio` 的构造失败及 continuation 失败，162 秒后主动中断，结果为 63 passed / 4 failed / 1 skipped；这不是完整基线结论。独立 browser 测试为 16 passed / 1 skipped，真实 Chromium 样本被跳过。仅对测试子进程移除代理环境变量后再次核验，最终结果记录于本文末尾。

实施期间环境命令：

```bash
mamba activate collection-agent-pydantic
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
export PYTHONPATH=src
uv sync --extra dev
uv run pytest tests/unit -q
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run pyright
uv build
```

Windows 使用同名环境，PowerShell 设置 `$env:UV_PROJECT_ENVIRONMENT = $env:CONDA_PREFIX` 和 `$env:PYTHONPATH = 'src'`。不得把 POSIX 进程组测试通过等同于 Windows 进程树已被回收。

## 2. 当前实现与迁移落点

| 现有证据 | 与 spec 的差距 | 处理方式 |
| --- | --- | --- |
| `agent.py:1679` 的 `build_agent()`，全文件 2731 行；`runner.py:510` 的 `run_agent_task()` | Agent 可调用搜索、抓取、存储、事实治理等工具；推进靠模型循环 | 新 `ResearchAgent` 仅返回决策；阶段、预算和恢复由 Orchestrator 执行。复用模型配置与 usage 读取经验，不搬迁工具全集 |
| `fetch.py:617` 的 `fetch_document()` | 同时下载、解析、浏览器回退与归档；返回 `IntelDocument` | 将字节获取、解析及保存拆开；新 Fetch 只返回 `FetchResult` |
| `crawl.py` 调用 `extract_resource_process()` 和 `archive_document()`；旧 `web_fetch` 走另一链路 | 存在两条解析归档路径 | 新远程采集与本地导入共用 AcquisitionPipeline；旧 crawl/工具路径在对应能力迁入并验证后移除 |
| `extract.py:421` 的 `_extract_pdf()` | 整份文档文本量决定是否 OCR，丢失逐页 coverage 和精确 bbox | 迁移 PyMuPDF 能力，改成逐页/区域策略，加入真实备用 PDF 后端 |
| `extract.py:665` 的 `_transcribe_media()` | 音视频共用整段音轨转写；没有字幕与帧 OCR 的独立证据流 | 复用 FFmpeg、faster-whisper；新增分段、字幕、采样与时间对齐 |
| `search/__init__.py`、`search/provider.py` | 无标准 SearchBatch；合并会丢 occurrences；URL 合并不够保守；相对日期与 rank=0 不符合新契约 | 复用响应字段解析，重写聚合、显式注册、能力描述、日期适配和 RRF |
| `fetch.py:98` 的 `canonicalize_url()` | 删除尾斜杠、排序查询参数并丢 fragment；已参与旧 ID 计算 | 新 Search/source identity 使用保守规则；旧函数及旧 ID 契约不保留 |
| `storage.py:153` 的 `verify_document_integrity()`；`fetch.py:502` 的 `archive_document()` | ID 绑定 URL 与 raw hash；恢复解析可更新已有记录；无独立 revision/artifact | 新数据库不可变文档产物；复用哈希核验行为，替换旧记录格式 |
| `state_db.py`、`state_store.py` | SQLite 已支持对话/ResearchRun/committed assets，但不含标准 blocks/chunks/index_jobs | 复用事务与迁移模式，不把新材料表塞入 3400 余行的 StateStore |
| `context.py` 与 `retrieval.py:42` 的 `TaskRetriever` | 上下文按字节估算；检索按 12 行动态切分；没有持久 Chunk、Qdrant 或实际 tokenizer 预算 | 新写入路径负责切块；Context 只选证据，固定 scope、引用及 token 计数 |
| `security.py` 与 `fetch.py:154` 的 `pinned_fetch()` | 公网校验与 DNS pinning 值得保留；自写 HTTP 协议且 body 聚合进内存 | 公网判定规则迁移为测试保护的纯函数；网络改为成熟 transport + 流式资源写入 |
| `browser.py:305` 的 `_route_handler()` | 校验后 `route.continue_()`，Chromium 自行解析/连接 | 受控出口是 M2 的验收门槛，不能继承“validated”名称就宣布安全 |

调用方核对至少包含：`agent.py`、`crawl.py`、`main.py`、`runner.py`、`continuation.py`、`conversation.py`、`web/runs.py`，以及 `scripts/` 和既有测试。迁移函数前再次运行 `rg`，不要仅以本表作为删除依据。

## 3. 先固定的实施决策

### 3.1 模块与入口

生产代码直接组织在 `src/intel_agent/`，去掉原计划为并存旧引擎增加的 `research/` 层。发行包仍使用现有项目名，最终只有一套运行语义，不建立 `legacy/`、旧路由兼容层或双写数据通道。

入口分为三种：Python 调用应用/业务 Interface；CLI 使用 `python -m intel_agent` / `research-agent`；FastAPI 使用 `intel_agent.api.app:create_app` 工厂启动。它们共用 `bootstrap.py` 创建的 `ResearchApplication`。`application.py` 负责提交、持有后台任务、取消、等待和关闭，不在其中重复研究状态机；`orchestration/` 负责一项研究内部的轮次与工作项推进。

`api/` 只负责 HTTP 入参、响应、错误映射和路由；请求/响应中与业务契约一致的对象直接复用，不机械复制一份 schema。`contracts/`、`agent/`、`orchestration/`、采集/检索/存储模块不能 import FastAPI。`bootstrap.py` 负责唯一组装，FastAPI lifespan 和 CLI 生命周期都调用它。

根目录 `web/` 是未来独立前端工程的位置，后续经 HTTP 调用 FastAPI。当前不生成页面、组件、前端状态库、占位前端工程或第二套 Node 后端；现有前端不作为必须保留的实现。默认状态查询轮询已足够，当前不因未来 UI 预建 SSE/WebSocket 模块。

新业务词汇以 spec 为准：`ResearchTask.resume()` 恢复同一任务，`Citation` 表示可定位的材料，不附带旧 `Evidence` 的语义审核结论。旧 `ResearchRun`、Conversation、Fact 审核/报告发布工作流不是本次范围，不为保持旧模型而复制它们；T19 更新根 `CONTEXT.md` 与架构说明。

### 3.2 本地目录、配置和数据生命周期

- `configs/default.yaml` 与 `configs/low-resource.yaml` 保存可提交、无凭据的完整/低资源配置；实际部署可显式指定其他配置文件，密钥通过环境变量注入。
- `data/research.sqlite` 保存业务、任务与索引状态；`data/resources/` 保存原件/派生件的内容寻址文件；`data/tmp/<task_id>/` 保存临时文件；`data/logs/` 保存脱敏日志。
- `data/models/` 是可配置的本地模型缓存；`data/qdrant/` 仅用于本机 Qdrant 的数据卷。它们不是 Python 源码，也不参与 wheel/sdist；使用外部 Qdrant 或模型路径时不创建对应目录。
- `output/<task_id>/result.json` 与 `result.md` 是导出产物，SQLite 是任务权威状态，不能靠扫描 output 推断任务是否完成。
- 配置内相对路径以配置文件所在目录为基准，运行时解析为绝对路径；示例配置使用 `../data`、`../output`。CLI 与 FastAPI 无论从哪个 cwd 启动，都不能意外生成两套数据。模型路径、导入允许根、SQLite 路径按同一规则处理。
- 新库从新 schema 初始化，不承诺读取旧 `data/intel/` 和旧 state DB；发现冲突/不兼容数据库时明确报错，不能覆盖或自动清空。用户已有数据不是“取消兼容性”就授权删除的对象。
- 不实现旧文档/引用 ID 的自动转换；需要历史材料时使用正常的显式原文件导入入口重新处理。新系统内部的 revision/artifact/Chunk 稳定性和旧快照引用保持仍是必须能力。
- `storage/migrations/` 仍保留：它管理新系统自身 schema 的升级，与兼容旧引擎无关。资源先原子落盘再提交数据库，显式垃圾回收只能处理没有引用的对象。
- 文件形式改为包目录时（`agent.py → agent/`、`fetch.py → fetch/`、`storage.py → storage/`、`context.py → context/`），在同一任务内迁出需要复用的行为并移除冲突旧文件，避免同名模块/包导入歧义。旧 `src/intel_agent/web/` 由新 `api/` 取代。此处是实施步骤，本次不移动现有文件。

### 3.3 具体依赖选择

| 能力 | 计划使用 | 原因与限制 |
| --- | --- | --- |
| 校验、LLM | 已有 Pydantic / Pydantic AI | 保留已锁定主版本；关闭 SDK 隐含格式/网络重试，计数归显式执行层 |
| HTTP | 已有 HTTPX，显式声明 HTTPCore 直接依赖 | 以 NetworkBackend 控制已验证 IP 的连接，保留 Host/TLS SNI；不继续自写 chunked HTTP 解析器 |
| HTML | Trafilatura + BeautifulSoup | 两个真实可选择 Adapter；保留结构，选择完整产物，禁止全文拼接 |
| PDF | 已有 PyMuPDF + pdfplumber | 两个真实文本/表格/几何位置后端；扫描页交给 OCR，不声称 pdfplumber 自带 OCR |
| OCR | 复用现有 Tesseract，读取 TSV/hOCR | 使用 `chi_sim`、`eng` 语言数据及矩形/置信度输出；不再只取 stdout 纯文本 |
| Office | 已有 python-docx / python-pptx / openpyxl | 各格式真实结构 Adapter；公式缓存缺失不能当计算结果 |
| 媒体/ASR | 现有 FFmpeg / FFprobe + faster-whisper | 显式本地模型目录、CPU 首先验证；新增分段与多通道语义 |
| 关键词 | sqlite3 + FTS5，确定性中英文 token 预处理 | 中文字符 unigram/bigram 与英文词分开编码到 FTS；固定 profile，真实中文检索测试 |
| 向量 | qdrant-client + 配置的 embedding Adapter | 使用实际 Qdrant；模型 ID/版本/维度隔离；embedding 用已有 HTTPX 对配置端点调用 |
| TokenCounter | 对实际模型绑定的 tiktoken 或本地 tokenizer 文件 | 已有传递依赖需在直接使用时声明；未知模型不得退回字符数猜测 |
| 进程/任务锁 | 标准库进程管理 + Windows Job Object / 文件锁 Adapter | POSIX 与 Windows 实际差异是抽象的理由；仅有一个实现的普通业务类不造额外接口 |

spec §8 的 Docling、PaddleOCR 是候选映射，并非指定依赖。因此选择 pdfplumber 和已使用的 Tesseract 不删减能力、不改变 Backend 契约；真实夹具若不能达到 A09–A12，替换相应 Adapter 并重新锁定 profile，不能降低验收标准。不增加分布式调度、插件发现、通用工作流框架或默认 reranker。

核验依据（查阅日期 2026-09-05；并不代表已完成本项目集成）：[HTTPCore NetworkBackend](https://www.encode.io/httpcore/network-backends/) 支持在网络执行层替换连接行为；[HTTPX transport](https://www.python-httpx.org/advanced/transports/) 提供可注入 transport。[pdfplumber](https://github.com/jsvine/pdfplumber) 提供字符、页面与表格信息；[Tesseract 输出格式](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html) 包括 TSV/hOCR。[Qdrant points](https://qdrant.tech/documentation/manage-data/points/) 接受 UUID/无符号整数并支持幂等覆盖，故使用确定性 UUID，而不是任意 hash 字符串。[Playwright 网络文档](https://playwright.dev/python/docs/network) 说明 proxy 与 Service Worker 限制，但路由拦截本身不构成完整出口隔离的证明。[faster-whisper](https://github.com/SYSTRAN/faster-whisper) 的 CPU/GPU 安装要求分别核验。OpenAlex 认证与配额以[官方接口文档](https://help.openalex.org/api/)为准，配置可选 key，不复用旧的“一律拒绝凭据 Provider”策略。

Browser 部署选择依据：[Docker Compose 的 internal network](https://docs.docker.com/reference/compose-file/networks/) 可隔离外部网络；[Squid ACL 文档](https://www.squid-cache.org/Doc/config/acl/) 提供目标地址规则。T06 使用支持该配置的 Squid 7 系列并锁定实际测试补丁版/镜像，不盲目使用 latest；仍需 A06 的实际出口测试，文档支持不等于部署已经安全。

### 3.4 公共契约的必要补充

下列均为实现补充，进入 T01 契约测试；spec 的字段和语义不能移除。

| 补充 | 用途 |
| --- | --- |
| `FetchRequest.allow_media: bool = False` | 承接 §14 显式媒体下载许可；仅验证 MIME/签名后允许 1 GiB，否则仍为普通资源上限 |
| `ProviderCapabilities`；`SearchProvider.capabilities` | 暴露支持/可靠后过滤/不支持的条件；不通过任意 kwargs 隐藏能力 |
| `SearchOccurrence.metadata: JsonValue` | 保存合并前标题、日期和诊断；不改变 occurrence 的 rank/score 语义 |
| `OperationContext(task_id, work_item_id, deadline_at)` | 基础设施注入持久尝试记录和预算。Service 公共方法沿用 §5，操作上下文由显式 `operation(...)` 上下文管理器绑定；未绑定即拒绝执行需持久预算的操作 |
| `ResourceStore.write_stream(chunks, *, origin, media_type, max_bytes, parent_resource_id=None, transform=None) -> Resource` | 流式保存远程/派生资源；不把本地导入伪装 HTTP，也不把 path 当外部资源引用 |
| `MaterialStore` 的工作项、scope 保存与索引状态方法 | 放在具体类的内部编排 Interface，详见 T02/T14/T18；不另立通用 Repository 框架 |
| `IndexReport`、`AcquisitionReport`、`BudgetUsage`、`Checkpoint` | 明确 lexical/vector 分离状态、逐工作项状态和恢复数据，不使用无结构字典承载这些必需语义 |

存储采用 spec 允许的同步业务 Interface：一次完整事务在受控线程内执行，连接在该线程内创建/关闭。异步调用方通过 `await asyncio.to_thread(store.method, ...)` 执行，统一用 runtime 的并发限额约束；不在事件循环里直接执行大范围 SQL，也不把单一连接跨线程共享。ResourceStore 的导入/写入为 async，`open()` 返回可关闭的受控二进制流。

## 4. 文件责任与依赖顺序

只在任务需要时创建文件，不提前建立空目录树。下列路径以 `src/intel_agent/` 为前缀；跨模块数据模型只保留一份定义。

| 路径 | 唯一责任 | 首次任务 |
| --- | --- | --- |
| `contracts/resources.py`, `contracts/documents.py`, `contracts/research.py`, `contracts/errors.py`, `contracts/ports.py` | 资源、证据/版本、任务/决策、错误与真正可替换端口 | T01 |
| `runtime/config.py`, `runtime/limits.py`, `runtime/execution.py`, `runtime/logging.py` | 配置与 profile、预算/尝试账本接入、可终止进程、脱敏事件 | T01/T03 |
| `storage/sqlite.py`, `storage/materials.py`, `storage/resources.py`, `storage/migrations/001_initial.sql` | 事务、材料身份/范围、字节文件、schema | T02 |
| `search/models.py`, `search/service.py`, `search/providers/{searxng,arxiv,openalex,rss}.py` | 多来源查询、Provider Adapter、保守 dedup/RRF（先放 service 内） | T04 |
| `fetch/models.py`, `fetch/security.py`, `fetch/transport.py`, `fetch/service.py`, `fetch/browser.py` | 公网出口、流式 HTTP、抓取路由、浏览器生命周期 | T05/T06 |
| `extraction/models.py`, `extraction/service.py`, `extraction/backends/{html,pdf,ocr,office,media,asr}.py`, `extraction/{audio,video}.py` | 后端能力/尝试、格式路由、文档/媒体解析 | T07–T11 |
| `normalization.py`, `indexing/{models,chunking,lexical,service,embedding}.py`, `storage/qdrant.py` | 纯规范化、持久切块、关键词、可恢复向量写入 | T12–T14 |
| `context/{models,retrieval,manager,formatter}.py` | 固定范围召回、最终 token 预算和引用 | T15 |
| `acquisition.py` | FETCH → EXTRACT → NORMALIZE → STORE（可选 INDEX）工作项推进 | T16 |
| `agent/researcher.py`, `orchestration/{state,orchestrator}.py` | 模型决策 Adapter、确定性状态机 | T17/T18 |
| `bootstrap.py`, `application.py`, `cli.py`, `__main__.py` | 唯一组装、任务提交/取消/关闭、CLI | T19 |
| `api/app.py`, `api/dependencies.py`, `api/schemas.py`, `api/errors.py`, `api/routes/{health,tasks,materials}.py` | FastAPI 生命周期、HTTP 契约、错误与路由 | T19 |

T01 同时建立必要的 `__init__.py` 和共享 `tests/conftest.py`；纯模型与策略测试放 `tests/unit/`，真实存储/Provider/backend 组合测试放 `tests/integration/`，HTTP 测试放 `tests/api/`，整流程测试放 `tests/e2e/`，真实夹具放 `tests/fixtures/`。下列 T01–T18 的测试路径为首个回归锚点；含真实 I/O 的用例在对应任务内分到 integration，并同步命令。旧测试按需求语义迁入或删除，不保留仅验证旧接口形状的兼容测试。

| Milestone | 任务 | 必须交出的结果 | 前置 |
| --- | --- | --- | --- |
| M1 | T01–T03 | 契约、资源/身份、SQLite、执行和预算基础 | 无 |
| M2 | T04–T06 | 四 Provider、HTTP/browser、完整网络策略 | M1 |
| M3 | T07–T09 | HTML 双后端、PDF 双后端、OCR、Office | M1 |
| M4 | T10–T11 | 音频分段、视频字幕/ASR/帧 OCR | T03、T08 |
| M5 | T12–T14 | 不可变标准文档、Chunk、lexical/Qdrant、恢复 | T02；T07–T11 的契约样本 |
| M6 | T15 | 同范围四路检索、预算及精确引用 | M5 |
| M7 | T16–T19 | 采集、研究循环、resume、共享应用入口、CLI/FastAPI | M2–M6 |
| Release gate | T20 | A01–A27 全矩阵、Windows 实测与交接 | M1–M7 |

M2 与 M3、T12 的纯转换逻辑可以在契约固定后独立推进。M4 不能推迟到“后续版本”；M7 的文本闭环只是一项中间验证。默认逐任务执行，是否采用并行 agent 由用户后续选择。

## 5. 逐任务实施

每个任务按“写失败测试 → 运行确认失败 → 最小实现 → 回归通过 → scoped commit”执行。下列代码块给出关键可运行测试或算法锚点；相邻文字中的场景同样是交付要求，不能只实现示例 happy path。每个任务里按格式/失败场景逐个完成这个循环，不先写完整模块再补测试。

### T01 / M1：稳定契约、配置和 profile 身份

**Files:** 创建 §4 的 contracts、`search/models.py`、`fetch/models.py`、`extraction/models.py`、`indexing/models.py`、`context/models.py`、`runtime/config.py`；创建 `tests/unit/test_contracts.py`、`tests/unit/test_config.py`、`tests/conftest.py`；修改 `pyproject.toml` 的测试 marker 配置。

**Interfaces:** 完整实现 spec §4/§5/§8.2 的模型；`profile_id(config: JsonValue) -> str`；`ResearchSettings`；`load_settings(path: Path) -> ResearchSettings`。`contracts/ports.py` 只定义 SearchProvider、Extractor/Backend、LLMClient、EmbeddingClient、TokenCounter、VectorIndex 等实际变化点，不为唯一的 Normalizer/Orchestrator 再造 Protocol。

- [ ] 先写 locator、决策互斥、JsonValue、时区、正数限制与序列化测试：

```python
import pytest
from pydantic import ValidationError
from intel_agent.contracts.documents import Locator
from intel_agent.contracts.research import ResearchDecision


def test_invalid_locations_and_decisions_are_rejected():
    for fields in (
        {"page": 0},
        {"start_ms": 20, "end_ms": 10},
        {"bbox": (0.8, 0.0, 0.2, 1.0)},
    ):
        with pytest.raises(ValidationError):
            Locator(**fields)
    with pytest.raises(ValidationError):
        ResearchDecision(
            action="search",
            queries=[],
            source_types=["web"],
            evidence_gaps=[],
            reason="Need evidence",
        )
```

- [ ] 运行 `uv run pytest tests/unit/test_contracts.py -q`，先确认因新模型不存在而失败。
- [ ] 用 Pydantic 校验结构；纯校验器拒绝矛盾位置、naive datetime、非 JSON metadata、无效日期范围、未知配置项。将 §14 的全部数值写进一个 typed settings 定义，并加入参数化测试。profile 采用 canonical JSON + SHA-256，包含实际后端/模型/tokenizer 版本、语言数据 hash、变换/分段/阈值；排除凭据、路径和运行耗时。

```python
def profile_id(config):
    payload = json.dumps(
        config,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] 验证同配置不同 key 顺序 ID 相同，换后端版本 ID 不同；JSON round-trip 等价；导入新 package 不联网、不加载模型。注册 `integration`、`real_backend`、`windows` marker；marker 不自动等于可跳过必需验收。
- [ ] 提交 `feat(research): define versioned contracts and configuration`，只暂存上述路径。

### T02 / M1：流式资源、不可变身份和事务存储

**Files:** 创建 `storage/resources.py`、`storage/sqlite.py`、`storage/materials.py`、`storage/migrations/001_initial.sql`；创建 `tests/unit/test_resource_store.py`、`tests/unit/test_material_store.py`；扩展 `tests/conftest.py`。

**Interfaces:** `ResourceStore(root: Path, allowed_import_roots: list[Path], store: MaterialStore)` 提供 import_file/open/write_stream；`MaterialStore(db_path: Path)` 提供 spec §5 全部存储方法。补充 `register_resource(resource) -> None`、`create_task(question) -> ResearchTask`、`save_scope(scope) -> None`、`get_scope(scope_id) -> MaterialScope`、`get_resource(resource_id) -> Resource`；资源文件完成后由 ResourceStore 调用同一 MaterialStore 登记元数据，确保 resolve_revision 可查询该资源的 hash。具体 task/work/index 方法在 T03/T14/T18 扩充，同一份库实现。conftest 提供临时库 `material_store`、引用该库的临时资源根 `resource_store`，仅使用 `tmp_path`。

- [ ] 写事务幂等、来源不同内容相同、越界导入、symlink、流式超限和取消清理测试：

```python
async def test_same_bytes_share_revision_but_not_document(
    material_store, resource_store, tmp_path
):
    path = tmp_path / "input.txt"
    path.write_text("研究材料", encoding="utf-8")
    resource = await resource_store.import_file(path)
    left = material_store.resolve_identity("https://example.org/a")
    right = material_store.resolve_identity("https://example.org/b")
    revision = material_store.resolve_revision(
        left.document_id, resource.resource_id
    )
    assert revision == material_store.resolve_revision(
        left.document_id, resource.resource_id
    )
    assert left.document_id != right.document_id
```

- [ ] 运行 `uv run pytest tests/unit/test_resource_store.py tests/unit/test_material_store.py -q` 确认 RED。
- [ ] 按 spec §9.2 建 resources/documents/revisions/artifacts/provenance/blocks/chunks/task_materials/index_jobs/tasks/work_items；另建 scopes/scope_artifacts、attempts、budget_reservations。FK 开启，source_key、revision identity、artifact identity、task association 使用唯一约束；schema 变更在事务中提交。资源元数据不可因共享 blob 而覆盖不同 origin/parent；仅字节文件按 hash 共享。

```sql
CREATE UNIQUE INDEX revision_identity
ON revisions(document_id, content_hash);
CREATE UNIQUE INDEX artifact_identity
ON artifacts(revision_id, extraction_profile_id, normalizer_version, manifest_hash);
CREATE UNIQUE INDEX task_artifact_identity
ON task_materials(task_id, artifact_id);
```

流式写入在目标文件系统建立临时文件，逐块计算 hash/bytes、检查大小，flush/fsync 后 replace，再提交资源记录。失败清理临时文件；已提交文件保留。scope 先约束 task_id，再按每 document 最近接纳顺序固定 artifact，不能用全库最新版本。空 scope 必须表示零材料。
- [ ] 验证 SQLite rollback 不暴露半个文档；第二个连接并发重试返回同一身份；保存新 artifact 后旧 scope 不变；重启后流可关闭、hash 可核验。运行存储测试和 `tests/test_storage.py`。
- [ ] 提交 `feat(research): persist immutable materials and resource blobs`。

### T03 / M1：持久预算、受控执行和事件

**Files:** 创建 `runtime/limits.py`、`runtime/execution.py`、`runtime/logging.py`；修改 `storage/materials.py`；创建 `tests/unit/test_limits.py`、`tests/unit/test_execution.py`、`tests/unit/test_events.py`。

**Interfaces:** `BudgetLedger.reserve(task_id, kind, amount) -> str`、`settle(reservation_id, actual) -> None`；`AttemptLedger.begin(work_item_id, stage, unit_key, limit) -> int`、`finish(...)`；`operation(OperationContext)`；`Executor.run_backend(backend_id, request) -> BackendOutput`；`Executor.run_process(argv: list[str], *, timeout_seconds: float, cwd: Path) -> ProcessResult`。账本全部由 MaterialStore 事务支撑。

- [ ] 先写竞争预留、恢复不重置、取消回收测试。使用真实短 Python 子进程代替真实重模型：

```python
async def test_timeout_terminates_owned_process(executor, tmp_path):
    marker = tmp_path / "late.txt"
    script = (
        "import time,pathlib; time.sleep(2); pathlib.Path('late.txt').touch()"
    )
    with pytest.raises(DomainError) as raised:
        await executor.run_process(
            [sys.executable, "-c", script], timeout_seconds=0.05, cwd=tmp_path
        )
    assert raised.value.code == "TIMEOUT"
    assert executor.active_process_count == 0
    assert not marker.exists()
```

本任务在 test_execution 内定义 executor fixture，创建配置了 CPU=2/GPU=1 的 Executor，并在 yield 后 close；所需 `DomainError`、`sys`、`pytest` 正常 import。
- [ ] 运行 `uv run pytest tests/unit/test_limits.py tests/unit/test_execution.py tests/unit/test_events.py -q` 确认 RED。
- [ ] 使用事务 `UPDATE ... WHERE available >= requested` 预留后再调度。deadline 保存 UTC 绝对值，运行时转成 monotonic 剩余量；阶段截止取二者较小值。崩溃遗留 reservation 按已记录调用状态结算/保守保留，不释放成额外预算；尝试在执行前递增，恢复沿用原值。
- [ ] CPU/GPU 模型在可终止 worker 内延迟加载；任务 IPC 传 resource ID 与受控路径，不传 1 GiB bytes。POSIX 使用进程组；Windows 使用 Job Object kill-on-close 管理后代，必要的 pywin32 仅在 Windows extra 添加。测试子进程再生子进程、取消、打开文件及删除临时目录、并发网络心跳；日志断言秘密参数/正文不出现，事件包含 §13.2 字段。
- [ ] 提交 `feat(research): enforce durable budgets and cancellable execution`。

### T04 / M2：标准 SearchService 与四个真实 Provider

**Files:** 创建 `search/service.py`、`search/providers/searxng.py`、`arxiv.py`、`openalex.py`、`rss.py`；修改 `search/models.py`、`runtime/config.py`；创建 `tests/unit/test_search.py`、`test_search_providers.py`，Provider 响应夹具放 `tests/fixtures/search/`。

**Interfaces:** `SearchService(providers, config, attempts).search(SearchRequest) -> SearchBatch`；各 Provider 通过构造函数接收 HTTP client/config，方法固定为 `search(query: SearchQuery, limit: int) -> list[SearchHit]`；`dedup_key(url: str, tracking_params: tuple[str, ...] = ()) -> str`。

- [ ] 写 A01–A05：使用真实 service + 本地 fake Provider 检验超时后保留成功，取消结束，空成功与全失败不同。同 Provider 重复只能贡献一次 RRF，但 occurrences 全保留。

```python
@pytest.mark.parametrize(
    "left,right",
    [
        ("https://example.org/a", "https://example.org/a/"),
        ("http://example.org/a", "https://example.org/a"),
        ("https://example.org/#/a", "https://example.org/#/b"),
    ],
)
def test_conservative_keys_do_not_merge_distinct_sources(left, right):
    assert dedup_key(left) != dedup_key(right)
```

- [ ] 运行 `uv run pytest tests/unit/test_search.py tests/unit/test_search_providers.py -q` 确认 RED。
- [ ] 显式注册四 Provider，重名报错。SearXNG/arXiv 复用旧响应解析知识，但 rank 从 1 开始，不导入旧聚合器；OpenAlex 支持配置 endpoint/key；RSS 用成熟 feed parser 对配置订阅匹配，来源类别由订阅配置决定，channel=`rss`。准确发布时间缺失时按日期规则排除；不支持且无法可靠后过滤的条件报 UNSUPPORTED_FILTER。保留 provider 内部原始标题/日期。

```python
done, pending = await asyncio.wait(calls, timeout=remaining_seconds)
for call in pending:
    call.cancel()
await asyncio.gather(*pending, return_exceptions=True)
```

上面只用于已经分别封装异常与单 Provider timeout 的任务集合；外部 CancelledError 必须清理所有子任务再向上传播。合并排序按 RRF + 稳定键；未选中的 disabled 不拖累正常启用 Provider，显式请求全部 disabled 则 failed。服务只重试临时错误，尊重 Retry-After 和剩余截止。
- [ ] Provider contract 测试覆盖分页/数量、日期日界、language、domain/exclude_domain、错误映射；注入相同 client 对四 Adapter 运行；真实服务验证留到 T20 并独立记录。新增 Provider 的测试证明只改 Adapter、注册和配置。
- [ ] 提交 `feat(research): add bounded multi-provider search`。

### T05 / M2：安全 HTTP 获取与流式资源保存

**Files:** 创建 `fetch/security.py`、`fetch/transport.py`、`fetch/service.py`；修改 `runtime/config.py`、`pyproject.toml`、`uv.lock`；创建 `tests/unit/test_fetch.py`、`test_network_policy.py`。

**Interfaces:** `FetchService(http_fetcher, browser_fetcher, resource_store, limits).fetch(FetchRequest) -> FetchResult`；`PublicNetworkBackend.connect_tcp(...)` 实现 HTTPCore 的 Adapter；`validate_public_url(url, resolver)` 返回已验证连接目标。一般地址策略和明确配置的基础设施 endpoint 策略分开：LLM/Qdrant/SearXNG 可以是本机，但资料 URL 不因此获得私网许可。

- [ ] 从 `tests/test_security.py`、`tests/test_document.py` 移植行为用例，不复制旧 HTTP 协议实现。新增 IPv6 mapped、DNS 重绑定、混合解析结果、跳转、TLS SNI/peer 校验与压缩炸弹。

```python
async def test_private_resolution_is_rejected():
    async def resolver(host):
        return ["127.0.0.1"]

    with pytest.raises(DomainError) as raised:
        await validate_public_url("https://source.example/report", resolver)
    assert raised.value.code == "UNSAFE_URL"
```

- [ ] 运行 `uv run pytest tests/unit/test_fetch.py tests/unit/test_network_policy.py -q` 确认 RED。
- [ ] 使用 HTTPX AsyncBaseTransport + HTTPCore AsyncConnectionPool 的可注入网络后端，复用成熟 HTTP 解析；传入已校验 IP 连接，Host/SNI 使用来源域名，校验连接 peer。重定向显式逐跳处理，`trust_env=False`，重试设为 0 交给服务；跨域丢弃认证与 cookies。

```python
async with client.stream(
    "GET", request.url, follow_redirects=False
) as response:
    resource = await resource_store.write_stream(
        bounded_decoded_chunks(response),
        origin=origin,
        media_type=media_type,
        max_bytes=effective_limit,
    )
```

`bounded_decoded_chunks` 在 transport 内定义，分别计算压缩输入和解压输出并以受限 buffer 解码，不能先由 HTTPX 解压整个大块再判断。读取有限前缀核验 MIME/签名，不吞掉该前缀；错误响应和未知媒体不得返回正常资源。allow_media=false 始终限制 50 MiB；只有显式许可且媒体类型确认后才提升到 1 GiB。
- [ ] 测试无 Content-Length、错误 Content-Length、chunked、大流、超限断流及临时文件清理；全局=8/host=2、速率=2/s burst=2 在并发中成立。网络错误与 HTTP_ERROR/BLOCKED/TIMEOUT/TOO_LARGE 区分，取消不重试。
- [ ] 提交 `feat(research): stream resources through validated HTTP transport`。

### T06 / M2：Browser 回退与可验证出口

**Files:** 创建 `fetch/browser.py`、`tests/unit/test_browser.py`、`tests/fixtures/browser/`；创建 `deploy/research-browser/compose.yaml`、`deploy/research-browser/Dockerfile`、`deploy/research-browser/squid.conf`、`deploy/research-browser/egress.nft`、`deploy/research-browser/start.ps1`；修改 `fetch/service.py`、`runtime/config.py`；在 `docs/development/js-dynamic-page-deployment.md` 添加新核心的出口要求。

**Interfaces:** `BrowserFetcher.fetch(request: FetchRequest) -> FetchResult`；`BrowserFetcher.close()`；HTTP/browser 都接收同一网络策略、资源存储和预算。抓取 route 判断只诊断页面是否需要 JS，不在 Fetch 内生成正文 EvidenceBlock。

- [ ] 写 A06/A07：HTTP app shell 只回退一次，正常短公告不回退；验证码/登录墙结合响应与结构报 BLOCKED。控制 resolver/transport 的 fixture 验证主页面、iframe、XHR、重定向、WebSocket、下载均不触达私网替身。

```python
async def test_auto_fallback_runs_once(fetch_harness):
    fetch_harness.http_app_shell()
    fetch_harness.browser_html("<article>可引用正文</article>")
    result = await fetch_harness.service.fetch(
        FetchRequest(url="https://example.org/app", mode="auto")
    )
    assert result.method == "browser"
    assert fetch_harness.browser_calls == 1
```

本任务的 `fetch_harness` 在 test_browser.py 定义：仅 fake HTTP/browser 网络返回，真实 FetchService 执行策略；记录 browser 调用数，不 mock service 自身。
- [ ] 运行 `uv run pytest tests/unit/test_browser.py -q` 确认 RED。
- [ ] 采用明确配置的受控出口代理或具备出口限制的浏览器进程环境作为完整模式前置条件；提供部署步骤和可运行阻断检查。Browser 的所有 HTTP 请求也经 policy，阻止 Service Worker、WebSocket、自动下载和额外窗口；取消关闭 page/context。不得仅凭 `browser_network_mode='isolated'` 自报已隔离。
- [ ] 完整验收部署固定为 Windows 宿主 CLI + Docker Desktop 的本机 Playwright browser/Squid 两个容器：browser 仅接内部网络，出口只允许代理端口，禁 UDP/QUIC 与直接外部 DNS；Squid 检查目标 IP，nftables 同时拒绝代理进程连接非公网目标，防止校验后重新解析绕过。HTTP/CONNECT 每次建连均校验，浏览器 control endpoint 仅绑定宿主 loopback，正文不得配置 endpoint。Squid 与防火墙的 IPv4/IPv6 拒绝集合从 T05 公网策略一致导出，测试覆盖映射地址及全部保留段；禁止 unrestricted proxy。锁定镜像 digest 与对应 Playwright 版本，提交上述部署文件和 Windows 启动步骤，声明 Docker Desktop 是该完整 browser profile 的外部前置。原生 Windows 无容器 browser 为后续部署变体，不作为本轮默认承诺。
- [ ] 运行真实 Chromium 的静态/JS/阻断 fixture，实测取消句柄回收；代理不可用时 preflight 明确不可用，绝不 fallback 直连。记录选定代理/镜像 digest、Chromium 版本及出口检查结果后提交 `feat(research): add bounded browser acquisition with controlled egress`。

### T07 / M3：Backend Registry 与双 HTML 后端

**Files:** 创建 `extraction/service.py`、`extraction/backends/html.py`；修改 `extraction/models.py`、`runtime/config.py`、`pyproject.toml`、`uv.lock`；创建 `tests/unit/test_extraction_registry.py`、`test_html_extraction.py` 与 `tests/fixtures/html/`。

**Interfaces:** `BackendRegistry.list_capabilities()/get()`，显式 `register(backend_id, backend)`；`ExtractionService.extract(Resource, profile_id) -> ExtractResult`；HTML 中 `TrafilaturaBackend.run(BackendRequest)`、`BeautifulSoupBackend.run(BackendRequest)` 返回同一 BackendOutput。

- [ ] 写注册重名、禁用/缺依赖、无导入副作用和 A08；两个真实 Adapter 对固定 HTML 的标题/段落/列表/表格运行。fixture 至少各一份中英文，正例各三条证据。

```python
@pytest.mark.parametrize("backend_id", ["trafilatura", "beautifulsoup"])
async def test_both_html_backends_keep_order(html_service, backend_id):
    result = await html_service.extract_fixture("article-zh.html", backend_id)
    assert [
        block.text
        for block in result.blocks
        if block.block_type == "paragraph"
    ] == [
        "项目于2025年启动。",
        "第一阶段覆盖三个城市。",
        "下一阶段计划扩展测试。",
    ]
```

`html_service` 为本文件 fixture：真实 registry + 两后端 + 临时 ResourceStore，extract_fixture 导入夹具并用 T01 计算选定后端的 profile；不替换后端执行。
- [ ] 运行 `uv run pytest tests/unit/test_extraction_registry.py tests/unit/test_html_extraction.py -q` 确认 RED。
- [ ] typed profile 选择首选/备用；Trafilatura 输出结构再转换为 blocks，BeautifulSoup 用 DOM 规则独立提取正文，去 script/style/nav，保留 section_path/dom_path。短有效正文不因为字符阈值被拒绝。首选失败/无正文/结构无效最多备用一次，选择一份完整产物；记录 BackendAttempt 与质量原因。
- [ ] 整项不可识别报 DomainError；空白内容为 empty；部分有效内容为 partial，取消传播。运行 A08 两后端真实夹具并保留全文不重复的断言。
- [ ] 提交 `feat(research): route extraction through real HTML backends`。

### T08 / M3：区域 OCR 与逐页双 PDF 后端

**Files:** 创建 `extraction/backends/ocr.py`、`extraction/backends/pdf.py`；修改 `extraction/service.py`、`runtime/config.py`、`pyproject.toml`、`uv.lock`；创建 `tests/unit/test_pdf_extraction.py`、`test_ocr.py`，以及 `tests/fixtures/pdf/`、`images/`。

**Interfaces:** `TesseractBackend.run(BackendRequest) -> BackendOutput`；`PyMuPDFBackend.run(...)`、`PdfplumberBackend.run(...)`；PDF 工作流在 service 内按 page/region 调度；后端只打开受控 Resource。derived page image 保留 parent resource、page、scale/rotation/crop transform。

- [ ] 写 A09–A12/A16：三页混合 PDF（原生、扫描、损坏/超时）、区域重叠、换后端 profile、新 artifact；图片旋转反映射；限制触发保留其余页。

```python
async def test_failed_page_does_not_discard_other_pages(pdf_harness):
    result = await pdf_harness.extract_with_page_failure(page=2)
    assert result.status == "partial"
    assert {block.locator.page for block in result.blocks} == {1, 3}
    assert [(u.locator.page, u.status) for u in result.coverage] == [
        (1, "success"),
        (2, "failed"),
        (3, "success"),
    ]
```

`pdf_harness` 在本任务测试中组装真实 PDF 调度与临时资源；仅对第 2 页 backend.run 注入 TIMEOUT，另有 `real_backend` 用例实际执行两个 PDF 后端及 OCR。
- [ ] 运行 `uv run pytest tests/unit/test_pdf_extraction.py tests/unit/test_ocr.py -q` 确认 RED。
- [ ] 用 PyMuPDF/pdfplumber 各自读取字符/行及表格，转换 bbox；逐页判断 native text 的异常字符、顺序及图像覆盖；扫描页和 profile 指定区域 OCR。Tesseract 以 argv 生成 TSV，用标准 csv 模块解析 word/line/置信度与矩形，关联原图变换；缺语言包和缺执行文件在 preflight 显式失败。
- [ ] 同区域 native/OCR 择优，后端置信度不跨后端直接比；空白页 empty 与失败页 failed 分开，密码/损坏分类；同单位最多两个 backend attempts，页面 fallback 与 OCR 的计数归属写进 profile，禁止多层重试。验证 500 页、25M pixels、单页 120s 与临时磁盘上限，两个 PDF 后端均在真实样本中可独立选择。
- [ ] 已完成 page/region 的 BackendOutput 清单随工作项保存到受控派生资源/单元记录，恢复只重跑未完成单元，成功块与新结果组成新 artifact。保存旧 ContextPackage 的引用不被补页覆盖；这套按单元持久化同样用于 T10 的 audio segment 和 T11 的 channel/frame。
- [ ] 提交 `feat(research): preserve page coverage and OCR evidence locations`。

### T09 / M3：Office 结构和嵌入图片

**Files:** 创建 `extraction/backends/office.py`、`tests/unit/test_office_extraction.py`；修改 `extraction/service.py`；新增 `tests/fixtures/office/`；依赖声明复用已有 media extra。

**Interfaces:** `OfficeBackend.run(BackendRequest) -> BackendOutput`，能力细分 `docx_structure`、`pptx_structure`、`xlsx_structure`；OCR 通过注入 Backend 调用，不能调用 ExtractionService 形成循环。

- [ ] 固定 DOCX 标题/段落/表格、PPTX 文本及图片、XLSX 表头/公式/合并区域的 fixture；每种格式中英文各一份。写超压缩大小、损坏页/表和旧二进制格式拒绝测试。

```python
async def test_uncached_formula_is_not_a_value(office_harness):
    result = await office_harness.extract_fixture("formulas.xlsx")
    cells = [b for b in result.blocks if b.locator.cell_range == "B2"]
    assert cells[0].metadata["formula"] == "=A2*2"
    assert cells[0].metadata["cached_value"] is None
    assert "uncalculated_formula" in result.warnings
```

`office_harness` 组装真实 OfficeBackend 与资源库；`formulas.xlsx` 预先保存 A2=3、B2 公式且无缓存，不在测试中调用计算引擎。
- [ ] 运行 `uv run pytest tests/unit/test_office_extraction.py -q` 确认 RED。
- [ ] 用 python-docx 按正文顺序遍历段落与表格；PPTX 保留 slide 和 shape 顺序；XLSX 同时读取公式表达式与已有缓存并保留 sheet/cell_range，按行流式读取。嵌入图片按 profile 走 OCR，并保留宿主段落/slide/sheet 位置。ZIP 预检累计声明大小和实际读取上限，不只信 header。
- [ ] 缺一页/表/图片通道不丢其他输出；表格恢复不可靠时降为文本并 warning，不造结构；默认 `.doc/.ppt/.xls` 报 UNSUPPORTED_MEDIA。运行与 T08 共用的取消/磁盘/像素限制测试。
- [ ] 提交 `feat(research): retain Office structure and embedded image evidence`。

### T10 / M4：音频探测、分段 ASR 与原始时间映射

**Files:** 创建 `extraction/backends/media.py`、`extraction/backends/asr.py`、`extraction/audio.py`、`tests/unit/test_audio_extraction.py`；修改 extraction registry；新增 `tests/fixtures/audio/`。

**Interfaces:** `FFmpegBackend.run(BackendRequest)` 输出轨道探测或派生 Resource；`WhisperBackend.run(...)` 输出带 `[start_ms,end_ms)` 的块；`AudioExtractor.extract(Resource, profile_id) -> ExtractResult`；`offset_locator(locator: Locator, offset_ms: int) -> Locator` 在 audio.py 内实现。

- [ ] 用 WAV/MP3 中英文、静音、一个失败段写 A13/A16。先验证变换，防止转写时间从每段 0 起错绑原始资源：

```python
def test_segment_time_is_mapped_to_original_audio():
    result = offset_locator(Locator(start_ms=500, end_ms=1500), 30_000)
    assert (result.start_ms, result.end_ms) == (30_500, 31_500)
```

- [ ] 运行 `uv run pytest tests/unit/test_audio_extraction.py -q` 确认 RED。
- [ ] FFprobe 校验时长/轨道/可解码能力，FFmpeg 将音轨分为约 30s 段，overlap 及时间 offset 明确写入 profile/transform；每段独立状态与最多两次后端尝试。ASR 本地模型路径和 hash/version 进入 profile，不自动联网下载。
- [ ] 使用明确配置的 VAD/no-speech 策略，静音为 empty；中英文自动识别与显式语言均测试，不生成说话人标签。重叠文本按时间/文字对齐去重，失败段与覆盖缺口持久化；单段 180s、总时长 60min、总解析 30min 及取消强制回收。真实识别检查预标注三条证据及 ±2s 语音锚点。
- [ ] 提交 `feat(research): transcribe bounded audio segments with provenance`。

### T11 / M4：视频字幕、ASR、帧 OCR 与 coverage

**Files:** 创建 `extraction/video.py`、`tests/unit/test_video_extraction.py`；扩展 `extraction/backends/media.py`；新增 `tests/fixtures/video/`；修改 registry/profile 配置。

**Interfaces:** `VideoExtractor.extract(Resource, profile_id) -> ExtractResult`，构造注入 media、asr、ocr Backend；`sample_times(duration_ms: int, interval_ms: int, max_frames: int) -> list[int]`。

- [ ] 先写 A14–A16：有字幕、字幕缺口、无字幕、无音轨、失败 OCR 通道、字幕/ASR冲突、重复帧。固定采样不能越过媒体尾部：

```python
def test_sampling_is_bounded_and_uses_original_time():
    assert sample_times(12_000, 5_000, 720) == [0, 5_000, 10_000]
    assert sample_times(12_000, 5_000, 2) == [0, 5_000]
```

- [ ] 运行 `uv run pytest tests/unit/test_video_extraction.py -q` 确认 RED。
- [ ] FFprobe 区分字幕/音轨；选定语言有效字幕优先，缺口补 ASR，always_asr 为显式配置。文本字幕保留时间，图像字幕走 OCR；帧按 5s 抽样最多 720，OCR 块保留 frame_ms+bbox、派生帧与父视频关联。sample_times 截断时必须另有 coverage warning 记录遗漏尾段。
- [ ] 独立执行三通道，再按时间稳定排序；相邻重复帧文本合并展示范围，metadata 保留全部原帧引用，字幕与 ASR 冲突不无标签拼接。一条通道失败另一条有效为 partial，无音轨不阻止帧 OCR；完整采样结果也注明不是逐帧理解。真实 MP4/WebM 记录实际 codec 与时长，定位容差不超过采样间隔。
- [ ] 提交 `feat(research): align video subtitles speech and frame evidence`。

### T12 / M5：纯 Normalize 与可复现 Chunk

**Files:** 创建 `normalization.py`、`indexing/chunking.py`；修改 `storage/materials.py`；创建 `tests/unit/test_normalization.py`、`test_chunking.py`、`tests/fixtures/contracts/document.json`。

**Interfaces:** `Normalizer.normalize(NormalizationInput) -> NormalizedDocument`；`chunk_document(document, profile, counter: TokenCounter) -> list[Chunk]`；`artifact_manifest(document) -> JsonValue`；MaterialStore `save_document()` 同事务保存 blocks/provenance/association/pending index job。测试中 `normalization_input` fixture 用 T02 真实资源与身份、三个 EvidenceBlock 组装，不 fake 身份计算。

- [ ] 写 A17/A23 的 identity、恢复补页、诊断变化不换 artifact、后端版本变化换 artifact；Chunk 的精确 Unicode span、标题附着、超长块、跨页、多行表格与 overlap。

```python
def test_attempt_timing_does_not_change_artifact(normalization_input):
    normalizer = Normalizer(version="1")
    original = normalizer.normalize(normalization_input)
    retried = normalization_input.model_copy(deep=True)
    retried.result.warnings.append("attempt_elapsed_ms=100")
    assert normalizer.normalize(retried).artifact_id == original.artifact_id
```

- [ ] 运行 `uv run pytest tests/unit/test_normalization.py tests/unit/test_chunking.py -q` 确认 RED。
- [ ] 使用 NFC、统一换行和段落空白，保留原文语义，绝不总结或依 query 删正文。artifact manifest 只包含有序块、位置、coverage 的稳定语义，剔除 attempts/耗时/瞬态诊断；backend/profile/version 独立参与身份。block ID 在规范化后确定，Chunk 的字符偏移以保存的标准 block 为准。

```python
span_text = block.text[span.char_start : span.char_end]
assert 0 <= span.char_start < span.char_end <= len(block.text)
```

- [ ] Chunk 按结构生成，600/900/80 由 profile 控制；跨页必保留每个 span，表头重复展示需映射到原表头 span；超长行切分后仍保留 cell_range。重建同 profile 的 chunk_id/ordinal/text/span 完全一致，更换 profile 不覆盖旧 chunks。`save_document` 幂等但允许新增独立 attempt 记录；不原地改写旧 snapshot。
- [ ] 提交 `feat(research): normalize versioned artifacts and stable chunks`。

### T13 / M5：任务范围内 direct 与中文 lexical

**Files:** 创建 `indexing/lexical.py`、`context/retrieval.py`；扩展 `storage/migrations/` 与 `storage/materials.py`；创建 `tests/unit/test_lexical_retrieval.py`、`test_scoped_retrieval.py`。

**Interfaces:** `lexical_tokens(text: str) -> list[str]`；`DirectRetriever.retrieve(query, scope, top_k)`；`LexicalRetriever.retrieve(query, scope, top_k)`；存储 `read_chunks(scope)` 与 `search_lexical(query_tokens, scope, top_k)`。top_k 必须在允许 artifact 集内计算。

- [ ] 写 A20/A21：两个 task 的高分相似材料，任务外全部更高分也不能挤走任务内结果；空 scope 返回空；中文长文本内的短 query 可匹配。

```python
def test_chinese_query_shares_index_terms_without_spaces():
    query = set(lexical_tokens("动力电池"))
    body = set(lexical_tokens("我国动力电池产业规模持续增长"))
    assert query <= body
```

- [ ] 运行 `uv run pytest tests/unit/test_lexical_retrieval.py tests/unit/test_scoped_retrieval.py -q` 确认 RED。
- [ ] 中文字符 unigram/bigram 转成带类型前缀的 ASCII token（避免 FTS 再次拆中文）；英文按 Unicode 词及 casefold 处理。正文与 query 同一 profile；不要复用旧 query planner 的非确定 list(set) 或长短中文不一致规则。FTS 输入参数化并转义表达式，不拼用户 SQL。
- [ ] SQLite 查询通过固定 scope 关联与 FTS join 在 LIMIT 前约束，日期按发布时间 UTC 日历日且未知日期默认排除；所有 four-path filters 最终来自一次 resolve_scope。read_chunks 分批，不加载全库。FTS5 不可用时 preflight 报依赖不可用，不假装 lexical ready。
- [ ] 提交 `feat(research): retrieve Chinese and English evidence within task scope`。

### T14 / M5：真实 Qdrant、embedding 与可恢复索引

**Files:** 创建 `indexing/service.py`、`indexing/embedding.py`、`storage/qdrant.py`；修改 `context/retrieval.py`、`storage/materials.py`、`runtime/config.py`、`pyproject.toml`、`uv.lock`；创建 `tests/unit/test_index_recovery.py`、`test_qdrant.py`。

**Interfaces:** `IndexingService.index(artifact_id) -> IndexReport`；`EmbeddingClient.embed(texts, profile_id) -> EmbeddingBatch`；VectorIndex 三个方法保持 spec §5；`vector_point_id(chunk_id, profile_id) -> str`；存储 `claim_index_batch()/record_index_batch()/mark_index_ready()/ready_artifact_ids(scope, profile_id)`。任务 key 包含完整 chunk+embedding profile。

- [ ] 写 A18/A19/A21/A23/A26：SQLite 已提交后 Qdrant 不可用；upsert 成功但 ready 提交前崩溃；重试累计 3 次；错误维度、数量、NaN/Inf 与未知 profile；真实 collection 测试。

```python
def test_vector_id_is_stable_uuid():
    value = vector_point_id("chunk-a", "embedding-v1")
    assert str(uuid.UUID(value)) == value
    assert value == vector_point_id("chunk-a", "embedding-v1")
    assert value != vector_point_id("chunk-a", "embedding-v2")
```

最小实现使用 `str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([profile_id, chunk_id])))`；算法版本固定并测试。
- [ ] 运行 `uv run pytest tests/unit/test_index_recovery.py tests/unit/test_qdrant.py -q` 确认 RED。
- [ ] 保存 Chunk/FTS ready 在 SQLite 事务完成；embedding 按固定批次，向量验证后 upsert `wait=True`，所有批次确认才标 vector ready。模型及维度隔离 collection，payload 带 spec 的四类 ID；使用 keyword payload index 过滤 artifact。保存批次进度、累计尝试、错误和模型 profile，不为每次 resume 新建工作账本。
- [ ] VectorRetriever 先求 scope ∩ 当前 profile ready artifacts，再在 Qdrant filter 内 Top K，之后向 SQLite 复查 scope/ready/chunk identity。hybrid 独立 lexical/vector 排名做 RRF，确定性 tie-break；向量失败显式 warning、实际 method=`lexical`；无索引的小范围材料通过 direct。故障恢复测试保证旧 chunk/citation 可读、无重复 points。
- [ ] 提交 `feat(research): recover durable Qdrant indexing and hybrid retrieval`。

### T15 / M6：Context 的固定范围、最终预算和引用

**Files:** 创建 `context/manager.py`、`context/formatter.py`；扩展 `context/retrieval.py`；创建 `tests/unit/test_context.py`、`test_citations.py`；修改 tokenizer 直接依赖声明及锁文件。

**Interfaces:** `ContextManager.build(ContextRequest) -> ContextPackage`；`format_context(chunks, citations, warnings) -> str`；`validate_citation_ids(ids, package) -> None`；`TokenCounter.count(text)` 绑定 model_id/tokenizer_version。Task scope 创建后整个 build 过程不重新 resolve。

- [ ] 写 A20/A22/A23：极小预算、单超长块、表格、不同来源、scope 更新竞争、虚构 ID；用真实目标 tokenizer 计数包含标题/分隔/引用的最终文本。

```python
async def test_final_text_and_citation_spans_fit_budget(context_harness):
    package = await context_harness.build(query="动力电池", max_tokens=96)
    assert package.token_count == context_harness.counter.count(
        package.formatted_text
    )
    assert package.token_count <= 96
    for citation in package.citations:
        assert context_harness.displayed_text(
            citation
        ) == context_harness.source_slice(citation)
```

`context_harness` 在本任务定义：真实 SQLite/Chunk/ContextManager、确定性的注入检索排序和 tokenizer；displayed_text/source_slice 由 formatter 展示记录与标准 block 独立读取比较。
- [ ] 运行 `uv run pytest tests/unit/test_context.py tests/unit/test_citations.py -q` 确认 RED。
- [ ] 先读轻量大小/索引元数据，只有有机会放入预算才读取全 scope 分批内容；精确格式化后能容纳走 direct，否则 scoped retrieval。默认规则近似去重与域名/文档软多样性，只有一个来源时不丢证据；无需新增 reranker 依赖。
- [ ] direct 的分批读取累计超过可容纳范围就停止，并切换 scoped retrieval；不能因为初始估计偏小而把大 scope 全部读入内存。
- [ ] 最终 format 后 count，优先移除末尾低排名整块；仅单块必要时按块/句/表格行边界裁剪，并同步建立缩小的 BlockSpan/Locator。引用映射稳定 `[C1]`，不能截断 marker。零预算/容不下任何内容返回空 text、零 tokens 和结构化 warning；不要为了展示 warning 超预算。缺匹配 tokenizer 在 preflight/构建时报错。
- [ ] 保存 scope 与 ContextPackage 的引用映射快照；恢复后相同引用仍解析到相同 resource/artifact/span。提交 `feat(research): build token-bounded context with immutable citations`。

### T16 / M7：唯一 AcquisitionPipeline 与单项恢复

**Files:** 创建 `acquisition.py`、`tests/unit/test_acquisition.py`；扩展 `storage/materials.py` 的 work item 方法。

**Interfaces:** `AcquisitionPipeline.acquire(task_id: str, source: SearchHit | Resource, profile_id: str, *, index_after_store: bool = False) -> AcquisitionReport`；`resume_item(work_item_id: str) -> AcquisitionReport`。构造注入 FetchService、ExtractionService、Normalizer、MaterialStore、IndexingService，不含 LLM。

- [ ] 写 batch 中一项失败不影响另一项、已 fetch 重启不重下载、已 store 不重解析、local import 不走 HTTP、两种 index 配置不会重复执行。

```python
async def test_resume_after_store_only_indexes(acquisition_harness):
    work_item_id = await acquisition_harness.stop_after_store()
    report = await acquisition_harness.pipeline.resume_item(work_item_id)
    assert report.artifact_id is not None
    assert acquisition_harness.fetch_calls == 1
    assert acquisition_harness.extract_calls == 1
    assert acquisition_harness.index_calls == 1
```

`acquisition_harness` 本任务定义：真实工作项持久化 + deterministic 网络/解析/索引 Adapter 的计数器；stop_after_store 使用 `index_after_store=True`，在保存之后模拟进程中断并用新 pipeline 实例恢复，不靠旧对象内存状态。另测 false 时恢复不会自行索引，只交给 Orchestrator INDEX 阶段。
- [ ] 运行 `uv run pytest tests/unit/test_acquisition.py -q` 确认 RED。
- [ ] 按 FETCH/EXTRACT/NORMALIZE/STORE 状态持久推进，每步保存 resource/artifact/attempt；同 work item 恢复检查已提交事实而非仅相信阶段字符串。DomainError 存到单项 report，unknown exception 使单项 failed 并留诊断；取消清理后向上传播。只有可恢复的未完成阶段执行，不额外包服务重试。
- [ ] Orchestrator 入口 index_after_store=false，INDEX 阶段统一索引；独立 import true。在 STORE 事务中建立 task_materials，允许 partial artifact 接纳并披露 coverage；仅新内容版本计入 no-progress 判定，单纯重复接纳或仅索引恢复不算新增内容。
- [ ] 提交 `feat(research): unify acquisition and per-item recovery`。

### T17 / M7：受约束 ResearchAgent 和模型使用量

**Files:** 创建 `agent/researcher.py`、`tests/unit/test_research_agent.py`；修改 `runtime/config.py` 的模型/tokenizer 配置。

**Interfaces:** `ResearchAgent.decide(task, context) -> ResearchDecision`；具体 `PydanticLLMClient.generate_decision(task, context, remaining_output_tokens) -> DecisionResponse`；每次调用前 reserve，响应后结算 input/output tokens；decide 通过注入 usage recorder 记录真实响应使用量，不改变公共返回值。

- [ ] 用 Pydantic AI 的测试模型/FunctionModel 写有效 finish/search、错误 JSON、第二次仍错、未知 citation、恶意材料指令、预算不足与取消。

```python
def test_finish_cannot_cite_unknown_evidence(empty_context):
    with pytest.raises(DomainError) as raised:
        validate_citation_ids(["C999"], empty_context)
    assert raised.value.code == "INVALID_DECISION"
```

`empty_context` fixture 用合法空 scope、空 chunks/citations、formatted_text=""、token_count=0 构造 ContextPackage。工具权限测试断言 LLM 没有 Fetch/SQL/进程工具。
- [ ] 运行 `uv run pytest tests/unit/test_research_agent.py -q` 确认 RED。
- [ ] 用已有 Pydantic AI 结构化输出能力；关闭自动输出重试与 HTTP 重试，显式最多一次修复，且格式/引用错误共享单次修复额度，不能两个地方各修一次。提示将材料全部标为不可信 data，模型只输出 action/queries/gaps/reason/draft/citations。
- [ ] 发送前按实际模型上下文减去系统/任务/历史/预留输出，剩余再给 Context；输入输出总计以及修复调用计入 10 calls / 100000 tokens。无可用预算不为结束语再请求模型；提供最近草稿或确定性摘录。返回的 model_id、tokens 与调用记录对应，完整正文不进入普通日志。
- [ ] 提交 `feat(research): constrain research decisions and account for model usage`。

### T18 / M7：研究状态机、检查点和跨进程 resume 锁

**Files:** 创建 `orchestration/state.py`、`orchestration/orchestrator.py`、`tests/unit/test_orchestrator.py`、`test_resume.py`；扩展 `storage/materials.py` 的任务/工作项操作。

**Interfaces:** `ResearchOrchestrator.run(question: str) -> ResearchResult`、`resume(task_id: str) -> ResearchResult`；MaterialStore `save_checkpoint(task_id, checkpoint, usage)`、`load_task(task_id)`、`list_work_items(task_id)`、`record_budget_change(task_id, change)`；`TaskLock(task_id)` 使用 OS 文件锁并在进程退出释放，不能仅 `asyncio.Lock`。

- [ ] 写 A24/A25/A27 的两轮脚本决策；继续决策含下一轮查询时只调用一次 EVALUATE，不回 PLAN 再问一遍。复现每个阶段的进程中断与两个恢复者竞争。

```python
async def test_two_rounds_do_not_replan_after_evaluate(research_harness):
    result = await research_harness.run_two_rounds()
    assert result.status == "completed"
    assert research_harness.decision_actions == ["search", "search", "finish"]
    assert research_harness.searched_queries == ["first query", "gap query"]
```

`research_harness` 在本任务定义：真实 Orchestrator/SQLite/Acquisition/Context，注入三个固定 DecisionResponse、受控两个 SearchBatch 与材料字节。run_two_rounds 只调用 orchestrator.run，不直接推进状态。
- [ ] 运行 `uv run pytest tests/unit/test_orchestrator.py tests/unit/test_resume.py -q` 确认 RED。
- [ ] 实现 PLAN→SEARCH→ACQUIRE→INDEX→BUILD_CONTEXT→EVALUATE，continue 保存新 plan 后进入 SEARCH 并增加 round。checkpoint 原子保存轮次、plan、各项阶段/尝试、artifact 接纳、scope/引用、预算与原始 deadline；不能依赖模型会话历史恢复。
- [ ] 分别测试 evidence_sufficient、max_rounds、deadline、llm_budget、material_budget、no_progress、cancelled、fatal_error。预算耗尽有材料 partial，无材料且无法继续 failed；只有有效 finish 且正常流程 completed。取消底层传播，在 run/resume 最外层保存 cancelled ResearchResult 并关闭资源。锁冲突报明确领域错误，resume 不重置预算、不延长 deadline；显式增预算须持久记录变更。
- [ ] 两轮 E2E 及逐阶段恢复通过后提交 `feat(research): orchestrate durable research rounds and resume`。

### T19 / M7：唯一应用入口、CLI 与 FastAPI

**Files:** 创建 `application.py`、`bootstrap.py`、`cli.py`；替换 `__main__.py`；创建 `api/app.py`、`api/dependencies.py`、`api/schemas.py`、`api/errors.py`、`api/routes/health.py`、`api/routes/tasks.py`、`api/routes/materials.py`；创建 `configs/default.yaml`、`configs/low-resource.yaml`、`tests/unit/test_cli.py`、`tests/integration/test_application.py`、`tests/api/test_tasks.py`、`tests/api/test_materials.py`、`tests/api/test_lifespan.py`；修改 `pyproject.toml`、`README.md`、`CONTEXT.md`、`AGENTS.md`、现有架构文档和 `scripts/README.md`。

**Interfaces:** `bootstrap(settings) -> AsyncContextManager[ResearchApplication]`；`ResearchApplication.submit(question: str) -> ResearchTask`、`resume(task_id: str) -> ResearchTask`、`cancel(task_id: str) -> None`、`wait(task_id: str) -> ResearchResult`、`status(task_id: str) -> ResearchTask`、`close() -> None`；CLI `main(argv: list[str] | None = None) -> int`；FastAPI `create_app() -> FastAPI`，配置文件通过显式环境变量 `INTEL_AGENT_CONFIG` 选择。依赖从 app.state 获取，允许测试覆盖，不注册全局运行实例。

- [ ] 先写真实应用控制测试：submit 返回已持久任务，wait 获得结果；重复 resume 被任务锁阻止；cancel 与 close 确实停止应用持有的协程/worker；HTTP 客户端断开不会隐式取消已经提交的研究。
- [ ] 写 HTTP 创建/状态/结果/恢复/取消与文件上传测试，使用真实 FastAPI app、临时 SQLite 和注入的确定性研究执行器；不调用付费模型。

```python
def test_submit_returns_durable_task_without_waiting_for_research(api_client):
    response = api_client.post(
        "/api/tasks", json={"question": "动力电池回收进展"}
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    status = api_client.get(f"/api/tasks/{task_id}")
    assert status.status_code == 200
    assert status.json()["task_id"] == task_id
```

`api_client` 在 tests/api/conftest.py 定义：通过 TestClient 上下文触发真实 lifespan，注入临时配置和阻塞在测试 Event 的研究执行器。断言完成后释放 Event 并验证退出上下文回收资源；fixture 文件计入本任务。

- [ ] 运行 `uv run pytest tests/unit/test_cli.py tests/integration/test_application.py tests/api -q` 确认 RED。
- [ ] application 在事务中先创建 task 再持有可取消的 asyncio.Task；使用现有持久状态机执行，受运行槽位限制，不实现另一套数据库队列。进程中断后，已记录任务保留，显式 resume 从检查点恢复。采用单 Uvicorn worker 的本地部署，跨进程重复运行继续由 T18 的 OS task lock 阻止；启动时取得数据目录运行所有权锁，拒绝另一个 API/CLI 执行进程同时占用该目录，确保全局 CPU/GPU/网络预算不被多进程绕过。后续多 worker 再引入外部执行器，当前不引入 Celery/Redis。
- [ ] bootstrap 用 AsyncExitStack 管理 HTTP、browser、执行器与 application 关闭。FastAPI lifespan 进入同一 bootstrap，shutdown 先取消并等待任务落检查点，再关闭依赖。CLI submit 后 wait，不自己重复搭建业务对象。不把持久研究依赖于请求级 BackgroundTasks。
- [ ] 实现最小 HTTP 契约：

| Method / path | 行为 |
| --- | --- |
| `GET /api/health` | 进程可响应，不伪报模型/远端后端均 ready |
| `GET /api/capabilities` | 已配置能力、依赖状态与明确缺失项 |
| `POST /api/tasks` | 校验 question，创建并提交任务，202 + task_id |
| `GET /api/tasks` | 有上限的任务列表及稳定分页 |
| `GET /api/tasks/{task_id}` | 阶段、轮次、usage、错误摘要 |
| `GET /api/tasks/{task_id}/result` | 回答、引用与局限；未结束时明确未就绪 |
| `POST /api/tasks/{task_id}/resume` | 202；重复运行/终态不允许恢复时 409 |
| `POST /api/tasks/{task_id}/cancel` | 记录取消并请求停止，不提前伪报已清理 |
| `POST /api/tasks/{task_id}/materials` | 有大小上限的文件上传，安全落入任务临时目录后走同一导入链路 |
| `GET /api/tasks/{task_id}/materials` | 当前任务的产物、coverage、索引状态 |
| `GET /api/tasks/{task_id}/materials/{artifact_id}/resource` | 校验任务关联后流式读取原件，不接受任意本机路径 |

HTTP schema 只定义上传/创建/分页等传输特有字段；任务、材料和结果复用业务模型中适合公开的字段，不能暴露 content_ref 的本机路径或认证配置。HTTP 错误映射集中在 api/errors.py，格式错误 422、缺记录 404、冲突 409、超限 413，其余失败有稳定 DomainError code。上传文件名不能控制落盘路径，总请求/解析后文件大小均受限，整个文件不能先读入 bytes 再校验。接口默认 loopback，未来前端通过显式 CORS origins 访问。

- [ ] CLI 保留 spec 的六操作，全部使用当前新核心，无旧 flags/路由别名：

```bash
research-agent --config configs/default.yaml preflight
research-agent --config configs/default.yaml run --question "动力电池回收进展"
research-agent --config configs/default.yaml run --question "分析本地材料" --prepare-only
research-agent --config configs/default.yaml import --task-id TASK_ID --path samples/report.pdf
research-agent --config configs/default.yaml resume --task-id TASK_ID
research-agent --config configs/default.yaml status --task-id TASK_ID
research-agent --config configs/default.yaml reindex --artifact-id ARTIFACT_ID
uv run uvicorn intel_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

`TASK_ID`/`ARTIFACT_ID` 来自前一步输出；上述数据路径以配置文件为基准，CLI import 的相对输入文件路径按 CLI 当前目录解释并校验允许导入根。preflight 可以离线运行，remote readiness 未检测则明确标注。结果从同一 ResearchResult 保存 JSON/Markdown；completed=0、failed/配置错误=1、partial=2、cancelled=130。

- [ ] 分别从两个 cwd 加载同一绝对配置路径，断言数据库/资源目录相同。所有新运行数据位于 data/output，模型不写入源码包。验证 FastAPI lifespan 启停、上传越界/超限、任务/材料隔离、运行取消和应用关闭。
- [ ] 迁入仍适用的行为测试，移除旧工具循环、旧 HTTP backend、旧入口及指向它们的脚本/测试依赖；同步重写现有架构/领域文档中与新 spec 冲突的内容。旧原件、配置和运行目录不自动删除。现有 web/ 前端不维护兼容，不在本任务开发新页面；源码清理与保留材料须区分。
- [ ] `uv build` 后检查 wheel/sdist 包含业务模块、SQL migrations、CLI/FastAPI 入口及两个配置示例；在临时安装环境运行 CLI help 和 HTTP smoke，不能靠源码 PYTHONPATH 掩盖漏包。分别提交 `feat(app): unify task lifecycle for CLI and API`、`feat(api): expose research tasks and materials`，最后以 `refactor: remove superseded engine entry points` 清理旧运行依赖。

FastAPI 的生命周期使用官方推荐的 [lifespan](https://fastapi.tiangolo.com/advanced/events/)，按 [APIRouter 多文件组织](https://fastapi.tiangolo.com/tutorial/bigger-applications/) 拆分任务和材料路由；这些是 HTTP Adapter 的职责，不进入研究业务模块。

### T20 / Release gate：完整验收与切换交接

**Files:** 创建 `tests/e2e/test_acceptance.py`、`tests/fixtures/manifest.json`、`tests/fixtures/README.md`；更新本文及 `README.md`、现有能力报告 `docs/reports/intelligence-research-agent-capability-boundary-report.md`；可复核运行产物按 `experiments/AGENTS.md` 放 `experiments/`，不把大模型/运行库写入 Git。

**Interfaces:** manifest 每项包含 fixture_id、path、sha256、license/origin、language、media_type、expected evidence（三条正例）、expected locator/coverage、预先固定的容差。结果记录包含 A-ID、命令、版本、设备、耗时、峰值内存/磁盘、pass/fail/skipped/blocked 与证据路径。

- [ ] 在首次真实运行前标注夹具及容差，保护验收标准不随输出漂移；检查每类中英文、空白/静音/无通道负例，模板不是只列格式名。

```python
def test_positive_fixtures_have_reviewable_evidence(fixture_manifest):
    for fixture in fixture_manifest:
        if fixture["kind"] == "positive":
            assert len(fixture["expected_evidence"]) >= 3
            assert all(
                item["text"] and item["locator"]
                for item in fixture["expected_evidence"]
            )
```

`fixture_manifest` 为本任务从 manifest.json 读取的 fixture；此断言只验证标注完整性，真实文本检索及引用逐项通过才算验收。
- [ ] 执行全部离线测试；按下表逐项执行真实 Adapter/网络替身/崩溃恢复测试；Linux 结果和 Windows 结果单独记录，禁止将 skipped 算 passed。
- [ ] 运行完整配置的两轮真实研究及本地多模态 import → Context → Citation 复查；OCR/ASR/视频/双 HTML/双 PDF 逐个实际运行。真实 embedding + Qdrant 不能用 fake 代替。没有外部凭据/模型/Windows 环境的项明确标为“集成未验证”，这时不能宣称整个 spec 完成。
- [ ] 运行 Ruff format/check、Pyright、完整新测试矩阵、uv build；验证 Python、CLI、FastAPI 三入口使用同一任务模型与材料数据，HTTP 异步提交/取消/上传/进程关闭单独验收。迁入仍适用的旧行为测试，不将故意废弃的接口兼容性作为验收门槛；Web 页面本轮不实现，不宣称其通过验收。
- [ ] 再次检查新核心无旧业务模块反向导入、没有全文进入日志、没有隐式 SDK 重试、没有把大型资源转为整块 bytes；按引用回查原件 hash、artifact、block span 和 locator；评审后提交 `test(research): verify complete multimodal acceptance matrix`。

## 6. A01–A27 验收映射

| ID | 主任务 | 测试文件 | 除离线测试外的必要证明 |
| --- | --- | --- | --- |
| A01 | T04 | test_search_providers.py | 新 Provider 只改 Adapter/注册/配置 |
| A02 | T04 | test_search.py | 截止时间内返回，pending 调用确实结束 |
| A03 | T04 | test_search_providers.py | 日期/域名/语言能力及可靠后过滤告警 |
| A04 | T04 | test_search.py | 双 occurrences 保留，不混加来源 score |
| A05 | T04/T05 | test_search.py / test_network_policy.py | `/a`、`/a/`、scheme、hash route 区分 |
| A06 | T05/T06 | test_network_policy.py / test_browser.py | 受控目标替身、实际连接与浏览器出口阻断 |
| A07 | T05/T06 | test_fetch.py / test_browser.py | 真实 JS fixture、受阻诊断、大流中止 |
| A08 | T07 | test_html_extraction.py | 两个真实 HTML 后端执行记录 |
| A09 | T08 | test_pdf_extraction.py | 文本/扫描/混合页及实际 OCR 坐标 |
| A10 | T08 | test_pdf_extraction.py | 单页损坏/超时后其他页仍可引用 |
| A11 | T08/T12 | test_pdf_extraction.py / test_normalization.py | 切换 PDF 后端，无上下游代码修改 |
| A12 | T08/T09 | test_ocr.py / test_office_extraction.py | 图片及三 Office 格式真实样本 |
| A13 | T10 | test_audio_extraction.py | 中英文 WAV/MP3、静音、分段失败 |
| A14 | T11 | test_video_extraction.py | 字幕、ASR、无音轨帧 OCR 实际执行 |
| A15 | T11 | test_video_extraction.py | 重复画面来源链、通道失败与抽样覆盖 |
| A16 | T03/T06/T08–T11 | test_execution.py 及对应格式测试 | Windows/POSIX 子进程树、句柄、临时文件回收 |
| A17 | T02/T12/T16 | test_material_store.py / test_normalization.py / test_acquisition.py | revision/artifact/任务关联幂等及更新差异 |
| A18 | T14 | test_index_recovery.py | SQLite 成功、实际 Qdrant 故障及恢复 |
| A19 | T14 | test_index_recovery.py | upsert 后 kill/restart，ready 前不可召回 |
| A20 | T13–T15 | test_scoped_retrieval.py / test_context.py | 四路径同 scope，Top K 前过滤 |
| A21 | T13/T14 | test_lexical_retrieval.py / test_qdrant.py | 中文/英文关键词、真实 embedding 正例 |
| A22 | T12/T15 | test_chunking.py / test_context.py | 实际 tokenizer 和截断后引用范围 |
| A23 | T02/T12/T14/T15 | test_chunking.py / test_citations.py | 重建索引后旧引用逐项回查 |
| A24 | T17/T18 | test_research_agent.py / test_orchestrator.py | 恶意/无效决策、修复和全部预算 |
| A25 | T16/T18 | test_acquisition.py / test_resume.py | 原 deadline、尝试次数与已完成工作保留 |
| A26 | T07/T14/T19 | test_extraction_registry.py / test_qdrant.py / test_cli.py | 必需缺失报错、向量降级明确 |
| A27 | T18–T20 | test_orchestrator.py / test_acceptance.py | 从问题开始的两轮真实运行及完整轨迹 |

本表之外，spec §13 重试/日志、§14 所有限制、§16 CLI/交接和 §9 生命周期都分别落在 T03、T05–T11、T19/T20、T02/T19，不以 A-ID 表替代正文要求。

## 7. 关键风险、停止门槛与回退

| 风险 | 最早暴露任务 | 必须满足的门槛 | 回退方式 |
| --- | --- | --- | --- |
| 原目录抽取拆分与实施分支重叠 | T07 前 | 核验最新提交/未提交文件，逐功能选择 | 原目录不动；不批量覆盖新 contracts |
| 新旧任务、审核和引用语义混用 | T01/T19 | 新模型与引用含义按 spec 统一，旧接口依赖清除 | 不伪造旧审核结论，不自动读旧 schema |
| Browser 仅拦 URL 无出口保证 | T06 | A06 的实际连接/子资源测试通过 | 完整模式不可宣布通过；低资源模式明确禁用 browser |
| 模型/tokenizer 不匹配 | T01/T15/T17 | 实际 tokenizer 可用且版本绑定 | preflight 报错，禁止字符估算冒充严格 token 上限 |
| Windows 后代进程残留 | T03/T10 | 子进程树在超时/取消后消失 | 阻止相关后端完整验收，不以 Linux 测试替代 |
| Qdrant 与 SQLite 状态分叉 | T14 | 双向崩溃注入均可恢复 | lexical/direct 可读，保留 pending job 重试 |
| 双 PDF/OCR 的真实质量不足 | T08/T20 | 固定三条证据、位置与语言夹具全部满足 | 调整/替换 Adapter 和 profile，旧 artifact 不动 |
| API 与 CLI 各自生成数据或执行状态 | T19 | 同一配置根、application、存储和执行锁 | 禁止各入口单独创建另一套业务状态 |
| 全量测试与环境不一致 | T01 前/T20 | 保留仍适用的行为测试，解释被替换契约 | 单独记录环境问题，不能删除安全/完整性测试逃避失败 |

各任务提交前只暂存明确文件。源码回退通过 Git 的已知提交处理，不在最终源码中维护第二套引擎。新库向前 schema 迁移，代码回退使用匹配的数据库备份，不能让旧二进制覆盖新 schema。取消兼容性不等于授权删除用户已有原件、配置或任务数据。

## 8. 完成定义与执行记录

- [ ] M1–M7 所有任务交付并通过对应回归。
- [ ] A01–A27 离线与要求的真实集成测试逐项有可复查结果，未验证项明确标出。
- [ ] 全能力配置、低资源配置、锁文件、模型/外部工具安装与 Windows 部署步骤完整。
- [ ] 两轮研究和多模态材料的回答、引用、局限、停止原因、实际 usage 均可读取。
- [ ] 数据导入、恢复、reindex、资源保留与显式清理说明完整。
- [ ] Python、CLI、FastAPI 共用单一研究核心，HTTP 提交/查询/恢复/取消/材料访问通过测试；旧引擎运行依赖已移除。Web 前端实现明确在本轮范围外。

**实施顺序建议：** 先完成 T01/T02/T03，审阅身份/事务/执行契约后进入 T04–T11；在真实多模态能力出现的同时推进 T12–T15；最后完成 T16–T20。不要从重写 2731 行 `agent.py` 开始，也不要将目录搬迁本身计作功能完成。

**计划自检：** 已建立 spec §1–§17 的任务落点、A01–A27 对照和真实后端门槛；按用户最新要求改为无兼容层、单一研究核心及 FastAPI/CLI 共用入口。A01–A27 之外的 HTTP 生命周期与任务/材料契约由 T19/T20 验收。业务实现尚未执行，本文勾选项均保持未完成状态。

### 计划阶段最终基线（2026-09-05）

在隔离工作树使用已有 conda 环境，仅从本次 pytest 子进程移除继承的 HTTP/HTTPS/ALL_PROXY（含小写）变量，不修改系统环境和项目依赖：

```bash
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy \
    -u HTTPS_PROXY -u https_proxy \
    UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" PYTHONPATH=src \
    uv run --no-sync pytest -q --maxfail=1
```

结果：**679 passed / 1 skipped / 90 warnings，159.31 秒**。跳过项为 `tests/test_browser.py::test_real_chromium_renders_local_javascript_fixture`，当前环境未检测到可用 Chromium；warning 来自既有 tldextract/FastAPI 弃用用法。移除代理后全套已有测试通过，首次失败未在该测试环境复现。此记录仅证明旧代码基线，不是 v0.1 功能验收，也不证明 Windows 或真实多模态后端已验证。
