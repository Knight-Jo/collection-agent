# 情报搜集智能体可观测性技术报告

本文描述当前项目已经实现的可观测性体系，目标是帮助初学者理解代码、帮助开发者扩展事件，也可作为面试时讲述该项目架构与取舍的材料。

## 1. 为什么普通日志不够

一次调研不是单次模型问答，而是一条长链路：模型判断缺口、选择工具、搜索或抓取材料、写入事实和证据、重新评估覆盖度，最后决定继续还是停止。

普通文本日志适合回答“哪里报错了”，但很难稳定回答：

- 第 17 次搜索为什么发生？
- 这次搜索属于哪个关键问题或调查项？
- 工具是否返回结果，耗时多久？
- 搜索之后事实、证据和覆盖度发生了什么变化？
- 本轮消耗了多少模型请求和 Token，最终是否成功？

本项目因此使用一条结构化 JSONL 事件流，同时投影出 L1 技术层、L2 业务层和 L3 结果层。它不依赖 Logfire；当前也没有启用 OpenTelemetry exporter 或 PydanticAI Graph 采集。

```text
PydanticAI stream events ──┐
                           ├── TrajectoryEvent
业务工具与状态更新 ───────┘          │
                                      ▼
                                trace.jsonl
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
                  L1 技术层         L2 业务层         L3 结果层
```

## 2. 最重要的边界：轨迹不是业务状态

`intel_state` 和 SQLite `StateStore` 仍是任务、ResearchRun、事实、证据、覆盖结果和报告版本的权威状态。`trace.jsonl` 是旁路审计记录，用于解释“发生过什么”，不能用来重建或提交业务状态。

这个边界有三个好处：

1. 轨迹写入失败不会让一半业务事件被错误地当作已提交状态。
2. 分析脚本可以随时从事件流重新生成摘要，不需要维护第二份可变统计表。
3. 将来更换模型 SDK 时，只需继续产出同一事件格式，评测与分析工具无需跟着重写。

## 3. 一条事件的结构

事件模型和记录器位于 `src/intel_agent/trajectory.py`。每一行都是独立 JSON 对象，公共信封包含：

| 字段 | 作用 |
|---|---|
| `schema_version` | 数据格式版本，当前为 `1.0` |
| `run_id` / `task_id` | 关联 ResearchRun 和任务 |
| `event_id` | 事件唯一标识 |
| `sequence` | 单个文件内严格递增的顺序号 |
| `parent_event_id` | 构造 decision → action → observation 因果链 |
| `timestamp` | UTC 时间 |
| `layer` / `event_type` / `origin` | 层级、事件类型和事件来源 |
| `step_id` | 模型决策轮次 |
| `question_id` | 关联关键问题 |
| `investigation_item_id` | 关联更细粒度调查项 |
| `payload` | 各事件专属的受约束数据 |

事件类型只有七种：

- `run_started`：记录输入主题、目标、问题、验收标准和报告深度。
- `model_call`：记录模型请求序号、Token、结束原因和耗时。
- `decision`：记录选择了什么动作，以及可公开解释的原因码。
- `action`：记录工具、参数摘要和稳定的 `action_id`。
- `observation`：记录对应动作的状态、耗时和有界结果摘要。
- `state_updated`：记录事实、证据或覆盖状态的前后变化。
- `run_finished`：记录成功、失败或取消，以及资源消耗和最终覆盖度。

例如一次工具调用的因果链是：

```text
decision evt-d1
  └── action evt-a1, action_id=call-17
        └── observation, action_id=call-17
```

`parent_event_id` 负责事件级因果关系，`action_id` 负责跨 PydanticAI 工具调用和结果的稳定关联。两者用途不同，不应合并。

## 4. L1 技术层：系统实际执行了什么

主入口是 `run_agent_task()`。它消费 `agent.run_stream_events()` 暴露的 PydanticAI 原生事件，并在 `_translate_stream_event()` 中做最小映射：

```text
FunctionToolCallEvent   → decision + action
FunctionToolResultEvent → observation
RunUsage                → model_call + run_finished
```

L1 当前提供：

- 模型请求数、输入/输出 Token、模型调用耗时；
- 工具调用次数、工具类型、执行状态和耗时；
- `succeeded`、`failed`、`denied`、`interrupted` 四种工具结果；
- `succeeded`、`failed`、`cancelled` 三种运行终态；
- 失败类型 `error_code`，但不保存可能含密钥的原始异常消息。

工具结果不会原样复制到轨迹。记录器只保存类型、字节数、SHA-256、常用标量字段和列表数量。完整网页、搜索结果和模型消息应留在原业务资产或实验 artifact 中。这样既限制日志体积，也减少凭据和敏感内容泄漏风险。

当运行在 tool call 之后被取消或崩溃、PydanticAI 没有发出结果事件时，runner 会补一条 `status=interrupted` 的 observation。完整性检查因此能区分“工具失败”与“轨迹丢了一半”。

## 5. L2 业务层：为什么做、产生了什么变化

仅有技术事件仍无法解释调研策略。L2 由业务代码主动发出两个核心事件：

### 5.1 Decision

