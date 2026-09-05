# Search Agent 重构未完成项记录

日期：2026-09-05
性质：进度报告 —— 记录本轮重构已交付与未完成/未验证的能力，供后续继续实现。
依据：`specs/2026-09-05-search-agent-design.md` 与
`docs/development/search-agent-refactor-plan.md`（T01–T20、A01–A27）。

## 1. 总体状态

单一模块化后端已按 spec 重建，文本链路（Search → Fetch → Extract →
Normalize → Store → Index → Context → Agent → Orchestrator）端到端可运行，
并通过 CLI 与 FastAPI 两个入口共用同一引擎。旧引擎与旧测试已删除（能力参考
保留在 git `84e6437`）。

当前验证基线（本环境实测）：

- `pytest`：62 passed
- `ruff check` / `ruff format --check`：通过
- `pyright`（basic，含 src/tests）：0 errors
- `uv build`：wheel/sdist 成功，包含业务模块、SQL 迁移、CLI/FastAPI 入口与
  `configs/` 两个配置示例

**未完成项均属于「真实后端」或「外部基础设施」范畴**，不是可省略的能力。按
spec §15/§16 的规定，这些项在未取得真实执行结果前只能标记为「集成未验证」，
不能据此宣称整个 spec 已完成。

## 2. 未完成任务清单

### T06 — Browser 回退与可验证出口（未实现）

- **现状**：`fetch/service.py` 中 `FetchRequest.mode == "browser"` 直接抛出
  `BACKEND_UNAVAILABLE`；`FetchService` 没有注入 browser fetcher；无 browser
  生命周期管理。
- **缺**：
  - `fetch/browser.py` 的 `BrowserFetcher`（Playwright，受控出口代理）
  - `deploy/research-browser/`（compose.yaml、Dockerfile、squid.conf、
    egress.nft、start.ps1）
  - HTTP → browser 的「仅一次」回退策略与受阻页（CAPTCHA/登录墙）诊断
- **阻塞验收**：A06（浏览器子资源出口隔离）、A07（JS/验证码/大流式回退）。
- **外部前置**：Playwright Chromium + Docker Desktop + Squid 7 容器；隔离网络
  是完整模式门槛，不能仅靠 `browser_network_mode='isolated'` 自报通过。

### T10 — 音频分段 ASR（骨架，未接真实后端）

- **现状**：`extraction/audio.py` 仅有纯函数 `offset_locator`（已测）+ 返回
  `empty`/`skipped` 的 `AudioExtractor` 骨架。`extraction/backends/media.py`、
  `extraction/backends/asr.py` 尚未创建。
- **缺**：
  - `FFmpegBackend`（FFprobe 探测时长/轨道/可解码性；FFmpeg 分段约 30s）
  - `WhisperBackend`（faster-whisper，本地模型目录，分段独立重试）
  - 分段时间映射、静音/无语判定（VAD）、失败段覆盖持久化
- **阻塞验收**：A13（中英文 WAV/MP3、静音、失败分段）、A16（子进程/句柄回收）。
- **外部前置**：FFmpeg 二进制 + faster-whisper 本地模型（`media` extra 已装包，
  模型文件需显式配置下载）。

### T11 — 视频字幕 / ASR / 帧 OCR（骨架，未接真实后端）

- **现状**：`extraction/video.py` 仅有纯函数 `sample_times`（已测）+
  `VideoExtractor` 骨架。
- **缺**：
  - FFprobe 区分子幕/音轨；选定语言字幕优先，缺口补 ASR，`always_asr` 配置
  - 帧抽样（5s / 720 帧上限）OCR、`frame_ms`/bbox 关联、相邻重复帧合并
  - 三通道时间排序、通道失败 partial、coverage 采样不足标注
- **阻塞验收**：A14、A15、A16。
- **外部前置**：同 T10（FFmpeg）+ 可解码 MP4/WebM 真实夹具。

### T14 — 真实 Qdrant、embedding 与可恢复索引（适配器已写，未接线）

- **现状**：`indexing/qdrant.py` 的 `QdrantVectorIndex`（upsert/search/delete，
  按 profile 隔离 collection）与 `vector_point_id`（确定性 UUID）已实现并通过
  纯函数测试；`IndexingService._index_vectors` 逻辑已写。但 `bootstrap.py` 未
  创建 embedding client 与 vector index，`HybridRetriever` 以 `vector=None`
  构造，向量路径实际不可用。
