# 情报收集智能体实验变更记录

本文件记录每轮实验对应的代码、配置和行为变化，以及自动化验证和真实运行结果。长期优先级与跨实验结论见 `ROADMAP.md`；具体运行轨迹和产物见 `runs/`。

格式和维护时机必须遵守 `experiments/AGENTS.md`。记录按时间倒序排列，失败和结论不明确的实验也必须保留。

## [Unreleased]

### 039-frozen-paired-benchmark

- 状态：planned
- 唯一假设：WP1–WP4 + judge 修复 + WP6 冻结评分分离后，Flash 与 Pro 各 3 次冻结材料配对运行的有效运行率与质量保持率可按 policy.frozen.yaml 可重复计算（基线：038 单次 Flash 233s done/with_gaps）。
- 基线：038（单次复验通过）
- 允许修改：无（纯运行+评分；`experiments/evaluation/results/` 产物不入库）
- 禁止修改：benchmark case、冻结配置、10 分钟截止口径
- 预期验收：6 次运行 manifest 均带 evaluation 元数据；每轮 analyze_run 产物完整；score/compare 按 frozen 模式输出；关键事实/引文人工盲审由人工补签（reviewer=null 标记）

Correction（端点与配置名变更）：
- 034/035 使用的本地 vLLM（127.0.0.1:8001）已停止，改由远程 vLLM 服务 `http://<vllm-host>:8001/v1` 提供同一 AWQ 模型（`qwen3.8-27B-AWQ-4bit`，16K）。
- 配置文件重命名为部署无关名：`qwen38-27b-local-awq-16k.yaml` → `qwen38-27b-awq-16k.yaml`、`qwen38-27b-local-awq-16k-report2k.yaml` → `qwen38-27b-awq-16k-report2k.yaml`，base_url 指向新端点。

## [038-frozen-flash-wp1-4] - 2026-08-22

### Changed

- `src/intel_agent/agent.py`（judge 自由文本修复，随 WP4 提交 22624fa）：`JudgeAgent` 放弃 `output_type=SupportJudgeResult`，改为纯文本完成 + `_parse_judge_verdicts` 解析 JSON。根因：deepseek-v4-flash thinking 模式拒绝结构化输出的 `tool_choice="required"`（400）且 `response_format=json_schema` 不可用，038 首跑中 191 次 evidence_audit 全部静默失败耗尽 200 请求预算。
- `tests/test_audit.py`：新增 3 个解析测试（纯 JSON、围栏剥离、垃圾拒绝）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（395 passed, 1 skipped）。
- `ruff format --check .` / `ruff check .` / `pyright`：PASS。
- 实时 API 探针：thinking 模式 judge 单次审核返回 verdict=full：PASS。

### Experiment result

- 状态：passed
- 产物：`experiments/runs/038-frozen-flash-wp1-4/`（manifest/trace/ANALYSIS/REPORT/output）
- 代码版本：`22624fa`
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，elapsed=233.3s，model_requests=30，total_tokens=1,612,449
- 关键指标：问题 2（冻结）；归档 5；事实 4；审核 6（3 full / 3 partial）；覆盖 insufficient（gap=6，no_progress）；报告 1（with_gaps，只纳入 full 事实）；trace 41 条工具事件 + usage 行完整落盘
- 基线对比：Flash 基线 586.4s 被 10 分钟截止中断、停在 collect、0 覆盖、0 报告、trace 丢失 → 本轮 233.3s 到达 done/with_gaps
- 假设结论：成立；WP1–WP4 + judge 自由文本修复使冻结材料复验一次通过

### Known issues

- 搜索未启用（冻结材料模式），搜索质量指标留待 WP5。
- 038 首跑（judge 修复前）为无效运行：191 次 evidence_audit 静默失败耗尽预算；该次运行目录已清理，trace 证据保留在分析记录中。

## [037-local-awq-assess-terminal-switch] - 2026-08-22

### Changed

