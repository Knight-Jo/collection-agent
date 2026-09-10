# 待办清单

> 2026-09-09 按当前源码核对。这里只保留未完成或未验证事项，不重复列出已接通的功能。
> 详细要求见 [基础引擎规格](specs/2026-09-05-search-agent-design.md) 与
> [监测、核验、媒体规格](specs/002-monitor-factcheck-media/spec.md)；规格目标不等于已验收能力。

## 安全与配置边界

- [ ] 浏览器受控出口与自动回退：当前只支持显式 browser 获取；补齐子资源、重定向、私网出口阻断与真实隔离验收（A06/A07），见[部署说明](docs/development/js-dynamic-page-deployment.md)。
- [ ] 配置凭证安全：设置接口已可用且读取脱敏，但提交的 Key/Cookie 仍写入 SQLite JSON；补齐安全存储，不能把“只写字段”当作静态加密。
- [ ] 运行配置冻结与自定义来源：按 spec 002 核对配置 revision 的原子性、运行中策略隔离；自定义来源目前仅登记，`executable=false`，不是新增可执行 Provider。

## 回归与真实环境验收

- [ ] SSE HTTP 测试：补会话事件流的连接、断开和清理检查；现有 EventBus 测试不能替代 HTTP 流测试。
- [ ] Provider 契约：补新增 Provider 扩展边界（A01）与不支持过滤条件的 `UNSUPPORTED_FILTER`（A03）回归。
- [ ] 真实媒体样本：补带字幕轨视频、帧 OCR、中文扫描件与真实 Office 材料；检查 `tests/fixtures/manifest.json` 中实际文件、语言及定位标注，不能将 authored 样本或跳过项视作真实验收通过。
- [ ] Windows/POSIX 分别验证取消、子进程树及临时资源回收（A16）；历史 Linux 结果不能代替 Windows 验收。
- [ ] arXiv 出站限流：以可复现运行评估重试、缓存和多来源策略，不把历史限流当作当前所有环境的固定结论。
- [ ] 对照 spec 002 逐项核验持久入队、恢复、幂等、原子基线、引用与核验质量；已有接口及调度器不代表完整规格通过。

## 文档收敛

- [ ] 逐篇核对重构前的架构长文、建设方案和演示稿；保留仍有效的设计约束，删除被替代内容。当前实现从 [README](README.md) 和 [CONTEXT](CONTEXT.md) 开始，历史报告中的测试数量及能力判断只适用于其记录版本。
