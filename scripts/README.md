# 实验与诊断脚本

所有命令从仓库根目录执行，推荐使用 `uv run python`，确保脚本与项目虚拟环境中的代码版本一致。

## 快速开始

只给主题，由 Agent 自动生成问题：

```bash
uv run python scripts/run_experiment.py \
  --name topic-smoke \
  --topic "量子计算产业发展情况" \
  --config config.yaml \
  --dry 5
```

完整实验：

```bash
uv run python scripts/run_experiment.py \
  --name quantum-deep \
  --topic "量子计算产业发展情况" \
  --objective "分析政策、技术路线和商业化进展" \
  --questions "近期政策如何变化" "主要商业化进展有哪些" \
  --time-range "2024-2026" \
  --geography "中国" "美国" \
  --language zh-CN en \
  --report-depth deep \
  --config config.yaml
```

`--max-turns` 默认 200。`--dry N` 将工具调用上限设为 N，适合先验证模型、搜索和工具链；正式实验不要使用 `--dry`。

## 脚本用途

| 脚本 | 用途 |
|---|---|
| `run_experiment.py` | 执行一次隔离的 CLI 调研，保存 manifest、轨迹、会话、状态和报告 |
| `analyze_run.py` | 综合分析新版本 SQLite 状态或旧版本 JSON 状态 |
| `analyze_trajectory.py` | 校验轨迹关联，或按 action 重建决策因果链 |
| `analyze_conversation.py` | 查看完整模型会话，可输出终端文本或 HTML |
| `run_benchmark.py` | 为同一 Benchmark、模型和重复次数生成或执行实验命令 |
| `evaluate_runs.py` | 校验评测输入、计算单次得分并进行配对模型比较 |
| `smoke_conversation.py` | 测试 Conversation-first Web API、引用和续研动作 |

## 分析实验

```bash
RUN_DIR=experiments/runs/058-topic-smoke

uv run python scripts/analyze_run.py "$RUN_DIR" --write
uv run python scripts/analyze_trajectory.py "$RUN_DIR/trace.jsonl" --check
uv run python scripts/analyze_conversation.py "$RUN_DIR"
uv run python scripts/analyze_conversation.py "$RUN_DIR" --html "$RUN_DIR/conversation.html"
```

`analyze_run.py` 优先读取 `data/intel/intel.db`，归档目录只有 `state/intel.db` 时也可以分析，并继续兼容旧实验的 `state/tasks/*.json`。

## Conversation API 烟测

先启动服务：

```bash
intel-agent-web --config config.yaml
```

创建新对话并发送消息：

```bash
uv run python scripts/smoke_conversation.py \
  --question "请调研2026年中国低空经济政策进展"
```

开启 Web Bearer Token 时，密钥只通过环境变量传递：

```bash
export WEB_AUTH_TOKEN="..."
uv run python scripts/smoke_conversation.py \
  --auth-token-env WEB_AUTH_TOKEN \
  --question "当前调研结论是什么"
```

已有任务可使用 `--task-id`，已有未绑定对话可使用 `--conversation-id`。`--continuation` 可追加续研指令，`--confirm-proposal` 可确认模型提出的续研建议。

## 模型评测

```bash
uv run python scripts/evaluate_runs.py validate \
  --policy experiments/evaluation/policy.yaml \
  --benchmark experiments/evaluation/benchmark.example.json

uv run python scripts/run_benchmark.py \
  --benchmark experiments/evaluation/benchmark.example.json \
  --model-id deepseek-v4-flash \
  --config experiments/evaluation/configs/deepseek-v4-flash.yaml \
  --repeats 3
```

`run_benchmark.py` 默认只打印命令；确认配置和控制变量后再添加 `--execute`。每个 Benchmark Case 必须包含 2–6 个问题，与调研任务约束一致。

## 两类测试边界

- `run_experiment.py` 测试一次性 CLI 调研，包括模型、搜索、抓取、事实、证据和报告。
- `smoke_conversation.py` 测试当前 Conversation、ResearchRun 和续研 API。

两者用途不同；正式系统验收时应分别运行，不能用单次 CLI 实验替代 Conversation-first 生命周期测试。
