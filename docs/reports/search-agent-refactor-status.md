# Search Agent 重构未完成项记录

日期：2026-09-05（已更新）
性质：进度报告 —— 记录本轮重构已交付与未完成/未验证的能力，供后续继续实现。
依据：`specs/2026-09-05-search-agent-design.md` 与
`docs/development/search-agent-refactor-plan.md`（T01–T20、A01–A27）。

## 1. 总体状态

单一模块化后端已按 spec 重建，文本链路（Search → Fetch → Extract →
Normalize → Store → Index → Context → Agent → Orchestrator）端到端可运行，
并通过 CLI 与 FastAPI 两个入口共用同一引擎。旧引擎与旧测试已删除（能力参考
保留在 git `84e6437`）。

本轮已补齐真实后端并通过真实数据端到端验收；详细见
`experiments/e2e-acceptance-2026-09-05.md`。

当前验证基线（本环境实测）：

- `pytest tests/ -m "not integration"`：**75 passed**（1 deselected）
- `pytest -m integration`（真实 LLM + 学术搜索两轮）：**1 passed**（136s，
  11 条真实引用，`completed/evidence_sufficient`）
- `ruff check` / `ruff format --check`：通过
- `pyright`（basic，含 src/tests）：0 errors
- `uv build`：wheel/sdist 成功

**剩余未完成项属于「真实 ASR」「向量」与「浏览器出口隔离」范畴**，按 spec
§15/§16 的规定，在未取得真实执行结果前只能标记为「集成未验证」，不能据此
宣称整个 spec 已完成。

## 2. 未完成任务清单

### T06 — Browser 受控出口隔离（渲染已实现，出口未验证）

- **已实现**：`fetch/browser.py` 的 `BrowserFetcher`（Playwright Chromium 渲染
  + 快照），`FetchService` 已注入并按 `mode="browser"` 路由；真实渲染回退已测
  （A07 的渲染部分）。
- **仍缺**：
  - `deploy/research-browser/`（compose.yaml、Dockerfile、squid.conf、
    egress.nft、start.ps1）
  - HTTP → browser 的「仅一次」自动回退策略与受阻页（CAPTCHA/登录墙）诊断
- **阻塞验收**：A06（浏览器子资源出口隔离）。A07 渲染部分已过。
- **外部前置**：Docker Desktop + Squid 7 容器 + 隔离网络；完整模式门槛不能仅
  靠代码自报通过。

### T10/T11 — 音频/视频 ASR（字幕与帧 OCR 已实现，ASR 未做）

- **已实现**：`extraction/backends/media.py`（FFmpeg/FFprobe 探测、字幕抽取、
  抽帧）、`extraction/video.py`（字幕路径 + 无字幕帧 OCR 路径）、`audio.py`
  探测。视频字幕与帧 OCR 真实样本已验证。
- **仍缺**：`WhisperBackend`（faster-whisper 分段转写）、VAD/静音判定、分段
  失败重试。
- **阻塞验收**：A13（真实 ASR）、A16 音视频子进程回收。

### T14 — 真实 Qdrant、embedding 与可恢复索引（适配器已写，未接线）

- **现状**：`indexing/qdrant.py` 的 `QdrantVectorIndex` 与 `vector_point_id`
  已实现并通过纯函数测试；但 `bootstrap.py` 未创建 embedding client 与 vector
  index，向量路径不可用（当前 hybrid 退化为 lexical）。
- **缺**：`HttpEmbeddingClient`、bootstrap 接线、`VectorRetriever`、可恢复
  索引状态双向崩溃注入实测。
- **阻塞验收**：A18、A19、A21 向量部分、A26（向量降级显式报告）。
- **外部前置**：可用的 embedding 端点 + Qdrant 服务器（本机 docker 无权限，
  需另行提供）。

## 3. 未验证（集成未验证）项

| 能力 | 状态 |
| --- | --- |
| 真实 ASR（音频转写） | 未接 Whisper；faster-whisper `small` 已装但未接线 |
| 向量检索 | Qdrant 适配器已写、未接线、未验证 |
| 浏览器出口隔离 | 渲染已实现，私网出口阻断未验证 |
| 中文 OCR | 仅英文真实 OCR 样本；中文扫描样本待补 |
| 真实字幕视频/真实 Office 源文件 | 用库生成样本替代，manifest 标 `origin=authored` |

## 4. 验收矩阵

- 已由真实后端/离线测试覆盖：A02、A04、A05、A08（双 HTML）、A09–A12（真实
  PDF/OCR/Office）、A14/A15（字幕 + 帧 OCR）、A17、A20（词法 scope）、A21
  （中文词法）、A22（token 预算）、A23（chunk 稳定，离线）、A24（决策校验，
  离线）、A25（恢复）、A27（真实两轮）。
- 未覆盖/未验证：A01（新增 Provider 回归测试）、A03（域名/语言能力）、A06
  （浏览器出口）、A13/A16（ASR）、A18/A19/A21 向量、A26（向量降级）。

## 5. 如何继续

1. **T14（接线成本最低）**：`bootstrap.py` 注入 embedding client 与
   `QdrantVectorIndex`，启用 `VectorRetriever`/hybrid，做双向崩溃恢复测试。
2. **T10/T11 ASR**：新建 `extraction/backends/asr.py`（Whisper），在
   `audio.py`/`video.py` 按 segment 编排，复用 `Executor` + `AttemptLedger`。
3. **T06 出口**：`deploy/research-browser/` + 受控代理，A06 用受控网络替身
   证明主页面/iframe/XHR/WebSocket/下载均不触达私网。
4. **补齐夹具**：中文 OCR 样本、真实字幕视频、真实 Office 源文件；更新
   `tests/fixtures/manifest.json`。

验证命令（沿用根 `AGENTS.md`，注意 `PATH` 需含 conda bin 以找到 tesseract）：

```bash
mamba activate collection-agent-pydantic
export UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX
export PYTHONPATH=src
export PATH="$CONDA_PREFIX/bin:$PATH"
uv sync --extra dev --extra media --extra browser
uv run pytest tests/ -m "not integration"
uv run pytest tests/e2e/test_two_round_research.py -m integration
uv run ruff format --check src tests && uv run ruff check src tests
uv run pyright
uv build
```

## 6. 明确不在本轮范围

- Web 前端页面（`web/` 已随旧引擎删除，未来独立工程经 HTTP 调用 FastAPI）。
- 分布式调度、多租户、插件自动发现、全网持续爬取、可视化界面。
- 旧 `ResearchRun`/`Conversation`/`Fact` 审核与报告发布工作流、旧数据迁移。
