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
| 009 | container-penalty | **done, sufficient, gap=0**（24 min, exit=0, 96 req） | CCDI 垃圾 16→1；事实 16/证据 18；审计产物补齐；news 引擎全灭→general fallback（009a 作废重跑）；垃圾再换形态：gov.cn 门户导航页 28/44（rel=0 深度链接无门槛） | ✅ |
| 010 | relevance-gate | **done, sufficient, gap=0**（6.3 min, exit=0, 60 req） | depth≥1 全链接相关性门槛：爬取垃圾 48→0、语料 44→10 全高质量、事实 16→22、证据 18→29、耗时 -74%、token -53%；词匹配出站发现未误伤；搜索预算仍 6 次耗尽 | ✅ |
| 011 | search-breadth | **done, sufficient, gap=0**（11.6 min, exit=0, 81 req） | 预算解绑（搜索 6→40/实际用 15）+ 最低召回 10 + 提示词广度纪律：语料 10→143 篇、爬取全面复活；修复 3 个工具链缺陷（参数重试/URL 编码/长 CJK 切词）；垃圾第 5 次换形态：etbbs 单域论坛 103/143；交叉验证仍 0（srcs=1 即 covered） | ✅ |
| 012 | truthful-coverage | **done + with_gaps 诚实终态**（26.6 min, exit=0, 190 req） | 覆盖门槛修正：虚假 covered 13/14→0；问题全事实契约；逐问题年份解析（Q1=2026，Q2 不受限）；报告列出 20 条局限；交叉验证执行能力不足暴露（19 事实全单源） | ✅ |
| 013 | source-fairness | **验收未通过，实验失败**（13.1 min, exit=0, 90 req） | 公平机制生效（social 36.4%→7.7%、转载→7.7%、状态持久化修复），但最大域 23.1%/前两域 46.2%/有效域 5.73 三项阈值未达标；根因：种子域多样性不足，公平调度无法凭空创造多样性 → 014 补输入侧 | ❌ |
| 014 | deterministic-query-matrix | **假设成立**（13.2 min, exit=0, 89 req） | 六槽位矩阵确定性执行 22 条（site: 8/filetype: 2/英文✅）；有效域 5.73→7.89 ✅、政府来源 2→7、新域候选 76、证据利用率 5.6%→46.7%；交叉验证双源率仍 0（闭环未完成）；013 剩余两项阈值仍略超（最大域 20.0%/前两域 40.0%） | ✅ |
| 015 | evidence-yield | **验收未通过，实验失败**（13.2 min, exit=0, 85 req） | 2/4 达标：利用率 37.5% ✅、报告低星材料 0 展开 ✅、转化漏斗首次可观测；来源组 5/8 ❌、双源率 0% ❌——backlog 机制已供给但模型未消费，闭环执行是模型行为缺口，需判定层强制执行 | ❌ |
| 016 | verification-gate | **门控机制验证成功**（17.2 min, exit=0, 110 req） | fact_save 判定层门控：双源率 0%→86.7%、来源组 5→7、gap 25→16；015 利用率/低星两项复测通过；来源组 7/8 与双源率 86.7%/100% 临界未满（2 事实全网单源，如实披露）；多媒体专项顺延 017 | ✅ |
| 017 | rendered-multimedia-recall | **验收未通过，实验失败**（19.1 min, exit=0, 141 req） | 3/5 达标：OCR/转写质量门控生产验证（3/3 噪声图片拦截、0 证据污染）、失败材料不进证据、附件矩阵全格式；JS 渲染 0 样本、PDF/Office/音视频 0 命中——控制变量主题语料构成无法支撑多媒体验收面，需 018 专项主题复测 | ❌ |
| 018 | multimedia-recall | **验收未通过，实验失败**（24.0 min, exit=0, 99 req） | 2/6 格式提取成功但实质进展：部署源种子机制生效、PDF 生产提取首次打通（pymupdf 43KB 文本）、视频到达归档层（CDN 直连超时）、gap 18→6；剩余缺口在环境与数据集层（爬取缺 httpx 回退、tessdata_best、Office/音频公开直链稀缺） | ❌ |
| 019 | environment-fixes | **假设成立**（17.5 min, exit=0） | 三项环境修复：whisper small 模型镜像缓存 + tessdata_best + 爬取 httpx 回退；3/3 固定媒体目标生产提取成功（PDF pymupdf / 视频 whisper 转写过门控 / 图片 tesseract-best OCR 过门控）；018 视频根因更正（模型下载超时，非 CDN） | ✅ |
| 020 | final-consolidation | **收官：9 项阈值 7 项达标**（17.8 min, exit=0, 70 req） | 四项缺陷修复（来源角色/报告防重/爬取批崩溃/门控死锁）；前两域 34.3%、有效域 10.47、来源组 8 三项历史首次达标；最大域 17.1% 与双源率 66.7% 临界未满（语料规模与真实单源稀缺），report+assessment 生成，建议封版 | ✅ |
| 021 | qwen35-9b-local-baseline | **上下文溢出失败**（18.2 min, exit=1） | 免密接口/tool calling 可用；40 次搜索→3 文档→1 证据→1 事实；现场观测审核生成约 32K，后续 32,870-token prompt 超过 32,768；失败 trace 丢失 | ❌ |
| 022 | bounded-context-qwen35-9b | **上下文边界生效、流程失败**（1.8 min, exit=2, 18 req） | 32K 历史裁剪与输出限制消除溢出；15 搜索/2 文档/0 证据；搜索门禁未返回候选 URL，模型重复搜索并重建任务 | ❌ |
| 023 | context-gate-recovery | **search→fetch 生效、证据阶段失败**（4.2 min, exit=2, 38 req） | 单任务保持正确、归档 6 文档；但快照未恢复文档 ID，模型对失败 URL 重复抓取，0 事实/0 证据 | ❌ |
| 024 | archive-state-recovery | **fetch→read 生效、事实阶段失败**（0.8 min, exit=2, 10 req） | 快照恢复归档文档后 document_read 0→4、阅读利用率 100%；但未记录已读状态且 runner 不续跑，0 事实/0 证据 | ❌ |
| 025 | small-model-continuation | **证据闭环成立、收尾未完成**（14.3 min, 主动终止） | 32K/9B 首次形成 1 事实/3 证据/2 引用文档；自动续跑有效；但 pending evidence 未驱动审核，coverage 重复 16 轮 | ⚠️ |
| 026 | stage-aware-resume | **中断恢复完成，done/with_gaps** | 3/3 证据审核、collect→assess→done、正式报告生成；最后恢复 3 req/16,566 tokens；搜索未增加，缺口如实披露 | ✅ |
| 027 | qwen38-27b-vllm | **开启思考首请求停滞**（400s，主动终止） | 短对话/单工具可用，但完整 Agent 0 工具、0 状态、0 上下文溢出；无法评价搜索质量 | ❌ |
| 028 | qwen38-27b-vllm-no-thinking | **关闭思考仍停滞，后端 502**（422.9s，主动终止） | 0 工具/0 状态；最小“系统提示+单工具”诊断返回 502，随后 health 连续 3 次 502；故障边界在远程服务/网关 | ❌ |
| 029 | qwen38-27b-vllm-16k | **服务恢复，工具编码失败**（138.6s，exit=1） | 服务实际窗口 16K；intel_plan 连续 4 次把 criteria 编码为 JSON 字符串，严格校验重试耗尽 | ❌ |
| 030 | qwen38-27b-vllm-criteria-compat | **研究链路完成，报告截断**（37.1min，exit=1） | 单任务；40 搜索/26 矩阵/4 归档/1 full 证据；到 assess/no_progress；报告 4 次撞满 1024 token | ❌ |
| 031 | qwen38-27b-report-resume | **2048 token 解决截断，draft 类型失败** | 完整报告参数生成成功，但 draft 被编码为 JSON 字符串，4 次校验失败 | ❌ |
| 032 | qwen38-27b-report-draft-compat | **类型兼容通过，业务草稿不收敛**（约 17min，主动终止） | 十余次请求未形成合法章节/事实组合；未重复搜索、无上下文溢出 | ❌ |
| 033 | qwen38-27b-verified-report-fallback | **真实任务完成，done/with_gaps**（3 req / 21,110 tokens） | 安全草稿只纳入 1 条 full 事实；报告落盘；确定性完成摘要阻止模型夸大；主要缺口转为搜索质量 | ✅ |
| 034 | local-awq-baseline | **未达终态，实验失败**（11 min, exit=1；续跑 30 min 主动终止） | 本地 AWQ 部署全链路跑通（工具调用/搜索→事实→assess），服务负载验收通过；1024 报告截断→参数层崩溃绕过 033 安全回退；2048 续跑 assess 死循环；trace 丢失复现 | ❌ |
| 035 | local-awq-report2k | **未达终态，实验失败**（20 min, exit=1） | 2048 输出消除截断，但 qwen3_xml 闭合标签泄漏进草稿尾部（`</draft></invoke>`）→ 工具参数层解析失败 ×3 | ❌ |
| 036 | local-awq-report-param-fallback | **未达终态，实验失败**（续跑 90 min 主动终止） | 参数层兜底（尾部噪声剥离+verified 回退）修复崩溃；续跑在 assess 死循环（backlog 注入使模型反复 audit↔coverage_eval，搜索耗尽无法补证） | ❌ |
| 037 | local-awq-assess-terminal-switch | **真实任务完成，done/with_gaps**（3 req / 20,935 tokens） | coverage_eval 判定层硬切换：no_progress 时系统确定性生成报告并推送 done；零 full 事实时允许诚实空章节报告；3 请求即达终态 | ✅ |
| 038 | frozen-flash-wp1-4 | **冻结材料复验一次通过**（233.3s, exit=0, done/with_gaps, 30 req / 1.61M tokens） | WP1 问题冻结 + WP2 审核并发/超时 + WP3 增量 trace + WP4 collect 确定性收敛全部生效；附加修复：judge 改纯文本完成（thinking 模式拒绝 tool_choice=required，首跑 191 次审核静默失败）；基线 586s 中断 → 233s done | ✅ |
| 057 | refactor-verify | 同主题 deepseek-chat 964.6s exit=0，manifest 无 final_stage（未达终态即中断） | 059 复跑的基线 | ⚠️ |
| 059 | humanoid-recompare | **同 057 主题复跑达 done/with_gaps**（两段 118 req，续跑段 40 req/1.56M tokens） | 模型切 qwen 27B AWQ（deepseek 密钥失效）；**qwen thinking 作 judge 必须 disable_thinking=true + audit_output_tokens=2048**（否则 JSON 解析失败/截断）；21 条审核全成功；9 文档/21 证据（利用率 77.8%）/7 active 事实全单源；gap=31，0 covered，诚实收尾 | ✅ |
| 061 | audit-loop-fixes | **P0 双修复验证通过**（386.1s, exit=0, done/with_gaps, 45 req/2.04M tokens） | audit batch 隔离 + 失败冷却护栏：75次/65连败 → 9次/8成功1瞬时失败，无连续簇；document_search 去 deep_crawl 门禁 + digest 语料：2/2 失败 → 1/1 成功；已验证事实 0→1；gap 31→10；耗时 -96% | ✅ |
| 062 | efficiency-fixes（首跑） | **中途终止，暴露新 P0**（87 req/~110 min 终止） | generate_research_report Markdown 草稿循环：qwen 把 draft 写成 Markdown 文本，静默 fallback 后业务校验失败，REPEATED 无出口 → 56 次全失败 | ❌ |
| 063 | efficiency-fixes（重跑） | **P1/P2 四组修复 + 报告循环修复全部生效**（448.1s, exit=0, done/with_gaps, 42 req/1.96M tokens） | 报告调用 56 次循环→1 次成功；垂直查询整句→关键词；已验证事实 2；gap=10；audit 5/5 成功；trace 失败保留 error 字段 | ✅ |
| 064 | cross-verify-budget-pools | **三组 P1 机制全部生效**（651.1s, exit=0, done/with_gaps, 38 req/2.08M tokens） | 门控注入被模型采纳（READ 候选+3 证据）；模型搜索精确 16/16（discovery 池）；矩阵 verify 独立执行 8 条；垂直查询 `2056台 138%`（数字单位）；gap 10→8；covered 1→0（第二来源引文 partial，单轮方差） | ✅ |

