# collection-agent-pydantic

基于 **pydantic-ai** 的开源情报（OSINT）收集与研判智能体 —— 对
[pi-prototype-collection](pi-prototype-collection)（TypeScript / Pi 框架）的完整 Python 移植。
核心目标不是堆积搜索结果，而是围绕主题形成**可复核、可审计的证据链**：事实 → 引文 → 文档 → 哈希，全程防篡改。

## 特性

- **15 个工具** 完整复刻原项目：`intel_plan` / `web_search` / `web_fetch` / `fact_save` / `fact_supersede` / `evidence_save` / `evidence_audit` / `evidence_conflict_create|resolve` / `coverage_eval` / `generate_package` / `intel_assess` / `intel_challenge_start|confirm` / `intel_status`
- **可信证据链**：所有关系用稳定 ID（fact/evidence/doc 为 SHA-256 派生 ID），引文逐字定位行号，文档原文与正文双重 SHA-256 完整性校验
- **语义审计**：独立的隔离 LLM 法官逐条判定引文是否完整蕴含事实（full/partial/irrelevant/contradicts），只有 `full` 才计入覆盖；审核结果不可重复抽样
- **安全边界**：DNS-pinned 抓取（SSRF 防护、私有地址拦截、重定向逐跳校验）、网页内容标记为不可信数据、注入检测
- **预算与门控**：搜索 6 次 / 抓取 6 次（自上次新证据起）预算持久化；阶段状态机 `collect → assess → challenge → done` 相邻推进，产物绑定覆盖快照哈希
- **红队复审**：最多两轮挑战，`addressed` 必须引用本轮新增且已 full 审核的证据
- **多文档类型**：HTML / PDF（pymupdf）/ Word .docx（python-docx）全文提取
- **来源扩展**：抓取结果返回 `outbound_links` 可继续展开（不消耗搜索预算）；已知权威来源（金融/IR/政策）可直接抓取

## 快速开始

```bash
# 环境（详见 Agent.md）
mamba activate collection-agent-pydantic
export DEEPSEEK_API_KEY=<your-key>

# 复制配置并按需修改（SearXNG 地址、模型、预算、已知来源）
cp config.example.yaml config.yaml

# 运行情报收集任务
python -m intel_agent --topic "低空经济" \
  --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" \
  --config config.yaml --min-sources 2 --min-quality 1 --recency 120
```

运行结束后产物位于：
- `data/intel/` — 任务/事实/证据/审核/覆盖等状态（JSON，原子写入）
- `data/raw/` — 文档原文（.raw）与提取正文（.txt）
- `output/` — 证据包与研判报告（Markdown）

## 配置（config.yaml）

| 配置项 | 说明 |
|--------|------|
| `model` | 主 agent 模型（默认 DeepSeek deepseek-chat，OpenAI 兼容 API） |
| `audit_model` | 语义审核独立模型（默认同主模型） |
| `search.searxng_url` | 本地 SearXNG 地址；`null` 则只用 Bing/Baidu 直连 |
| `budgets` | 搜索/抓取/模型请求预算（request_limit 默认 200） |
| `fetch.enable_httpx_fallback` | pinned 抓取失败时回退 httpx（兼容 WAF/Cloudflare 站点） |
| `sources` | 金融/IR/政策已知权威来源清单（intel_plan 按问题关键词建议） |

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
├── document_extract.py # HTML/PDF/Word 文本、日期与外链提取
├── fact.py         # 事实 CRUD + supersede（无环替换链）
├── evidence.py     # 证据 CRUD + 引文行号定位
├── audit.py        # 语义支撑审计（独立 LLM 法官）
├── conflicts.py    # 证据冲突登记/消解
├── coverage.py     # 覆盖评估 + 停止条件（sufficient/no_progress）
├── package.py      # 证据包 Markdown 生成
├── assess.py       # 结构化研判（fact/reported/inference）
├── challenge.py    # 红队挑战（两轮，容错 ID 匹配）
├── task.py         # 任务生命周期、预算、阶段门控
└── main.py         # CLI 入口
tests/              # pytest 测试套件（60+ 用例）
scripts/            # 实验运行器与分析器
experiments/        # 迭代实验结果、轨迹与报告
```

## 测试

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
```

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
