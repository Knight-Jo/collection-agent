# DeepSeek V4 256K 实验问题与修复任务

本文用于把 2026-08-22 的云端模型实验交接给后续开发 Agent。每个工作包必须独立
实现、独立测试、独立提交，不得一次修改多个工作包。

## 1. 实验边界

| 项目 | 实际值 |
| --- | --- |
| 代码版本 | `6b90f50` |
| 模型 | `deepseek-v4-flash`、`deepseek-v4-pro` |
| 上下文 | 262144 tokens（256K） |
| 思考模式 | 开启 |
| 任务 | `low-altitude-policy-001`，2 个用户问题 |
| 输入 | 5 个固定政府公开页面 |
| 搜索 | 关闭；本轮是冻结材料实验，不评价搜索召回 |
| 单次截止 | 10 分钟 |

实验使用的提交不包含 `main` 工作区尚未提交的 037 终态切换。因此，037 已解决的
`assess + no_progress → done/with_gaps` 不应重复实现；本轮新增问题发生在 collect 和
证据审核阶段，仍需单独修复。

## 2. 实测结果

| 指标 | V4 Flash | V4 Pro |
| --- | ---: | ---: |
| 运行时间 | 586.4 秒 | 608.3 秒 |
| 最终阶段 | collect | collect |
| 最终问题数 | 4 | 5 |
| 归档文档 | 5 | 5 |
| 事实 | 10 | 14 |
| 证据 | 10 | 8 |
| 事实证据覆盖率 | 100% | 57.14% |
| 覆盖快照 | 0 | 0 |
| 报告 | 0 | 0 |
| 上下文溢出 | 0 | 0 |
| 诊断质量分 | 54.58 | 49.63 |
| 有效运行 | 否 | 否 |

两次运行都由操作员在 10 分钟截止时中断。中断后没有 `trace.jsonl`，所以模型请求数、
token、工具调用合法率和云端成本均未测量。质量分只能用于诊断，不能作为模型选型
结论。

## 3. 修复顺序

### WP1（P0）：冻结用户问题

**现象**

- 用户明确给出 2 个问题，Flash 扩展为 4 个，Pro 扩展为 5 个。
- Flash 只有 5/10 条证据用于原始问题；Pro 只有 3/8 条已登记证据用于原始问题。

**根因**

- `src/intel_agent/runner.py::build_task_prompt` 明确要求模型“原样保留并补充必要问题”。
- `src/intel_agent/agent.py::_intel_plan` 信任模型传入的 `questions`，没有与
  `TaskRunSpec.questions` 做确定性比对。

**只允许修改**

- `src/intel_agent/runner.py`
- `tests/test_runner.py`

**最小实现**

- 当 `TaskRunSpec.questions` 非空时，提示改为“必须且只能使用以下问题，不得新增、
  删除、合并或改写”。
- 主题模式下仍允许模型生成 3—6 个问题，不改变现有行为。

**验收**

- 新增回归测试：显式问题提示包含“不得新增”，且不再包含“补充必要问题”。
- 真实冒烟运行后，state 中问题文本、顺序和数量与 manifest 完全一致。
- `pytest -q tests/test_runner.py` 通过。

### WP2（P0）：限制证据审核并发并设置超时

**现象**

- Flash 冒烟单轮规划 7 个工具调用，Pro 规划 10 个。
- Flash 审核阶段同时保持 10 余个外部连接，数分钟无状态推进。
- Pro 在 14 条事实中只完成 8 条证据审核。

**根因**

- `src/intel_agent/audit.py::audit_task_evidence` 使用无上限 `asyncio.gather`，为全部
  fact 同时调用 judge。
- `src/intel_agent/agent.py::JudgeAgent.__call__` 没有单次审核超时。
- 审核结果在全部请求返回后才统一落盘；一个长尾请求会阻塞整个批次。

**允许修改**

- `src/intel_agent/config.py`
- `src/intel_agent/audit.py`
- `src/intel_agent/agent.py`
- `tests/test_audit.py`
- `tests/test_config.py`

**最小实现**

- 增加 `context.audit_concurrency`，默认 2；增加
  `context.audit_timeout_seconds`，默认 60。
- 使用标准库 `asyncio.Semaphore` 限制 judge 并发，并用 `asyncio.timeout` 限制单次
  请求。
- 每一小批完成后立即原子保存 review；超时项返回明确的
  `SEMANTIC_AUDIT_TIMEOUT`，已完成 review 不回滚。
- 不增加任务队列框架，不引入新依赖。

**验收**

- 假 judge 同时活跃数始终 `<= audit_concurrency`。
- 一个永久等待的 judge 在配置时间内退出，其他已完成 review 保留。
- 10 条证据、并发 2 的测试不会创建超过 2 个并行请求。
- `pytest -q tests/test_audit.py tests/test_config.py` 通过。

### WP3（P0）：中断时保留增量轨迹和资源计数

**现象**

- 两次实验都因中断没有 `trace.jsonl`。
- `ANALYSIS.md` 显示 0 次工具调用，无法计算请求、token、错误率和成本。

**根因**

- `src/intel_agent/main.py::_run` 仅在 `run_agent_task` 正常返回后调用 `_write_trace`。
- `src/intel_agent/runner.py::run_agent_task` 虽逐事件消费流，但没有持久化事件。

**允许修改**

- `src/intel_agent/main.py`
- `src/intel_agent/runner.py`
- `scripts/analyze_run.py`
- `tests/test_runner.py`
- 新增或使用现有 CLI 测试文件

