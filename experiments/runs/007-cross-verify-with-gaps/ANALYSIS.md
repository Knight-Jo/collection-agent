# 实验分析: 007-cross-verify-with-gaps

- 主题: 低空经济
- 问题: 2026年低空经济投资与融资趋势; 亿航智能商业化进展与订单情况
- 耗时: 1175.8s  exit=0
- git: 90aef6e

## 工具调用轨迹（共 74 次）

| # | 工具 | 参数摘要 |
|---|------|----------|
| 1 | intel_plan | topic=低空经济 q=2 |
| 2 | web_search | q=2026年低空经济投资与融资趋势 n=5 |
| 3 | web_search | q=亿航智能商业化进展与订单情况 2026 n=5 |
| 4 | web_search | q=低空经济 2026 融资 规模 亿 投资趋势 n=5 |
| 5 | web_search | q=亿航智能 订单 交付 EH216 2026 财报 n=5 |
| 6 | web_search | q=EHang 2026 order deliveries commercial p n=5 |
| 7 | web_search | q=低空经济 产业 亿 投资 2026 券商 研报 n=5 |
| 8 | web_fetch | url=https://ir.ehang.com/ |
| 9 | web_search | q=低空经济 融资 亿元 2026 产业基金 通用航空 n=5 |
| 10 | crawl_collect | {"task_id": "task-3de8207e-d0f8-4e73-aa4c-d965daa3b1f5"} |
| 11 | document_read | {"document_id": "doc-cf8583d36a4c7db1", "start_line": 1, "end_line": 60} |
| 12 | document_search | {"query": "订单 交付 亿航 EH216", "task_id": "task-3de8207e-d0f8-4e73-aa4c-d965daa3b1f |
| 13 | document_read | {"document_id": "doc-858a68dcdd217f3b", "start_line": 40, "end_line": 80} |
| 14 | web_search | q=EHang Q2 2026 results revenue orders ERI n=5 |
| 15 | document_read | {"document_id": "doc-858a68dcdd217f3b", "start_line": 40, "end_line": 75} |
| 16 | web_search | q=EHang EH216-S Kazakhstan flight passenge n=5 |
| 17 | document_search | {"query": "低空经济 投资 融资", "task_id": "task-3de8207e-d0f8-4e73-aa4c-d965daa3b1f5"} |
| 18 | document_search | {"query": "亿航 订单 营收 财报 EH216 交付", "task_id": "task-3de8207e-d0f8-4e73-aa4c-d965d |
| 19 | web_fetch | url=https://www.ehang.com/news/ |
| 20 | web_fetch | url=https://ir.ehang.com/news-events/news-releases |
| 21 | web_fetch | url=https://apnews.com/article/china-flying-cars-drones-evtol-ai |
| 22 | web_fetch | url=https://www.chinadailyhk.com/hk/article/627891 |
| 23 | document_search | {"query": "flying taxi low-altitude investment market China", "task_id": "task-3 |
| 24 | document_search | {"query": "EHang flying taxi airspace electric", "task_id": "task-3de8207e-d0f8- |
| 25 | document_read | {"document_id": "doc-c5f81e343da86e97", "start_line": 1, "end_line": 40} |
| 26 | document_search | {"query": "turbulence flying taxis China eVTOL airspace electric vertical", "tas |
| 27 | document_read | {"document_id": "doc-c5f81e343da86e97", "start_line": 40, "end_line": 120} |
| 28 | fact_save | q=q-d271bd87-b0fd- stmt=低空经济被列入国家"十五五规划"（2026-2030）建议中作为拟加速发展的战略 |
| 29 | fact_save | q=q-5c0f0d1c-c853- stmt=2026年8月10日，亿航智能的EH216-S在哈萨克斯坦首都完成中亚地区首次无 |
| 30 | fact_save | q=q-5c0f0d1c-c853- stmt=亿航智能入选香港"低空经济监管沙盒X"试验项目；其本地合作伙伴冠忠集团向香港民航 |
| 31 | evidence_save | doc=doc-99547c008a2d rel=supports quote=The LAE is also named in the r |
| 32 | evidence_save | doc=doc-858a68dcdd21 rel=supports quote=EH216-S Completes Central Asia |
| 33 | evidence_save | doc=doc-3a33c82ed7cb rel=supports quote=EH216-S Completes Central Asia |
| 34 | evidence_save | doc=doc-99547c008a2d rel=supports quote=Hong Kong's Civil Aviation Dep |
| 35 | evidence_save | doc=doc-3a33c82ed7cb rel=supports quote=EHang Selected for Hong Kong’s |
| 36 | document_read | {"document_id": "doc-99547c008a2da527", "start_line": 70, "end_line": 110} |
| 37 | evidence_save | doc=doc-99547c008a2d rel=supports quote=The LAE is also named in the r |
| 38 | evidence_save | doc=doc-99547c008a2d rel=supports quote=Yang said that Hong Kong’s Civ |
| 39 | evidence_audit | task=task-3de8207e-d0 |
| 40 | coverage_eval | task=task-3de8207e-d0 |
| 41 | document_read | {"document_id": "doc-3a33c82ed7cb5a6d", "start_line": 80, "end_line": 100} |
| 42 | document_search | {"query": "低空经济 eVTOL 融资 市场 规模 2026", "task_id": "task-3de8207e-d0f8-4e73-aa4c-d |
| 43 | document_read | {"document_id": "doc-c5f81e343da86e97", "start_line": 120, "end_line": 200} |
| 44 | document_search | {"query": "Kazakhstan flight EHang Central Asia", "task_id": "task-3de8207e-d0f8 |
| 45 | document_read | {"document_id": "doc-3a33c82ed7cb5a6d", "end_line": 130, "start_line": 100} |
| 46 | web_fetch | url=https://xueqiu.com/S/EH |
| 47 | crawl_collect | {"task_id": "task-3de8207e-d0f8-4e73-aa4c-d965daa3b1f5"} |
| 48 | web_fetch | url=https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&c |
| 49 | web_fetch | url=https://www.foxbusiness.com/technology/chinese-company-launc |
| 50 | web_fetch | url=https://so.eastmoney.com/news/s?keyword=%E4%BD%8E%E7%A9%BA%E |
| 51 | web_fetch | url=https://ir.ehang.com/press-releases |
| 52 | web_fetch | url=https://www.ehang.com/en/news/ |
| 53 | fact_supersede | {"fact_id": "fact-9c25289e9262a7d8", "replacement_fact_ids": [], "reason": "Defe |
| 54 | web_fetch | url=https://ir.ehang.com/news |
| 55 | coverage_eval | task=task-3de8207e-d0 |
| 56 | coverage_eval | task=task-3de8207e-d0 |
| 57 | intel_status | task=task-3de8207e-d0 |
| 58 | generate_package | task=task-3de8207e-d0 |
| 59 | intel_assess | task=task-3de8207e-d0 |
| 60 | intel_assess | task=task-3de8207e-d0 |
| 61 | intel_status | task=task-3de8207e-d0 |
| 62 | intel_challenge_start | round=1 points=3 |
| 63 | intel_challenge_confirm | round=1 resolutions=3 |
| 64 | coverage_eval | task=task-3de8207e-d0 |
| 65 | generate_package | task=task-3de8207e-d0 |
| 66 | intel_assess | task=task-3de8207e-d0 |
| 67 | intel_status | task=task-3de8207e-d0 |
| 68 | intel_challenge_start | round=2 points=2 |
| 69 | intel_challenge_start | round=2 points=2 |
| 70 | intel_challenge_confirm | round=2 resolutions=2 |
| 71 | coverage_eval | task=task-3de8207e-d0 |
| 72 | generate_package | task=task-3de8207e-d0 |
| 73 | intel_assess | task=task-3de8207e-d0 |
| 74 | intel_status | task=task-3de8207e-d0 |

### 工具调用分布
- web_fetch: 12
- web_search: 9
- document_read: 9
- document_search: 8
- evidence_save: 7
- coverage_eval: 5
- intel_status: 4
- intel_assess: 4
- fact_save: 3
- generate_package: 3
- intel_challenge_start: 3
- crawl_collect: 2
- intel_challenge_confirm: 2
- intel_plan: 1
- evidence_audit: 1
- fact_supersede: 1

### 重复/可疑调用
- 连续重复 coverage_eval: task=task-3de8207e-d0

## 任务最终状态
- stage: done  challenge_round: 2
- collection: {"search_attempts": 6, "search_stop_reason": "search_budget_exhausted", "fetch_attempts_since_evidence": 6, "evidence_count": 4, "stop_reason": "fetch_without_evidence"}
- outputs: package=True, assessment=True

## 最新覆盖快照
- level: insufficient  gap_score: 7  stop_reason: no_progress
- no_progress_rounds: 6
- Q[partial] 2026年低空经济投资与融资趋势: facts=1 covered=0
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「低空经济被列入国家"十五五规划"(2026-2030)建议中作为拟加速发展的战略性新兴产业集群。」的交叉验证来源（第 2 个独立来源组）
- Q[partial] 亿航智能商业化进展与订单情况: facts=2 covered=0
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 建议搜索「亿航智能入选香港"低空经济监管沙盒X"试验项目;其本地合作伙伴冠忠集团向香港民航处提交的沙盒飞行申请已获接受。」的交叉验证来源（第 2 个独立来源组）; 1 条引文只部分支持 Fact
    - F[partial] gap=3 srcs=0 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 2 条引文只部分支持 Fact

## 挑战轮次 1: confirmed converged=False
- [dismissed] evidence_gap: 关于'2026年低空经济投资与融资趋势'，未提供任何具体投资规模、融资额、基金或公司融资案例的数据；唯一事实仅涉及政策/
- [dismissed] evidence_gap: '亿航智能商业化进展与订单情况'核心的哈萨克斯坦EH216-S载人飞行仅由亿航公司自身来源（且为标题级、审核为parti
- [dismissed] recency: 亿航相关证据的发布时间多为2026年8月(哈萨克斯坦)与2026年1月(香港沙盒)，中国日报文章发布于2026年1月28
## 挑战轮次 2: confirmed converged=True
- [dismissed] evidence_gap: 第二轮：'2026年低空经济投资与融资趋势'仍无具体融资/投资规模数据，且唯一事实仅有1个独立来源组（chinadail
- [dismissed] evidence_gap: 第二轮：'亿航智能商业化进展与订单情况'的哈萨克斯坦EH216-S载人飞行证据仍为亿航单源且审核为partial，无法获

## 事实统计: 总 3（active 3 / superseded 0）
- 亿航智能入选香港"低空经济监管沙盒X"试验项目;其本地合作伙伴冠忠集团向香港民航处提交的沙盒飞行申请已获接受。
- 低空经济被列入国家"十五五规划"(2026-2030)建议中作为拟加速发展的战略性新兴产业集群。
- 2026年8月10日,亿航智能的EH216-S在哈萨克斯坦首都完成中亚地区首次无人驾驶载人eVTOL飞行。
