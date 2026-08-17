# collection-agent-pydantic

基于 **pydantic-ai** 的公开信息调研智能体。用户只需给出主题，Agent 会自主制定问题、检索公开来源、提取和核验信息，并生成一份结构化公开信息调研报告。事实 → 引文 → 文档 → 哈希的证据链作为底层质量保障和审计能力保留。

## 特性

- **报告优先**：主产物为带编号引用、材料导读、局限和来源目录的 `research-report.md`；证据包和红队复审为可选审计步骤
- **主题驱动**：只输入主题即可运行，也可附加调研目标、问题、时间、地区、语言和报告深度
- **材料导读**：每份材料提供唯一的 1–5 星阅读推荐和一句话评价，并按任务生成内容摘要与优先阅读清单；不重复增加可信度标签
- **完整工具链**：除检索、事实、证据、审核和覆盖工具外，提供 `crawl_collect` 运行持久化抓取队列、`document_search` 检索归档语料、`document_read` 分页读取已校验正文
- **可信证据链**：所有关系用稳定 ID（fact/evidence/doc 为 SHA-256 派生 ID），引文逐字定位行号，文档原文与正文双重 SHA-256 完整性校验
- **语义审计**：独立的隔离 LLM 法官逐条判定引文是否完整蕴含事实（full/partial/irrelevant/contradicts），只有 `full` 才计入覆盖；审核结果不可重复抽样
- **安全边界**：DNS-pinned 抓取（SSRF 防护、私有地址拦截、重定向逐跳校验）、网页内容标记为不可信数据、注入检测
- **声明级核验**：一手披露和带归属转述可由一个审核通过的来源支持；重大或争议性声明继续要求独立来源交叉验证
- **预算与门控**：搜索 6 次 / 抓取 6 次（自上次新证据起）预算持久化；报告绑定覆盖快照、报告及引用文档哈希，过期或被修改的产物不能完成任务
- **按需深度抓取**：默认使用定向抓取；显式启用或选择 `deep` 报告时，搜索结果播种持久化队列，并逐跳执行 SSRF、DNS pinning、robots、速率、并发和字节限制
- **动态网页采集**：静态正文不足时可按需启动隔离 Chromium，执行 JavaScript 后继续复用正文提取、链接发现、原文/渲染 DOM 双哈希和证据审核
- **多文档类型**：从页面链接及 `img/audio/video/source/object/embed` 自动发现 HTML、PDF、Office、文本/CSV、图片、音视频；原件始终按 SHA-256 归档，处理器缺失时正文标记为不可用且不能进入证据链
- **来源扩展**：抓取结果返回 `outbound_links` 可继续展开（不消耗搜索预算）；部署方可配置直连来源提示

## 快速开始

```bash
# 环境（详见 Agent.md）
mamba activate collection-agent-pydantic
export DEEPSEEK_API_KEY=<your-key>

# 复制配置并按需修改（SearXNG 地址、模型、预算、已知来源）
cp config.example.yaml config.yaml

# 开发依赖；需要 Office/图片/音视频提取时同时安装 media extra
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev --extra media

# 可选：支持 JavaScript 动态网页，并安装匹配版本的 Chromium
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev --extra browser
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run playwright install chromium

# 只提供主题即可运行
python -m intel_agent --topic "量子计算产业发展情况" --config config.yaml

# 可选：补充目标、范围、核心问题和报告深度
python -m intel_agent --topic "量子计算产业发展情况" \
  --objective "了解产业现状、政策和主要参与者" \
  --questions "近期政策如何变化" "主要商业化进展有哪些" \
  --time-range "2024-2026" --geography "中国" \
  --language zh-CN --language en --report-depth deep \
  --config config.yaml
```

`--deep-crawl` 显式启用递归采集；普通任务默认关闭。`--report-depth deep`
也会启用递归采集。媒体处理还需要系统可执行文件：Tesseract（并安装
`chi_sim`/`eng` 语言数据）、FFmpeg 和 LibreOffice。音视频转写使用 media extra
中的 `faster-whisper`；缺少任一可选处理器不会丢弃已下载原件。