`decision` 保存结构化 `reason_codes`，例如覆盖不足、缺少一手来源或需要继续抓取。`reason_source` 明确区分来源：

- `rule`：确定性业务规则直接给出的原因；
- `derived`：系统依据调用工具和当时状态推导出的解释；
- `explicit`：业务输入中明确给出的原因。

`derived` 不是模型隐藏思维链，也不能伪装成模型的真实心理过程。它只是可复现、可审核的系统解释。

### 5.2 StateUpdated

事实、证据和 coverage 发生变化时，业务模块发出 `state_updated`，包含：

- `state_scope` 和稳定的状态 ID；
- `version_before` / `version_after`；
- 有界的 `before`、`after` 和 `delta`；
- 更新后规范化 JSON 的 SHA-256。

覆盖评估只记录 gap、等级、已覆盖问题数、无进展轮次和停止原因，不把完整覆盖对象复制进轨迹。事实更新会带上 `question_id` 和 `investigation_item_id`，用于计算每个问题真正获得了多少搜索、事实和证据。

确定性搜索矩阵也发出完整的 decision → action → observation，而不是只记录“决定搜索”。因此模型动作和规则动作可以在同一分析脚本中比较。

## 6. L3 结果层：如何判断这一轮是否值得

L3 不维护独立数据库，而是由 `scripts/analyze_trajectory.py` 从同一事件流确定性计算。当前摘要包含：

- 完整性：schema、唯一事件 ID、严格递增 sequence、父引用、生命周期和 action/observation 闭环；
- 技术指标：模型与工具耗时 P50/P95、成功率、Token 和调用分布；
- 业务指标：原因码分布、规则/推导来源、问题归属率、事实/证据更新数、coverage gap 变化；
- 结果指标：运行状态、最终 stage、错误类型和最终覆盖度；
- 资源指标：耗时、Token、模型请求和工具调用，可直接进入实验评测。

它有意不把“调用更多工具”当成质量更高。报告事实是否被证据支持、来源是否独立等质量指标，仍由现有 evidence audit 和 benchmark 评测负责；轨迹只提供资源与过程证据。

## 7. ResearchRun 生命周期如何接入

Web 多轮对话的初始调研和续研都以 ResearchRun 为运行实体：

- 初始运行默认写入 `data/runs/<run_id>/trace.jsonl`；
- 续研创建新的 ResearchRun，并写入该 run 自己的轨迹；
- `/api/runs` 兼容入口最终也复用 ResearchRun runner，因此没有第二套轨迹状态机；
- 排队时取消、构建 Agent 前失败等早期终止，由 lifecycle repair 补齐最小的 `run_started` 和 `run_finished`；
- 续研同样消费 PydanticAI stream events。仅测试 fake 没有流式接口时保留 `.run()` 兼容分支。

ContextVar 负责在异步调用和工具线程之间传递 run、task、step、question、investigation item 和 recorder。每次绑定都保存 token，并在 `finally` 中恢复上层上下文，避免一个并发运行的 ID 泄漏到另一个运行。

## 8. 可靠性保证

`JsonlTrajectoryRecorder` 采用 append-only JSONL，原因是它比单个大 JSON 更适合长运行：每次事件写入一行并立即 `flush()`，进程异常时最多损失尚未发出的事件，不会因为缺少末尾 `]` 而破坏整个文件。

当前保证包括：

- 多线程写入由锁保护，sequence 单调且一行不会交错；
- 重新打开已有文件时，从最大 sequence 继续编号；
- 文件末尾缺少换行时自动补齐，避免两条 JSON 粘连；
- 所有正常、失败和取消路径都尝试写入终态；
- 清理路径始终恢复 ContextVar、关闭 recorder 并释放 ResearchGate；
- 凭据字段、URL 查询密钥和异常详情不会进入结构化 payload。

`flush()` 不是 `fsync()`。机器断电时操作系统缓存中的最后几行仍可能丢失，这是当前本地开发版本接受的取舍。

## 9. 使用方法

### 9.1 校验轨迹完整性

```bash
uv run python scripts/analyze_trajectory.py \
  data/runs/<run-id>/trace.jsonl --check
```

成功时输出 `OK`；任何缺失终态、孤儿父事件或未闭合 action 都返回非零退出码，适合放入实验流水线。

### 9.2 查看或保存三层摘要

```bash
uv run python scripts/analyze_trajectory.py \
  data/runs/<run-id>/trace.jsonl --summary

uv run python scripts/analyze_trajectory.py \
  data/runs/<run-id>/trace.jsonl \
  --summary --output data/runs/<run-id>/summary.json
```

不带 action 参数时也会默认输出摘要。

### 9.3 回放某次动作的因果链

```bash
uv run python scripts/analyze_trajectory.py \
  data/runs/<run-id>/trace.jsonl --action-id <action-id>
```

实验目录还可以按第 N 次 `web_search` 定位：

```bash
uv run python scripts/analyze_trajectory.py \
  experiments/runs/<run>/trace.jsonl --action 17
```

### 9.4 生成实验报告和资源输入