## 011 产物复盘（012 的事实基线）

以下数字来自 `runs/011-search-breadth/state/`、`trace.jsonl` 和最终报告。后续实验必须使用相同口径重新统计，不得只引用 `stage=done`、`gap_score=0` 或文档总数证明成功。

| 指标 | 011 实际值 | 诊断 |
|------|-----------:|------|
| 归档文档 | 143 | 原始召回已不是主要瓶颈 |
| 活跃事实 | 14 | 比 010 的 15 个更少 |
| 持久化证据记录 | 28 | 只来自 8 个文档 |
| 文档证据利用率 | 5.6%（8/143） | 010 为 50%，扩大语料反而降低转化率 |
| etbbs.com | 103/143（72.0%） | 单域论坛洪泛 |
| 前两域 | 124/143（86.7%） | 表面有 18 个域，有效域数量仅 1.85 |
| 来源类型 | other 142 / government 1 | 新闻、企业官网和 IR 分类失真 |
| 活跃事实声明类型 | reported 13 / primary 1 / corroborated 0 | 模型通过 reported 绕过交叉验证门槛 |
| 阅读推荐 | 1 星 12、2 星 134、4 星 2、5 星 6 | 94.8% 材料不适合进入正文导读 |
| 抓取格式 | HTML 135、JPEG 5、PNG 3 | PDF/Office/音频/视频均为 0 |
| 浏览器渲染 | 0 | 不能证明 JS 动态网页能力有效 |
| 抓取状态 | 任务 done，但 crawl.status=running | 状态持久化不一致 |

