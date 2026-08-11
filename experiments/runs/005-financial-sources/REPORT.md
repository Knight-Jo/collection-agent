# 实验 005 — financial-sources（金融数据源 + IR 回退 + 挑战容错）

- 主题: 低空经济（同 001-004）
- 变更: ① httpx 回退抓取（ir.ehang.com 等 WAF 站点）；② intel_plan 返回 suggested_direct_sources
  （金融/IR/政策关键词匹配）；③ coverage 单源交叉验证提示；④ 金融数据源提示词（caixin/cls/eastmoney/xueqiu/filetype=pdf/orders FY2025）
- 耗时: **1893s（31 分钟，最长一次）**，exit=0，无 crash

## 成果（对比 004）

| 维度 | 004 | 005 | 说明 |
|------|-----|-----|------|
| ir.ehang.com | 3 次超时失败 | ✅ **成功**（httpx 回退）| 投资者关系页可抓 |
| 财务数据 | 无 | ✅ **Q1 2026 营收 2570 万、FY2025 营收 4.18 亿、2026 指引 6 亿** | stockanalysis.com + IR |
| 金融来源 | 无 | ✅ caixin/cls/eastmoney/thepaper/stockanalysis | suggested_direct_sources 生效 |
| Q2 facts | 9 | 9（含真实财务+AP 报道） | |
| 覆盖 | 1 covered | 0 covered（财务 fact 单源） | 见问题 |
| 挑战点 | addressed 1 个 | 3 个挑战点更尖锐（独立性/矛盾/订单缺失） | 发现 contradicits 证据！|

## 暴露的新问题（核心 bug）

### P0 — 挑战 confirm 死锁：LLM 抄错长 UUID 导致 9 连败
trace 实证：模型将 `cp-r1-e634d625-...` 抄成 `cp-r1-e634d625f-...`（多一个 f），
而 confirm_challenge 用精确匹配，错误信息仅提示"必须处理本轮全部挑战点"（不列有效 ID），
模型无从自纠 → 9 次 confirm 全败 → 挑战轮滞留 open，任务以未收敛终态收场。

**根因**：36 字符 UUID 对 LLM 复制容错性差 + 错误信息不含可恢复信息。
**修复**（已实现并验证）：
1. 挑战点 ID 改为 **8 位短 ID**（`cp-r1-xxxxxxxx`），从源头降低抄错概率
2. `tolerant_id()` 容错匹配：精确 → 唯一前缀 → difflib 模糊（cutoff 0.85）
   —— 已验证 005 的真实污染 ID（e634d625f）可正确解析回 e634d625
3. 错误信息列出全部有效 ID，模型可自纠

### P2 — 财务数据仍单源
三项核心财务数据（Q1/FY2025/指引）全部仅 stockanalysis.com 单一来源组，
模型尝试 globenewswire/sec.gov/EDGAR/marketscreener/tipranks/nasdaq 均被网络拦截（403/404），
搜索预算 6/6 耗尽后无法交叉验证。模型如实披露并降置信度为 medium。

### P2 — contradicits 证据出现（十五五规划 fact）
judge 判定一条引文 contradicts（窄引文片段 vs 完整上下文），
模型识别为"同源窄引文截取导致的误判"，但 confirm 失败未能走完解决流程。
挑战机制首次暴露真实矛盾处理场景，值得 006 关注。

### P3 — 冗余抓取：wappass.baidu.com 验证码页
模型抓了一个百度安全验证页（302 重定向后的垃圾页），浪费 1 次抓取预算。
可考虑在 fetch 阶段检测"验证码/安全验证"特征页并明确报错。

## 005 结论

金融数据源体系打通（IR/行情/新闻源全部命中），fetch 回退解决 WAF 站点；
但挑战 confirm 的 ID 容错问题暴露并已修复。**该 bug 是运行流程级的**
——若未修复，006 仍会随机触发。

## 006 建议（候选）

1. 验证容错 ID 修复：重跑确认挑战 confirm 不再死锁
2. 财务数据交叉验证渠道: 尝试 stockanalysis 页内链接展开（其页面含多个数据源链接）
3. 验证码页检测: fetch 结果识别"百度安全验证"类页面并拒绝归档
4. 单源 fact 自动建议第二来源查询词（已有提示，观察执行率）