CLI 的 `--max-turns` 限制单次运行的模型请求数，`--max-tool-calls` 限制工具调用数。
核心问题均得到回答时任务以 `completion_status=sufficient` 完成；仍有明确缺口时以
`completion_status=with_gaps` 完成并在报告中披露，不要求先完成红队挑战。

等价的最小 API 请求为：

```json
POST /api/runs
{"topic": "量子计算产业发展情况"}
```

### Web 工作台

工作台提供主题式任务创建、实时进度、调研报告和按星级排序的来源材料。任务详情默认打开调研报告；证据链和原件下载位于“来源与材料”。前端依赖与脚本统一使用 Bun 1.3.14：

```bash
cd web
bun install --frozen-lockfile
bun run build
cd ..
intel-agent-web --config config.yaml
```

默认访问 `http://127.0.0.1:6780`。监听地址和端口通过 `config.yaml` 的 `web.host`、`web.port` 配置；`--host` 与 `--port` 可用于临时覆盖。开发时分别运行后端和 `cd web && bun run dev`；Vite 会将 `/api` 转发到本地后端。

运行结束后产物位于：
- `data/intel/` — 任务/材料导读/抓取队列/事实/证据/审核/覆盖等状态（JSON，原子写入）
- `data/raw/` — 文档原文（.raw）与提取正文（.txt）
- `output/` — 正式调研报告，以及可选的证据包和旧研判产物（Markdown）

主报告路径为 `output/{topic}-research-report.md`。材料推荐按当前任务存储：5 星表示直接支撑审核通过的核心发现，4 星表示已用于候选证据，3 星表示与主题相关，2 星表示阅读关联有限，1 星表示正文不可用或采集失败。

## 配置（config.yaml）

| 配置项 | 说明 |
|--------|------|
| `model` | 主 agent 模型（默认 DeepSeek deepseek-chat，OpenAI 兼容 API） |
| `audit_model` | 语义审核独立模型（默认同主模型） |
| `search.searxng_url` | 本地 SearXNG 地址；`null` 则只用 Bing/Baidu 直连 |
| `budgets` | 搜索/抓取/模型请求预算（request_limit 默认 200） |
| `fetch.enable_httpx_fallback` | 单次 `web_fetch` 的 pinned 抓取失败时回退 httpx（兼容 WAF/Cloudflare 站点）；递归 crawler 始终仅使用 pinned fetch |
| `fetch.enable_browser_fallback` | 静态 HTML 无有效正文时是否按需执行 Chromium（默认 `false`） |
| `fetch.browser_network_mode` | `validated` 表示应用层公网 URL 校验；生产隔离部署声明为 `isolated` |
| `fetch.browser_timeout_seconds` / `fetch.browser_max_requests` / `fetch.browser_max_bytes` | 单页渲染时间、请求数和下载字节限制 |
| `fetch.browser_concurrency` | 同一渲染器的页面并发数（默认 1） |
| `crawl.enabled_by_default` | 新任务省略开关时是否默认深度抓取（默认 `false`） |
| `crawl.max_depth` / `crawl.max_urls` | 递归深度与任务 URL 上限（默认 2 / 200） |
| `crawl.max_total_bytes` | 整个任务的下载硬上限（默认 1 GiB，失败响应也计数） |
| `crawl.max_html_bytes` / `crawl.max_attachment_bytes` | 单响应 HTML / 附件硬上限（默认 5 MiB / 50 MiB） |
| `crawl.concurrency` / `crawl.per_host_concurrency` | 全局 / 单主机并发（默认 4 / 1） |
| `crawl.per_host_delay_seconds` | 同主机请求起始间隔（默认 1 秒） |
| `crawl.cache_ttl_hours` / `crawl.retries` | 跨任务缓存时长 / 429、5xx、超时重试次数（默认 24 / 2） |
| `crawl.obey_robots` | 是否逐跳遵守 robots.txt（默认 `true`） |
| `crawl.ocr_languages` / `crawl.whisper_model` | Tesseract 语言与 faster-whisper 模型（默认 `chi_sim+eng` / `small`） |
| `web.host` / `web.port` | Web 工作台监听地址与端口（默认 `0.0.0.0:6780`） |
| `sources` | 可选的部署级直连来源提示；默认留空，由 Agent 针对主题检索 |

