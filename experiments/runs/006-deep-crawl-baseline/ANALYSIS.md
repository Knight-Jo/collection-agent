# 实验分析: 006-deep-crawl-baseline

- 主题: 低空经济
- 问题: 2026年低空经济投资与融资趋势; 亿航智能商业化进展与订单情况
- 耗时: 1274.3s  exit=0
- git: ee068aa

## 工具调用轨迹（共 162 次）

| # | 工具 | 参数摘要 |
|---|------|----------|
| 1 | intel_plan | topic=低空经济（低空经济政策、产业与投资） q=2 |
| 2 | web_search | q=2026年低空经济投资与融资趋势 n=5 |
| 3 | web_search | q=亿航智能商业化进展与订单情况 2026 n=5 |
| 4 | web_search | q=低空经济 融资 投资规模 2026 n=5 |
| 5 | web_search | q=亿航智能 EH216 订单 交付 2026 n=5 |
| 6 | web_search | q=低空经济 万亿 政策 规划 市场 2025 n=5 |
| 7 | web_search | q=EHang orders deliveries FY2025 commercia n=5 |
| 8 | web_fetch | url=https://www.gov.cn/yaowen/liebiao/202502/content_7004451.htm |
| 9 | web_fetch | url=https://www.ehang.com/cn/news/1098.html |
| 10 | fact_save | q=q-82cba3ce-4606- stmt=2024年「低空经济」写入政府工作报告，2025年政策端、产业端同频共振，全国约 |
| 11 | fact_save | q=q-82cba3ce-4606- stmt=有机构预测2025年我国低空经济整体市场规模将达到8591.7亿元。 |
| 12 | fact_save | q=q-bd12be7e-ab49- stmt=2024年6月，亿航智能与浙江省温州市文成县政府签署合作协议，文成县交通发展集团 |
| 13 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=2024年，「低空经济」写入政府工作报告...一年来，政策端 |
| 14 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=据不完全统计，去年至今，约30个省份将发展低空经济写入当地政 |
| 15 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=有机构预测，2025年我国低空经济整体市场规模将达到8591 |
| 16 | evidence_save | doc=doc-33796c59102f rel=supports quote=文成县交通发展集团有限公司已与亿航智能签署首批30架EH21 |
| 17 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=2024年，「低空经济」写入政府工作报告，凸显其在国家经济发 |
| 18 | crawl_collect | {"task_id": "task-7cab926f-ab32-4ac3-a0e0-42e0c2a9b7ec"} |
| 19 | document_read | {"document_id": "doc-03886d6f340df92a", "start_line": 1, "end_line": 80} |
| 20 | document_read | {"document_id": "doc-4d18623abb1681fb", "start_line": 1, "end_line": 60} |
| 21 | fact_save | q=q-82cba3ce-4606- stmt=近三年资本市场上低空经济相关领域融资事件累计380起，其中2023年63次、20 |
| 22 | fact_save | q=q-82cba3ce-4606- stmt=中商产业研究院报告显示2025年中国低空经济市场规模已达1.5万亿元，并预测20 |
| 23 | fact_save | q=q-bd12be7e-ab49- stmt=截至2026年5月，亿航智能旗舰产品EH216-S无人驾驶载人航空器已累计完成超 |
| 24 | fact_save | q=q-bd12be7e-ab49- stmt=2026年6月，亿航智能联合冠忠智慧出行有限公司及香港数码港管理有限公司开展低空 |
| 25 | evidence_save | doc=doc-03886d6f340d rel=supports quote=近三年，资本市场低空经济相关领域融资活跃，融资事件累计380 |
| 26 | evidence_save | doc=doc-03886d6f340d rel=supports quote=中商产业研究院发布的《2025-2030年中国低空经济行业市 |
| 27 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=截至2026年5月，亿航智能的旗舰产品EH216-S无人驾驶 |
| 28 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=亿航智能联合冠忠智慧出行有限公司及香港数码港管理有限公司开展 |
| 29 | document_read | {"document_id": "doc-be364516d5e3a116", "start_line": 30, "end_line": 50} |
| 30 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=2024年，“低空经济”写入政府工作报告，凸显其在国家经济发 |
| 31 | web_search | q=低空经济 融资 2025 亿元 财联社 投融资事件 n=5 |
| 32 | web_search | q=亿航智能 2025 财报 营收 订单 交付 财新 n=5 |
| 33 | document_read | {"document_id": "doc-ff06af41daf9b2a9", "start_line": 1, "end_line": 60} |
| 34 | web_fetch | url=https://ir.ehang.com/ |
| 35 | fact_save | q=q-bd12be7e-ab49- stmt=2026年8月10日，亿航EH216-S在哈萨克斯坦首都完成中亚首次无人驾驶载人 |
| 36 | evidence_save | doc=doc-8b1d4172fcc9 rel=supports quote=EH216-S Completes Central Asia |
| 37 | document_read | {"document_id": "doc-8b1d4172fcc9f934", "start_line": 1, "end_line": 60} |
| 38 | evidence_save | doc=doc-8b1d4172fcc9 rel=supports quote=EH216-S Completes Central Asia |
| 39 | web_fetch | url=https://www.caixin.com/search/searchresult.jsp?keyword=低空经济+ |
| 40 | evidence_audit | task=task-7cab926f-ab |
| 41 | fact_save | q=q-82cba3ce-4606- stmt=2024年「低空经济」写入政府工作报告。 |
| 42 | fact_save | q=q-82cba3ce-4606- stmt=据不完全统计，约30个省份将发展低空经济写入当地政府工作报告或出台相关政策。 |
| 43 | fact_supersede | {"fact_id": "fact-a5d82bda5444f2da", "replacement_fact_ids": ["fact-c7682e33dec9 |
| 44 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=2024年，“低空经济”写入政府工作报告，凸显其在国家经济发 |
| 45 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=据不完全统计，去年至今，约30个省份将发展低空经济写入当地政 |
| 46 | evidence_audit | task=task-7cab926f-ab |
| 47 | fact_save | q=q-82cba3ce-4606- stmt=中商产业研究院报告显示2025年中国低空经济市场规模已达1.5万亿元。 |
| 48 | fact_save | q=q-82cba3ce-4606- stmt=中商产业研究院预测2030年中国低空经济市场规模将达到2万亿元。 |
| 49 | fact_save | q=q-82cba3ce-4606- stmt=2024年中国低空经济相关领域融资事件161次，较2023年的63次增长155. |
| 50 | fact_save | q=q-82cba3ce-4606- stmt=2025年中国低空经济相关领域融资事件156次，同比下降3.1%。 |
| 51 | fact_supersede | {"fact_id": "fact-03b0358620834660", "replacement_fact_ids": ["fact-703494ff15e8 |
| 52 | fact_supersede | {"fact_id": "fact-ab09491d9802d943", "replacement_fact_ids": ["fact-09be1558bb81 |
| 53 | evidence_save | doc=doc-03886d6f340d rel=supports quote=中商产业研究院发布的《2025-2030年中国低空经济行业市 |
| 54 | evidence_save | doc=doc-03886d6f340d rel=supports quote=2024年发生融资事件数量161次，增长155.6% |
| 55 | evidence_save | doc=doc-03886d6f340d rel=supports quote=2025年发生融资事件156次，下降3.1% |
| 56 | fact_save | q=q-bd12be7e-ab49- stmt=2024年6月，亿航智能与浙江省温州市文成县政府达成合作，文成县交通发展集团有限 |
| 57 | fact_save | q=q-bd12be7e-ab49- stmt=亿航智能计划2026年年底前由文成县额外采购270架EH216-S，且已支付不可 |
| 58 | fact_save | q=q-bd12be7e-ab49- stmt=截至2026年5月，亿航智能旗舰产品EH216-S无人驾驶载人航空器已累计完成超 |
| 59 | fact_save | q=q-bd12be7e-ab49- stmt=亿航EH216-S在广州与合肥开展常态化试运营。 |
| 60 | fact_supersede | {"fact_id": "fact-535138ac21c2ae24", "reason": "复合文成订单事实被审核为 partial：拆分为首批30架采购与 |
| 61 | fact_supersede | {"fact_id": "fact-0983f530993f47ed", "reason": "复合商业化事实被审核为 partial：拆分为累计9万架次飞行与 |
| 62 | evidence_save | doc=doc-33796c59102f rel=supports quote=文成县交通发展集团有限公司已与亿航智能签署首批30架EH21 |
| 63 | evidence_save | doc=doc-33796c59102f rel=supports quote=计划2026年年底前额外采购270架EH216-S，且已支付 |
| 64 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=截至2026年5月，亿航智能的旗舰产品EH216-S无人驾驶 |
| 65 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=并在广州与合肥开展常态化试运营，为低空经济行业迈入商业运营阶 |
| 66 | fact_save | q=q-82cba3ce-4606- stmt=关于2025年中国低空经济市场规模，有机构预测整体市场规模将达8591.7亿元， |
| 67 | evidence_save | doc=doc-be364516d5e3 rel=supports quote=有机构预测，2025年我国低空经济整体市场规模将达到8591 |
| 68 | evidence_save | doc=doc-03886d6f340d rel=contradicts quote=2025年中国低空经济市场规模已达1.5万亿元 |
| 69 | evidence_conflict_create | {"fact_id": "fact-2202174fb09c9bfa", "evidence_ids": ["ev-96e7ea9af54043cc", "ev |
| 70 | evidence_audit | task=task-7cab926f-ab |
| 71 | fact_supersede | {"fact_id": "fact-2202174fb09c9bfa", "reason": "该复合事实同时表述两个冲突数值，语义审核无法给出有效判定。改为保 |
| 72 | evidence_audit | task=task-7cab926f-ab |
| 73 | web_fetch | url=https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&c |
| 74 | web_fetch | url=https://www.thepaper.cn/searchResult?query=%E4%BA%BF%E8%88%A |
| 75 | web_fetch | url=https://www.cls.cn/searchPage?keyword=%E4%BA%BF%E8%88%AA%E6% |
| 76 | coverage_eval | task=task-7cab926f-ab |
| 77 | evidence_save | doc=doc-03886d6f340d rel=supports quote=其中，2023年中国低空经济相关领域融资事件63次，2024 |
| 78 | evidence_save | doc=doc-03886d6f340d rel=supports quote=其中，2023年中国低空经济相关领域融资事件63次，2024 |
| 79 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=中国广州，2026年6月23日——随着香港积极推进多轮监管沙 |
| 80 | evidence_save | doc=doc-8b1d4172fcc9 rel=supports quote=August 10, 2026
EH216-S Comple |
| 81 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=中国广州，2026年6月23日——随着香港积极推进多轮监管沙 |
| 82 | evidence_save | doc=doc-33796c59102f rel=supports quote=中国广州，2024年6月21日——全球领先的城市空中交通（U |
| 83 | evidence_save | doc=doc-33796c59102f rel=supports quote=此外，计划2026年年底前额外采购270架EH216-S，且 |
| 84 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=并在广州与合肥开展常态化试运营，为低空经济行业迈入商业运营阶 |
| 85 | evidence_audit | task=task-7cab926f-ab |
| 86 | coverage_eval | task=task-7cab926f-ab |
| 87 | fact_save | q=q-bd12be7e-ab49- stmt=亿航智能联合冠忠智慧出行有限公司及香港数码港管理有限公司，成功入选香港低空经济「 |
| 88 | fact_supersede | {"fact_id": "fact-1d041b703d40192c", "reason": "原事实包含日期成分导致引文无法完整蕴含被审核为 partial； |
| 89 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=亿航智能联合冠忠智慧出行有限公司及香港数码港管理有限公司开展 |
| 90 | evidence_save | doc=doc-4d18623abb16 rel=supports quote=截至2026年5月，亿航智能的旗舰产品EH216-S无人驾驶 |
| 91 | evidence_audit | task=task-7cab926f-ab |
| 92 | coverage_eval | task=task-7cab926f-ab |
| 93 | intel_status | task= |
| 94 | web_fetch | url=https://stockanalysis.com/stocks/eh/ |
| 95 | fact_save | q=q-bd12be7e-ab49- stmt=2025年亿航智能（EHang）营收为4.18亿元人民币，较2024年的4.56 |
| 96 | fact_save | q=q-bd12be7e-ab49- stmt=亿航智能2025年实现创纪录的eVTOL交付和强劲营收增长，并首次实现单季度GA |
| 97 | fact_save | q=q-bd12be7e-ab49- stmt=2026年年中，多家投行下调亿航智能（EH）评级或目标价：Goldman Sac |
| 98 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=In 2025, EHang Holdings's reve |
| 99 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=Record eVTOL deliveries and st |
| 100 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=Goldman Sachs downgraded EHang |
| 101 | document_read | {"document_id": "doc-60d47844ae2fa406", "start_line": 125, "end_line": 180} |
| 102 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=Goldman Sachs downgraded EHang |
| 103 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=BofA double downgraded EHang ( |
| 104 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=JPMorgan analyst Beatrice Lam  |
| 105 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=Morgan Stanley analyst Tim Hsi |
| 106 | evidence_audit | task=task-7cab926f-ab |
| 107 | coverage_eval | task=task-7cab926f-ab |
| 108 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=EH216-S Completes Central Asia |
| 109 | document_read | {"document_id": "doc-60d47844ae2fa406", "start_line": 115, "end_line": 126} |
| 110 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=EH216-S Completes Central Asia |
| 111 | evidence_audit | task=task-7cab926f-ab |
| 112 | coverage_eval | task=task-7cab926f-ab |
| 113 | intel_status | task=task-7cab926f-ab |
| 114 | generate_package | task=task-7cab926f-ab |
| 115 | intel_assess | task=task-7cab926f-ab |
| 116 | intel_assess | task=task-7cab926f-ab |
| 117 | intel_status | task=task-7cab926f-ab |
| 118 | intel_challenge_start | round=1 points=3 |
| 119 | web_fetch | url=https://www.globenewswire.com/news-release/2026/03/12/325438 |
| 120 | web_fetch | url=https://www.globenewswire.com/news-release/2026/08/10/334160 |
| 121 | web_fetch | url=https://www.tipranks.com/news/the-fly/ehang-downgraded-to-ne |
| 122 | web_fetch | url=https://stockanalysis.com/stocks/eh/financials/ |
| 123 | evidence_save | doc=doc-6b66301df1ac rel=supports quote=417.98 456.15 ... Revenue Grow |
| 124 | document_read | {"document_id": "doc-6b66301df1ac9fc1", "start_line": 60, "end_line": 85} |
| 125 | document_read | {"document_id": "doc-6b66301df1ac9fc1", "end_line": 92, "start_line": 85} |
| 126 | evidence_save | doc=doc-6b66301df1ac rel=supports quote=417.55 417.98 456.15 117.43 44 |
| 127 | evidence_audit | task=task-7cab926f-ab |
| 128 | fact_save | q=q-bd12be7e-ab49- stmt=亿航EH216-S在哈萨克斯坦首都完成中亚首次无人驾驶载人eVTOL载人飞行。 |
| 129 | fact_supersede | {"fact_id": "fact-86adef45fbe0cc44", "reason": "移除日期成分，使得作为第二独立来源（stockanalysis. |
| 130 | evidence_save | doc=doc-8b1d4172fcc9 rel=supports quote=EH216-S Completes Central Asia |
| 131 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=EH216-S Completes Central Asia |
| 132 | evidence_audit | task=task-7cab926f-ab |
| 133 | coverage_eval | task=task-7cab926f-ab |
| 134 | fact_save | q=q-bd12be7e-ab49- stmt=据StockAnalysis引用的S&P Global财务数据，亿航智能2025 |
| 135 | fact_supersede | {"fact_id": "fact-13d44baf0126bd7f", "reason": "该事实的一条补充证据（财务表格数字摘录）被语义审核判为矛盾，故收 |
| 136 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=In 2025, EHang Holdings's reve |
| 137 | evidence_audit | task=task-7cab926f-ab |
| 138 | intel_challenge_confirm | round=1 resolutions=3 |
| 139 | coverage_eval | task=task-7cab926f-ab |
| 140 | fact_save | q=q-bd12be7e-ab49- stmt=2025年亿航智能营收为417.98百万（人民币单位，折合约4.18亿元），较2 |
| 141 | fact_supersede | {"fact_id": "fact-478f867b5224c4cb", "reason": "收敛陈述去除来源前缀，使引文能够完整蕴含事实内容。", "rep |
| 142 | evidence_save | doc=doc-60d47844ae2f rel=supports quote=In 2025, EHang Holdings's reve |
| 143 | evidence_audit | task=task-7cab926f-ab |
| 144 | generate_package | task=task-7cab926f-ab |
| 145 | generate_package | task=task-7cab926f-ab |
| 146 | intel_status | task=task-7cab926f-ab |
| 147 | intel_assess | task=task-7cab926f-ab |
| 148 | generate_package | task=task-7cab926f-ab |
| 149 | intel_status | task=task-7cab926f-ab |
| 150 | generate_package | task=task-7cab926f-ab |
| 151 | coverage_eval | task=task-7cab926f-ab |
| 152 | generate_package | task=task-7cab926f-ab |
| 153 | intel_assess | task=task-7cab926f-ab |
| 154 | intel_status | task=task-7cab926f-ab |
| 155 | intel_status | task=task-7cab926f-ab |
| 156 | intel_challenge_start | round=2 points=1 |
| 157 | intel_challenge_confirm | round=2 resolutions=1 |
| 158 | coverage_eval | task=task-7cab926f-ab |
| 159 | generate_package | task=task-7cab926f-ab |
| 160 | intel_assess | task=task-7cab926f-ab |
| 161 | intel_status | task=task-7cab926f-ab |
| 162 | intel_status | task=task-7cab926f-ab |

### 工具调用分布
- evidence_save: 48
- fact_save: 26
- web_fetch: 12
- evidence_audit: 12
- fact_supersede: 10
- document_read: 9
- coverage_eval: 9
- intel_status: 9
- web_search: 8
- generate_package: 7
- intel_assess: 5
- intel_challenge_start: 2
- intel_challenge_confirm: 2
- intel_plan: 1
- crawl_collect: 1
- evidence_conflict_create: 1

### 重复/可疑调用
- 连续重复 generate_package: task=task-7cab926f-ab

## 任务最终状态
- stage: challenge  challenge_round: 2
- collection: {"search_attempts": 6, "search_stop_reason": "search_budget_exhausted", "fetch_attempts_since_evidence": 0, "evidence_count": 40, "stop_reason": null}
- outputs: package=True, assessment=True

## 最新覆盖快照
- level: insufficient  gap_score: 29  stop_reason: no_progress
- no_progress_rounds: 2
- Q[partial] 2026年低空经济投资与融资趋势: facts=7 covered=0
    - F[partial] gap=1 srcs=1 hq=1 recent=0 uncf=0 独立来源组不足; 建议搜索「有机构预测2025年我国低空经济整体市场规模将达到8591.7亿元。」的交叉验证来源（第 2 个独立来源组）
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「2024年中国低空经济相关领域融资事件161次,较2023年的63次增长155.6%。」的交叉验证来源（第 2 个独立来源组）; 1 条引文只部分支持 Fact
    - F[gap] gap=3 srcs=0 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「中商产业研究院报告显示2025年中国低空经济市场规模已达1.5万亿元。」的交叉验证来源（第 2 个独立来源组）
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「2025年中国低空经济相关领域融资事件156次,同比下降3.1%。」的交叉验证来源（第 2 个独立来源组）; 1 条引文只部分支持 Fact
    - F[partial] gap=1 srcs=1 hq=1 recent=0 uncf=0 独立来源组不足; 建议搜索「2024年「低空经济」写入政府工作报告。」的交叉验证来源（第 2 个独立来源组）
    - F[partial] gap=1 srcs=1 hq=1 recent=0 uncf=0 独立来源组不足; 建议搜索「据不完全统计,约30个省份将发展低空经济写入当地政府工作报告或出台相关政策。」的交叉验证来源（第 2 个独立来源组）
- Q[partial] 亿航智能商业化进展与订单情况: facts=9 covered=0
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「截至2026年5月,亿航智能旗舰产品EH216-S无人驾驶载人航空器已累计完成超过9万架次安全飞行。」的交叉验证来源（第 2 个独立来源组）
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「亿航智能计划2026年年底前由文成县额外采购270架EH216-S,且已支付不可退还订金。」的交叉验证来源（第 2 个独立来源组）; 1 条引文只部分支持 Fact
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「2025年亿航智能营收为417.98百万(人民币单位,折合约4.18亿元),较2024年的456.15百万下降8.37%,净亏损275.98百万。」的交叉验证来源（第 2 个独立来源组）
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「亿航EH216-S在广州与合肥开展常态化试运营。」的交叉验证来源（第 2 个独立来源组）; 1 条引文只部分支持 Fact
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「亿航智能联合冠忠智慧出行有限公司及香港数码港管理有限公司,成功入选香港低空经济「监管沙盒X」首批非传统航空器试点项目。」的交叉验证来源（第 2 个独立来源组）
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「2026年年中,多家投行下调亿航智能(EH)评级或目标价:Goldman Sachs降至Neutral(目标价$7.30)、BofA降至Underperform($5.40)、JPMorgan降至Underweight($4.40)、Morgan Stanley下调目标价至$7.70。」的交叉验证来源（第 2 个独立来源组）
    - F[partial] gap=1 srcs=2 hq=0 recent=0 uncf=0 高质量独立来源组不足
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「2024年6月,亿航智能与浙江省温州市文成县政府达成合作,文成县交通发展集团有限公司与亿航智能签署首批30架EH216-S采购协议,并已支付总货款50%作为预付款。」的交叉验证来源（第 2 个独立来源组）; 1 条引文只部分支持 Fact
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「亿航智能2025年实现创纪录的eVTOL交付和强劲营收增长,并首次实现单季度GAAP盈利,2026年营收指引为6亿元人民币,无人驾驶eVTOL商业运营在中国和泰国启动。」的交叉验证来源（第 2 个独立来源组）

## 挑战轮次 1: confirmed converged=False
- [dismissed] source_independence: Q1所有事实（政策写入报告、约30省、2025市场规模、融资事件数）均只锚定单一独立来源组（gov.cn 或 seccw
- [dismissed] data_consistency: 研判将2025年中国低空经济市场规模同时引用了两个显著冲突的数字：gov.cn引述机构预测8591.7亿元，中商产业研究
- [addressed] self_reporting_bias: Q2亿航的运营与订单事实（9万架次、文成30+270架、广州合肥试运营、香港沙盒）几乎全部来自公司自身的官网/新闻稿，存
## 挑战轮次 2: confirmed converged=False
- [dismissed] coverage_sufficiency: 最终覆盖为 insufficient（gap_score 29），两问题均未达到 covered，除哈萨克斯坦一事实外所

## 事实统计: 总 26（active 16 / superseded 10）
- 有机构预测2025年我国低空经济整体市场规模将达到8591.7亿元。
- 2024年中国低空经济相关领域融资事件161次,较2023年的63次增长155.6%。
- 2025年中国低空经济相关领域融资事件156次,同比下降3.1%。
- 据不完全统计,约30个省份将发展低空经济写入当地政府工作报告或出台相关政策。
- 2024年「低空经济」写入政府工作报告。
- 2024年6月,亿航智能与浙江省温州市文成县政府达成合作,文成县交通发展集团有限公司与亿航智能签署首批30架EH216-S采购协议,并已支付
- 中商产业研究院预测2030年中国低空经济市场规模将达到2万亿元。
- 中商产业研究院报告显示2025年中国低空经济市场规模已达1.5万亿元。
- 亿航EH216-S在广州与合肥开展常态化试运营。
- 亿航智能计划2026年年底前由文成县额外采购270架EH216-S,且已支付不可退还订金。
- 2026年年中,多家投行下调亿航智能(EH)评级或目标价:Goldman Sachs降至Neutral(目标价$7.30)、BofA降至Un
- 截至2026年5月,亿航智能旗舰产品EH216-S无人驾驶载人航空器已累计完成超过9万架次安全飞行。
- 亿航智能联合冠忠智慧出行有限公司及香港数码港管理有限公司,成功入选香港低空经济「监管沙盒X」首批非传统航空器试点项目。
- 亿航智能2025年实现创纪录的eVTOL交付和强劲营收增长,并首次实现单季度GAAP盈利,2026年营收指引为6亿元人民币,无人驾驶eVTO
- 亿航EH216-S在哈萨克斯坦首都完成中亚首次无人驾驶载人eVTOL载人飞行。
- 2025年亿航智能营收为417.98百万(人民币单位,折合约4.18亿元),较2024年的456.15百万下降8.37%,净亏损275.98