**最小实现**

- 复用现有 `on_event` 回调，在每个模型响应、工具调用和工具返回后追加一条 JSONL。
- 正常结束时补写最终 usage 摘要；中断和异常时在 `finally` 中写终止事件。
- `analyze_run.py` 同时兼容旧版整块 JSON 和新版逐行 JSONL。
- 不在轨迹中写 API key、Authorization、Cookie 或完整敏感请求头。

**验收**

- 模拟第二轮抛出 `CancelledError` 后，trace 仍包含第一轮工具事件和终止事件。
- 正常运行的工具计数与 trace 行数可复核。
- 旧实验 trace 仍能被 `analyze_run.py` 读取。

### WP4（P0）：collect 阶段确定性收敛

**现象**

- 两次运行均已有官方文档和有效证据，但始终停留在 collect，没有 coverage 或报告。
- 037 只处理 assess 阶段的 `no_progress`，不能覆盖本轮 collect 阶段审核长尾。

**前置条件**

- 必须先完成 WP2 和 WP3；没有审核超时和轨迹时不得猜测新的终态规则。

**允许修改**

- `src/intel_agent/runner.py`
- 必要时修改 `src/intel_agent/agent.py` 的覆盖评估返回值
- `tests/test_runner.py`
- `tests/test_deep_crawl_workflow.py`

**最小实现方向**

- crawl 已完成且至少存在一条 full review 时，审核批次完成后必须进入
  `coverage_eval`。
- collect 连续两轮 facts/reviews/coverage 指纹不变时，确定性推进到 assess，并复用
  037 的 `with_gaps` 报告路径。
- 不把“增大 max_turns、上下文或 HTTP 超时”作为收敛修复。

**验收**

- 固定 5 文档、10 条候选证据场景在 10 分钟内到达 done/with_gaps。
- 输出必须有报告和最新 coverage 绑定。
- 零 full review 时允许诚实空报告，但不得把 partial 写成结论。

### WP5（P1）：恢复可用的搜索候选

**现象**

- SearXNG 首页可访问，但 `/search` 查询超时。
- Bing 中国旧端点会重定向；改为 `www.bing.com` 后，部分中文组合查询仍返回明显
  不相关或不安全候选。
- 本轮只能关闭搜索，不能衡量覆盖范围。

**相关文件**

- `src/intel_agent/search.py`
- `src/intel_agent/agent.py::_web_search`
- `tests/test_search.py`
- `tests/test_deep_crawl_workflow.py`
- `experiments/AGENTS.md`

**修复方向**

- 健康检查必须执行一次真实 `/search` 查询，不能只检查首页。
- 将现有主题相关性门禁应用到返回给模型的 candidates，而不只用于 crawl seed。
- 无主题词匹配的候选返回空结果并记录原因；不得自动抓取成人、脚本或可执行内容。
- 保留 SSRF、robots 和重定向逐跳校验，不实现登录、验证码破解或反爬绕过。

**验收**

- 固定恶意/无关搜索结果夹具不会进入模型 candidates 或 crawl frontier。
- 真实中文查询 Top10 相关率至少 70%，必查官方来源 Top50 召回率 100%。
- 搜索服务不可用时快速失败并标明 engine，而不是等待到任务超时。

### WP6（P1）：区分冻结材料和端到端评分

**现象**

- 冻结材料配置用 `search_attempts=0` 模拟禁用搜索，任务被标成
  `search_budget_exhausted`。
- 搜索未测时仍会生成一个数值搜索分，容易误读。

**相关文件**

- `scripts/evaluate_runs.py`
- `experiments/evaluation/policy.yaml`
- `experiments/evaluation/README.md`
- `tests/test_evaluate_runs.py`

**修复方向**

- 最简单方案是新增独立 `policy.frozen.yaml`，去掉搜索组并重新归一化权重。
- 运行清单明确记录 `evaluation_mode=frozen|live`，不同模式禁止直接计算保持率。

**验收**

- frozen 评分不出现 `precision_at_10` 或 `must_find_recall_at_50`。
- compare 拒绝配对不同 evaluation mode 的结果。

### WP7（P2）：补齐多媒体 benchmark

本轮 5 个固定来源都是 HTML，benchmark 声明的 PDF 要求未被验证。新增一套固定、体积
较小、许可证明确的公开材料，至少各包含 HTML、PDF、DOCX、XLSX、PPTX、PNG/JPEG、
MP3/WAV 和 MP4/WebM。处理器缺失场景必须单独测试，不能与处理器可用场景混算。

验收要求：每种格式至少 3 个夹具；抽取成功率、原件哈希、引用行号/时间戳和处理器
缺失降级均有自动测试，且 unsupported/unavailable 内容不能进入正式证据。

## 4. 禁止做法

- 不通过扩大上下文、轮次或超时掩盖死循环。
- 不删除失败运行或把中间 facts 当作正式报告。
- 不关闭 robots、SSRF、DNS pinning 或内容类型限制换取覆盖率。
- 不让模型自由决定终态转换。
- 不同时实施多个工作包；每包必须先写失败测试，再做最小修复。

## 5. 推荐执行顺序

`WP1 → WP2 → WP3 → WP4 → WP5 → WP6 → WP7`

WP1—WP4 完成后先复跑 Flash 单次；达到 done/with_gaps 后，再对 Flash 和 Pro 各跑
3 次配对实验。有效运行率仍低于 90% 时不得进入模型选型或蒸馏结论。
