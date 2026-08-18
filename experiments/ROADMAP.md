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
| 006 | deep-crawl-baseline | 2 轮挑战未收敛但干净终态（21 min, exit=0, 114 req） | **深爬引擎首跑**：34 文档/40 证据；**P0 容错 ID 实跑验证通过**；订单数据（文成 270 架）+ 融资统计 + 投行评级全部命中；暴露链接农场污染与交叉验证缺失 | ✅ |
| 007 | cross-verify-with-gaps | **stage=done 全程走完**（20 min, exit=0, 58 req） | **首次完整流程**；document_search 调用 8 次；gap=7 历史最优；但语料被 26 张图片（tesseract 缺失）+ 外文垃圾链接淹没，仅 3 事实；completion_status 标签语义错误 | ✅ |
| 008 | image-gate-ocr | **coverage=sufficient 首次达成**（9.3 min, exit=0, 57 req, gap=0） | 图片门槛+OCR 修复生效：图 26→5 全 complete、事实 3→15、证据 4→18；垃圾换形态：CCDI 视频页 16/41；OCR 质量低（tessdata_fast）；搜索预算仍 6 次耗尽 | ✅ |

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
- [x] **P0** 长 UUID 抄错死锁: 短 ID + tolerant_id 容错匹配（**006 实跑验证：2/2 confirm 一次成功**）
- [x] **P1** 交叉验证: document_search 工具（本地修改，007 验证调用 8 次）
- [x] **P1** nav/footer 链接惩罚 + 空正文拒绝（本地修改，007 验证 0 垃圾完整页）
- [x] **P1** with_gaps 完成状态（本地修改，007 验证 stage=done 全程走完）
- [x] **P0** tesseract 安装 + chi_sim（**008 验证：OCR 管道 5/5 complete**）
- [x] **P0** enqueue relevance 门槛 + 图片过滤（**008 验证：图 26→5 且全高相关，占比上限 max(3,10%) 生效**）
- [ ] **P0** aside/related/ad 容器链接惩罚（008 发现 CCDI 视频页 16/41 垃圾语料）
- [ ] **P1** OCR 质量: tessdata_best + 纯照片跳过（008 发现 tessdata_fast 输出不可用）
- [ ] **P2** 搜索预算按问题数分配（008 发现 4 问仍只有 6 次总预算）
- [ ] **P2** completion_status 语义修正: coverage sufficient 才算 "sufficient"（008 sufficient 路径已自然达成）
- [ ] **P2** 新闻时效优先: news 种子标记 time_range / 优先 2026 链接
- [ ] **P3** sufficient 路径审计产物（008 outputs: package=False, assessment=False）
- [ ] **P3** harness --max-turns 默认值对齐（007 首跑被压到 request_limit=40）
- [ ] **P2** 单源财务数据交叉验证渠道（stockanalysis 页内链接展开）
- [ ] **P3** 验证码页检测（百度安全验证类页面拒绝归档）
- [ ] **P3** contradicts 证据处理流程验证（005 首次出现）

## 结论沉淀（跨实验）

1. **证据链框架（ID/哈希/门控/预算）多次运行零故障** — 架构可靠，瓶颈在检索行为
2. **检索质量的三个关键杠杆**（按效力排序）:
   - 来源扩展（outbound_links + 已知权威源直接抓取）— 004 最大功臣
   - 查询专业化（公司名/机型/年份/英文术语）
   - 已归档标记（防止重复抓取同一簇）
3. **模型纪律需系统性注入**：提示词 + 工具输出引导（fresh_count/hint）+ 状态机终态指引三层配合
4. **诚实度指标良好**：多次运行均未伪造来源，单源内容如实标记 reported
5. **语料垃圾按链接来源转移**：修好一类（图片），下一类成为瓶颈（007 图片 → 008 CCDI 容器外链接）。容器级惩罚需覆盖 nav/footer/aside/related/ad 全集合
6. **环境依赖修复能直接改变实验结论**：tesseract 缺失时图片全 unavailable 掩盖了 enqueue 门槛的价值；两者同轮验证缺一不可