### 011 根因结论

1. **P0 覆盖误判**：任务要求 `min_independent_sources=2`、`min_high_quality_sources=1`，但 `reported` 事实只需 1 个来源且无需高质量来源；13/14 个活跃事实走了该路径。
2. **P0 问题误判**：一个问题只要有任意一个 covered fact 就整体 covered，因此 2023 年市场规模可以使“2026 年投资与融资趋势”被判为已回答。
3. **P0 时间约束丢失**：问题包含“2026 年”，但 `scope.time_range` 为空且 `require_recency=false`，最终报告显示“时间：未限定”。
4. **P1 广度失真**：普通优先级队列被一个相关词密集的论坛域灌满；URL 相关不等于来源有价值。
5. **P1 查询计划未执行**：系统已生成 `site:`、`filetype:`、中英文和反证查询，但 15 次实际搜索没有 `site:` 或 `filetype:` 查询，仅 1 次 news 查询。
6. **P1 深度失真**：深度 1/2 共归档 128 个资源，却只有 8 个文档进入证据链；链接跳数不是研究深度。
7. **P2 报告失真**：报告称“未发现额外局限”，但实际存在零多源事实、时间缺口、来源集中和低材料利用率。

### 下一阶段硬约束

- 012–016 必须按顺序执行；前一轮未达到验收标准时，不得开始下一轮。
- 每轮只修改该实验“允许修改”列出的范围，不得顺手重构无关模块。
- 012–015 不得提高 `max_urls`、`max_depth`、搜索上限或模型请求上限；先提高现有预算的有效产出。
- 不得用提示词代替可确定执行的门槛、配额或调度逻辑。
- 不得把搜索结果数量、归档数量、`exit_code=0`、`stage=done` 或 `gap_score=0` 单独作为成功证据。
- 每轮开始和结束都必须按 `AGENTS.md` 更新 `CHANGELOG.md`；计划与实测结果必须分开书写。

## 改进清单（按优先级）