```bash
uv run python scripts/analyze_run.py experiments/runs/<run> --write

uv run python scripts/evaluate_runs.py resources \
  --trace experiments/runs/<run>/trace.jsonl \
  --output experiments/runs/<run>/resources.json
```

`analyze_run.py` 会把三层摘要写入 `ANALYSIS.md`；`resources` 命令生成评测模型需要的可复现资源字段。

## 10. 如何扩展

### 新增工具

如果工具通过 PydanticAI 标准 `FunctionToolCallEvent` 和 `FunctionToolResultEvent` 执行，L1 通常无需修改。只需要：

1. 确认参数中的 `question_id` / `investigation_item_id` 能被传入；
2. 如需在结果摘要中保留新的标量，在 `_RESULT_SCALAR_KEYS` 增加字段；
3. 为新的确定性业务动作补齐 decision、action 和 observation。

### 新增业务状态

在状态真正提交成功后调用 `emit_state_updated()`。不要先写轨迹、后写业务状态，否则轨迹会声明一个实际没有提交的变化。只传分析所需的最小 before/after 字段。

### 新增原因码或指标

原因码应来自可说明的业务规则，并在 `reason_rules.py` 统一维护。新指标优先在 `summarize()` 中从现有事件推导；只有无法从现有事件得到时，才增加 payload 字段或事件类型。

### 修改数据格式

新增可选字段可以保持 `1.0`。删除字段、改变语义或类型时必须升级 `schema_version`，同时更新校验器、分析脚本和回归测试。不要让分析器猜测不同版本字段的含义。

## 11. 当前局限与升级条件

| 局限 | 当前影响 | 何时升级 |
|---|---|---|
| 单文件 JSONL + 进程内锁 | 适合本机单进程，不适合多个进程同时写同一 run | 多 worker 共享运行时改为单 writer、数据库或日志队列 |
| 启动时扫描文件查最大 sequence | O(n)，长轨迹打开会变慢 | 单条轨迹达到数十万事件后增加 sidecar checkpoint 或数据库序列 |
| `flush()` 不执行 `fsync()` | 断电可能损失尾部事件 | 有强审计或合规耐久性要求时批量 fsync/WAL |
| 结果是摘要，不是完整内容 | 不能只靠 trace 重放研究资产 | 调试内容问题时同时读取业务状态和受控 artifact |
| derived reason 是规则推断 | 不能证明模型真实理由 | 需要更强解释时让 Agent 输出受约束的公开 reason code，不采集隐藏思维链 |
| 暂无 OTel | 看不到跨 HTTP、模型服务和搜索服务的分布式性能树 | 出现跨服务性能定位需求时接标准 OTel exporter |
| 暂无 Graph 节点轨迹 | 看不到 PydanticAI 内部节点级状态 | 调试 Agent Graph 路由时按开发开关采集，避免与主流事件重复 |
| 没有内置日志保留策略 | 长期运行会占用磁盘 | 部署时按敏感级别和审计周期做归档/删除 |

## 12. 面试讲述模板

可以按“问题—设计—可靠性—取舍—结果”讲述：

> 这个情报搜集 Agent 是多轮、长时间、工具密集型工作流，文本日志无法解释为什么重复搜索，也不能稳定计算覆盖增益。我把 PydanticAI 的工具流事件和业务状态更新映射到统一的 append-only JSONL 事件流，再从同一数据源投影 L1 技术指标、L2 决策语义和 L3 结果评测。action_id 与 parent_event_id 保证因果关联，ContextVar 保证并发上下文，终态修复和 interrupted observation 保证失败、取消路径也可审计。轨迹是旁路记录，SQLite 和 intel_state 仍是业务真相，因此没有引入事件溯源的一致性复杂度。当前单机版本没有接 OTel；只有出现跨服务性能定位需求时才增加。

面试官继续追问时，可以强调：

- 为什么不用完整消息做日志：体积、敏感数据和重复存储成本太高；
- 为什么不用模型思维链：不可验证且不应采集，改用结构化原因码；
- 为什么不用三套存储：三层是同一事件流的投影，避免统计口径漂移；
- 如何判断轨迹可信：严格 sequence、唯一 ID、生命周期和 action/observation 不变量；
- 如何演进：先保持统一 schema，需要跨服务性能树时再旁接 OTel，而不是替换业务轨迹。

## 13. 代码导航

| 文件 | 职责 |
|---|---|
| `src/intel_agent/trajectory.py` | 事件模型、脱敏、上下文和 JSONL recorder |
| `src/intel_agent/runner.py` | PydanticAI 事件转换、模型与运行生命周期 |
| `src/intel_agent/continuation.py` | ResearchRun 初始运行、续研和提前终止修复 |
| `src/intel_agent/coverage.py` | 覆盖评估状态变化 |
| `src/intel_agent/fact.py` | 事实变化与问题/调查项归属 |
| `src/intel_agent/agent.py` | 确定性动作的业务轨迹 |
| `scripts/analyze_trajectory.py` | 完整性校验、因果回放和三层摘要 |
| `scripts/analyze_run.py` | 实验目录综合报告 |
| `scripts/evaluate_runs.py` | 从轨迹提取评测资源字段 |
