# Quickstart: 架构加固与多轮广深调研

本页描述计划实现后的验证顺序。P0/P1 必须先通过，之后才验证 AI-native 搜索。

## 1. Prepare a Reproducible Environment

```bash
mamba activate collection-agent-pydantic
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev
cp config.example.yaml config.yaml
```

先确认导入来自当前工作区，而不是旧 editable worktree：

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run python -c \
  "import intel_agent; print(intel_agent.__file__)"
```

输出路径必须位于当前仓库。若指向 `.worktrees/benchmark-dataset` 或其他目录，重新执行 `uv sync` 后再测试。

## 2. Static and Baseline Verification

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
```

完整 Web 验证：

```bash
cd web
bun install --frozen-lockfile
bun run test
bun run typecheck
bun run build
```

## 3. P0 Network Security Gate

运行安全回归，预期 literal、DNS answer、redirect 和 browser policy 都拒绝：

- `::ffff:127.0.0.1`
- `::ffff:10.0.0.1`
- `::ffff:169.254.169.254`

另外验证：

- 默认 Web host 是 `0.0.0.0`，无认证启动日志包含明确的开发暴露警告。
- 配置 bearer token/trusted host 后，所有 API、SSE 和资源下载都执行认证及 Host 校验；生产或外网部署不得使用未认证默认配置。
- pinned 请求失败后不会由另一个按 hostname 重新解析的 fallback 连接。
- 超限 document/search response 最多读取 `limit + 1` 字节。
- 含数万链接的 HTML 只产生配置上限内的唯一链接。

详见 [workbench-security.md](./contracts/workbench-security.md)。

## 4. P0 Committed-state Fault Injection

准备一个已有 committed Fact、full Evidence、Coverage 和已发布 ReportVersion 的任务，然后依次注入以下失败：

1. 续研创建新 Fact/Evidence/Review 后抛异常。
2. 续研尝试 supersede 已提交 Fact 后取消。
3. 续研修改 Conflict/Coverage 后进程退出。
4. 续研给已提交 Fact 新增未提交 Evidence/Review 后失败。

每次重启后预期：

- committed version、snapshot fingerprint 和旧报告状态不变。
- Agent context、TaskView、Retriever、资源下载和 ReportPublisher 都看不到 abandoned workspace。
- 已提交 Fact 仍保持原 revision；未提交 Evidence 不会成为 verified citation。
- orphan 内容文件可以存在，但没有 manifest 引用，不能影响正确性。

详见 [committed-state.md](./contracts/committed-state.md)。

## 5. Report Snapshot Race

在 ReportPublisher 读取 snapshot 后、落库前提交另一个 checkpoint。

预期结果：

- 报告落库 CAS 返回 `STALE_REPORT` 或重新针对新 snapshot 渲染。
- 旧内容不得绑定新的 committed version/checkpoint。
- Review、Conflict 或 Evidence 变化但 Fact ID 不变时，旧 Coverage fingerprint 仍被判 stale。

## 6. P1 Runtime Recovery Matrix

分别在以下状态关闭进程并重新创建 Runtime：

- accepted/processing message
- queued initial Run
- queued continuation Action
- queued report Action
- queued retry Run
- executing Action + running Run
- checkpoint committed、但 Run/Action 尚未完成

预期结果：

- queued work 只执行一次；一个 Action 最多一个 Run。
- 旧 active Run 明确转 interrupted；不会因未到两分钟 lease 永久卡住。
- 已提交 checkpoint 的组合幂等收敛为 succeeded；未提交组合转失败/中断并允许 retry。
- 过期 proposal 不发送 queued 事件、不创建 Run。
- queued cancellation 立即返回，不等待前一个长运行释放锁。

详见 [runtime-recovery.md](./contracts/runtime-recovery.md)。

## 7. Agent and Dialogue Gates

- 绑定 Task A 的 Agent 对 Task B、B 的 Fact/Document/Evidence/Plan 的读写全部返回 `INVALID_INPUT`。
- 只有 committed + active Fact + supports + full Review + valid Document 的 Evidence 被标为 verified。
- 只有 material clue 或未审核 Evidence 时，事实回答最多为 partial。
- repair 一个无效流式 JSON 时，客户端只能看到最终已验证答案。
- 一条 supports 加一条 contradicts 不得解除交叉验证 backlog。
- 极端 history compaction 始终小于配置字节上限，且 ToolCall/ToolReturn 完整配对。
- Judge 请求计入运行总预算；预算耗尽时保留已完成审核并披露缺口。

## 8. Run the Workbench

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run python -m intel_agent
```

验证新主题、计划和版本行为：

1. intake 创建绑定对话的任务和 queued initial Run。
2. 每个执行 Run 都能读取 active SearchPlanVersion。
3. 修改计划引用旧版本时返回 expired，不静默覆盖。
4. 在已绑定对话输入实质性新主题时提示新建对话和任务。
5. 空续研只记录 no-progress，不推进 committed version，不使报告 stale。

## 9. AI-native Search Gate

P0/P1 全部通过后，在 `config.yaml` 显式启用至少一个 AI-native Adapter，并设置对应环境变量：

```bash
export EXA_API_KEY='<redacted>'
# 或 BRAVE_SEARCH_API_KEY / TAVILY_API_KEY
```

使用同时包含国内外公开资料的主题，预期：

- 配置的 Exa、Brave 或 Tavily 提供带 provenance 的候选。
- 国内外公开搜索和垂直 Provider 继续工作。
- 单个 Adapter 缺密钥、超时、限流、无效响应或超限时只标 degraded。
- 搜索 answer、summary、snippet 和 highlight 不直接成为 Evidence。
- 正式报告引用来自固定 committed snapshot 中的归档原文。

## 10. Framework Decision Check

验收不应出现 `langchain`、`langgraph` 或第二套业务 checkpoint。若未来出现跨进程节点级恢复、多专家 fan-out/fan-in 或长期 HITL 的已测需求，再按 [research.md](./research.md#re-evaluation-triggers) 做隔离 spike。
