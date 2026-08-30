# Implementation Plan: 多轮广深情报调研

**Branch**: `001-conversational-research` | **Date**: 2026-08-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-conversational-research/spec.md`

## Summary

先修复当前实现中会破坏安全、任务隔离和 committed-state 可信度的缺口，再增加 Exa、Brave、Tavily 等 AI-native 搜索渠道。保留 Pydantic AI 作为模型与工具循环的 Implementation；不迁移 LangChain 或 LangGraph。P0 工作包括 SSRF 绕过、默认未认证网络暴露、未提交资产污染、报告快照竞态和任务工具越权；P1 工作统一 Action、ResearchRun、ResearchCheckpoint 的认领、完成与恢复语义；P2 再补 SearchPlanVersion、上下文/预算边界和搜索 Adapter。搜索摘要始终只是候选线索，正式事实必须来自同一 committed snapshot 中已归档、审核的证据。

## Technical Context

**Language/Version**: Python 3.12；现有 Web 工作台为 TypeScript、Bun 1.3.14

**Primary Dependencies**: Pydantic AI 2.x、Pydantic 2、FastAPI、httpx、PyYAML；不新增 LangChain、LangGraph 或厂商 SDK

**Storage**: SQLite WAL 保存任务、对话、运行、检查点、报告版本和持久事件；任务目录保存内容寻址的归档材料和研究资产；本计划要求一个数据库迁移以加强 Action/Run 唯一性、资产版本可见性和原子完成

**Testing**: pytest、pytest-asyncio、Ruff、Pyright；Web 侧使用 Bun test、TypeScript typecheck、Biome 和 build

**Target Platform**: 首版为本地单机单用户 Linux 部署，同时提供 CLI 和 Web 工作台

**Project Type**: Python 应用，含 FastAPI 后端、CLI 和独立 Web 前端

**Performance Goals**: 外部响应在解析前执行硬字节上限；运行受模型、审核、搜索、抓取总预算约束；可用渠道并发执行；单个渠道失败不阻断其他渠道；长运行持续输出阶段与降级信息

**Constraints**: 仅访问公开网络；开发默认监听 `0.0.0.0` 并在未认证时明确警告；生产或外网暴露必须启用认证和可信 Host；密钥只从环境变量读取；搜索摘要不得成为证据；`StateStore` 是唯一业务状态源；所有读路径使用同一个 committed snapshot；Agent 工具绑定唯一 Task/Run；首版同一工作区只允许一个活动调研运行；不得引入第二套消息、事实、证据或报告持久化

**Scale/Scope**: 每个任务 2 至 6 个核心问题；默认抓取上限 200 个 URL、深度 2（部署可调）；本地单用户、单工作区运行；完成 P0/P1 门禁后实现 Exa、Brave、Tavily 三个可选 Adapter，并保留现有国内外通用和垂直搜索渠道

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

项目 constitution 仍为未填充模板，没有可执行的项目级门禁。本计划依照仓库 `AGENTS.md` 和规格中的安全、隔离、恢复不变量检查。当前实现存在阻断项，但本设计给出对应修复；AI-native 搜索实现不得先于 P0/P1 门禁：

- **PASS — 最小依赖**: 复用 Pydantic AI、httpx 和现有 SearchProvider，不增加编排框架或厂商 SDK。
- **PASS — 单一状态源设计**: 不引入图 checkpoint 或第二个 Run registry；SQLite StateStore 继续拥有业务状态。
- **PASS — committed snapshot 设计**: 所有事实、证据、审核、冲突、覆盖和报告读取通过同一可见性 Module；运行中写入在 checkpoint 前不可见。
- **PASS — 安全设计**: 修复 IPv4-mapped IPv6 SSRF；保留开发默认 `0.0.0.0` 并输出未认证暴露警告；生产配置认证和可信 Host；删除不安全 DNS 回退；外部响应流式限额。
- **PASS — 原子生命周期设计**: Action 认领、Run 创建、checkpoint 提交和终态收敛由 StateStore 事务化；启动恢复全部持久工作。
- **PASS — 可验证性**: P0/P1 每项均有故障注入、跨任务和安全回归场景；P2 才进入供应商响应归一化测试。

**Phase 1 复核**: PASS（有前置门禁）。数据模型保持一个业务状态源并增加最小 schema 约束；契约定义 committed snapshot、恢复和网络安全不变量。只有 P0/P1 验证通过后才能接入新的付费搜索 Adapter。

## Architecture Decision

### 保留 Pydantic AI

Pydantic AI 当前只负责模型调用、工具循环、结构化输出、历史、预算、取消和流事件；任务状态、证据可信度和报告发布均由框架外的深 Module 控制。迁移 LangChain 会替换已经工作的同类能力，迁移 LangGraph 则会在现有 `ResearchRun`/`ResearchCheckpoint` 之外增加第二套执行状态和恢复语义，当前规格没有相应收益。

### 深化现有搜索 Seam

`SearchProvider` 是已经被多个垂直搜索 Adapter 使用的稳定 Interface，但通用 `web_search` 仍直接调用 SearXNG、Bing、Baidu 和 Baidu News。实现阶段将让 `web_search` 复用该 Interface，接入 Exa、Brave、Tavily，统一结果归一化、缓存、限流、去重、超时和降级。Agent 仍只看到一个 `web_search` 工具，避免供应商细节和密钥进入模型上下文。

### 保持业务检查点语义

搜索结果只产生候选 URL。网页必须经既有 fetch、archive、evidence 和 support review 流程，才能在 `ResearchCheckpoint` 中成为已提交材料。供应商返回的 answer、summary 或 highlights 不直接进入正式证据。

### 修复 committed-state Interface

当前 `ResearchCheckpoint` 只记录 document/fact/evidence ID，但工具会直接修改共享 Fact、Review、Conflict、Coverage 和 Task 文件；失败运行仍可能改变后续 Agent、对话和报告。本计划新增一个深的 committed-state Module：普通读取只看固定 snapshot；活动 Agent 读取“固定 snapshot + 当前 Run 工作集”；所有新资产使用不可变内容或修订记录，checkpoint 原子提升可见性。禁止调用方自行扫描全局 JSON 目录判断当前状态。

### 统一持久运行生命周期

Action 认领与唯一 Run 创建在一个事务完成；Run 结果、checkpoint、Action 终态在一个事务收敛。启动时恢复 queued Action/initial Run，收敛 executing/旧 active Run，并提供实际可执行的 retry。旧内存 `/api/runs` 不再作为第二套状态真相。

### 安全默认值

HTTP 抓取必须使用实际连接地址已验证的路径，逐跳重定向校验保持不变；IPv4-mapped IPv6 归一化后再判断公网。为方便本地和局域网开发，默认监听 `0.0.0.0`；未配置认证时必须输出醒目警告，生产或外网暴露必须显式配置认证令牌和可信 Host。外部正文、搜索响应和 HTML 链接数量在完整缓冲或持久化前受硬上限约束。

## Project Structure

### Documentation (this feature)

```text
specs/001-conversational-research/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── configuration.md
│   ├── committed-state.md
│   ├── runtime-recovery.md
│   ├── search-provider.md
│   └── workbench-security.md
└── tasks.md                 # 由 $speckit-tasks 生成，本阶段不创建
```

### Source Code (repository root)

```text
src/intel_agent/
├── agent.py                 # 工具绑定唯一 Task/Run；修正预算和证据门禁
├── audit.py                 # 审核只读取当前 Run 工作集并计入运行预算
├── context.py               # committed snapshot + 合法且严格有界的历史
├── continuation.py          # 调用 StateStore 的原子 claim/finish Interface
├── conversation.py          # 恢复 queued work，移除重复调度窗口
├── config.py                # 安全默认值和 AI-native 配置
├── fetch.py                 # 公网地址归一化、固定连接、流式字节上限
├── report_versions.py       # 固定 snapshot 渲染和 expected-version CAS
├── security.py              # 完整公网地址判断
├── state_db.py              # 最小约束迁移
├── state_store.py           # committed snapshot 与生命周期事务
├── web/
│   ├── app.py               # 开发暴露警告、可选认证/Host、移除内存 Run 真相
│   └── conversation.py      # retry/recovery 与最终验证后事件
└── search/
    ├── __init__.py          # 通用 web_search 统一编排现有和新增 Provider
    ├── provider.py          # 复用 Interface、注册、缓存、限流、去重
    └── providers/
        ├── exa.py
        ├── brave.py
        └── tavily.py

