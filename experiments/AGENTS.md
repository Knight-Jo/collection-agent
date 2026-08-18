# 迭代实验操作规范（Agent 版）

对情报收集智能体（pydantic-ai 移植版）进行真实运行迭代实验。本文件是 Agent 执行实验观察的完整操作规范。

## 实验循环

每轮实验遵循：**假设 → 最小改动 → 实跑 → 观察 → 结论 → 沉淀 ROADMAP**。

1. 每轮只验证 1–2 个核心假设，代码改动最小化
2. 先分析 trace（工具序列/重复/错误）再下结论，不猜
3. 结论沉淀到 `ROADMAP.md`，防止同一问题复发

## 目录与产物

```
experiments/
├── ROADMAP.md          # 实验记录 + 改进清单 + 跨实验结论
├── runs/
│   └── NNN-<name>/
│       ├── manifest.json   # 配置/主题/问题/标准/耗时/git/exit_code
│       ├── trace.jsonl     # 完整 agent 消息轨迹（工具调用序列）
│       ├── run.log         # CLI 输出与错误
│       ├── state/          # data/intel 状态快照（tasks/facts/evidence/coverage/conflicts/challenges）
│       ├── output/         # 证据包 + 研判报告
│       ├── ANALYSIS.md     # 结构化分析（scripts/analyze_run.py --write 生成）
│       └── REPORT.md       # 实验报告：成果 + 问题分级 + 下一轮建议
```

## 运行规范

```bash
python scripts/run_experiment.py --name <hypothesis> --topic "低空经济" \
    --questions "问题一" "问题二" [--recency 120] [--min-sources 2] \
    [--min-quality 1] --max-turns 200 [--dry N] [--deep-crawl] [--config path]
```

- **命名**: 序号自动递增，`name` 描述本轮假设（如 `fix-repetition`、`cross-verify-with-gaps`）
- **控制变量**: 主题与 questions 尽量沿用上一轮（现用「低空经济」两问），每轮只变 1–2 个变量；变更列表要写进 REPORT
- **`--max-turns` 必须传 200**：runner 将其映射为 pydantic-ai `request_limit=min(config.budgets.request_limit, max_turns)`，默认 40 会把预算从 200 压到 40，跑到一半 `UsageLimitExceeded`（007 首跑教训）
- **冒烟调试**: 先 `--dry 5` 跑几轮工具调用验证 harness，再完整运行
- **环境前置检查**（跑前确认，缺一项就修一项）:
  - `DEEPSEEK_API_KEY` 已导出、`config.yaml` 存在
  - searxng 可访问（`curl http://127.0.0.1:8888/`）或 config 中 searxng_url=null 走 Bing/Baidu
  - 多媒体依赖：`which tesseract`（OCR，007 缺失导致 26 图全 unavailable）、`which ffmpeg`、`python -c "import faster_whisper"`、`which libreoffice`
  - 浏览器 fallback：`fetch.enable_browser_fallback`（默认 false，开了才可能走 Playwright 渲染）
- 每次实跑约 10–30 分钟、50–200 次模型请求；中途失败先读 run.log 错误码，不盲目改代码

## 观察规范（分析阶段）

```bash
python scripts/analyze_run.py experiments/runs/NNN-name --write
```

按以下清单逐项检查，一切结论附 trace/state 证据：

1. **终态**: manifest 的 `exit_code` + state/tasks 的 `stage`（done/challenge/collect…）与 `challenge_round`
2. **资源**: `elapsed_seconds`、模型请求数、token 量；请求数贴着 request_limit 即预算问题
3. **工具分布**: 各工具调用次数；注意 `web_fetch`/`document_search` 是否被采纳（新工具要有采纳证据才算验证成功）
4. **重复/可疑调用**: 连续相同工具调用（死循环信号，003 教训）
5. **错误码**: run.log 中 `[XXX]` 模式（如 BROWSER_UNAVAILABLE、UNSAFE_URL、COLLECTION_BUDGET_EXHAUSTED）
6. **覆盖快照**: `level`、`gap_score`、`stop_reason`、`no_progress_rounds`、per-question status
7. **语料质量**: state/documents 的文档类型分布与 unavailable 原因（图片占比、robots、空正文）
8. **事实**: active/superseded 数量与单源占比（srcs=1 说明交叉验证未生效）
9. **冲突与挑战**: conflicts 条数、挑战轮次收敛情况（confirm 一次成功才算稳定）

**陷阱（007 实证）**:
- `exit_code=0` 且 stage=done ≠ 成功：gap 高、事实稀少仍算失败
- gap_score 下降可能是"事实稀少"的假象——语料越干净事实越少、分数越低
- 挑战收敛（converged）≠ 证据充分；completion_status 曾误标 sufficient

## 报告规范（REPORT.md 模板）

```markdown
# 实验 NNN — <name>（<本轮假设一句话>）

- 主题: <topic>（同 NNN，控制变量）
- 变更: ①… ②…（每项指向代码/提示词改动）
- 耗时: **Xs（X 分钟）**，exit=N，N 次模型请求（N tokens）

## 核心成果（对比 NNN）
| 维度 | 上轮 | 本轮 | 说明 |
…（终态/文档/证据/事实/gap_score/挑战/关键数据命中）

## 暴露的问题
### P0/P1/P2/P3 — <标题>
现象 → 根因 → 修复方向（每条必须三段齐全）

## <NNN> 结论
假设验证结果：成立/不成立 + 一句话证据

## <NNN+1> 建议（候选）
按优先级列出下一轮可做的改动
```

## ROADMAP 维护规范

每轮结束必须更新 `ROADMAP.md` 三处：

1. **运行记录表**新增一行：结果一句话 + 关键改进/问题
2. **改进清单**：完成的勾选；新问题按 P0–P3 追加待办
3. **结论沉淀**：跨实验可复用的规律（如"证据链框架零故障""检索质量三杠杆"）追加到结论区

## 禁止事项

- 不凭印象下结论：每个判断必须能指出 trace/ANALYSIS/run.log 里的具体证据
- 不伪造指标：对比表数字必须来自 ANALYSIS.md 或 state 快照
- 不跳过环境检查直接跑：tesseract、ffmpeg、faster-whisper、LibreOffice、浏览器或搜索栈缺失会静默改变实验结果