## 项目结构

```
src/intel_agent/
├── agent.py        # pydantic-ai Agent：15 工具注册 + 系统提示词（AGENTS.md 移植）
├── models.py       # 全部 Pydantic 数据模型（Task/Fact/Evidence/Review/Coverage...）
├── storage.py      # 原子 JSON I/O + SHA-256 完整性校验
├── security.py     # URL 校验、私有地址拦截、DNS 解析
├── source.py       # 域名分类（government/news/social/...）
├── search.py       # SearXNG + Bing + Baidu 并行搜索与结果聚合
├── search_queries.py # 查询词分析、去重与变体生成
├── fetch.py        # DNS-pinned 抓取、HTTP 解析、注入检测与文档归档
├── browser.py      # 动态页面判定、浏览器请求策略与可选 Playwright 渲染
├── crawl.py        # 持久化优先队列、robots、限速、缓存和资源归档
├── extract.py      # PDF/Office/图片/音视频安全提取与处理器边界
├── document_extract.py # HTML/PDF/Word 文本、日期与外链提取
├── fact.py         # 事实 CRUD + supersede（无环替换链）
├── evidence.py     # 证据 CRUD + 引文行号定位
├── audit.py        # 语义支撑审计（独立 LLM 法官）
├── conflicts.py    # 证据冲突登记/消解
├── coverage.py     # 覆盖评估 + 停止条件（sufficient/no_progress）
├── materials.py    # 任务级材料星级、内容摘要和阅读导引
├── report.py       # 带验证引用的正式公开信息调研报告
├── package.py      # 证据包 Markdown 生成
├── assess.py       # 结构化研判（fact/reported/inference）
├── challenge.py    # 可选红队挑战（最多两轮）
├── task.py         # 任务生命周期、预算、阶段门控
├── main.py         # CLI 入口
├── runner.py       # CLI 与 Web 共用的 Agent 运行器
└── web/            # FastAPI API、运行状态与前端读模型
tests/              # pytest 测试套件（60+ 用例）
web/                # React/Vite 本地工作台
scripts/            # 实验运行器与分析器
experiments/        # 迭代实验结果、轨迹与报告
```

## 测试

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
```

动态采集的生产网络隔离、运行状态和反爬边界参见
[`docs/js-dynamic-page-deployment.md`](docs/js-dynamic-page-deployment.md)。

## 迭代实验

`experiments/` 记录了真实运行 → 轨迹分析 → 改进 → 再运行的完整迭代历史
（详见 `experiments/README.md` 与 `experiments/ROADMAP.md`）：

| 实验 | 核心改进 | 结果 |
|------|---------|------|
| 001 | 基线 | 请求预算不足，未达 done |
| 002 | 预算 + 提示词纪律 | 到达 done；检索仍同质 |
| 003 | 搜索多样性（已归档标记） | gap 下降；出现死循环 |
| 004 | 来源扩展 + PDF/Word | 首个 covered fact + addressed 挑战点 |
| 005 | 金融数据源 + IR 回退 | 财务数据破冰；发现并修复 ID 抄错死锁 |

## 架构说明

- **模型**：DeepSeek（OpenAI 兼容 API，`OpenAIChatModel` + 自定义 `OpenAIProvider`），key 从环境变量读取
- **信任模型**：网页内容是不可信数据，搜索摘要不是证据；只有归档 + 精确引文 + 语义审核通过的才算证据
- **审计隔离**：`evidence_audit` 使用独立 Agent 与独立 prompt，杜绝主上下文污染
