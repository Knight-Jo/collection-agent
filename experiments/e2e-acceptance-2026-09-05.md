# E2E Acceptance Run — 2026-09-05

真实数据端到端验收。范围：文本链路 + 真实后端（PDF/OCR/Office/媒体/浏览器）+ 真实
LLM 两轮研究。向量/Qdrant、真实 ASR、浏览器出口隔离不在本轮（标「集成未验证」）。

## 环境

- Python 3.12.3（conda `collection-agent-pydantic`）
- 本地 LLM：Ollama 0.31.1，模型 `qwen3.5:9b`（`think:false` + JSON）
- 搜索：arXiv / OpenAlex（真实公网 API，经受控代理出站）；本机 SearXNG 未运行
- OCR：Tesseract 4.1.1（`chi_sim`/`eng` 已装，位于 conda env）
- 媒体：FFmpeg / FFprobe（系统 `/usr/bin`）
- 浏览器：Playwright Chromium（`chromium-1234`）
- 代理：mihomo `http://10.108.10.66:7890`（`fetch.proxy_url` 配置）

## 真实样本（`samples/`，gitignore；清单 `tests/fixtures/manifest.json`）

| fixture_id | 来源 | 类型 |
| --- | --- | --- |
| pdf-attention | arXiv `1706.03762`（Attention Is All You Need） | 真实 PDF |
| ocr-en / ocr-zh | Wikimedia `Test OCR document (2).jpg` | 真实 OCR 图片 |
| docx/xlsx/pptx | 库生成、真实格式与内容（origin=authored） | Office |
| video-subtitle / video-nosub | ffmpeg 生成、真实字幕/帧文字（origin=authored） | 视频 |

## 验证命令与结果

```bash
PATH=$CONDA_PREFIX/bin:$PATH \
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX PYTHONPATH=src \
uv run --no-sync pytest tests/ -m "not integration" -q
# => 75 passed, 1 deselected

uv run --no-sync pytest tests/e2e/test_two_round_research.py -m integration -q
# => 1 passed (136.82s)  # 真实 qwen3.5:9b + arXiv/OpenAlex 两轮

uv run --no-sync ruff check src tests && ruff format --check src tests
# => All checks passed

uv run --no-sync pyright
# => 0 errors
```

两轮研究实测产出：`status=completed`、`stop_reason=evidence_sufficient`、
11 条真实引用（DOI + arXiv URL）、`usage={llm_calls:2, input_tokens:8574,
output_tokens:585}`。

## A-ID 验收映射（本轮实测）

| 状态 | A-ID |
| --- | --- |
| 已验证（离线或真实后端） | A02、A04、A05、A08（双 HTML）、A09–A12（真实 PDF/OCR/Office）、A14/A15 字幕+帧路径、A17、A20（词法 scope）、A21（中文词法）、A22（token 预算）、A23（chunk 稳定，离线）、A24（决策校验，离线）、A25（恢复）、A27（真实两轮） |
| 集成未验证 | A06（浏览器出口隔离）、A13/A16（真实 ASR）、A18/A19/A21 向量、A26（向量降级） |
| 未写回归测试 | A01（新增 Provider 只改 Adapter/注册/配置）、A03（域名/语言能力 UNSUPPORTED_FILTER） |

## 遗留问题

1. arXiv 直连会被限流（端口 80 关闭、重连被拒）；经受控代理出站稳定，故
   `fetch.proxy_url` 是本环境必需配置。
2. DeepSeek/OpenAI 环境变量中的 key 已失效；真实 LLM 用本地 Ollama 替代。
3. 中文 OCR、真实字幕视频、真实 Office 源文件未取得稳定公网 URL，暂用
   库生成/英文真实样本替代，已在 manifest 标注 `origin`。