### 已完成
- [x] **P1** 修复 logging.py formatter format string（059 前置：损坏串导致日志 emit TypeError 洪水）
- [x] **P1** qwen thinking judge 修复：audit_output_tokens 512→2048 + disable_thinking=true（059 验证：21/21 评审可解析）
- [x] **P1** 中断续跑路径实测：同一 cwd 直接重跑 CLI 从 intel.db 恢复（059 验证：78→118 请求，续跑段 40 请求到达 done）
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
- [x] **P0** aside/related/ad 容器链接惩罚（**009 验证：CCDI 视频页 16/41→1/44**）
- [x] **P0** 相关性剔除裸年份 token 与引擎评分（**009 生效**：/2026/ URL 匹配与 score=1.0 垃圾不再入种子）
- [x] **P1** news 引擎全灭兜底：同次预算内回退 general 搜索（**009a 环境失败后修复，009 重跑通过**）
- [x] **P0** depth≥1 全链接 relevance 门槛（**010 验证：爬取 rel-0 条目 48/50→0/9，语料 44→10 全高质量，事实 16→22、证据 18→29、耗时 -74%**）
- [x] **P1** 预算解绑 + 检索广度（**011 验证：搜索 40 上限实际用 15 未耗尽、语料 10→143 篇、爬取复活**）
- [x] **P1** 工具链健壮性: Agent retries=3 + 非 ASCII URL 百分号编码 + 长 CJK 串切词（**011a/b 崩溃修复，011c 通过**）
- [x] **P0** 覆盖语义修正：除可验证的一手声明外，reported/corroborated 均执行任务级独立来源和高质量来源门槛（**012 验证：虚假 covered 13/14→0，任务诚实以 with_gaps 收尾**）
- [x] **P0** 问题维度覆盖：禁止"任意一个 covered fact 即问题 covered"（**012 验证：问题需全部 active fact covered**）
- [x] **P0** 时间约束解析：从问题中的显式年份/时间范围写入 scope，并用于检索、覆盖和报告（**012 验证：Q1 "2026年"→time_range='2026'，Q2 无年份不受限**）
- [x] **P0** crawl per-domain 配额 + 来源类型轮转 + 论坛 10% 上限（**013 机制生效：social 36.4%→7.7%、状态持久化修复；域占比三项阈值未达标，待 014 补种子多样性后复测**）
- [x] **P1** 同稿转载血缘：正文哈希合并、reused 不重复建档（**013 验证：转载 12.5%→7.7%**）
- [ ] **P1** 来源角色修正：公司主站（ehang.com 等）识别为 official，补齐 ir.* 之外的信号（013 已知缺口）
- [x] **P1** 确定性查询矩阵：程序保留一手、独立验证、结构化数据、附件、反证和多语言查询槽位（**014 验证：22 条矩阵查询确定性执行，site: 8/filetype: 2/英文✅，有效域 5.73→7.89**）
- [x] **P1** 语料转证据排序：按相关性、来源质量、时效、新颖性和交叉验证价值选择阅读文档（**015 机制验证：novel_group 排序 + 转化漏斗可观测 + 报告低星材料 0 展开；双源闭环未发生，见结论 16**）
- [x] **P0** 交叉验证判定层强制：fact_save 在单源 backlog 存在时门控（**016 验证：双源率 0%→86.7%，四轮供给侧修复未竟之事由硬约束一次达成**）
- [x] **P1** OCR/转写质量门控 + 附件矩阵全格式（**017 生产验证：3/3 噪声图片拦截、0 证据污染；JS 与多格式命中为零，需 018 专项主题复测**）
- [x] **P1** 爬取路径 httpx 回退（**019 实现：pinned 网络错误回退 httpx，确定性测试锁定**）
- [x] **P1** tessdata_best 环境项（**019 验证：海报 OCR 过质量门控；fast 已备份**）
- [x] **P1** whisper 模型环境项（**019 验证：hf-mirror 缓存后视频转写成功**；018 根因更正）
- [x] **P1** 来源角色修正：部署源注册域识别为 official（**020 验证：ehang.com→official 6 篇，013 缺口关闭**）
- [x] **P3** generate_research_report 防重（**020 实现：同草稿连续 4 次阻断**）
- [x] **P1** 爬取批崩溃修复：pinned+httpx 双败条目落终态（**020a 自签名 SSL 站点击穿整批修复**）
- [x] **P1** fact_save 门控诚实出口（**020b 死锁修复：search 耗尽/no_progress 解锁，with_gaps 全程走完**）
- [ ] 封版观察项（非阻塞）：最大非一手域 17.1%/15%、双源率 66.7%/100%——语料规模与真实单源稀缺（结论 22）
- [ ] **P3** generate_research_report 防重（009 重试 12 次；011 no_progress_rounds=2）
- [ ] **P1** OCR 质量: tessdata_best + 纯照片跳过（008 发现 tessdata_fast 输出不可用）
- [ ] **P2** 搜索预算按问题和阶段保留（发现 40% / 交叉验证 40% / 反证与时效 20%），不是继续提高总预算
- [ ] **P2** completion_status 语义修正: coverage sufficient 才算 "sufficient"（008 sufficient 路径已自然达成）
- [ ] **P2** 新闻时效优先: news 种子标记 time_range / 优先 2026 链接
- [ ] **P3** sufficient 路径审计产物（008 outputs: package=False, assessment=False）
- [ ] **P3** harness --max-turns 默认值对齐（007 首跑被压到 request_limit=40）
- [ ] **P2** 单源财务数据交叉验证渠道（stockanalysis 页内链接展开）
- [ ] **P3** 验证码页检测（百度安全验证类页面拒绝归档）
- [ ] **P3** contradicts 证据处理流程验证（005 首次出现）
- [x] **P0** 本地小模型按角色限制输出与上下文：32K/64K/128K/256K 可配，审核与主 Agent 独立输出上限，可关闭长推理（**022 验证：18 请求/203,137 tokens，无上下文溢出**）
- [ ] **P0** trace 按事件增量持久化，异常退出也保留模型请求、token、工具调用与最后错误（021 可观测性缺口）
- [ ] **P1** 小模型阶段硬门控：限制连续搜索，命中候选后强制 search → fetch → read → evidence（021 搜索 40→证据 1）
- [x] **P1** 小模型门禁恢复：`FETCH_REQUIRED` 返回具体候选 URL，`intel_plan` 对未完成任务幂等（**023 验证：单任务、归档文档 2→6**）
- [x] **P1** 压缩快照恢复已归档文档及精确下一动作，推动 `document_read → fact_save → evidence_save`（**025 验证：1 事实/3 证据**）
- [x] **P1** 已读阶段状态 + 未完成任务自动续跑，避免小模型“承诺下一步”后提前结束（**025 验证：跨自然语言终点继续形成证据**）
- [x] **P1** 阶段感知快照：pending evidence→audit、审核更新→coverage、stop_reason→assess、导读→报告→done（**026 验证：3/3 审核，最终 done/with_gaps**）
- [ ] **P1** 搜索结果跨查询 canonical URL 去重与主题实体最低相关性门槛（021 日历/节假日结果污染）
- [ ] **P2** llama-server 启用 metrics，并在 manifest 记录 slot 数、n_ctx、prompt/decode 吞吐（021 请求/token 不可测）
- [ ] **P0** 远程模型服务真实负载验收：4.2K prompt + 16 工具 schema 必须 60 秒内返回有效工具调用，且请求后 `/health` 保持 200（027–028 服务故障）
- [x] **P0** 16K 上下文档位与远程服务边界对齐（**029–033：0 上下文溢出，最终 done**）
- [x] **P0** Qwen 嵌套工具参数兼容：criteria/draft 对象或 JSON 字符串均统一严格校验（**030/032 验证**）
- [x] **P0** 证据安全报告回退与确定性完成摘要（**033：报告只纳入 1 条 full 事实，模型夸大的第二事实未进入交付**）
- [x] **P0** 本地 vLLM 工具调用协议：`vllm.config` EXTRA_ARGS 增加 `--enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3`（**034：缺失时 `tool_choice:"auto"` 被 400 拒绝；补齐后 pydantic-ai 全链路可用**）
- [x] **P0** generate_research_report 参数层兜底：非法 JSON/尾部噪声剥离，仍失败回退确定性安全草稿（**036 验证：尾部 `</draft></invoke>` 噪声草稿可恢复，垃圾草稿不再崩溃**）
- [x] **P1** assess→report 判定层硬切换：no_progress 时系统确定性生成报告并推送 done（**037 验证：90 分钟死循环 → 3 请求 done/with_gaps**）
- [x] **P1** no_progress 零结论报告豁免：允许诚实空章节 with_gaps 报告（**037 验证：0 full 事实仍能如实交付，不伪造结论**）
- [x] **P0** trace 按事件增量持久化（**038 验证：41 条工具事件 + usage 行落盘，异常路径写 terminated；analyze_run 兼容新旧格式**）
- [x] **P0** 用户问题冻结：显式问题不得新增/删除/合并/改写（**038 验证：2 问保持 2 问，基线被扩成 4–5 问**）
- [x] **P0** 审核并发限制与超时：`audit_concurrency=2`/`audit_timeout_seconds=60`，逐批落盘，超时返回 SEMANTIC_AUDIT_TIMEOUT（**038 验证：4 次审核无长尾阻塞**）
- [x] **P0** collect 阶段确定性收敛：no_progress 时判定层推进 assess（**038 验证：gap=6 no_progress → 报告 → done/with_gaps**）
- [x] **P1** qwen thinking 机型审核输出预算：`audit_output_tokens` 512→2048（**059 验证：截断错误消失；2048 后仍需关 thinking 才可解析，见下条**）
- [x] **P1** qwen thinking 机型 `disable_thinking=true`（**059 验证：21/21 评审 JSON 可解析，full 3/partial 16/contradicts 1/irrelevant 1；README 建议配置落地**）
- [x] **P0** 审核 batch 隔离：单 batch judge 失败不丢弃其余批次，summary 带 `failed_batches`（**061 验证：瞬时失败 1 次零浪费，下轮立即恢复**）
- [x] **P0** 审核失败冷却护栏：连续 2 次全失败后 300s 内返回 skip（ok:true），成功复位（**061 验证：9 次审核无连续簇；提示词规则 6 同步约束模型**）
- [x] **P0** document_search 取消 deep_crawl 门禁 + 语料源改任务 digest（**061 验证：非 deep 任务 1/1 成功；059 的 2/2 失败根因关闭**）
- [x] **P0** document_read 返回 total_lines + 已读区间提示（**063 验证：修复生效；生产未触发重复读场景**）
- [x] **P1** evidence_save 元数据行拒绝 + 同文档同引文去重（**063 验证：单元测试覆盖，生产未触发**）
- [x] **P1** 垂直检索事实句→关键词抽取（**063 验证：gap routing 查询为关键词形式**）
- [x] **P0** 搜索预算耗尽成为覆盖 stop_reason + 判定层收尾 + 报告空章节豁免（**063 验证：assess 放行、报告 1 次成功**）
- [x] **P1** trace 工具失败保留 error code/message（**063 验证：错误可观测**）
- [x] **P0** generate_research_report 工具契约：docstring 明确 JSON 格式 + Markdown 草稿显式报错 + REPEATED 出口指引（**062 首跑 56 次循环 → 063 1 次成功**）
- [x] **P1** 交叉验证确定性代偿：fact_save 门控注入 document_search 命中（**064 验证：模型 READ 注入候选并保存 3 条证据；063 的 0 次 document_search 缺口由系统代偿关闭**）
- [x] **P1** 搜索预算分池 discovery/verify/adversarial=40/40/20（**064 验证：模型搜索精确 16/16 耗尽即停，矩阵 verify 独立执行 8 条；全池耗尽才设 stop_reason**）
- [x] **P1** 垂直检索关键词英文/数字单位优先（**064 验证：`2056台 138%` 无碎片**）
- [ ] **P2** 门控注入附带相关行号区间提示（064：第二来源引文 partial 率仍高）
- [ ] **P2** 同配置 3 次运行取交叉验证达成率分布（063 与 064 covered 1 vs 0 为方差）
- [ ] **P2** 原子事实拆分降低 partial 率：059 中 16/21 评审 partial，多数"引文只部分支持 Fact"——事实陈述宽于单条引文（059 实证）
- [x] **P0** judge 结构化输出兼容 thinking 模型：改纯文本 JSON 完成 + 解析（**038 验证：deepseek-v4-flash thinking 模式审核返回 full**）
- [ ] 口径确认：零 full 事实的 with_gaps 全空报告是否满足交付标准（037 遗留，人工确认）
- [ ] **P1** 搜索候选修复（WP5）：SearXNG 真实查询健康检查、Bing 新端点、候选相关性门禁（038 冻结材料未覆盖）

