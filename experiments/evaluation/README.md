# 模型评测执行说明

本目录保存版本化评测口径和可直接运行的样例。样例评分是演示数据，不能作为任何模型的真实效果结论。

DeepSeek V4 256K 冻结材料实验的问题、根因和逐文件修复任务见
[`DEEPSEEK_V4_256K_FINDINGS.md`](DEEPSEEK_V4_256K_FINDINGS.md)。

## 文件

- `policy.yaml`：质量权重、硬门槛和小模型选型阈值。
- `benchmark.example.json`：任务、问题、必查来源、关键事实和冲突的格式样例。
- `evaluation.*.example.json`：一次运行的人工复核、自动指标和资源数据评分表。
- `results/`：本地生成的单次评分及对比结果，不提交到 Git。

所有比例型质量指标都使用 `0—1`，每项必须填写至少一个可复核的 `evidence` 引用。引用可以指向 `manifest`、`trace`、`ANALYSIS.md`、state 文件、报告章节或人工复核记录。

## 1. 校验格式

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run python scripts/evaluate_runs.py validate \
  --policy experiments/evaluation/policy.yaml \
  --benchmark experiments/evaluation/benchmark.example.json
```

## 2. 生成基准运行命令

省略 `--execute` 时只打印命令，不启动模型：

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run python scripts/run_benchmark.py \
  --benchmark experiments/evaluation/benchmark.example.json \
  --model-id qwen-local-27b \
  --config experiments/configs/qwen38-27b-vllm-16k.yaml \
  --repeats 3 --max-turns 200 --deep-crawl
```

确认模型、搜索服务和媒体处理器可用后追加 `--execute`。每次运行的 `manifest.json` 会记录 `benchmark_id`、`case_id`、`model_id` 和重复序号。

## 3. 填写评分表

复制相应 `evaluation.*.example.json`，替换运行目录、模型信息、指标、证据和资源数据。计算口径见项目文档《情报搜集智能体评估指标与模型对比方案》；禁止把样例数字复制为实测值。

## 4. 单次评分

```bash
mkdir -p experiments/evaluation/results

UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run python scripts/evaluate_runs.py score \
  --policy experiments/evaluation/policy.yaml \
  --benchmark experiments/evaluation/benchmark.example.json \
  --input experiments/evaluation/evaluation.cloud.example.json \
  --output experiments/evaluation/results/cloud.json

UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run python scripts/evaluate_runs.py score \
  --policy experiments/evaluation/policy.yaml \
  --benchmark experiments/evaluation/benchmark.example.json \
  --input experiments/evaluation/evaluation.local.example.json \
  --output experiments/evaluation/results/local.json
```

## 5. 配对比较

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run python scripts/evaluate_runs.py compare \
  --policy experiments/evaluation/policy.yaml \
  --baseline-model cloud-large \
  --scores experiments/evaluation/results/cloud.json \
           experiments/evaluation/results/local.json \
  --output experiments/evaluation/results/comparison.json \
  --markdown experiments/evaluation/results/comparison.md
```

正式比较必须保证每个模型覆盖相同 `case_id`。评分器只使用交集任务，并在结果中报告 `paired_cases`；成本缺失时选型结论为 `incomplete`，不会猜测本地部署收益。