- `src/intel_agent/agent.py`：`_coverage_eval_with_backlog` 增加终态切换——task 处于 assess 且最新覆盖评估 `stop_reason=no_progress` 时，系统用 `build_verified_report_draft` 确定性生成报告并返回 `terminal_report` 指令（推送 intel_status(done)），不再注入 pending_cross_verification；报告已存在时同样只推送 done。
- `src/intel_agent/report.py`：`generate_research_report` 在 `coverage.stop_reason=no_progress` 时允许零结论草稿（跳过 NO_REPORTABLE_FINDINGS 与空章节的"必须逐一回答"检查），输出诚实 with_gaps 报告（全章节"未形成可验证结论"+ 局限披露）。
- `tests/test_deep_crawl_workflow.py`：新增 2 个回归测试（full 审核下终态报告生成；partial 审核零验证事实下空结论报告仍可生成且披露局限）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q tests/test_deep_crawl_workflow.py -k 'coverage_eval'`：PASS（3 passed）。
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q`：PASS（368 passed, 1 skipped）。
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .` / `ruff check .`：PASS。
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）。
- 从 035 assess 状态原地续跑：PASS（3 requests，20,935 tokens，报告落盘，stage=done）。

### Experiment result

- 状态：passed
- 产物：`experiments/runs/035-local-awq-report2k/`（状态与报告）、`experiments/runs/037-local-awq-assess-terminal-switch/`（README+REPORT）、`resume-trace-037.jsonl`
- 代码版本：`6b90f50`（改动尚未提交）
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，model_requests=3，total_tokens=20,935；无上下文溢出
- 关键指标：coverage gap=12（no_progress）；活跃事实 3（全部 partial 审核）；已验证事实 0；报告 4 章节全空 + 局限披露。036 死循环（90 分钟 90+ 请求未收敛）→ 037 三请求到达诚实终态。
- 假设结论：成立；报告转换的判定层硬切换 + no_progress 空报告豁免使 done 从不可达变为确定性可达，且未妥协诚实性（0 结论 0 伪造，摘要由持久状态生成）

### Known issues

- 零 full 事实的 with_gaps 报告（全空章节）是否满足交付口径需人工确认。
- 搜索/取证质量仍是主瓶颈：本地模型 5 条证据审核全 partial/irrelevant，无一条 full（对比 033 远程 1 full）。
- trace 事件级增量持久化（P0 #138）未修；036 死循环轨迹永久缺失。

## [036-local-awq-report-param-fallback] - 2026-08-22

### Changed

- `src/intel_agent/agent.py`：`generate_research_report` 的 `draft` 字符串解析增加兜底——先完整解析，失败则截断尾部噪声（`rpartition("}")`）再解析，仍失败回退到 `build_verified_report_draft` 确定性草稿（034/035 参数层崩溃的根因修复）。
- `tests/test_deep_crawl_workflow.py`：新增 2 个回归测试（尾部 XML 噪声剥离、垃圾草稿回退 verified facts）。

### Verification

- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest -q tests/test_deep_crawl_workflow.py -k 'generate_research_report'`：PASS（5 passed）。
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .`：PASS。
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .`：PASS。
- `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright`：PASS（0 errors）。
- 从 035 assess 状态原地续跑：主动终止（约 90 分钟、约 90 次模型请求后，stage 停在 assess、无报告落盘；trace 因主动终止再次丢失）。

### Experiment result

- 状态：failed
- 产物：`experiments/runs/035-local-awq-report2k/`（续跑状态与 `resume-trace-036.jsonl` 未落盘）
- 代码版本：`6b90f50`（改动未提交）
- 真实运行：主动终止，未达终态；stage=assess，search=40/search_budget_exhausted，evidence=4，facts=3，coverage gap=9、no_progress_rounds=12、stop_reason=no_progress
- 关键指标：请求预算未耗尽；状态文件自 06:22 UTC 后除 coverage 快照外零变化
- 假设结论：无法判断参数层兜底对终态的作用——续跑过程中模型从未调用 generate_research_report（无报告落盘、无崩溃），真实阻塞点转移到 assess 阶段行为死循环；根因定位见 Known issues

### Known issues

- assess 死循环根因（第三次复现，025/034/036）：`_coverage_eval_with_backlog` 在单源事实存在时持续注入 pending_cross_verification，模型反复 audit↔coverage_eval；搜索预算已耗尽使补证永远无法完成，而 history processor 的 assess 分支因 reviews 始终比 coverage 新而永远不被触发。
- 死循环期间 trace 丢失（P0 #138 未修），工具序列无法直接取证，结论来自状态文件与请求计数。

## [035-local-awq-report2k] - 2026-08-22

### Changed

- 仅运行配置：全程使用 `experiments/configs/qwen38-27b-local-awq-16k-report2k.yaml`（`main_output_tokens` 2048）。

### Verification

- 冒烟 `--dry 5`：PASS（5 轮工具调用后按 dry 上限中止，冒烟目录已清理）。
- `ruff format --check .` / `ruff check .` / `pyright`：PASS（035 无代码改动，沿用 034 基线）。

### Experiment result

- 状态：failed
- 产物：`experiments/runs/035-local-awq-report2k/`
- 代码版本：`6b90f50`
- 真实运行：exit_code=1，stage=assess，elapsed=1202.7s，model_requests≈99（vLLM POST 计数 575→674）
- 关键指标：搜索 40/矩阵 26（推断，沿用口径）；归档 3；活跃事实 1；证据 2；coverage insufficient；0 上下文溢出
- 失败模式：2048 输出下草稿 JSON 完整（1024 截断消除），但 `qwen3_xml` 工具调用闭合标签泄漏进参数字符串尾部（`...]}</draft>\n</invoke>`），`ResearchReportInput.model_validate_json` 报 "trailing characters at column 1181"，Agent retries 3 次耗尽 → `UnexpectedModelBehavior`
- 假设结论：不成立；2048 消除了截断，但暴露了新的参数层污染——兜底必须挂在工具内部而非依赖模型输出干净

