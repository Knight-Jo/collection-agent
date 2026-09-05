# E2E Acceptance Run — 2026-09-05

真实数据端到端验收。范围：文本链路 + 真实后端（LLM / 搜索 / 抓取 / 多模态解析 /
索引 / 检索 / 音频视频转写 / 浏览器渲染）+ 真实两轮研究。剩余未验证：
浏览器出口隔离、字幕/帧 OCR 真实样本（代码已实现但缺带字幕真实视频）。

## 环境

- Python 3.12.3（conda `collection-agent-pydantic`）
- LLM：vLLM `qwen3.8-27B-AWQ-4bit`（`http://10.108.25.128:8001/v1`，
  `disable_thinking: true`）；（早期曾用 Ollama `qwen3.5:9b` 做冒烟）
- Embedding：vLLM `qwen3-embedding-0.6b`（`http://127.0.0.1:8001/v1`，dim 1024）
- 向量库：Qdrant `http://127.0.0.1:6333`
- 搜索：arXiv / OpenAlex（真实公网 API，经受控代理出站）；本机 SearXNG 未运行
- OCR：Tesseract 4.1.1（`chi_sim`/`eng`）
- 媒体：FFmpeg / FFprobe；ASR：faster-whisper `small` CUDA `float16`
  （2× RTX 3090，ctranslate2 4.8.1）
- 浏览器：Playwright Chromium（`chromium-1234`）
- 代理：mihomo `http://127.0.0.1:7890`（`fetch.proxy_url`）

## 真实样本（`samples/`，gitignore；清单 `tests/fixtures/manifest.json`）

| fixture_id | 来源 | 类型 |
| --- | --- | --- |
| pdf-attention | arXiv `1706.03762` | 真实 PDF |
| ocr-en / ocr-zh | Wikimedia `Test OCR document (2).jpg` | 真实 OCR 图片 |
| docx/xlsx/pptx | 库生成、真实格式与内容（origin=authored） | Office |
| audio-mp3 | 用户提供 | 真实 mp3（183s，中文） |
| audio-m4a | 用户提供 | 真实 m4a（183s，中文） |
| video-mp4 | 用户提供 | 真实 mp4（183s，无字幕，中文） |

## 验证命令与结果

```bash
PATH=$CONDA_PREFIX/bin:$PATH \
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX PYTHONPATH=src \
uv run --no-sync pytest tests/ -m "not integration" -q
# => 77 passed, 3 skipped  # skip 为已移除的合成视频夹具

uv run --no-sync pytest tests/e2e/test_two_round_research.py -m integration -q
# => 1 passed  # 真实 qwen3.8-27B-AWQ-4bit + arXiv/OpenAlex 两轮

uv run --no-sync ruff check src tests && ruff format --check src tests
# => All checks passed

uv run --no-sync pyright
# => 0 errors
```

### 真实运行实测产出

- 两轮研究：`status=completed`、`stop_reason=evidence_sufficient`、
  10 条真实引用（DOI + arXiv）、`usage={llm_calls:2, input_tokens:8245,
  output_tokens:1250}`。
- 音频/视频转写（RTX 3090 + whisper `small` `float16`）：mp3/m4a/mp4 各 ~183s，
  3 个文件合计约 22s（~20–25× 实时）；语言自动检测为 `zh`。
- 向量：真实 embedding（dim 1024）→ Qdrant upsert/search/delete roundtrip，
  命中 `score=0.696`；PDF 索引 `lexical:ready + vector:ready`（16 chunks）。

## A-ID 验收映射（本轮实测）

| 状态 | A-ID |
| --- | --- |
| 已验证（离线或真实后端） | A02、A04、A05、A08（双 HTML）、A09–A12（真实 PDF/OCR/Office）、A13（真实 ASR）、A14（无字幕视频→ASR）、A17、A20（词法 scope）、A21（中文词法）、A22（token 预算）、A23（chunk 稳定，离线）、A24（决策校验，离线）、A25（恢复）、A26/A18/A19/A21 向量（真实 Qdrant+embedding roundtrip）、A27（真实两轮） |
| 集成未验证 | A06（浏览器出口隔离）、A15/A16（字幕/帧 OCR 真实样本 + 子进程回收） |
| 未写回归测试 | A01（新增 Provider）、A03（域名/语言能力 UNSUPPORTED_FILTER） |

## 遗留问题

1. arXiv 直连会被限流（端口 80 关闭、重连被拒）；经受控代理出站稳定，故
   `fetch.proxy_url` 是本环境必需配置。
2. DeepSeek/OpenAI 环境变量中的 key 已失效；真实 LLM 用本地 vLLM 27b 替代。
3. 字幕提取与帧 OCR 路径代码已实现，但当前真实 mp4 无字幕轨，暂无真实样本
   覆盖；需要一份带字幕轨视频（并开启 `video_frame_ocr`）后才能验证。
4. 中文 OCR、真实 Office 源文件仍用库生成/英文样本替代，manifest 标
   `origin`。
