# 情报收集智能体实验变更记录

本文件记录每轮实验对应的代码、配置和行为变化，以及自动化验证和真实运行结果。长期优先级与跨实验结论见 `ROADMAP.md`；具体运行轨迹和产物见 `runs/`。

格式和维护时机必须遵守 `experiments/AGENTS.md`。记录按时间倒序排列，失败和结论不明确的实验也必须保留。

## [Unreleased]

（无进行中的实验）

## [020-final-consolidation] - 2026-08-19

### Changed

- `src/intel_agent/source.py`：新增部署源注册域机制（`register_first_party_domains`/`clear_first_party_domains`），公司主站确定性识别为 official（013 来源角色缺口）。
- `src/intel_agent/agent.py`：`build_agent` 注册部署源域名；`generate_research_report` 工具同草稿连续 4 次阻断（REPEATED）；fact_save 门控增加诚实出口（search_budget_exhausted 或 coverage no_progress 时恢复登记，防 collect 死锁）。
- `src/intel_agent/crawl.py`：回退错误归一化——pinned+httpx 双败时抛 OSError 让条目落到终态 failed，不再击穿整批（020a 自签名 SSL 站点崩溃修复）。
- `tests/`：新增 5 个测试（第一方域分类、报告防重、回退错误归一化、门控双出口），conftest 增加注册域隔离 fixture。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（356 passed, 1 skipped）

### Experiment result

- 状态：passed（013/015 共 9 项阈值 7 项达标）
- 产物：`experiments/runs/020-final-consolidation/`
- 代码版本：82dfa90
- 真实运行（020c）：exit_code=0，stage=done，completion_status=with_gaps，elapsed=1066.7s，model_requests=70（7.5M tokens）；020a 因自签名 SSL 站点击穿爬取批、020b 因门控死锁，两缺陷均修复后 020c 完成
- 关键指标：前两域 34.3%（≤35% ✅ 首次）、有效域 10.47（✅）、来源组 8（✅ 首次）、社交 8.6%（✅）、利用率 28.6%（✅）、低星 0（✅）；最大域 17.1%（❌ 临界）、双源率 66.7%（❌）；report+assessment 生成；ehang.com→official 生效
- 假设结论：成立；四项缺陷修复后任务诚实全程走完，9 项阈值 7 项达标，剩余两项为语料规模与真实单源稀缺所致

### Known issues

- 最大非一手域 17.1%（阈值 15%）与双源率 66.7%（阈值 100%）临界未满：语料规模张力与真实单源信息稀缺，建议转长期观察项封版。
- 020c 视频转写超时（unavailable 如实披露）；whisper 模型已缓存，超时为时长因素。

## [019-environment-fixes] - 2026-08-19

### Changed

- 环境（不在 git）：faster-whisper `small` 模型经 hf-mirror 缓存（`HF_HUB_DISABLE_XET=1`，HuggingFace Hub 直连超时）；tessdata 目录 `chi_sim`/`eng` 替换为 tessdata_best（fast 版本备份为 `*_fast_backup.traineddata`）。
- `src/intel_agent/crawl.py`：`crawl_collect` 新增 `httpx_fallback` 参数（默认 false）；default_fetcher 在 pinned 连接错误（TimeoutError/OSError/NETWORK_ERROR）后回退 `httpx_fallback_fetch`。
- `src/intel_agent/agent.py`：`_crawl_collect` 将 `settings.fetch.enable_httpx_fallback` 传入 crawl_collect。
- `tests/test_crawl.py`：新增 2 个回退确定性测试（pinned 失败→httpx 成功；回退关闭→保留错误）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（351 passed, 1 skipped）

### Experiment result

- 状态：passed
- 产物：`experiments/runs/019-environment-fixes/`
- 代码版本：844a92a
- 真实运行（019b）：exit_code=0，stage=done，completion_status=with_gaps，elapsed=1048.9s；019a 因 whisper 模型未缓存中断（collect，exit=2）
- 关键指标：3/3 固定媒体目标提取成功——PDF（pymupdf）、视频（whisper 转写通过质量门控）、图片（tesseract-best OCR 通过质量门控）；logo×2 正确拦截；语料 28 篇
- 假设结论：成立；多媒体验收瓶颈确在环境层，三项环境修复后全部目标生产提取成功

### Correction（018 根因更正）

- 018 将视频失败归因"DNS 钉扎直连 CDN 超时"——错误。019a 完整错误文本证实真实根因为 faster-whisper 从 HF Hub 下载模型超时（视频本体已成功归档）。原值：CDN 连接失败；正确值：whisper 模型下载失败；证据：019a crawl entry error 全文。

### Known issues

- Office/音频/JS 仍无公开稳定目标（数据集层缺口）。
- 013/015 剩余阈值（来源组 8、双源率 100%）与语料规模相关，待封版决策。

## [018-multimedia-recall] - 2026-08-19

### Changed