### Known issues

- 034 已预判的参数层兜底缺口未在本轮修复（本轮为纯配置实验，禁止改代码）。
- 解析失败发生在工具函数体 `model_validate_json`（异常被 pydantic-ai retries 重试 3 次后升级为 UnexpectedModelBehavior），033 的业务层回退同样被绕过。

## [034-local-awq-baseline] - 2026-08-22

### Changed

- `experiments/configs/qwen38-27b-local-awq-16k.yaml`（新增）：base_url 改为本地 127.0.0.1:8001/v1，模型名改为 vLLM 实际服务名 `qwen3.8-27B-AWQ-4bit`（vLLM 对未知模型名返回 404，远程配置的 `qwen3.8-27b-int4` 不可复用）。
- `experiments/configs/qwen38-27b-local-awq-16k-report2k.yaml`（新增）：同上，`main_output_tokens` 1024→2048（031 证明 2048 解决报告截断）。
- `qwen3.8-27B-AWQ-4bit/vllm.config`（环境修复）：EXTRA_ARGS 增加 `--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3`（模型 README 推荐组合；缺失时 pydantic-ai 的 `tool_choice:"auto"` 被 400 拒绝，vLLM 无法解析工具调用）。
- 未修改任何运行代码（本轮为配置+环境实验）。

### Verification

- `curl http://127.0.0.1:8001/v1/models`：PASS（qwen3.8-27B-AWQ-4bit，max_model_len=16384）
- 单轮工具调用探针（get_weather + tool_choice:auto）：PASS（`<tool_call>` 解析成功）
- 冒烟 `python3 scripts/run_experiment.py --dry 5`：PASS（5 轮工具调用后按 dry 上限中止，模型/工具链正常；冒烟目录已清理）
- `vllm serve` 重启后 `/health`：200（全程）
- `python3 scripts/analyze_run.py experiments/runs/034-local-awq-baseline --write`：PASS（ANALYSIS.md 已生成）

### Experiment result

- 状态：failed
- 产物：`experiments/runs/034-local-awq-baseline/`
- 代码版本：`6b90f50`
- 真实运行（阶段一，1024 输出）：exit_code=1，stage=assess，elapsed=660.4s，model_requests≈75（vLLM 日志 POST 计数）；`generate_research_report` 草稿在 1024 token 截断（"EOF while parsing a string at column 3214"），工具参数层 JSON 解析失败重试 3 次耗尽 → `UnexpectedModelBehavior`
- 真实运行（阶段二，2048 输出续跑）：原地续跑约 30 分钟、169 次请求后主动终止；stage 停在 assess，文档/事实/证据/审核零变化；trace 未落盘（异常终止，P0 #138 复现）
- 关键指标：搜索 40/矩阵 26；归档 3；活跃事实 3（全部 srcs=0）；证据 1；coverage insufficient（gap=15，no_progress=4）；0 上下文溢出
- 假设结论：不成立；本地部署全链路可用（搜索→事实→审核→assess）且服务负载验收通过（60s 返回/health 200/无溢出），但报告截断与 assess 死循环未达成 done/with_gaps

### Known issues

- 报告参数层截断绕过 033 安全草稿回退（回退只覆盖业务校验，不覆盖工具参数层非法 JSON）；report2k 配置已建但续跑未走到报告阶段，2048 修复效果未验证。
- assess→report 死循环根因因 trace 丢失不可追溯（025 同型）。
- 三事实全部 srcs=0：本地模型补源能力与远程同弱，搜索质量缺口仍是主要瓶颈。

## [033-qwen38-27b-verified-report-fallback] - 2026-08-21

### Changed