## 012–016 顺序实施计划

执行模型每次只领取一个实验。完成代码、测试、真实运行、分析和文档更新后停止，等待人工确认；不要在同一个分支连续实现多个实验。

### 012 — truthful-coverage（先修“虚假充分”）

**目标**：只有真正满足问题时间范围、来源要求和核心维度时，任务才可进入 `sufficient`。

**主要文件**：

- `src/intel_agent/models.py`：为问题和覆盖快照保存可审计的时间约束结果。
- `src/intel_agent/coverage.py`：事实和问题覆盖判定。
- `src/intel_agent/runner.py`、`src/intel_agent/task.py`：显式年份/时间范围进入任务约束和提示。
- `src/intel_agent/report.py`：根据覆盖缺口生成局限，不再输出错误的“未发现额外局限”。
- `tests/test_coverage.py`、`tests/test_runner.py`、`tests/test_report.py`：回归测试。

**必须完成**：

1. 先写失败测试，复现“criteria 要求 2 个来源，但单源 reported 被判 covered”。
2. 修正规则：`reported` 和 `corroborated` 均执行任务的 `min_independent_sources`、`min_high_quality_sources` 和时效要求。
3. `primary` 只有在至少一个 full support 文档的 `source_type` 为 `official` 或 `government` 时，才允许单一来源；否则按 `reported` 门槛计算。报告对该例外固定显示“单一一手来源，尚未独立验证”。不得只凭模型填写 `claim_type=primary` 绕过检查。
4. 先写失败测试，复现“一个 covered fact 使同问题的另一个 partial fact 被忽略”。012 采用最简单且可审计的定义：同一问题下所有 active fact 都视为核心事实；只有全部 covered 且没有未解决冲突时，问题才 covered。不属于答案的背景信息不要登记为 active fact，已有冗余事实应 supersede。
5. 在 `IntelQuestion` 增加默认空值的 `time_range`。只实现两种可确定解析格式：单年 `YYYY` 和闭区间 `YYYY-YYYY`/`YYYY至YYYY`。用户显式 task scope 优先并复制到每个问题；scope 为空时分别从每个问题解析，不能把问题一的“2026年”错误施加给问题二。
6. 在 `FactCoverage` 保存 `in_scope_sources` 和 `time_scope_gap`。有问题级时间范围时，至少一个 full support 文档的 `publish_time` 必须落在范围内；未知发布时间不满足时间范围。`recency_days` 继续独立工作，不得把“2026年”错误换算成最近 120 天。
7. 报告局限必须列出：单源事实、未覆盖问题、时间缺口、来源过度集中和未解决冲突；无缺口时才允许写“未发现额外局限”。

**禁止事项**：

- 不修改 crawl 配额、搜索预算、查询生成或媒体提取。
- 不通过修改实验问题、降低 `min_independent_sources` 或关闭时效要求使测试通过。
- 不要求所有背景事实都多源；门槛针对进入问题答案和综合结论的核心事实。

