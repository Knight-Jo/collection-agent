# 迭代实验目录

对情报收集智能体（pydantic-ai 移植版）进行真实运行迭代实验。

完整操作规范（运行/观察/报告/ROADMAP 维护）见 [AGENTS.md](AGENTS.md)。

## 结构

```
experiments/
├── ROADMAP.md          # 实验记录与改进清单（跨实验）
├── runs/
│   └── NNN-<name>/
│       ├── manifest.json   # 实验配置（主题/问题/标准/耗时/git）
│       ├── trace.jsonl     # 完整 agent 消息轨迹（工具调用序列）
│       ├── run.log         # CLI 输出与错误
│       ├── state/          # data/intel 状态快照
│       ├── output/         # 证据包 + 研判报告
│       ├── ANALYSIS.md     # 结构化分析（scripts/analyze_run.py 生成）
│       └── REPORT.md       # 实验报告: 问题 + 改进方向
```

## 工作流

```bash
# 1. 运行实验（自动创建 runs/NNN-name 并保存全部产物；--max-turns 200 必填）
python scripts/run_experiment.py --name baseline --topic "低空经济" \
    --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" \
    --max-turns 200

# 2. 分析运行轨迹
python scripts/analyze_run.py experiments/runs/001-baseline --write

# 3. 根据 REPORT 中的问题改进代码 → 下一轮实验
```

## 迭代原则

1. 每轮实验只验证 1-2 个核心假设，改动最小化
2. 先分析 trace（工具序列/重复/错误）再下结论，不猜
3. 结论沉淀到 ROADMAP.md，防止同一问题复发