- `src/intel_agent/report.py`：从持久状态确定性构建安全草稿，每题一节，只纳入具有 full 审核支持的事实，未回答问题保留空章节。
- `src/intel_agent/agent.py`：模型报告草稿未通过业务校验时使用安全草稿调用同一报告生成器，不放宽证据、覆盖或引用校验。
- `src/intel_agent/runner.py`：done 后用持久状态生成 CLI/Web 共用的完成摘要，不再转发模型可能夸大的自由文本。
- `tests/test_deep_crawl_workflow.py`、`tests/test_runner.py`：覆盖安全报告回退和确定性完成摘要。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q tests/test_report.py tests/test_deep_crawl_workflow.py -k 'report or json_encoded'`：PASS（17 passed）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q tests/test_runner.py -k 'done_task_replaces or streams_events'`：PASS（2 passed）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check .`：PASS（76 files）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check .`：PASS。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright`：PASS（0 errors）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q`：PASS（364 passed, 1 skipped）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv build`：PASS（sdist + wheel）。
- 从 030 assess 状态原地续跑：PASS（3 requests，21,110 tokens，正式报告生成并到达 done/with_gaps）。

### Experiment result

- 状态：passed
- 产物：`experiments/runs/030-qwen38-27b-vllm-criteria-compat/`、`experiments/runs/033-qwen38-27b-verified-report-fallback/`
- 代码版本：`b6a00f3`（改动尚未提交）
- 真实运行：exit_code=0，stage=done，completion_status=with_gaps，model_requests=3，total_tokens=21,110；续跑墙钟未单独记录
- 关键指标：搜索保持 40；归档 4；活跃事实 2，其中 full 审核支持事实 1；证据 1；coverage gap=10/no_progress；报告 1；0 上下文溢出。正式报告只纳入 1 条 full 事实，4 个未回答问题保持空章节。
- 假设结论：成立；确定性安全草稿让 Qwen3.8-27B/16K 完成报告并诚实以 with_gaps 收尾。

### Known issues

- 搜索质量较弱：两个用户原始问题均未回答，4 份归档中有两份年份关键词误召回。
- 模型最终自由文本曾夸大为“2 条已核验事实 + 推断”；正式报告未受污染，runner 已改为持久状态摘要（已验证事实数=1）。
- 030 主运行失败路径仍无增量 trace；033 成功续跑保留 `resume-trace-033.jsonl`。


## [032-qwen38-27b-report-draft-compat] - 2026-08-21

### Changed

- `src/intel_agent/agent.py`：`generate_research_report.draft` 接受对象或 JSON 字符串，并统一通过 `ResearchReportInput` 校验。
- `tests/test_deep_crawl_workflow.py`：新增字符串化报告草稿回归测试。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q tests/test_deep_crawl_workflow.py -k 'json_encoded or generate_research_report'`：PASS（3 passed）。
- 从 030 assess 状态原地续跑：ABORTED（约 17 分钟内十余次模型请求持续返回业务校验失败草稿，人工终止）。

### Experiment result

- 状态：failed（参数类型兼容通过，报告业务内容未收敛）
- 产物：`experiments/runs/030-qwen38-27b-vllm-criteria-compat/`、`experiments/runs/032-qwen38-27b-report-draft-compat/`
- 代码版本：`b6a00f3`
- 真实运行：exit_code=130（主动终止），stage=assess，elapsed=约 17 分钟；精确 model_requests 未测量
- 关键指标：搜索保持 40、事实/证据保持 1/1、0 上下文溢出；字符串 draft 已进入报告业务校验，但模型未在合理时间内修正为合法章节/事实组合。
- 假设结论：部分成立；工具协议兼容完成，但把诚实报告收尾完全交给模型仍不稳定。

### Known issues

- 合法报告可以由持久状态确定性构建：每题一节，只纳入 full 审核事实，未回答题留空；033 验证该安全回退。
- 主动终止仍没有增量 trace/usage。


## [031-qwen38-27b-report-resume] - 2026-08-21

### Changed

- `experiments/configs/qwen38-27b-vllm-16k-report2k.yaml`：16K 历史边界不变，主输出由 1024 提高至 2048 token。

### Verification

- 从 `experiments/runs/030-qwen38-27b-vllm-criteria-compat/` 原地续跑：FAIL（报告 `draft` 类型校验重试耗尽）。
- 服务健康检查：PASS（续跑期间 HTTP 200，无排队）。

### Experiment result

- 状态：failed（输出截断已解决，嵌套参数类型仍不兼容）
- 产物：`experiments/runs/030-qwen38-27b-vllm-criteria-compat/`、`experiments/runs/031-qwen38-27b-report-resume/`
- 代码版本：`b6a00f3`
- 真实运行：exit_code=1，stage=assess，elapsed=未精确测量（人工观察约 10 分钟），model_requests=4（初次 + 3 次工具校验重试）
- 关键指标：搜索保持 40、事实/证据保持 1/1、0 上下文溢出；报告参数不再 EOF，而是完整生成后因 `draft` 为 JSON 字符串被拒绝。
- 假设结论：部分成立；2048 token 解决截断，但 Qwen3.8 的嵌套对象编码兼容仍阻止报告落盘。

### Known issues

- `generate_research_report.draft` 需兼容对象或 JSON 字符串，同时保持 `ResearchReportInput` 业务校验；032 单独验证。
- 续跑失败仍未增量保存 trace/usage。


## [030-qwen38-27b-vllm-criteria-compat] - 2026-08-21

