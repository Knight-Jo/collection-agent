# 情报收集智能体实验变更记录

本文件记录每轮实验对应的代码、配置和行为变化，以及自动化验证和真实运行结果。长期优先级与跨实验结论见 `ROADMAP.md`；具体运行轨迹和产物见 `runs/`。

格式和维护时机必须遵守 `experiments/AGENTS.md`。记录按时间倒序排列，失败和结论不明确的实验也必须保留。

## [Unreleased]

（无进行中的实验）

## [013-source-fairness] - 2026-08-19

### Changed

- `src/intel_agent/source.py`：论坛/社区/股吧域名（etbbs/xueqiu/guba/tieba/taoguba）归入 social；`ir.*` 子域识别为 first-party official；政府/新闻/学术分类保持。
- `src/intel_agent/crawl.py`：非一手域按注册域配额（默认 `max(8, ceil(max_urls×0.10))`，`CrawlConfig.per_domain_cap` 可配，government/official 豁免）；social 总量上限改为相对已建 frontier 的 10%；队列批次改为按"来源类型→注册域"轮转（`_fair_batch`）；正文 SHA-256 同稿转载合并（`reused` 状态、不重复建档）；`create_crawl` 状态改为按实际 queued 计算（重复种子不再把已完成队列永久翻回 running）。
- `src/intel_agent/config.py`：`CrawlConfig.per_domain_cap: int | None = None`。
- `config.example.yaml`：补充 `per_domain_cap` 说明。
- `tests/test_crawl.py`、`tests/test_source.py`、`tests/test_deep_crawl_workflow.py`：新增 11 个确定性测试（域配额/一手豁免/social 上限/轮转/转载合并/状态持久化/来源分类），改写 1 个受域配额影响的既有测试。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（336 passed, 1 skipped）

### Experiment result

- 状态：**failed**（013a/013b/013c 三轮；013a/013b 因实现缺陷与配额未达验收作废，013c 为最终判定）
- 产物：`experiments/runs/013-source-fairness/`
- 代码版本：2392cd7（013c 运行时）
- 真实运行（013c）：exit_code=0，stage=done，completion_status=with_gaps，elapsed=788.5s，model_requests=90（6.5M tokens）
- 关键指标（013c，per_domain_cap=6）：最大非一手域 23.1%（阈值 ≤15%，❌）；前两域 46.2%（≤35%，❌）；有效域 5.73（≥6，❌）；论坛/社区 7.7%（≤10%，✅）；近重复 7.7%（≤10%，✅）；crawl.status=complete（✅）；013a→013c 改善：social 36.4%→7.7%、转载 12.5%→7.7%、状态持久化修复
- 假设结论：不成立；公平机制（配额/轮转/转载合并）生效，但最大域占比与有效域数量在现有搜索种子域多样性下无法达标——公平调度无法凭空创造域多样性，缺口指向 014 确定性查询矩阵

### Known issues

- 主域名公司官网（如 ehang.com 主站）仍归 other：013 只覆盖 `ir.*` 子域信号，无域名清单时无法确定性识别公司主站。
- 013 剩余三项阈值需在 014 提高种子域多样性后复测。

## [012-truthful-coverage] - 2026-08-19

### Changed

- `src/intel_agent/models.py`：`IntelQuestion` 增加 `time_range` 字段；`FactCoverage` 增加 `in_scope_sources`/`time_scope_gap`。
- `src/intel_agent/coverage.py`：reported/corroborated 事实执行任务级 `min_independent_sources`/`min_high_quality_sources` 门槛（原先仅 corroborated 执行）；primary 仅在 ≥1 个 full support 文档为 official/government 来源时允许单一来源；问题 covered 改为"全部 active fact covered 且无未解决冲突"（原先任意 1 个 covered 即 covered）；问题级时间范围内检查。
- `src/intel_agent/task.py`：新增 `parse_time_range`（YYYY / YYYY-YYYY / YYYY至YYYY）；`create_task` 将显式 scope 时间范围复制到每个问题，scope 为空时逐问题解析年份。
- `src/intel_agent/runner.py`：提示词更新交叉验证标准（reported 需多源）并注入逐问题时间约束。
- `src/intel_agent/report.py`：局限节改为强制列出单源事实、未覆盖问题、时间缺口、来源过度集中和未解决冲突；无缺口才允许"未发现额外局限"。
- `tests/test_coverage.py`、`tests/test_runner.py`、`tests/test_report.py`：新增/改写 7 个测试覆盖新契约。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（325 passed, 1 skipped）
- TDD 红阶段确认：新增测试实现前全部失败（reported 单源、primary 非官方、问题全事实契约、时间范围缺口、年份解析×2、报告局限）

### Experiment result

- 状态：passed
- 产物：`experiments/runs/012-truthful-coverage/`
- 代码版本：46caa44
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，elapsed=1593.6s，model_requests=190（23.2M tokens）
- 关键指标：虚假 covered 事实 13/14 → 0（011 → 012）；coverage level sufficient → insufficient（gap=41, stop_reason=no_progress）；事实 22(14 active) → 34(19 active)；证据 28 → 35；Q1 time_range='2026'、Q2=''；报告局限 0 条 → 20 条
- 假设结论：成立；单源事实不再被误判 covered，任务诚实以 with_gaps 收尾，报告明确披露单源与未覆盖缺口（来自 state/tasks、ANALYSIS.md 与 output 报告）

### Known issues

- 19 个 active 事实全部单源（srcs=1）：交叉验证执行层能力不足，190 次请求未补齐任何第二来源组；留待 013/014 按 ROADMAP 顺序解决。
- 成本显著上升（190 req / 23.2M tokens），012–015 预算上限不变的前提下需靠 014/015 提高单位预算产出。

## [Documentation baseline] - 2026-08-19

### Changed

- `experiments/ROADMAP.md`：根据 011 持久化产物补充量化复盘，将后续工作拆分为按顺序执行的 012–016 实验，并为每轮定义范围、禁止事项和量化验收。
- `experiments/AGENTS.md`：增加 CHANGELOG 的写入时机、固定模板、审计规则和提交前检查。
- `experiments/CHANGELOG.md`：建立实验变更记录，并登记 012 的待实施基线。

### Verification

- 文档结构与 011 state/trace 人工复核：PASS。
- 自动化测试：未运行；本次只修改实验文档，不改变运行代码。

### Experiment result

- 状态：inconclusive
- 产物：无新实验产物。
- 代码版本：未运行新实验。
- 真实运行：未运行。
- 关键指标：沿用 011 基线，不声明改进。
- 假设结论：无法判断；012 尚未实施。

### Known issues

- 012–016 均为计划状态，必须逐轮实现和真实运行，不得将本文档更新视为功能完成。