**自动化验收**：

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_coverage.py tests/test_runner.py tests/test_report.py
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
```

**真实运行验收**：

- 沿用 011 的主题和两个问题，criteria 保持 2 个独立来源、1 个高质量来源。
- 显式“2026年”必须出现在任务 scope 或等价的逐问题时间约束中。
- 第二个不含年份的问题不得被错误限制为 2026 年。
- 任一核心 reported/corroborated 事实只有 1 个来源时不得 covered。
- 如果无法补齐第二来源，允许最终 `done_with_gaps`/等价诚实终态，不得伪装成 sufficient。
- 最终报告必须披露仍存在的单源、时间和问题维度缺口。

### 013 — source-fairness（来源公平而非站内遍历）

**前置条件**：012 全部验收通过。

**目标**：阻止单域和同稿转载占满 frontier，同时保留企业官网、政府和监管机构的一手材料。

**主要文件**：`src/intel_agent/crawl.py`、`src/intel_agent/source.py`、`src/intel_agent/config.py`、`src/intel_agent/models.py`、对应测试和 `config.example.yaml`。

**必须完成**：

1. 按注册域统计 queued/fetching/complete 数量；非一手域默认最多 `max(8, ceil(max_urls * 0.10))`。
2. 队列按“问题 → 来源类型 → 注册域”轮转；不能继续只按全局 priority 排序。
3. 将论坛、社区、股吧和聚合转载站降级，其总量不得超过 corpus 的 10%。
4. 正确表达 `government`、`official/IR`、`news`、`academic/research`、`social/forum`、`other`；不得继续让已知高价值来源全部落入 other。
5. 用正文哈希加一个轻量近重复判断合并同稿转载；同一原始稿件只能计为一个独立来源组。
6. crawl 队列处理结束后必须持久化 `status=complete`。

**自动化验收**：循环、多域、单域洪泛、同稿转载和一手域豁免均有确定性测试；完整 Ruff、Pyright、pytest 通过。

**真实运行验收**：最大非一手域占比 ≤15%，前两域占比 ≤35%，有效域数量 ≥6，论坛/社区 ≤10%，近重复比例 ≤10%；若搜索结果本身不足，报告实际值并判定实验失败，不得放宽阈值。

### 014 — deterministic-query-matrix（确定性搜索广度）

**前置条件**：013 全部验收通过。

**目标**：查询广度由程序保证，不依赖模型是否遵守 query_plan。

**主要文件**：`src/intel_agent/search_queries.py`、`src/intel_agent/search/`、`src/intel_agent/agent.py`、trace/实验分析脚本及对应测试。

**必须完成**：

1. 每个问题保留六类查询槽位：广泛发现、一手来源、独立验证、结构化数据、附件、反证/争议。
2. 适用时执行中文和英文实体查询；公司问题必须包含官网/IR/监管申报，政策问题必须包含政府原文。
3. 预算按问题和阶段分配：发现 40%、交叉验证 40%、反证与时效 20%；未使用的保留预算可在最后阶段释放。
4. trace 记录每条搜索的 query、category、language、time_range、引擎、排名、URL、是否新域、是否归档和未采用原因。
5. 基于新增独立证据的边际收益停止，而不是达到文档数就停止。

**真实运行验收**：每个问题至少覆盖 3 类来源、至少 1 次 `site:` 和 1 次附件/结构化查询；适用时具备中英文查询；每个问题至少产生 1 个一手候选和 2 个独立验证候选。

### 015 — evidence-yield（提高语料到证据的转化率）

**前置条件**：014 全部验收通过。

**目标**：让 Agent 优先阅读能回答问题、补交叉验证或揭示冲突的材料，不再归档 143 篇只使用 8 篇。

**主要文件**：本地 `document_search`/排序实现、`src/intel_agent/materials.py`、`src/intel_agent/report.py`、对应测试和分析脚本。

**必须完成**：

1. 文档排序同时考虑问题相关度、来源角色、发布时间、域名新颖性和交叉验证价值。
2. 已有同域同观点来源时，优先返回不同来源组或反证材料。
3. 对每个核心事实执行“本地语料补证 → 定向网络补证”，再允许覆盖评估。
4. 正式报告只展示最多 20 份优先阅读材料；1–2 星材料进入附录/资源列表，不展开污染正文。
5. 分析脚本输出搜索→归档→阅读→证据→独立事实的转化漏斗，以及各深度的证据产出率。

**真实运行验收**：文档证据利用率 ≥20%；正式报告中 1–2 星材料占比 ≤30%；两个问题合计引用 ≥8 个独立原始来源组；报告中的关键数字双源验证率 100%。

### 016 — rendered-multimedia-recall（动态网页和多媒体专项）

**前置条件**：015 全部验收通过。

**目标**：用专门数据集证明 JS、PDF、Office、图片、音频和视频不是“代码存在但真实搜索没有命中”。

**主要文件**：`src/intel_agent/browser.py`、`src/intel_agent/extract.py`、搜索附件发现逻辑、系统能力接口、夹具和集成测试。

**必须完成**：

1. 建立至少一个 JS 页面主题和一个多媒体主题，保存固定公开目标清单作为验收基线。
2. 普通 HTTP 正文不足时才触发浏览器；记录触发原因、渲染结果和失败原因。
3. 附件查询和页面附件发现必须覆盖 PDF、DOCX/XLSX/PPTX、图片、音频和视频。
4. OCR/转写只有通过最小文本质量检查才可成为证据；处理器 unavailable 时只归档原件。
5. 原件、提取文本、SHA-256、来源 URL、处理器状态和证据行号/时间戳保持关联。

**真实运行验收**：专项目标清单中的格式均至少成功归档并提取 1 份；JS 页面有非零渲染成功样本；处理失败的材料不进入事实证据；报告准确披露未安装处理器和失败格式。

## 统一质量指标（012 起每轮必报）

| 分类 | 指标 | 计算方式 |
|------|------|----------|
| 搜索质量 | Precision@10 | 每条查询前 10 个结果中与问题直接相关的比例 |
| 权威覆盖 | Authoritative@10 | 前 10 个结果中一手/政府/监管/高质量媒体比例 |
| 时效 | InScope@10 | 前 10 个结果中处于任务时间范围内的比例 |
| 来源广度 | 最大域、前两域占比、有效域数量 | 有效域数量=`1 / Σ(domain_share²)` |
| 研究深度 | 各 depth 证据产出率 | 该 depth 进入证据链的文档数 / 该 depth 归档文档数 |
| 转化效率 | 文档证据利用率 | 被证据引用的唯一文档数 / 归档文档数 |
| 交叉验证 | 关键事实双源率 | 具备 ≥2 个独立原始来源组的关键事实 / 全部关键事实 |
| 问题覆盖 | 必须维度覆盖率 | 已满足的必须维度 / 全部必须维度 |
| 报告可读性 | 低推荐材料正文占比 | 正文展示的 1–2 星材料 / 正文全部材料 |

指标没有可计算数据时必须写“不可计算”并说明缺少什么观测数据；不得写 0、100% 或“基本满足”。

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
7. **语料垃圾第三次换形态**（007 图片 → 008 CCDI 容器外链接 → 009 gov.cn 门户导航页）：只要 depth≥1 的非图片链接只降优先级不拒入队，frontier 容量富余时垃圾必然占满。阈值型修复要覆盖整条入队路径，不能只修一个资源类型
8. **搜索引擎降级需要工具级兜底**：searxng news 引擎全灭时模型 6/8 次选择 news 类别导致整轮饿死；同预算内 fallback 是比提示词约束更可靠的韧性修复
9. **垃圾抓取是双重成本**：010 证明语料质量提升同时带来产出提升（事实 +38%）与成本下降（token -53%）——阈值型入队门槛是投入产出比最高的一类修复
10. **广度检索放大工具链缺陷面**：011 一次实跑暴露 3 个此前小语料下不可见的缺陷（工具参数校验崩溃、URL latin-1 编码、长 CJK 切词失效）；预算解绑类改动必须在真实广度下验收
11. **语料垃圾第 5 次换形态**（单域论坛洪泛）：rel 门槛后，词匹配的论坛帖以单域 103/143 灌满 frontier。下一层防御必须是 per-domain 配额，单一 URL 级门槛已到能力边界
12. **广度≠多源**：143 篇语料下仍 0 多源事实——coverage 判定（srcs=1 即 covered）与"独立来源"要求结构性矛盾，交叉验证需要判定层而非提示词层驱动
13. **诚实判定与执行能力是两层问题**：012 修好判定层后（虚假 covered 归零），交叉验证的**执行层**缺口暴露——190 次请求未补齐任何第二来源。判定诚实是必要不充分条件，执行层需要确定性查询矩阵（014）而非更多预算
14. **公平调度无法凭空创造多样性**：013 的配额/轮转/转载合并全部生效，但"单域 ≤15%/前两域 ≤35%/有效域 ≥6"在种子域多样性不足时无法达成——输出侧的公平机制受制于输入侧的种子质量，013 与 014 必须作为一对验证
15. **候选供给与闭环执行是两层问题**：014 确定性矩阵把候选供给解决了（新域 76、利用率 46.7%），但双源率仍 0——模型在 no_progress 前优先登记新事实而非补第二来源。执行层闭环需要排序驱动（015），供给层到位只是必要条件
16. **提示词与供给侧修复已到能力边界**：015 把 backlog 清单直接放进 coverage_eval 输出（先补证再登记新事实的显式指令），模型行为依然不变。证据链闭环的最后一段需要判定层强制执行（如 fact_save 门控），继续提示词优化是无效投入
17. **判定层强制一次达成供给侧四轮未竟之事**：016 的 fact_save 门控把双源率 0%→86.7%——012-015 的诚实判定、公平配额、确定性矩阵、backlog 排序全部是必要条件，但闭环只能由硬约束闭合；"门控+预算重标定"应成为后续判定层修复的标准模式
18. **能力专项验收必须换专门数据集**：017 证明质量门控在真实语料上按设计工作（3/3 噪声拦截），但控制变量主题（低空经济）的语料构成不产生 JS 页面与 PDF/Office/音视频命中——多媒体类验收与常规检索质量实验不能共用同一主题，专项主题+固定目标清单是此类验收的必备前提
19. **多媒体验收的瓶颈已从管线转移到环境与数据集**：018 用部署源种子把 PDF/视频/图片全部推到归档层后，暴露的是三层环境问题（whisper 模型下载、tessdata_best 未装、Office/音频公开直链稀缺）——管线代码本身两轮未暴露新缺陷，后续投入应集中在环境项而非继续改管线
20. **环境修复一轮打通三格式**：019 的 whisper 镜像缓存 + tessdata_best + 爬取回退让 3/3 固定媒体目标生产提取成功——验证了"环境依赖修复能直接改变实验结论"（结论 6）在多媒体验收面的复现；且 019a 全量错误文本修正了 018 的视频根因误判（模型下载超时，非 CDN）
21. **门控必须有诚实出口**：016 的 fact_save 门控在 020b 造成 collect 死锁（单源事实补不齐第二来源→登记被永久阻断）；search 耗尽与 coverage no_progress 两个出口解锁后，任务诚实走完 with_gaps。判定层硬约束必须成对设计：强制 + 出口
22. **020 收官：9 项阈值 7 项达标**——前两域/有效域/来源组三项历史首次达标，剩余两项（最大域 17.1%、双源率 66.7%）均为语料规模张力与真实单源信息稀缺，继续迭代边际收益递减，建议封版转长期观察
23. **本地模型的工具协议成功不等于研究流程成功**：021 中 Qwen3.5-9B 能调用工具，但 40 次搜索只形成 1 条证据；长流程必须由确定性阶段门控约束，不能只依赖提示词纪律
24. **结构化审核必须有严格的生成边界**：021 单次审核输出约 32K tokens 并拖垮整个任务；本地小模型应按角色设置独立输出上限、推理模式和历史窗口
25. **失败轨迹是验收数据，不是可选日志**：021 在异常路径丢失 trace，导致请求数和总 token 无法计算；实验 harness 必须增量落盘，成功后一次性保存不足以支持真实故障分析
26. **小模型需要可执行状态，不需要更长提示词**：022–026 逐段证明 search→fetch→read→fact/evidence→audit→report 的唯一下一动作比重复工作流说明有效；32K 足以完成，关键是从持久状态恢复阶段。
27. **自动续跑只能放大当前 next_action 的质量**：025 形成证据闭环，也把错误的 coverage 动作重复 16 轮；runner 续跑必须与阶段感知快照成对使用，并共享累计请求预算。
28. **with-gaps 报告必须允许空问题章节**：未回答问题若被强制填写结论，只会诱导小模型复用无关事实；026 允许空结论并由系统生成“未形成可验证结论”，最终在不伪造 Q2 的前提下完成报告。
29. **短对话连通不等于 Agent 负载可用**：027–028 中远程 Qwen3.8-27B 能在 3.7 秒完成短对话和单工具 ping，但真实首请求连续 400 秒以上无工具动作，最小真实系统提示诊断最终触发 502；远程模型验收必须包含完整提示与工具 schema，并同时检查延迟、结束原因和请求后的健康状态。
30. **模型工具调用成功仍需兼容嵌套对象编码**：029/031 中 Qwen3.8 会把 criteria/draft 对象编码为 JSON 字符串；边界兼容必须在解析后继续走原 Pydantic 模型，不能用宽松 dict 绕过校验。
31. **低吞吐模型需要按角色分配输出预算**：030 的普通工具调用在 1024 token 内可用，但五章节报告连续截断；报告使用 2048 token 后完整生成，16K 历史窗口无需扩大。
32. **报告与完成摘要必须以持久证据为最终权威**：033 中模型自由文本夸大为 2 条事实和推断，但安全草稿只写入 1 条 full 事实；CLI/Web 完成摘要也必须从 state 生成，不能转发模型自述。
33. **参数层失败先于业务回退，兜底必须覆盖整条失败链**：034 中 1024 token 截断使草稿在 pydantic-ai 工具参数层就解析失败（重试 3 次 → UnexpectedModelBehavior），033 的业务校验安全回退完全未触发——确定性兜底要挂在参数层与业务层两处，或直接提高报告输出上限为默认。
34. **模型端点迁移需要实测验证而非配置替换**：034 中远程配置的模型名 `qwen3.8-27b-int4` 在本地 vLLM 上直接 404；本地服务还缺失工具调用解析器——端点替换必须包含 /v1/models 探测、单轮工具调用探针和健康检查三重验证，之后才能实跑。
35. **终态转换不能留给模型**：025/034/036 三次死循环的共同根因是"报告转换权在模型手里"——backlog 注入、审核快照时序与补证不可达组合出 audit↔coverage_eval 环。037 把转换收归判定层（coverage_eval 在 no_progress 时确定性生成报告并推送 done）后 3 请求即达终态。判断模型"何时应该停"的责任必须与执行分离，小模型只执行不决策。
36. **诚实终态优先于产出数量**：037 允许 no_progress 下的零结论报告后，任务以 0 验证事实、全空章节、完整局限披露收尾——对比 025 的 16 轮循环和 034/036 的 90 分钟死循环，披露空结果比假装在推进更接近交付。报告层必须给"没有可验证结论"留合法出口。
37. **结构化输出不是所有模型都支持**：deepseek-v4-flash 的 thinking 模式拒绝 tool_choice=required 且 json_schema 不可用，038 首跑 191 次审核静默失败耗尽预算——judge 这类内部结构化调用必须走"纯文本完成 + 确定性解析"，不能依赖 provider 的结构化输出能力；静默失败必须能通过 trace 的工具调用分布诊断。
38. **冻结材料复验证明修复链闭环**：WP1（问题冻结）→ WP2（审核约束）→ WP3（增量 trace）→ WP4（collect 收敛）四个 P0 包一次验证通过，基线 586s 中断变为 233s done/with_gaps；判定层收敛 + 诚实报告 + 可观测性三者缺一不可。
39. **qwen thinking 机型作 judge 必须关闭 thinking**：059 首段 75 次 evidence_audit 因 thinking 耗尽 512 输出预算/污染 JSON 全部失败；`audit_output_tokens=2048` 消除截断错误，`disable_thinking=true` 才让 21 条评审全部可解析（full 3/partial 16）。结论 37（纯文本 judge）在 qwen thinking 上仍需输出预算与推理模式两项配套，缺一不可。
40. **中断恢复是真实可用的实验路径**：059 首段被外部超时终止后，直接以 `--cwd` 指向同一运行目录续跑即可从 intel.db 恢复（`reused_existing_task`），续跑段快照重建后上下文从 79K 降至 5.5K tokens；长任务实验不必一次跑完，恢复能力本身值得每轮验收。
41. **工具失败必须有失败治理，否则模型把失败当任务重复执行**：059 的 65 次审计连败是"工具抛错+提示词强制+无护栏"三重合谋——模型看到相同错误文本仍以相同理由重试（75 次决策全为 EVIDENCE_NOT_VERIFIED）。061 的 batch 隔离 + 连续失败冷却（skip 而非再错）把审计调用从 75/65 连败降到 9/1 瞬时失败；工具失败反馈必须附带可执行指引或改变状态，不能只回传错误文本。
42. **工具门禁必须与提示词契约一致**：059 中 coverage 提示要求所有任务"先 document_search 本地补证"，工具却只对 deep_crawl 任务开放（2/2 必失败）——模型照做必失败，交叉验证通道被废。061 移除门禁并把语料源从 crawl entries 改为任务 digest 后 1/1 成功；工具可用性与提示词描述的偏差比工具缺失更隐蔽（模型不会报告，只会静默弃用）。
43. **结构化参数工具必须让模型看到格式，否则模型会自由发挥**：062 中 qwen 把 generate_research_report 的 draft 写成 Markdown 报告文本（docstring 未说明格式），静默 fallback 掩盖了错误让模型循环 56 次。063 修复三件套（docstring 给 JSON 示例 + Markdown 显式报错 + 阻断消息带出口指引）后 1 次成功——内部工具的参数契约要写进模型可见的 description，失败要给出"下一步做什么"。
44. **新增 stop_reason 必须同步所有消费点**：063 引入 search_budget_exhausted 后，report 的空章节/空结论豁免仍只认 no_progress（037），导致预算耗尽的零验证事实任务系统兜底生成报告也失败。判定层新状态的豁免矩阵（coverage stop、report 空章节、terminal switch）必须一次性对齐，否则修复 4 的出口又成死路。
45. **确定性代偿比提示词有效**：064 中 fact_save 门控不再发"先用 document_search 补证"的通用指令，而是系统直接检索并把 document_id+snippet 注入错误消息——模型立即采纳（READ 候选、存 3 条证据），而 059/061/063 三轮回合中同样指令下 document_search 调用为 0。对模型行为缺口的修复要"把结果送上门"，而不是"告诉它去哪找"。
46. **预算分池直接改变模型行为**：064 中 discovery 池 16 次用尽后模型搜索立即停止（063 硬撞 34 次仍继续），转读材料补证；可观测的"池耗尽"比隐形的"总预算"对模型行为约束力强。分池不仅是资源分配，也是行为引导。
