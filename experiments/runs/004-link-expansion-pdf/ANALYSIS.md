# 实验分析: 004-link-expansion-pdf

- 主题: 低空经济
- 问题: 2026年低空经济投资与融资趋势; 亿航智能商业化进展与订单情况
- 耗时: 961.2s  exit=0
- git: 2eccf9d

## 工具调用轨迹（共 149 次）

| # | 工具 | 参数摘要 |
|---|------|----------|
| 1 | intel_plan | topic=低空经济（Low-Altitude Ec q=2 |
| 2 | web_search | q=2026年低空经济投资与融资趋势 n=5 |
| 3 | web_search | q=亿航智能商业化进展与订单情况 EHang n=5 |
| 4 | web_search | q=低空经济 2026 投资 市场规模 万亿 预测 n=5 |
| 5 | web_search | q=EHang 亿航智能 2025 订单 交付 商业化 n=5 |
| 6 | web_fetch | url=https://www.ehang.com/cn |
| 7 | web_search | q=低空经济 2026 投资 eVTOL 融资 亿元 n=5 |
| 8 | web_fetch | url=http://ir.ehang.com |
| 9 | web_search | q=亿航智能 EH216-S 订单 交付 架 2025年 n=5 |
| 10 | web_search | q=EHang EH216-S orders deliveries 2025 ear n=5 |
| 11 | web_fetch | url=https://ir.ehang.com/ |
| 12 | web_fetch | url=https://baijiahao.baidu.com/s?id=1868217835089792720 |
| 13 | web_fetch | url=https://www.ehang.com/cn/news.html |
| 14 | fact_save | q=q-0de07e4b-0c6a- stmt=根据中国电子技术标准化研究院数据，2024年中国低空经济规模达6,703亿元，同 |
| 15 | fact_save | q=q-b83ce2ad-6639- stmt=亿航EH216-S已在海外多地（哈萨克斯坦、瑞士、墨西哥、泰国等）开展载人飞行示 |
| 16 | evidence_save | doc=doc-d9b767e928bc rel=supports quote=根据中国电子技术标准化研究院数据，我国低空经济产业正处在快速 |
| 17 | evidence_save | doc=doc-291964f66968 rel=supports quote=亿航智能多款飞行器亮相春晚，16架EH216-S与22580 |
| 18 | evidence_save | doc=doc-291964f66968 rel=supports quote=中亚首次eVTOL载人飞行！亿航EH216-S在哈萨克斯坦首 |
| 19 | fact_save | q=q-b83ce2ad-6639- stmt=亿航智能EH216-S于2026年在哈萨克斯坦首都中心完成中亚首次eVTOL载人 |
| 20 | fact_save | q=q-b83ce2ad-6639- stmt=2026年央视春晚，16架亿航EH216-S载人eVTOL与22580架GD4. |
| 21 | fact_supersede | {"fact_id": "fact-6bceb41609f5a00d", "replacement_fact_ids": ["fact-13622ee3a478 |
| 22 | evidence_save | doc=doc-291964f66968 rel=supports quote=中亚首次eVTOL载人飞行！亿航EH216-S在哈萨克斯坦首 |
| 23 | evidence_save | doc=doc-291964f66968 rel=supports quote=亿航智能多款飞行器亮相春晚，16架EH216-S与22580 |
| 24 | web_fetch | url=https://www.news.cn/info/20260618/a178f39fc95e46a8b6d1fc5c2f |
| 25 | web_fetch | url=https://jingji.cctv.com/2026/06/08/ARTIyMrOEZS4nw33wQsdkcci2 |
| 26 | fact_save | q=q-0de07e4b-0c6a- stmt=CCTV报道称，"十五五"时期中国将把低空经济作为新兴支柱产业打造，飞行汽车（e |
| 27 | fact_save | q=q-b83ce2ad-6639- stmt=新华网报道，2026年6月17日亿航智能EH216-S无人驾驶载人航空器从大理喜 |
| 28 | evidence_save | doc=doc-c666f8176689 rel=supports quote="十五五"时期，我国将把低空经济作为新兴支柱产业进行打造，市 |
| 29 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 30 | evidence_save | doc=doc-c666f8176689 rel=supports quote=有望牵引万亿级至十万亿级产业集群 |
| 31 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 32 | evidence_audit | task=task-6ff68abf-8b |
| 33 | evidence_save | doc=doc-c666f8176689 rel=supports quote="十五五"时期，我国将把低空经济作为新兴支柱产业进行打造，市 |
| 34 | fact_save | q=q-0de07e4b-0c6a- stmt=央视网报道称，飞行汽车（eVTOL）有望牵引万亿级至十万亿级产业集群。 |
| 35 | evidence_save | doc=doc-c666f8176689 rel=supports quote=有望牵引万亿级至十万亿级产业集群 |
| 36 | fact_supersede | {"fact_id": "fact-f52e3bd1cf70a6b1", "replacement_fact_ids": ["fact-2400c351f60f |
| 37 | fact_save | q=q-0de07e4b-0c6a- stmt=乐居财经援引中国电子技术标准化研究院数据称，2024年中国低空经济规模达6,70 |
| 38 | evidence_save | doc=doc-d9b767e928bc rel=supports quote=根据中国电子技术标准化研究院数据，我国低空经济产业正处在快速 |
| 39 | fact_supersede | {"fact_id": "fact-e62de9185f643022", "replacement_fact_ids": ["fact-420d38ee5535 |
| 40 | evidence_audit | task=task-6ff68abf-8b |
| 41 | fact_save | q=q-b83ce2ad-6639- stmt=亿航智能EH216-S在哈萨克斯坦首都中心完成中亚首次eVTOL载人首飞。（来源 |
| 42 | fact_save | q=q-b83ce2ad-6639- stmt=央视春晚中，16架亿航EH216-S与22580架GD4.0无人机编队表演。（来 |
| 43 | fact_supersede | {"fact_id": "fact-13622ee3a4781ba9", "replacement_fact_ids": ["fact-d00a949cf0a2 |
| 44 | fact_supersede | {"fact_id": "fact-9809f48e10fde166", "replacement_fact_ids": ["fact-19b8fc759f6a |
| 45 | evidence_save | doc=doc-291964f66968 rel=supports quote=中亚首次eVTOL载人飞行！亿航EH216-S在哈萨克斯坦首 |
| 46 | evidence_save | doc=doc-291964f66968 rel=supports quote=亿航智能多款飞行器亮相春晚，16架EH216-S与22580 |
| 47 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 48 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能分别与雄飞智慧航空（大理）有限公司、空际全视线（云南 |
| 49 | evidence_audit | task=task-6ff68abf-8b |
| 50 | fact_save | q=q-b83ce2ad-6639- stmt=新华网报道，亿航智能EH216-S从大理喜洲古镇飞往双廊古镇用时10分钟飞越洱海 |
| 51 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 52 | fact_supersede | {"fact_id": "fact-0f14bd114973fa6e", "replacement_fact_ids": ["fact-99d9268e74f0 |
| 53 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 54 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能分别与雄飞智慧航空（大理）有限公司、空际全视线（云南 |
| 55 | evidence_audit | task=task-6ff68abf-8b |
| 56 | coverage_eval | task=task-6ff68abf-8b |
| 57 | evidence_save | doc=doc-c666f8176689 rel=supports quote=作为低空经济的核心赛道之一，飞行汽车（eVTOL），是面向空 |
| 58 | fact_save | q=q-b83ce2ad-6639- stmt=据新华网报道，亿航智能EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊古镇，用 |
| 59 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 60 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能分别与雄飞智慧航空（大理）有限公司、空际全视线（云南 |
| 61 | fact_supersede | {"fact_id": "fact-99d9268e74f07c7a", "replacement_fact_ids": ["fact-b57383cfb11b |
| 62 | evidence_audit | task=task-6ff68abf-8b |
| 63 | web_fetch | url=http://app.caacmedia.cn/zixun/toutiao/202602/t20260217_13934 |
| 64 | fact_save | q=q-b83ce2ad-6639- stmt=《中国民航报》报道，2026年2月16日亿航智能旗下亿航白鹭在合肥骆岗公园完成2 |
| 65 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=2月16日，在中央广播电视总台2026年春节联欢晚会合肥分会 |
| 66 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=2月16日，在中央广播电视总台2026年春节联欢晚会合肥分会 |
| 67 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=22580架新一代编队无人机GHOSTDRONE 4.0（简 |
| 68 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=当晚，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机 |
| 69 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=当晚，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机 |
| 70 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=刷新了全球无人机编队飞行表演架次纪录，并获得“单台电脑控制最 |
| 71 | evidence_audit | task=task-6ff68abf-8b |
| 72 | coverage_eval | task=task-6ff68abf-8b |
| 73 | fact_save | q=q-b83ce2ad-6639- stmt=新华网报道，亿航智能EH216-S无人驾驶载人航空器从大理喜洲古镇飞往双廊古镇， |
| 74 | fact_save | q=q-b83ce2ad-6639- stmt=新华网报道，亿航智能分别与雄飞智慧航空（大理）有限公司、空际全视线（云南）科技有 |
| 75 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 76 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能分别与雄飞智慧航空（大理）有限公司、空际全视线（云南 |
| 77 | fact_supersede | {"fact_id": "fact-b57383cfb11ba144", "replacement_fact_ids": ["fact-6dacc8f6ee78 |
| 78 | evidence_save | doc=doc-c666f8176689 rel=supports quote=飞行汽车是低空经济实现从工业级无人机"生 |
| 79 | fact_save | q=q-0de07e4b-0c6a- stmt=央视网报道称，飞行汽车（eVTOL）是低空经济的核心赛道之一，是面向空地一体化交 |
| 80 | evidence_save | doc=doc-c666f8176689 rel=supports quote=作为低空经济的核心赛道之一，飞行汽车（eVTOL），是面向空 |
| 81 | fact_supersede | {"fact_id": "fact-2400c351f60fdd83", "replacement_fact_ids": ["fact-610ae932c9fd |
| 82 | fact_save | q=q-b83ce2ad-6639- stmt=《中国民航报》报道，2026年2月16日亿航智能旗下亿航白鹭在合肥骆岗公园完成2 |
| 83 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=当晚，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机 |
| 84 | fact_supersede | {"fact_id": "fact-e405715978fc81b4", "replacement_fact_ids": ["fact-b4d39195de12 |
| 85 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=当晚，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机 |
| 86 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=刷新了全球无人机编队飞行表演架次纪录，并获得“单台电脑控制最 |
| 87 | evidence_audit | task=task-6ff68abf-8b |
| 88 | coverage_eval | task=task-6ff68abf-8b |
| 89 | intel_status | task=task-6ff68abf-8b |
| 90 | generate_package | task=task-6ff68abf-8b |
| 91 | intel_assess | task=task-6ff68abf-8b |
| 92 | fact_save | q=q-b83ce2ad-6639- stmt=新华网报道，亿航智能EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊古镇，用时 |
| 93 | fact_save | q=q-b83ce2ad-6639- stmt=《中国民航报》报道，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机GHO |
| 94 | fact_supersede | {"fact_id": "fact-6dacc8f6ee78810f", "replacement_fact_ids": ["fact-3815b5b268a3 |
| 95 | fact_supersede | {"fact_id": "fact-b4d39195de12756c", "replacement_fact_ids": ["fact-a1243d6607f4 |
| 96 | evidence_save | doc=doc-9fe51175c24b rel=supports quote=亿航智能 EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊 |
| 97 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=当晚，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机 |
| 98 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=刷新了全球无人机编队飞行表演架次纪录，并获得“单台电脑控制最 |
| 99 | evidence_audit | task=task-6ff68abf-8b |
| 100 | intel_assess | task=task-6ff68abf-8b |
| 101 | fact_save | q=q-b83ce2ad-6639- stmt=《中国民航报》报道，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机GHO |
| 102 | fact_save | q=q-b83ce2ad-6639- stmt=《中国民航报》报道，亿航白鹭刷新全球无人机编队飞行表演架次纪录，并获得"单台电脑 |
| 103 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=当晚，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机 |
| 104 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=刷新了全球无人机编队飞行表演架次纪录，并获得“单台电脑控制最 |
| 105 | fact_supersede | {"fact_id": "fact-a1243d6607f47c7e", "replacement_fact_ids": ["fact-f70692948733 |
| 106 | evidence_audit | task=task-6ff68abf-8b |
| 107 | intel_assess | task=task-6ff68abf-8b |
| 108 | intel_assess | task=task-6ff68abf-8b |
| 109 | generate_package | task=task-6ff68abf-8b |
| 110 | intel_status | task=task-6ff68abf-8b |
| 111 | generate_package | task=task-6ff68abf-8b |
| 112 | coverage_eval | task=task-6ff68abf-8b |
| 113 | generate_package | task=task-6ff68abf-8b |
| 114 | intel_assess | task=task-6ff68abf-8b |
| 115 | intel_challenge_start | round=None points=0 |
| 116 | intel_challenge_start | round=1 points=3 |
| 117 | web_fetch | url=https://world.people.com.cn/n1/2026/0303/c1002-40673274.html |
| 118 | web_fetch | url=http://ir.ehang.com/news-events/press-releases |
| 119 | evidence_save | doc=doc-6a4cfbce3744 rel=supports quote=2026年央视春晚合肥分会场的舞台...2026年央视春晚合 |
| 120 | evidence_save | doc=doc-6a4cfbce3744 rel=supports quote=在电视屏幕前，丽雅和亿万中国观众一起见证亿航智能16架EH2 |
| 121 | fact_save | q=q-b83ce2ad-6639- stmt=人民日报海外版报道，亿航智能EH216-S已在全球21个国家完成超过8万架次安全 |
| 122 | fact_save | q=q-b83ce2ad-6639- stmt=《中国民航报》报道，2026年2月16日亿航白鹭在合肥骆岗公园完成22580架新 |
| 123 | evidence_save | doc=doc-6a4cfbce3744 rel=supports quote=工作人员还为我讲解过它的"硬核履历"，已在全球21个国家完成 |
| 124 | evidence_save | doc=doc-6a4cfbce3744 rel=supports quote=已在全球21个国家完成超8万架次安全飞行，在合肥骆岗公园也已 |
| 125 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=2月16日，在中央广播电视总台2026年春节联欢晚会合肥分会 |
| 126 | evidence_save | doc=doc-bc1e07ca2350 rel=supports quote=当晚，亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机 |
| 127 | evidence_audit | task=task-6ff68abf-8b |
| 128 | coverage_eval | task=task-6ff68abf-8b |
| 129 | intel_challenge_confirm | round=1 resolutions=3 |
| 130 | coverage_eval | task=task-6ff68abf-8b |
| 131 | generate_package | task=task-6ff68abf-8b |
| 132 | intel_assess | task=task-6ff68abf-8b |
| 133 | intel_assess | task=task-6ff68abf-8b |
| 134 | intel_status | task=task-6ff68abf-8b |
| 135 | intel_challenge_start | round=2 points=2 |
| 136 | web_fetch | url=https://huacheng.gz-cmc.com/pages/2026/04/30/705825e9250f469 |
| 137 | fact_save | q=q-b83ce2ad-6639- stmt=广州日报报道，亿航智能已集齐全球首个无人驾驶载人eVTOL型号合格证、生产许可证 |
| 138 | evidence_save | doc=doc-61705eb05ec8 rel=supports quote=亿航智能已集齐全球首个无人驾驶载人eVTOL型号合格证、生产 |
| 139 | evidence_audit | task=task-6ff68abf-8b |
| 140 | intel_challenge_confirm | round=2 resolutions=2 |
| 141 | fact_save | q=q-b83ce2ad-6639- stmt=广州日报报道，亿航智能已集齐全球首个无人驾驶载人eVTOL型号合格证、生产许可证 |
| 142 | evidence_save | doc=doc-61705eb05ec8 rel=supports quote=亿航智能已集齐全球首个无人驾驶载人eVTOL型号合格证、生产 |
| 143 | fact_supersede | {"fact_id": "fact-84187f1f76432e83", "replacement_fact_ids": ["fact-e3f9b739c757 |
| 144 | evidence_audit | task=task-6ff68abf-8b |
| 145 | coverage_eval | task=task-6ff68abf-8b |
| 146 | generate_package | task=task-6ff68abf-8b |
| 147 | intel_assess | task=task-6ff68abf-8b |
| 148 | intel_status | task=task-6ff68abf-8b |
| 149 | intel_status | task=task-6ff68abf-8b |

### 工具调用分布
- evidence_save: 48
- fact_save: 25
- fact_supersede: 14
- evidence_audit: 12
- web_fetch: 11
- intel_assess: 8
- web_search: 7
- coverage_eval: 7
- generate_package: 6
- intel_status: 5
- intel_challenge_start: 3
- intel_challenge_confirm: 2
- intel_plan: 1

## 任务最终状态
- stage: challenge  challenge_round: 2
- collection: {"search_attempts": 6, "search_stop_reason": "search_budget_exhausted", "fetch_attempts_since_evidence": 0, "evidence_count": 36, "stop_reason": null}
- outputs: package=True, assessment=True

## 最新覆盖快照
- level: insufficient  gap_score: 20  stop_reason: None
- no_progress_rounds: 0
- Q[partial] 2026年低空经济投资与融资趋势: facts=2 covered=0
    - F[partial] gap=2 srcs=1 hq=0 recent=1 uncf=0 独立来源组不足; 高质量独立来源组不足
    - F[partial] gap=2 srcs=1 hq=0 recent=1 uncf=0 独立来源组不足; 高质量独立来源组不足
- Q[partial] 亿航智能商业化进展与订单情况: facts=9 covered=1
    - F[covered] gap=0 srcs=2 hq=1 recent=1 uncf=0 
    - F[partial] gap=1 srcs=1 hq=1 recent=1 uncf=0 独立来源组不足
    - F[partial] gap=3 srcs=0 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 2 条引文只部分支持 Fact
    - F[partial] gap=3 srcs=0 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足; 1 条引文只部分支持 Fact
    - F[partial] gap=2 srcs=1 hq=0 recent=1 uncf=0 独立来源组不足; 高质量独立来源组不足
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足
    - F[partial] gap=1 srcs=1 hq=1 recent=1 uncf=0 独立来源组不足
    - F[partial] gap=2 srcs=1 hq=0 recent=1 uncf=0 独立来源组不足; 高质量独立来源组不足
    - F[partial] gap=2 srcs=1 hq=0 recent=0 uncf=0 独立来源组不足; 高质量独立来源组不足

## 挑战轮次 1: confirmed converged=False
- [dismissed] source_bias: q1两条事实均仅单一来源组：市场规模【6703亿元/2026破万亿】仅来自乐居财经转述中国电子技术标准化研究院，缺第二独
- [dismissed] missing_data: 关键问题要求订单情况，但现有证据全部为商业化场景展示（洱海飞行、哈萨克斯坦首飞、春晚编队、吉尼斯纪录），无具体订单数量、
- [addressed] source_bias: 亿航哈萨克斯坦首飞与春晚编队事实仅依赖亿航官网企业自述（低质量来源），无独立第三方交叉验证，存在企业宣传口径偏差风险。
## 挑战轮次 2: confirmed converged=False
- [dismissed] missing_data: q2仍缺乏具体订单/交付量化数据；前一轮已dismiss，缺口仍存在于事实层面。
- [dismissed] source_bias: q1市场规模（6703亿/2026破万亿）与eVTOL核心赛道两条事实仍为单一来源，无法交叉验证，投资融资趋势研判的证据

## 事实统计: 总 25（active 11 / superseded 14）
- 央视网报道称,飞行汽车(eVTOL)是低空经济的核心赛道之一,是面向空地一体化交通的电动垂直起降航空器。
- 乐居财经援引中国电子技术标准化研究院数据称,2024年中国低空经济规模达6,703亿元,同比增长32%,预计2026年有望突破万亿元,202
- 央视春晚中,16架亿航EH216-S与22580架GD4.0无人机编队表演。(来源:亿航官网新闻动态)
- 亿航智能EH216-S在哈萨克斯坦首都中心完成中亚首次eVTOL载人首飞。(来源:亿航官网新闻动态)
- 新华网报道,亿航智能EH216-S无人驾驶载人航空器从喜洲古镇飞往双廊古镇,用时10分钟飞越洱海,亿航物流航空器同步完成配送飞行。
- 《中国民航报》报道,亿航白鹭刷新全球无人机编队飞行表演架次纪录,并获得"单台电脑控制最多无人机同时升空"的吉尼斯世界纪录认证。
- 新华网报道,亿航智能分别与雄飞智慧航空(大理)有限公司、空际全视线(云南)科技有限公司进行合作签约,共同推进大理低空经济高质量发展。
- 《中国民航报》报道,亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机GHOSTDRONE 4.0同时升空。
- 《中国民航报》报道,2026年2月16日亿航白鹭在合肥骆岗公园完成22580架新一代编队无人机GHOSTDRONE 4.0同时升空,亮相20
- 人民日报海外版报道,亿航智能EH216-S已在全球21个国家完成超过8万架次安全飞行,并在合肥骆岗公园开展常态化试运行。
- 广州日报报道,亿航智能已集齐全球首个无人驾驶载人eVTOL型号合格证、生产许可证、标准适航证以及运营合格证,构建起低空载人领域合规壁垒,正在