### Changed

- `src/intel_agent/agent.py`：`intel_plan.criteria` 接受模型原生对象或 JSON 字符串，并统一通过 `SufficiencyCriteria` 严格校验。
- `tests/test_deep_crawl_workflow.py`：新增 Qwen3.8 字符串化嵌套条件的回归测试。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q tests/test_deep_crawl_workflow.py -k 'intel_plan or runner_deep_crawl_setting'`：PASS（5 passed）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check src/intel_agent/agent.py tests/test_deep_crawl_workflow.py`：PASS。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check src/intel_agent/agent.py tests/test_deep_crawl_workflow.py`：PASS。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright src/intel_agent/agent.py tests/test_deep_crawl_workflow.py`：PASS（0 errors）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name qwen38-27b-vllm-criteria-compat --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen38-27b-vllm-16k.yaml`：FAIL（报告参数 4 次在 1024 token 处截断）。

### Experiment result

- 状态：failed（采集与审核链路通过，报告收尾失败）
- 产物：`experiments/runs/030-qwen38-27b-vllm-criteria-compat/`
- 代码版本：`b6a00f3`
- 真实运行：exit_code=1，stage=assess，elapsed=2225.5s；服务 metrics 为共享值，不声明精确 model_requests
- 关键指标：搜索预算 40、查询矩阵 26、归档 4、活跃事实 1、证据 1、full 审核 1、证据文档利用率 25%；coverage gap=6/no_progress；0 上下文溢出；报告 4 次均生成满 1024 token 后以 JSON EOF 失败。
- 假设结论：部分成立；`intel_plan` 一次成功并完整走通 search→fetch→read→fact/evidence→audit→coverage→assess，但 1024-token 主输出不足以容纳五章节报告参数。

### Known issues

- 两个用户原始问题均未形成事实；检索材料存在“2026 半年报/节假日”年份污染，最终必须如实 with-gaps。
- 异常退出仍无增量 trace，ANALYSIS 的工具调用数为 0，只能用持久 state 和服务 metrics 分析。


## [029-qwen38-27b-vllm-16k] - 2026-08-20

### Changed

- `src/intel_agent/config.py`：新增 16K 上下文档位，对应 24,576-byte 历史与 4,096-byte 单工具结果预算。
- `README.md`、`config.example.yaml`、`experiments/configs/qwen38-27b-vllm-16k.yaml`：记录并启用服务实际声明的 16K 边界。
- `tests/test_config.py`：覆盖 16K 派生预算与 8K 非法档位。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q tests/test_config.py tests/test_context.py`：PASS（14 passed）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check src/intel_agent/config.py tests/test_config.py`：PASS。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check src/intel_agent/config.py tests/test_config.py`：PASS。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright src/intel_agent/config.py tests/test_config.py`：PASS（0 errors）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name qwen38-27b-vllm-16k --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen38-27b-vllm-16k.yaml`：FAIL（工具参数校验重试耗尽）。

### Experiment result

- 状态：failed
- 产物：`experiments/runs/029-qwen38-27b-vllm-16k/`
- 代码版本：`b6a00f3`
- 真实运行：exit_code=1，stage=未建立，elapsed=138.6s，model_requests=4（由初次调用及 3 次工具校验重试推断）
- 关键指标：上下文溢出=0，后端健康=200；模型调用 `intel_plan` 时把 `criteria` 对象编码为 JSON 字符串，工具调用 4 次均未通过 Pydantic 校验。
- 假设结论：部分成立；16K 配置和服务稳定性通过，但 Qwen3.8 的嵌套工具参数编码不兼容阻断了任务建立。

### Known issues

- `intel_plan.criteria` 需要在保持业务模型校验的前提下兼容 JSON 字符串；030 单独验证。
- 异常退出仍未增量保存 trace，工具重试次数只能由错误栈和 `retries=3` 推断。

## [028-qwen38-27b-vllm-no-thinking] - 2026-08-20

### Changed

