# 实验 002 — fix-prompt-budget（提示词纪律 + 请求预算）

- 主题: 低空经济（与 001 相同，控制变量对比）
- 变更: ① UsageLimits(request_limit=200)；② 提示词强制原样使用用户问题、明确充分性标准数值、
  检索/事实/挑战纪律；③ publish_time 提取增强（PubDate meta + 正文/URL 兜底）
- 耗时: **291.8s（5 分钟，001 为 37 分钟）**，exit=0
- 结果: **stage=done 达成**，挑战轮 1 confirmed converged=True

## 与 001 的对比

| 维度 | 001 | 002 | 结论 |
|------|-----|-----|------|
| 到达 done | ❌ request_limit 耗尽 | ✅ 完成 | P0 修复生效 |
| 用户问题 | 被替换为模型自拟 4 问 | 原样使用 2 问 | P1 提示词修复生效 |
| 充分性标准 | 模型自设 require_recency=true | 按 CLI 值（false） | P3 修复生效 |
| publish_time | 4/4 文档 None | cq.gov.cn=2025-11-27, lrsd=2026-04-29 等 | P2 修复生效 |
| 时效缺口 | 全事实 recency 缺口 | 无 recency 缺口（criteria 关闭） | 修复生效 |
| 检索产出 | 4 文档 | 5 文档（+EHang 官网 2 页） | 无实质改善 |

## 仍未解决的问题（核心瓶颈 = 检索多样性）

### P1 — 6 次搜索产出仍只有 5 篇文档，0 个 covered 事实
最终覆盖 insufficient（gap=20, no_progress_rounds=4），两个问题均 partial：
- 10 个 active 事实全部仅 1 个来源组（或 0 个 full 支持），无一达到 covered
- 与 001 相同的 4 篇文档（cq.gov.cn / lrsd.org.cn / gov.cn / baike）再度被抓取，仅新增 EHang 官网 2 页
- 未获取任何 2026 年投资/融资动态、第三方对 EHang 订单的报道

### P1 — 搜索引擎环境核查（网络探测）
| 引擎 | 状态 | 说明 |
|------|------|------|
| SearXNG (127.0.0.1:8888) | ✅ 可用（0.14s/次） | 10 条结果，但**不同查询返回同一簇文档**（baike/lrsd/gov.cn/cq.gov.cn） |
| Bing | ✅ 200 | 中文查询返回大量 SEO 垃圾站（kanpianwangzhan/csdn/zhidao） |
| Baidu | ❌ 302→验证码 | wappass.baidu.com 人机验证，直连不可用 |

根因: 不是引擎不可用，而是**查询词多样性不足**——模型反复搜索同一批宽泛查询词，
SearXNG 顶刊结果被同一簇文档垄断，模型又逐篇重复抓取，预算耗尽前无法触达新来源。

### P2 — 事实-证据比例失衡
16 条证据 / 10 active 事实 ≈ 1.6 条/事实，且部分事实 0 full 支持（partial 引文）。
模型把有限证据摊到过多事实，加剧来源不足。

### P3 — done 门槛偏低
挑战轮两点均 dismissed + accepted_partial 后 converged=True 即进入 done，
最终报告以 insufficient 收场。规则允许，但"完成"质量感不足。

## 003 实验的改进（检索多样性）

1. web_search 结果标注 `already_archived` + `fresh_count` + `hint`，防止重复抓取已归档 URL，
   强制模型在结果枯竭时换词/换语言
2. 提示词新增【检索多样性】纪律: 换具体查询词（公司/事件/年份）、language=en 搜英文一手来源、
   百科不得作为主要证据
3. 保留 002 全部修复

## 值得肯定

- EHang 官网（一手来源）方向正确，说明模型理解了"公司动态应查公司官网"
- 5 分钟内完成全流程，成本与速度显著改善
