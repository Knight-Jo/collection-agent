# 实验 007 — cross-verify-with-gaps（本地修改后首跑）

- 主题: 低空经济（同 001-006，控制变量）
- 变更（用户基于 006 的本地修改 90aef6e）: ① document_search 工具（检索已归档语料）；② with_gaps
  完成状态（挑战未收敛可合法 done）；③ nav/footer 链接 relevance 惩罚 + 空正文拒绝；
  ④ 多媒体链接发现（img/audio/video 入队 + attachment 优先级 5→20）；⑤ 百度跳转桩 fetchable=False；
  ⑥ COVERAGE_STALE 守卫；⑦ --max-turns 映射 request_limit
- 耗时: **1176s（20 分钟）**，exit=0，58 次模型请求（3.2M tokens）
- 注: 首跑因 harness 默认 `--max-turns 40` 被映射为 request_limit=40 提前耗尽（40 请求在 collect 烧完），
  清理后以 `--max-turns 200` 重跑成功。

## 核心成果（对比 006）

| 维度 | 006 | 007 | 说明 |
|------|-----|-----|------|
| **终态** | challenge 卡死 | ✅ **stage=done, exit=0** | 首次走完全程！ |
| **completion_status** | - | "sufficient"（⚠️ 标签误导，见问题） | |
| **document_search** | 不存在 | ✅ **调用 8 次** | 交叉验证工具被采纳 |
| **挑战死锁** | 无 | ✅ 2 start → 2 confirm 一次成功 | 持续稳定 |
| **gap_score** | 29 | **7**（历史最优） | 但见问题④ |
| 空正文页 | 大量 nav/404 完整页 | ✅ 0 篇（全部 complete/unavailable 有明确状态） | 空正文拒绝生效 |
| 证据/事实 | 40 / 16 | 4 / 3 | ⚠️ 大幅下降 |

## 暴露的问题

### P0 — 语料被图片与垃圾外链淹没（48 篇中 26 篇是图片）
多媒体链接发现（本地修改）把爬取页面上的**所有** img 标签全部入队：
- 26 篇 image/png+jpg：eh216_f.png（亿航机型图，有价值）混着 Spotify logo、Disney
  EpicUniverse 宣传图、马来肾脏病文章配图、签证页面图标等
- attachment 优先级 5→20 使图片**抢先**消耗 50 个队列槽位与下载预算
- **根因 1**: `enqueue_url` 无 relevance 门槛 — relevance=0 也照单全收，只影响排序
- **根因 2**: **tesseract 未安装**（`which tesseract` → not found）→ 26 张图片全部
  `unavailable`，OCR 管道完全失效；ffmpeg 有、whisper 未见实际调用

### P1 — 垃圾外链升级：推荐栏/侧栏链接绕过 nav 惩罚
nav/footer 惩罚只对 header/footer 容器生效，但随机外文页进入语料：
- "Themenparks in Orlando"（迪士尼）、"Tanda Buah Pinggang Rosak"（马来肾脏病）、
  "BLS Spain Visa"（西班牙签证）——来自某抓取页的侧栏"相关文章"/广告链接
- 这类链接不在 nav/header/footer 容器内，relevance 惩罚不生效

### P1 — 语料 48 篇却只产出 3 个事实
语料质量过低（26 图片 + 外文垃圾 + 百度首页），可用正文文档仅 ~10 篇；
agent 用 document_search 8 次 + document_read 9 次筛选后只找到 3 个可存事实，
转而用 web_fetch（12 次）救火 → COLLECTION_BUDGET_EXHAUSTED（6 次无新证据）。

### P2 — completion_status 标签语义错误
挑战 r2 converged=True（全部 dismissed + accepted_partial）→ 标记 "sufficient"，
但 coverage level=insufficient、gap=7。**挑战收敛 ≠ 证据充分**。
应改为：coverage level==sufficient → "sufficient"，否则一律 "with_gaps"。

### P3 — harness --max-turns 与 request_limit 映射冲突
`--max-turns 40` 默认值被 runner 映射为 `request_limit=min(config, max_turns)`，
把 config 的 200 压成 40，首跑 40 请求即崩。harness 默认值需对齐（改为不传或 200）。

## 007 结论

**流程完整性达成**（done + exit 0 + 工具采纳 + 无死锁），但**语料质量成为新瓶颈**：
多媒体发现与无门槛入队叠加，把爬虫从"情报收集"变成了"页面资产下载器"。
gap=7 的历史最优是"事实稀少"的假象——语料越干净、事实越少、分数越低。

## 008 建议（候选）

1. **P0 安装 tesseract + chi_sim**（`mamba install tesseract` + 中文语言包）— OCR 管道才能活
2. **P0 enqueue 门槛**：relevance < 阈值的链接不入队（只提升已有条目的 priority）；
   图片入队需满足 relevance > 0 或来自高相关页面
3. **P0 图片过滤**：小尺寸/图标类（< 20KB 或已知 logo/CDN 域名）跳过；限制图片占总队列比例
4. **P1 容器惩罚扩展**：aside/related-articles/ad 容器链接惩罚（extract.py _LinkParser）
5. **P2 completion_status 修正**：coverage sufficient → "sufficient"；否则 "with_gaps"
6. **P3 harness 默认 max-turns 对齐**（不传或 200）