- `experiments/configs/qwen38-27b-vllm-no-thinking.yaml`：保持 Qwen3.8-27B、32K 和 Agent 预算不变，仅关闭思考以隔离 027 的停滞原因。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python -c <load_config>`：PASS（模型 `qwen3.8-27b-int4`，32K，免密接口）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name qwen38-27b-vllm-no-thinking --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen38-27b-vllm-no-thinking.yaml`：ABORTED（首请求 422.9 秒无工具调用或状态进展）。
- 完整系统提示 + 单个 `intel_plan` 工具 + 128 输出 token：FAIL（约 34 秒后 HTTP 502）。
- 后端恢复探测：FAIL（连续 3 次 `/health` 均为 HTTP 502）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/analyze_run.py experiments/runs/028-qwen38-27b-vllm-no-thinking --write`：PASS（0 次工具调用、0 份归档文档）。
- `git diff --check`：PASS。

### Experiment result

- 状态：failed
- 产物：`experiments/runs/028-qwen38-27b-vllm-no-thinking/`
- 代码版本：`b6a00f3`
- 真实运行：exit_code=130（主动终止），stage=未建立，elapsed=422.9s，model_requests=1
- 关键指标：工具调用=0、搜索=0、归档文档=0、事实/证据=0、上下文溢出=0；关闭思考未改善首请求停滞，诊断后服务健康从 200 变为 502。
- 假设结论：不成立；瓶颈不只是思考模式，当前远程推理服务无法稳定承载真实 Agent 工具负载。

### Known issues

- 服务端需先修复真实工具请求触发的 502；本地 Agent 无状态产物可供搜索质量评价。
- vLLM metrics 为共享全局累计值，未取得独占测试窗口前不能把总 token 增量精确归因到本实验。

## [027-qwen38-27b-vllm] - 2026-08-20

### Changed

- `experiments/configs/qwen38-27b-vllm.yaml`：接入远程 `qwen3.8-27b-int4`，按服务声明使用 32K 上下文并开启思考。

### Verification

- `curl http://10.108.25.82:8001/health`：PASS（HTTP 200）。
- `curl http://10.108.25.82:8001/v1/models`：PASS（模型 `qwen3.8-27b-int4`，`max_model_len=32768`）。
- 关闭思考的普通对话与 ping 工具调用：PASS（3.7 秒；ping 参数为 `ok`）。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name qwen38-27b-vllm --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen38-27b-vllm.yaml`：ABORTED（首请求 400 秒无工具调用或状态进展）。

### Experiment result

- 状态：failed
- 产物：`experiments/runs/027-qwen38-27b-vllm/`
- 代码版本：`b6a00f3`
- 真实运行：exit_code=130（主动终止），stage=未建立，elapsed=400.0s，model_requests=1
- 关键指标：服务指标显示本请求 prompt=4,203 tokens、终止时 generation=475 tokens，约 1.49 token/s；工具调用=0，归档文档=0，上下文溢出=0。
- 假设结论：不成立；开启思考在当前服务吞吐和 1024-token 输出边界下无法及时进入第一个工具动作。

### Known issues

- vLLM 当前单请求思考生成吞吐约 1.49 token/s，远低于此前预期，需用关闭思考的 028 区分模型能力与思考开销。
- 主动终止时 harness 不会自动补写 manifest 终态，本轮根据进程退出码、墙钟和服务 metrics 补记。

## [026-stage-aware-resume] - 2026-08-20

### Changed

- `src/intel_agent/context.py`：快照按任务及研判子阶段给出唯一动作：待审证据→审核、审核更新→覆盖、覆盖停止→assess、导读→报告、报告→done。
- `src/intel_agent/models.py`、`src/intel_agent/report.py`：事实型报告结论可省略可推导的 `kind`；系统按事实与覆盖状态自动添加来源归属，并允许未回答问题以空结论章节诚实写入 with-gaps 报告。
- `tests/test_context.py`、`tests/test_report.py`：覆盖 assess 防回跳、导读后转报告、无 kind 事实结论和未回答章节。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q`：PASS（359 passed, 1 skipped）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv build`：PASS
- 从 `experiments/runs/025-small-model-continuation/` 原地恢复：PASS；3/3 证据完成审核，collect→assess→done，搜索次数保持 40。

### Experiment result

- 状态：passed
- 产物：`experiments/runs/025-small-model-continuation/`（`resume-trace-4.jsonl` 与 `output/低空经济-research-report.md`）
- 代码版本：`b6a00f3`（改动尚未提交，原 manifest 记录运行时 HEAD）
- 真实运行：最终 stage=done，completion_status=with_gaps；最后一次恢复 model_requests=3，total_tokens=16,566
- 关键指标：审核 0→3，stage collect→done，正式报告 0→1，新增搜索 0；报告明确披露 Q2 未形成可验证结论及 2026 时间缺口
- 假设结论：成立；阶段感知快照和简化报告契约让 32K Qwen3.5-9B 从中断状态恢复并完成正式报告，未靠扩大上下文或伪造缺失结论。

### Known issues

- 首次 025 主运行和两个中间恢复因主动终止未写 trace/usage，异常路径增量观测仍待单独解决。
- 本轮语料质量有限：仅 1 个活跃事实，Q2 未回答；这是搜索结果质量缺口，不是上下文溢出。

## [025-small-model-continuation] - 2026-08-20

### Changed

- `src/intel_agent/agent.py`、`src/intel_agent/context.py`：记录本轮已读文档，`document_read` 返回明确的 `fact_save → evidence_save` 下一动作，快照不再要求重复读取。
- `src/intel_agent/runner.py`：模型在任务未完成时返回自然语言会自动续跑；所有续跑共享依赖、消息历史和累计请求预算。
- `tests/test_context.py`、`tests/test_deep_crawl_workflow.py`：覆盖已读状态、工具下一动作和未完成任务自动续跑。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q`：PASS（356 passed, 1 skipped）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv build`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name small-model-continuation --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen35-9b-llama-server.yaml`：ABORTED（达到本轮闭环验收后，因重复 coverage_eval 主动终止）