- **缺**：
  - `HttpEmbeddingClient`（对配置端点调用，模型 ID/版本/维度隔离）
  - bootstrap 接线 + `VectorRetriever` + hybrid 实际启用
  - 可恢复索引状态（ready 前不可召回、重试累计、双向崩溃注入）实测
- **阻塞验收**：A18、A19、A21（向量部分）、A26（向量降级显式报告）。
- **外部前置**：可用的 embedding 端点 + Qdrant 服务器。

## 3. 未验证（集成未验证）项

按 spec §16 末尾规则，以下适配代码与离线测试已交付，但真实执行未验证，需在
取得外部条件后补齐记录，否则不得宣称对应能力已交付：

| 能力 | 已交付 | 未验证原因 |
| --- | --- | --- |
| Tesseract OCR | `TesseractBackend`（TSV/bbox/置信度） | 未在真实扫描页样本上运行；需 Tesseract 二进制 + `chi_sim`/`eng` 语言数据 |
| 音频/视频 | 纯函数 + 骨架 | 未接 FFmpeg/Whisper（见 T10/T11） |
| 向量检索 | Qdrant 适配器 | 无 Qdrant 服务器、无 embedding 端点 |
| Browser 出口 | — | 未实现（见 T06） |
| 双 PDF 真实质量 | PyMuPDF/pdfplumber 已跑通英文样本 | 中文/扫描/混合型样本与 OCR 坐标未按夹具验证 |
| 两轮真实研究 | Orchestrator 以固定决策通过离线测试 | 无真实 LLM 凭据（`DEEPSEEK_API_KEY`）跑端到端 |

## 4. 验收矩阵阻塞情况

A-ID 与未完成项的对应关系（离线测试通过、真实执行缺失的项不算通过）：

- 已由离线测试覆盖（确定性/契约层面）：
  - A02（超时 partial）、A04（occurrences 保留）、A05（保守去重）——`test_search.py`
  - A08（双 HTML 真实后端）——`test_html_extraction.py`
  - A17（revision/artifact 身份幂等）——`test_material_store.py`、`test_normalization.py`
  - A20（scope 一致性，lexical 路径）——`test_lexical_retrieval.py`
  - A21（中文词法）——`test_lexical_retrieval.py`
  - A22（token 预算）——`test_context.py`
  - A24（决策/citation 校验的离线部分）——`test_contracts.py`、`test_context.py`
  - A25（恢复不重复执行）——`test_acquisition.py`
  - A27（两轮脚本决策）——`test_orchestrator.py`
- 仅部分覆盖（缺真实执行）：A03（日期后过滤已测，域名/语言能力与
  UNSUPPORTED_FILTER 未覆盖）；A09–A12（PDF 双后端用 pymupdf 生成的英文样本
  跑通，中文/扫描/混合型与 OCR 坐标未验证）；A23（chunk 稳定性已测，引用逐项
  回查未做）。
- 未覆盖：A01（新增 Provider 只改 Adapter/注册/配置，未写该回归测试）；A06、
  A07（T06）；A13–A16（T10/T11/T06）；A18、A19、A21 向量部分、A26（T14）；
  A27 真实模型两轮（T20）。

## 5. 如何继续

1. **T14（接线成本最低）**：在 `bootstrap.py` 注入 embedding client 与
   `QdrantVectorIndex`，启用 `VectorRetriever`/hybrid；先做双向崩溃恢复测试。
2. **T10/T11**：新建 `extraction/backends/media.py`（FFmpeg）与
   `extraction/backends/asr.py`（Whisper），在 `audio.py`/`video.py` 里按
   segment/channel 编排，复用 `Executor.run_process` 与 `AttemptLedger`。
3. **T06**：新建 `fetch/browser.py` 与 `deploy/research-browser/`，A06 出口测试
   必须用受控网络替身证明主页面/iframe/XHR/WebSocket/下载均不触达私网。
4. **T20**：补 `tests/fixtures/manifest.json`（每类中英文正例 ≥3 条证据 +
   容差），逐项执行 A01–A27 真实样本与 Windows 实测，按
   `experiments/AGENTS.md` 落运行产物。

验证命令（沿用根 `AGENTS.md`）：

```bash
mamba activate collection-agent-pydantic
export UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX
export PYTHONPATH=src
uv sync --extra dev --extra media --extra browser
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv build
```

## 6. 明确不在本轮范围

- Web 前端页面（`web/` 已随旧引擎删除，未来独立工程经 HTTP 调用 FastAPI）。
- 分布式调度、多租户、插件自动发现、全网持续爬取、可视化界面。
- 旧 `ResearchRun`/`Conversation`/`Fact` 审核与报告发布工作流、旧数据迁移。
