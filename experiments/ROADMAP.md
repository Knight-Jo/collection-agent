# 情报收集智能体迭代实验 — ROADMAP

每次实验: 真实运行 → 保存轨迹与产物 → 分析 → 改进 → 下一轮。

## 运行记录

| 实验 | 名称 | 结果 | 关键改进/问题 | 状态 |
|------|------|------|--------------|------|
| 001 | baseline | stage=challenge，未达 done（request_limit=50 耗尽） | 请求预算不足；用户问题被替换；检索产出低；publish_time 失败 | ✅ |
| 002 | fix-prompt-budget | **done**（5 min） | 预算 200/用户问题原样/标准显式/publish_time 修复；检索仍同质 | ✅ |
| 003 | search-diversity | 卡死循环（150 事件） | gap_score 20→13；Q2=gap；死循环；`str.replace` bug | ✅ |
| 004 | link-expansion-pdf | 2 轮挑战未收敛但**干净终态**（16 min, exit=0） | **首个 covered fact + 首个 addressed 点**；来源扩展/PDF/纪律生效；订单数据仍缺 | ✅ |
| 005 | financial-sources | 挑战 confirm 9 连败（ID 抄错），未收敛终态（31 min, exit=0） | **财务数据破冰**（Q1/FY2025/指引）；IR httpx 回退生效；**发现 P0: 长 UUID 抄错死锁** | ✅ |

## 改进清单（按优先级）

### 已完成
- [x] **P0** usage_limits 显式配置（request_limit=200），config.yaml 可调
- [x] **P0** 来源扩展: web_fetch 返回 outbound_links，绕过搜索预算（004 生效）
- [x] **P0** PDF（pymupdf）/ Word .docx（python-docx）全文提取与抓取
- [x] **P1** 提示词: 用户问题原样使用；充分性标准显式数值；原子事实/完整引文
- [x] **P1** 检索多样性: already_archived 标记 + fresh_count + 换词/英文/反百科纪律
- [x] **P1** 挑战纪律: 至少 1 addressed（除非预算耗尽）
- [x] **P1** 防死循环: 两轮未收敛终态指引（summarize_task 注入）
- [x] **P2** fetch 发布时间提取: PubDate meta + 正文/URL 兜底
- [x] **P3** 修复 `str.replace(count=)` TypeError 与 `result.usage()` crash

### 待办（006+）
- [x] **P1** IR 抓取超时: httpx 回退（005 生效，ir.ehang.com 成功）
- [x] **P1** 金融/IR 定向来源: suggested_direct_sources + caixin/cls/eastmoney 提示词（005 生效）
- [x] **P0** 长 UUID 抄错死锁: 短 ID + tolerant_id 容错匹配 + 错误信息列有效 ID（005 修复，待 006 验证）
- [ ] **P2** 单源财务数据交叉验证渠道（stockanalysis 页内链接展开）
- [ ] **P3** 验证码页检测（百度安全验证类页面拒绝归档）
- [ ] **P3** contradicts 证据处理流程验证（005 首次出现）

## 结论沉淀（跨实验）

1. **证据链框架（ID/哈希/门控/预算）四次运行零故障** — 架构可靠，瓶颈在检索行为
2. **检索质量的三个关键杠杆**（按效力排序）:
   - 来源扩展（outbound_links + 已知权威源直接抓取）— 004 最大功臣
   - 查询专业化（公司名/机型/年份/英文术语）
   - 已归档标记（防止重复抓取同一簇）
3. **模型纪律需系统性注入**：提示词 + 工具输出引导（fresh_count/hint）+ 状态机终态指引三层配合
4. **诚实度指标良好**：四次运行均未伪造来源，单源内容如实标记 reported