### Experiment result

- 状态：inconclusive（核心假设成立，完整任务未完成）
- 产物：`experiments/runs/025-small-model-continuation/`
- 代码版本：`b6a00f3`（本轮改动尚未提交，manifest 记录运行时 HEAD）
- 真实运行：exit_code=-15（主动终止），stage=collect，elapsed=858.1s；异常终止未写 usage/trace，model_requests 不可计算
- 关键指标：事实 0→1、证据 0→3、被证据引用文档 0→2，首次完成 32K/9B 的 fetch→read→fact→evidence；搜索预算 40 次耗尽，审核 0，coverage gap=5/no_progress
- 假设结论：核心成立；已读状态和自动续跑解决了 024 的提前退出并形成证据闭环，但快照未区分待审核证据，模型在 coverage_eval 重复 16 轮，完整终态仍未达成。

### Known issues

- 有 pending evidence 时快照仍返回通用 collect 动作，未强制 `evidence_audit`。
- 自动续跑会忠实放大错误 next_action；必须先让持久快照按阶段给出唯一动作。
- 主动终止路径仍无 trace/usage，异常增量观测问题未解决。

## [024-archive-state-recovery] - 2026-08-20

### Changed

- `src/intel_agent/context.py`：压缩快照加入最多 8 份最近归档文档的 ID、标题和 URL；无证据时明确要求停止检索并调用 `document_read → fact_save → evidence_save`。
- `tests/test_context.py`：增加归档文档状态恢复回归测试。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q`：PASS（355 passed, 1 skipped）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv build`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name archive-state-recovery --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen35-9b-llama-server.yaml`：FAIL（模型提前返回，exit=2）

### Experiment result

- 状态：failed
- 产物：`experiments/runs/024-archive-state-recovery/`
- 代码版本：`b6a00f3`（本轮改动尚未提交，manifest 记录运行时 HEAD）
- 真实运行：exit_code=2，stage=collect，elapsed=45.8s，model_requests=10，total_tokens=98,135
- 关键指标：`document_read` 0→4、被阅读文档 0→1；事实和证据仍为 0；无上下文溢出且单任务保持正确
- 假设结论：部分成立；归档状态使模型正确进入 document_read，但快照没有“已读”状态，模型重复读取后以承诺继续的自然语言提前结束。

### Known issues

- `document_read` 阶段未记录在运行上下文，压缩快照持续要求再次读取同一文档。
- runner 把未完成任务中的自然语言回复当作本轮终点，不会基于持久化 stage 自动续跑。
- trace 只保留 4 次工具调用，少于 usage 的 10 次模型请求。

## [023-context-gate-recovery] - 2026-08-20

### Changed

- `src/intel_agent/agent.py`：`FETCH_REQUIRED` 返回最多 10 个具体候选 URL 和下一动作；成功抓取后清空待抓候选；`intel_plan` 复用未完成的活动任务。
- `tests/test_deep_crawl_workflow.py`：增加候选恢复和任务规划幂等回归测试。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest -q`：PASS（354 passed, 1 skipped）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv build`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name context-gate-recovery --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen35-9b-llama-server.yaml`：FAIL（模型提前返回，exit=2）

### Experiment result

- 状态：failed
- 产物：`experiments/runs/023-context-gate-recovery/`
- 代码版本：`b6a00f3`（本轮改动尚未提交，manifest 记录运行时 HEAD）
- 真实运行：exit_code=2，stage=collect，elapsed=249.2s，model_requests=38，total_tokens=453,018
- 关键指标：任务数 2→1，归档文档 2→6，显式 `web_fetch` 0→11；证据和事实仍为 0；无上下文溢出
- 假设结论：部分成立；具体候选和规划幂等使模型完成 search→fetch，但压缩快照没有归档文档 ID，最终仍指示继续抓取，未进入 evidence。

### Known issues

- 压缩快照只恢复任务、事实和覆盖，不恢复已归档文档；历史裁剪后小模型不知道可调用 `document_read` 的 ID。
- 模型对 `https://www.lowaltitude.cn/` 的自签名证书失败反复调用，现有连续重复门禁不足以完成阶段转换。
- trace 仍只反映裁剪后 14 次工具调用，少于 usage 的 38 次模型请求。