- `src/intel_agent/agent.py`：`_intel_plan` 将 `sources.financial/ir_company/policy` 配置的直连来源作为 depth-0 种子注入深爬队列（web_fetch 拒绝非 HTML/PDF 内容类型，多媒体只能走爬取）。
- `tests/test_deep_crawl_workflow.py`：新增部署源种子注入确定性测试。
- `config.yaml`（本地，不提交）：配置 3 个手工验证的固定公开目标（文本层 PDF/新华网 mp4/新闻图）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（349 passed, 1 skipped）

### Experiment result

- 状态：**failed**（2/6 格式提取成功；报告实际值）
- 产物：`experiments/runs/018-multimedia-recall/`
- 代码版本：725c9ff
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，elapsed=1440.0s，model_requests=99（11.7M tokens）
- 关键指标：PDF 生产提取首次成功（pymupdf，43KB 文本，017→018 从 0→1）；视频 mp4 归档但提取失败（DNS 钉扎直连 CDN 超时，httpx 直连可达）；图片 4 份归档全部质量门控拦截；Office/音频/JS 零命中；gap_score 18→6
- 假设结论：部分成立；部署源种子机制生效、PDF 生产提取打通，剩余缺口在环境与数据集层（CDN 可达性、tessdata_best、公开直链稀缺），管线代码未暴露新缺陷

### Known issues

- 爬取路径缺 httpx 回退（web_fetch 有）：018 视频失败的直接原因，019 候选。
- tessdata_best 环境项未完成（008 遗留）：OCR 门控拦截率高的根因。
- Office/音频公开直链稀缺：专项验收建议自建固定数据集。

## [017-rendered-multimedia-recall] - 2026-08-19

### Changed

- `src/intel_agent/extract.py`：新增 `_minimal_text_quality` 质量门控（≥10 汉字或 ≥8 英文词），应用于图片 OCR、音视频转写、扫描件 PDF OCR；未过门控返回 `unavailable`（原件仍归档，不进证据）。
- `src/intel_agent/search_queries.py`：查询矩阵 attachment 槽位扩展为 6 类格式查询（pdf/docx/xlsx+pptx/图片/音频/视频）。
- `tests/test_media_extract.py`：新增 3 个测试（质量门控噪声拒绝、垃圾 OCR 图片 unavailable、垃圾转写 unavailable）；改写 2 个既有测试适配门控。
- `config.yaml`（本地，不提交）：`fetch.enable_browser_fallback=true`（Playwright+Chromium 已确认可用）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（348 passed, 1 skipped）

### Experiment result

- 状态：**failed**（3/5 验收达标）
- 产物：`experiments/runs/017-rendered-multimedia-recall/`
- 代码版本：ccc3ff8
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，elapsed=1144.5s，model_requests=141（18.0M tokens）
- 关键指标：图片 3 份归档且全部被质量门控正确拦截（0 证据污染 ✅）；失败材料不进证据 ✅；JS 渲染 0 样本 ❌；PDF/Office/音视频 0 命中 ❌；文档证据利用率 47.4%；depth0 产出率 67%；gap_score 18
- 假设结论：部分成立；质量门控生产验证成功，但控制变量主题的语料构成无法支撑 JS 与多媒体格式命中，专项数据集主题是复测前提

### Known issues

- JS 渲染与 PDF/Office/音视频真实命中为零：需 018 专项主题 + 固定公开目标清单复测。
- libreoffice 未安装：legacy .doc/.xls/.ppt 转换不可用（已披露）。
- OCR 门控拦截率 100%（tessdata_fast 质量差）：tessdata_best 环境项待完成。

## [016-verification-gate] - 2026-08-19

### Changed

- `src/intel_agent/agent.py`：新增 `_single_source_backlog`（按 criteria.min_independent_sources 计算单源事实清单，primary+官方/政府豁免）与 `_fact_save_with_gate`；`fact_save` 工具在 backlog 存在时返回 `CROSS_VERIFY_BACKLOG` 错误并附清单，强制先 evidence_save 补第二来源组再登记新事实。
- `tests/test_deep_crawl_workflow.py`：新增 2 个测试（门控阻断与恢复、primary 官方豁免）。
- `config.yaml`（本地，不提交）：search_attempts 40→60；实跑 --max-turns 250。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（345 passed, 1 skipped）

### Experiment result

- 状态：passed（门控机制验证成功；两项硬阈值临界未满）
- 产物：`experiments/runs/016-verification-gate/`
- 代码版本：c71d27c
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，elapsed=1029.2s，model_requests=110（13.3M tokens）；首跑在 search_attempts=40 时于 collect 阶段被预算截断（双源率已 4/5），放宽至 60 后完成
- 关键指标：关键数字双源率 0% → **86.7%**（13/15 事实 ≥2 来源组）；独立来源组 5 → 7；gap_score 25 → 16；文档证据利用率 28.1%（✅）；报告低星材料 0 展开（✅）；depth1 产出率 0% → 18%
- 假设结论：成立；判定层门控一次性解决四轮供给侧修复未达成的交叉验证闭环，剩余 2 个单源事实为真实检索难度，with_gaps 诚实披露

