# 待办清单（TODO）

> 语境：新引擎已合并进 main，前端研究闭环已重连真实后端。以下为尚未完成的能力与收尾项。

## P0 — 前端功能补齐（当前仍 mock）

- [ ] **Monitor 监测闭环**
  - [ ] 后端：`monitors` / `monitor_runs` / `monitor_changes` 表 + 定时调度（`runNow` 即时触发一轮）
  - [ ] 端点：`GET/POST /api/monitors`、`GET /api/monitors/{id}`、`POST /api/monitors/{id}/toggle`、`POST /api/monitors/{id}/run`
  - [ ] 前端：`client.ts` 的 `monitors/monitor/createMonitor/toggleMonitor/runMonitorNow` 换真 HTTP（`use-monitors.ts` 签名不变）

- [ ] **FactCheck 事实核验闭环**
  - [ ] 后端：`fact_checks` / `fact_evidence` 表 + 核验逻辑（LLM 判定 claim 支持度 → verdict/evidence_sufficiency）
  - [ ] 端点：`GET/POST /api/fact-checks`、`GET /api/fact-checks/{id}`
  - [ ] SSE：`FactCheckEvent`（timeline/evidence/verdict/refetch）
  - [ ] 前端：`client.ts` + `use-fact-check-stream.ts`（`subscribeFactCheck` → 真实 SSE）

- [ ] **MediaJob 媒体闭环**
  - [ ] 后端：`media_jobs` 表 + 上传 → ASR 转写 → 事实/证据抽取（复用已接好的 whisper 后端）
  - [ ] 端点：`GET/POST /api/media-jobs`、`GET /api/media-jobs/{id}`
  - [ ] SSE：`MediaEvent`（segment/fact/evidence/status/refetch）
  - [ ] 前端：`client.ts` + `use-media-stream.ts`（`subscribeMedia` → 真实 SSE）

- [ ] **Library 完整化**
  - [ ] 当前 `/api/library` 仅返回 `research`；`monitors`/`factChecks` 待 P0 前三项落地后补全

## P1 — 配置 CRUD（当前后端 501 占位）

- [ ] **搜索源管理**
  - [ ] `POST /api/search-sources`（add）、`/toggle`、`PATCH /api/search-sources/{id}`（cookies 更新）
  - [ ] cookies/凭据走环境变量或加密存储，不落明文；实现 Provider 配置的运行时读写

- [ ] **AI 工具管理**
  - [ ] `POST /api/ai-search-tools/{id}/toggle`、`PATCH .../api-key`（api_key 走环境变量）
  - [ ] `ai_search_tools()` 目前只返回 exa/brave/tavily 静态骨架，需接入真实 Provider 配置

## P2 — 测试与健壮性

- [ ] **SSE 自动化 HTTP 测试**
  - [ ] TestClient 对无限流会挂起；用真实异步客户端或特殊处理，为 `GET /api/conversations/{id}/events` 补自动化测试（当前仅 EventBus 单测 + 手动冒烟）

- [ ] **arXiv 直连限流**
  - [ ] 已加抓取重试与向量降级；直连仍周期性被 arXiv 限流。评估更稳健的出站/缓存策略（多 Provider 均衡、结果缓存）

- [ ] **回归测试缺口**
  - [ ] A01：新增 Provider 只改 Adapter/注册/配置的回归测试
  - [ ] A03：域名/语言等能力不支持时的 `UNSUPPORTED_FILTER` 测试

## P3 — 规格收尾（继承自原 refactor 计划）

- [ ] **浏览器出口隔离（A06）**
  - [ ] `deploy/research-browser/`（compose.yaml / Dockerfile / squid.conf / egress.nft / start.ps1）+ 受控出口实测

- [ ] **字幕 / 帧 OCR 真实样本**
  - [ ] 带字幕轨视频样本（测字幕路径）、`video_frame_ocr=true` 的样本（测帧 OCR 路径）；更新 `tests/fixtures/manifest.json`

## P4 — 文档

- [ ] **文档同步**
  - [ ] README / `docs/reports/search-agent-refactor-status.md`：补新 conversation API 面、前端联调说明（dev server 代理 8000、启动顺序）
