# 实验 001 — Baseline（首次真实运行）

- 主题: 低空经济
- 用户问题: ① 2026年低空经济投资与融资趋势 ② 亿航智能商业化进展与订单情况
- 模型: deepseek-chat（DeepSeek V4 云端），SearXNG 不可用（回退 Bing/Baidu 直连）
- 耗时: 约 37 分钟（DeepSeek 推理较慢），**未到达 done，被 pydantic-ai 默认 request_limit=50 中断**
- 产物: 证据包 + 研判报告已生成并绑定（challenge 阶段输出），stage=challenge

## 运行轨迹摘要（基于 state 快照，此轮尚未启用 trace 记录）

| 阶段 | 实际行为 |
|------|---------|
| plan | 模型**自行拟定 4 个问题**（官方定义/2024-2025政策/产业链进展），完全弃用用户给的 2 个问题 |
| search | 6 次搜索全部用完（search_budget_exhausted），仅归档 **4 篇文档** |
| fetch | 4 文档: gov.cn 政策解读、lrsd.org.cn 指数报告、百度百科、重庆市人民政府 |
| fact/evidence | 14 个事实、24 条证据（其中 3 条为挑战轮补充） |
| audit | 24 条支持全部审核；**大量 partial**，full 支持稀少 |
| coverage | 5 次快照，最终 insufficient（gap=34），stop_reason=no_progress |
| assess | 全部结论为「单源转述 reported」（诚实归因），**0 条多源验证的事实结论** |
| challenge | 3 个挑战点全部 dismissed（模型以"已在研判中处理"为由驳回），converged=False |
| done | **未到达** — 50 请求上限在 challenge 后重新出包/研判阶段耗尽 |

## 暴露的问题（按严重度排序）

### P0 — 默认请求预算不足以完成全流程
pydantic-ai `UsageLimits` 默认 `request_limit=50`。本流程每次工具轮 = 1 次主模型请求，
每次 `evidence_audit` 按 fact 分批 = 每批 1 次独立 judge 请求（24 条证据约 10+ 次）。
全流程实际需要 **100+ 次请求**，50 次必然中断。
**修复**: 显式设置 `UsageLimits(request_limit=200)`，并加入 config.yaml 可配置。

### P1 — 用户问题被模型替换
模型无视 CLI 提供的 2 个问题，自拟 4 个不同问题，导致"亿航智能商业化"根本没有被检索。
**修复**: 提示词强制"必须原样使用用户提供的 question 列表调用 intel_plan，不得替换"。

### P1 — 检索产出极低: 6 次搜索 → 4 篇文档
搜索预算耗尽但候选面极窄，4 篇文档全是 2024 年前后政策/百科类，无 2026 年投资/公司动态，
也无任何英文/公司一手来源。疑似: 查询被模型一次用完、语义重复查询、Bing/Baidu 直连结果有限。
**修复**: 提示词要求按问题逐一检索、每问题至少 2 个不同来源组、优先官方/新闻；后续观察 trace 后针对性优化 search 本身。

### P1 — 事实粒度与引文完整性 → 大量 partial
14 个事实中多个只有 1-2 条候选支持且全 partial（引文只支持部分命题组成）。
模型倾向把多组件命题存为单事实，或引文截断过早。
**修复**: 提示词明确"事实必须是单一可独立核验的原子命题；引文必须逐字覆盖命题全部重要组成；audit 返回 partial 时用 fact_supersede 拆分"。

### P2 — 发布时间提取失败 → 全事实 recency 缺口
gov.cn 用 `<meta name="PubDate" content="2025-11-27 09:57">`，提取正则未覆盖该 name，
4 篇文档 publish_time 全部为 None，叠加模型自设 require_recency=true，所有事实 recency 缺口+1。
**修复**: fetch.py 扩展 meta name 匹配（PubDate/publishdate/article:modified_time/datePublished 等），并增加正文/URL 日期兜底。

### P2 — 挑战轮全部 dismissed，converged=False
模型对 3 个挑战点均选择 dismissed（理由笼统"已在研判中处理"），回避了"addressed 必须新增证据"的要求，
挑战实际未收敛 → done 被门控拦截（配合 P0 才彻底卡死）。
**修复**: 提示词要求 dismissed 必须给出具体、可审查的替代处理说明；鼓励用新增证据 addressed。

### P3 — 模型自设 require_recency=true 与用户默认不符
CLI 未传 --require-recency，但模型在 intel_plan 中自行开启强制时效，放大了 P2 的杀伤。
**修复**: 提示词明确写出本次充分性标准数值（含 require_recency=false），禁止自行修改。

## 值得肯定的行为

- 单源内容全部诚实标记为 `reported` 并注明 attribution，未伪造多源
- 挑战点识别的问题（时效、来源独立性、证据完备性）全部命中真实缺陷
- fact_supersede 机制被正确使用（存在被拆分的事实链）
- 引用全部逐字定位，行号/哈希完整

## 改进方向（对应 002 实验）

1. usage_limits 提至 200 并可配置（P0）
2. 提示词: 用户问题原样使用 + 明确充分性标准 + 原子事实/完整引文 + 检索纪律 + 挑战处置纪律（P1/P3）
3. fetch 发布时间提取增强（P2）
