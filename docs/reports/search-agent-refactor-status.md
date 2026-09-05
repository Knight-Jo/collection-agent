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

真实后端与真实数据端到端验收已覆盖：LLM（vllm qwen3.8-27b）、搜索/抓取
（arXiv/OpenAlex，经受控代理）、多模态解析（双 HTML/双 PDF/OCR/Office）、
索引（词法 + 真实 embedding + Qdrant）、音频/视频转写（faster-whisper CUDA）、
浏览器渲染、CLI/FastAPI、真实两轮研究。详细见
`experiments/e2e-acceptance-2026-09-05.md`。

当前验证基线（本环境实测）：

- `pytest tests/ -m "not integration"`：**77 passed / 3 skipped**（skip 为
  已移除的合成视频夹具）
- `pytest -m integration`（真实 LLM + 学术搜索两轮）：**1 passed**，11 条真实
  引用，`completed/evidence_sufficient`
- 音频/视频转写：mp3/m4a/mp4 各 ~183s，3 个文件合计约 22s（RTX 3090 +
  whisper `small` `float16`，~20–25× 实时）
- `ruff check` / `ruff format --check`：通过
- `pyright`（basic，含 src/tests）：0 errors
- `uv build`：wheel/sdist 成功

**剩余未完成项收敛为「浏览器出口隔离」「字幕/帧 OCR 真实样本」与「少数回归
测试」**。按 spec §15/§16，未取得真实执行结果的能力仍标「集成未验证」，不能
据此宣称整个 spec 已完成。

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

### 字幕提取 / 帧 OCR 真实样本（代码已实现，缺真实样本覆盖）

- `extraction/video.py` 字幕路径与帧 OCR 路径均已实现（帧 OCR 由
  `video_frame_ocr` 开关默认关闭）。
- 当前 `samples/` 中的真实 `videoplayback.mp4` 无字幕轨，故字幕提取与帧 OCR
  两条路径暂无真实样本覆盖；需要一份带字幕轨的视频 + 开启 `video_frame_ocr`
  后才能真实验证。

### 回归测试缺口

- A01（新增 Provider 只改 Adapter/注册/配置，无回归测试）。
- A03（域名/语言等能力不支持时的 UNSUPPORTED_FILTER，无测试）。

## 3. 未验证（集成未验证）项

| 能力 | 状态 |
| --- | --- |
| 浏览器出口隔离 | 渲染已实现，私网出口阻断未验证 |
| 字幕提取 / 帧 OCR | 代码在，缺真实样本（真实 mp4 无字幕轨） |
| 中文 OCR | 仅英文真实 OCR 样本；中文扫描样本待补 |
| 真实字幕视频/真实 Office 源文件 | 用库生成样本替代，manifest 标 `origin=authored` |

## 4. 验收矩阵

- 已由真实后端/离线测试覆盖：A02、A04、A05、A08（双 HTML）、A09–A12（真实
  PDF/OCR/Office）、A13（真实 ASR）、A14（无字幕视频→ASR）、A17、A20（词法
  scope）、A21（中文词法）、A22（token 预算）、A23（chunk 稳定，离线）、A24
  （决策校验，离线）、A25（恢复）、A26/A18/A19/A21 向量（真实 Qdrant +
  embedding roundtrip）、A27（真实两轮）。
- 未覆盖/未验证：A01（新增 Provider 回归测试）、A03（域名/语言能力）、A06
  （浏览器出口）、A15/A16（字幕/帧 OCR 真实样本 + 子进程回收）。

## 5. 如何继续

1. **T06 出口**：`deploy/research-browser/` + 受控代理，A06 用受控网络替身
   证明主页面/iframe/XHR/WebSocket/下载均不触达私网。
2. **补齐真实样本**：带字幕轨的视频（测字幕路径）、开启 `video_frame_ocr`
   的视频（测帧 OCR）、中文 OCR 扫描样本；更新 `tests/fixtures/manifest.json`。
3. **补回归测试**：A01（新增 Provider 只改 Adapter/注册/配置）、A03（能力
   不支持 → UNSUPPORTED_FILTER）。

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