## [022-bounded-context-qwen35-9b] - 2026-08-20

### Changed

- `src/intel_agent/config.py`、`src/intel_agent/context.py`：新增 32K/64K/128K/256K 上下文档位、按档位派生的历史与工具结果上限，以及基于持久化任务状态的消息历史裁剪。
- `src/intel_agent/agent.py`：主 Agent 与审核 Agent 分别限制输出，支持关闭 Qwen thinking，并增加连续搜索转抓取门禁。
- `config.example.yaml`、`README.md`、`experiments/configs/qwen35-9b-llama-server.yaml`：记录并启用本地 32K 小模型配置。
- `tests/test_config.py`、`tests/test_context.py`、`tests/test_deep_crawl_workflow.py`：覆盖档位校验、历史压缩、状态恢复、输出限制和搜索门禁。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest`：PASS（353 passed, 1 skipped）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv build`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name bounded-context-qwen35-9b --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen35-9b-llama-server.yaml`：FAIL（模型提前返回，exit=2）

### Experiment result

- 状态：failed
- 产物：`experiments/runs/022-bounded-context-qwen35-9b/`
- 代码版本：`b6a00f3`（上下文管理改动尚未提交，manifest 记录运行时 HEAD）
- 真实运行：exit_code=2，stage=collect，elapsed=106.8s，model_requests=18，total_tokens=203,137
- 关键指标：上下文溢出 1→0；搜索 40→15，文档 3→2，证据 1→0，事实 1→0；活动任务错误地从原任务切换为重复规划的新任务
- 假设结论：部分成立；32K 历史与输出边界消除了溢出，但门禁只返回错误、不返回候选 URL，小模型持续搜索并重复调用 `intel_plan`，未进入证据闭环。

### Known issues

- `FETCH_REQUIRED` 缺少具体候选 URL 和明确下一工具参数，小模型无法恢复到 `web_fetch`。
- `intel_plan` 非幂等，压缩后模型重复调用会覆盖活动任务。
- trace 只保存最终压缩后的消息，工具统计 12 次与 usage 的 18 次请求不一致，仍不能完整还原压缩前轨迹。

## [021-qwen35-9b-local-baseline] - 2026-08-20

### Changed

- `src/intel_agent/config.py`、`src/intel_agent/main.py`：允许 `api_key_env: null`，使本机免密 OpenAI 兼容服务可被 Agent 和模型连通性检查共同使用。
- `config.example.yaml`、`README.md`：记录免密本地 llama-server 配置方式。
- `tests/test_config.py`、`tests/test_web_api.py`：覆盖免密配置解析和系统接口模型探测。
- `experiments/configs/qwen35-9b-llama-server.yaml`：固定本轮模型地址、模型 ID、搜索预算和关闭 deep crawl 的控制变量。

### Verification

- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff format --check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run ruff check .`：PASS
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pyright`：PASS（0 errors）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run pytest`：PASS（342 passed, 1 skipped，coverage 85%）
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv build`：PASS
- 本地 `build_agent` 冒烟：PASS；Qwen 调用 `intel_status` 1 次并返回 `LOCAL_AGENT_OK`。
- `UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv run python scripts/run_experiment.py --name qwen35-9b-local-baseline --topic "低空经济" --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" --recency 120 --min-sources 2 --min-quality 1 --max-turns 200 --config experiments/configs/qwen35-9b-llama-server.yaml`：FAIL（上下文 32,870 > 32,768，exit=1）

### Experiment result

- 状态：failed
- 产物：`experiments/runs/021-qwen35-9b-local-baseline/`
- 代码版本：`b6a00f3`（模型接口改动尚未提交，manifest 仅记录当时 HEAD）
- 真实运行：exit_code=1，stage=collect，elapsed=1094.0s；失败时未写 `trace.jsonl`，model_requests 和总 token 无法准确测量
- 关键指标：40 次搜索；矩阵 26 条中 5 条有结果；归档 3、证据 1、活跃事实 1、审核记录 0；0/5 问题 covered；无最终报告
- 假设结论：不成立；免密接口和 tool calling 冒烟成功，但真实任务在语义审核阶段生成失控并超过 32K 上下文，未完成研究主流程

### Known issues

- 审核角色缺少输出上限和历史压缩；现场 `/slots` 观测到一次约 32K 的生成（未持久化），run.log 可复核的后续请求因 32,870-token prompt 超限退出。
- 40 次搜索仅转化 3 篇文档和 1 条证据；9B 模型缺少可靠的 search → fetch → evidence 阶段转换。
- SearXNG/Bing 多次返回相同的节假日、日历和世界杯结果，并归档一篇无关政府页面。
- harness 仅在成功返回时写 trace，失败实验的请求数、token 和工具序列不可恢复；服务端也未启用 metrics。

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