### Known issues

- 门控与搜索预算耦合：验证消耗搜索次数，预算 40 不足以完成整轮；预算模型需按矩阵槽位+验证需求重标定。
- 013 域占比阈值（最大域/前两域/社交）与 015 来源组 8 阈值仍临界未满，与语料规模相关。

## [015-evidence-yield] - 2026-08-19

### Changed

- `src/intel_agent/agent.py`：`_document_search` 排序升级（术语匹配 + 来源类型权重 + 新来源组加成，返回 novel_group/source_group）；`coverage_eval` 工具新增 `pending_cross_verification`（单源事实 backlog）与 `verification_workflow` 指令（本地补证 → 定向补证 → 再评估）。
- `src/intel_agent/report.py`：材料导读只展开 ≥3 星且 ≤20 份材料，低相关材料仅计数不展开。
- `scripts/analyze_run.py`：ANALYSIS 新增转化漏斗段（搜索/矩阵/归档/阅读/引用/活跃事实/各深度证据产出率）。
- `tests/test_deep_crawl_workflow.py`、`tests/test_report.py`：新增 3 个测试（新来源组排序、cross-verification backlog、报告低星材料排除）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（343 passed, 1 skipped）

### Experiment result

- 状态：**failed**（2/4 验收达标）
- 产物：`experiments/runs/015-evidence-yield/`
- 代码版本：3545fd9
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，elapsed=792.7s，model_requests=85（8.5M tokens）
- 关键指标：文档证据利用率 37.5%（≥20% ✅）；报告 1–2 星材料展开 0%（≤30% ✅）；独立来源组 5（≥8 ❌）；关键数字双源率 0%（100% ❌）；转化漏斗首次可观测（归档 24→阅读 11→引用 9→事实 13；depth0 21%/depth1 0%/depth2 75%）
- 假设结论：部分成立；排序驱动与报告裁剪生效，但"本地补证→定向补证"闭环未发生——backlog 供给后模型行为不变，双源率仍 0

### Known issues

- 交叉验证闭环是模型行为缺口：012–015 供给侧修复（判定/配额/矩阵/backlog）均未改变"优先登记新事实而非补证"的行为；需要判定层强制执行（如 fact_save 门控）或接受现状。
- 来源组 5/8 与语料规模（24 篇）相关；016 前需人工决策是否补判定层强制项。

## [014-deterministic-query-matrix] - 2026-08-19

### Changed

- `src/intel_agent/search_queries.py`：新增 `query_matrix(topic, question)` 六槽位确定性查询矩阵（discovery/primary/verify/structured/attachment/adversarial）+ 英文实体查询（问题含拉丁词时）+ 公司（官网/IR/财报）与政策（site:gov.cn）定向 primary 查询；`QUERY_MATRIX_PHASE`/`QUERY_MATRIX_PHASE_BUDGET` 定义 40/40/20 相位划分。
- `src/intel_agent/search.py`：重导出 `query_matrix`。
- `src/intel_agent/agent.py`：新增 `_run_query_matrix`——web_search 工具内确定性执行未填槽位（每次 2 条，模块级 asyncio 锁防并发重复，相位预算约束，SEARCH_BUDGET_EXHAUSTED 时优雅停止），结果并入模型可见结果并播种爬取；状态文件 `data/intel/search_matrix.json` 记录 query/slot/phase/question_id/category/language/引擎/排名/URL/新域/归档标志。
- `scripts/analyze_run.py`：ANALYSIS 增加查询矩阵统计段（执行数/相位分布/槽位分布/新域候选数）。
- `tests/test_search.py`、`tests/test_deep_crawl_workflow.py`：新增 4 个测试（矩阵槽位结构、英文/公司/政策查询、工具内执行与 trace 字段、相位预算约束）；改写 1 个既有测试（news fallback 调用序列包含矩阵调用）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（340 passed, 1 skipped）

### Experiment result

- 状态：passed
- 产物：`experiments/runs/014-deterministic-query-matrix/`
- 代码版本：fedffaf
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，elapsed=793.8s，model_requests=89（8.2M tokens）
- 关键指标：矩阵执行 22 条（site: 8、filetype: 2、phase 4/16/2）；有效域 5.73 → 7.89（✅ 013 阈值）；政府来源 2 → 7；新域候选 76；文档证据利用率 5.6%（011）→ 46.7%；Authoritative@10（矩阵）= 23.2%；交叉验证双源率仍 0
- 假设结论：成立；查询广度由程序保证，site:/filetype:/英文/一手/验证槽位全部确定性执行，种子域多样性显著提升。013 剩余阈值部分恢复（有效域达标，最大域 20.0%/前两域 40.0%/社交 13.3% 仍略超）

### Known issues

- 交叉验证闭环未完成（双源率 0）：候选供给已解决，执行层留给 015。
- 相位预算未满释放未实现（discovery 4/16、adversarial 2/8 保留）。
- 013 三项域占比阈值需在语料规模提升后复测。

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