tests/
├── test_security.py
├── test_state_store.py
├── test_continuation.py
├── test_conversation_recovery.py
├── test_retrieval.py
├── test_report_versions.py
├── test_context.py
├── test_web_api.py
├── test_config.py
├── test_search.py
└── test_search_providers.py

config.example.yaml          # 示例开关与环境变量名
README.md                    # 配置、降级和证据边界说明

web/                         # 现有 API/界面契约不变
```

**Structure Decision**: 保持现有单一 Python 项目和独立 Web 工作台。修复现有 StateStore、storage、fetch、runtime 和 search Module；不增加 orchestration 框架、repository、factory 或第二个运行时 Module。committed-state 是现有 StateStore/storage 之上的一个深读取 Interface，不是新的持久化系统。

## Implementation Boundaries

1. 先修复 IPv4-mapped IPv6 SSRF、不安全 httpx DNS 回退和未认证开发监听缺少警告的问题；提供生产认证/Host 配置，并对所有外部响应流式限额。
2. 把 Task/Run 固定在 AgentDeps，所有 Task-scoped 工具从依赖取值或拒绝不匹配 ID；停止依赖全局 active-task 指针做授权。
3. 建立 committed snapshot 读取 Interface；过滤未提交/未 full 审核/已 superseded 资产；现有可变状态改为 append-only 修订或 Run 工作集。
4. StateStore 原子 claim Action + 创建唯一 Run，并原子完成 checkpoint + Run + Action；空工作集不推进版本，只记录明确的 no-progress outcome。
5. 启动恢复 queued Action、queued initial/retry Run 和 executing 遗留状态；单机模式启动时直接中断旧 active Run，不保留无 heartbeat 的虚假 lease。
6. 报告针对一次固定 `{state_version, checkpoint_id, asset hashes}` 渲染，并以 expected-version CAS 落库；coverage fingerprint 校验不得被 allowlist 覆盖。
7. 修正上下文极端压缩、Judge 总预算、流式答案先校验后展示、支持/反证来源计数和 httpx client 关闭。
8. 接通 SearchPlanVersion、modify-plan/new-topic 行为；移除或迁移旧内存 `/api/runs`。
9. 完成上述门禁后，为 Exa、Brave、Tavily 实现现有 `SearchProvider` Interface，并保留当前证据归档流程。

## Remediation Order

### P0 — 新搜索接入前必须完成

1. SSRF、开发监听警告/生产认证和 httpx 回退。
2. committed snapshot、未提交资产隔离和可变资产版本化。
3. 对话只将 full supporting evidence 标为 verified；TaskView/下载/报告不暴露工作态。
4. 报告固定快照和 CAS，保留完整 coverage fingerprint。
5. Agent Task/Run 绑定和跨任务归属校验。

### P1 — 功能验收前必须完成

1. Action/Run/Checkpoint 原子 claim/finish、空结果语义和重启恢复。
2. checkpoint 只允许 running Run；started checkpoint 必须有终态。
3. 单工作区进程约束、旧 active Run 收敛和可执行 retry。
4. 消息 attempt 原子 claim/complete，避免跨进程重复回答。
5. 外部输入/链接/事件数量上限和敏感 URL 参数脱敏。

### P2 — 质量与维护

1. SearchPlanVersion 生产接线、新主题分流和 modify-plan 契约。
2. 历史压缩、Judge 预算、对话流校验、来源计数与 client 生命周期。
3. AI-native Provider Adapter、搜索响应上限和降级观测。
4. `agent.py` 内部 Locality 改善、依赖主版本上限和开发环境可重复性。

## Deferred Architecture Work

`agent.py` 约两千行、Dialogue streaming Protocol Seam 不完整等属于维护热点，但不先做全面拆分。先在现有深 Module 修复不变量；只有多个真实调用方需要变化时才新增 Seam。

仅当出现可测的跨进程节点级恢复、多个搜索专家 fan-out/fan-in、跨重启的运行中人工审批，或单 Agent 工具选择质量被基准证明成为瓶颈时，再做 LangGraph 限时试验。试验也应让 Pydantic AI 作为节点 Implementation，并保持 `StateStore` 为唯一业务状态源。

## Complexity Tracking

无门禁违例；不需要复杂度豁免。
