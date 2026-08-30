# Contract: Workbench Security

## Web Exposure

- 为方便本地和局域网开发，默认 host MUST 为 `0.0.0.0`。
- 默认无认证开发启动 MUST 输出醒目的网络暴露警告，且文档 MUST 提示不得直接暴露到公网。
- 配置 bearer token 后，全部 `/api`、SSE 和资源下载请求 MUST 认证。
- 生产或外网暴露 MUST 配置 bearer token 和可信 Host，或由受信反向代理提供等价保护；未知 Host 返回 400。
- system status 只返回 capability/configured 布尔值，不返回密钥或敏感路径。
- CORS 不是认证机制；直接 HTTP 请求必须受到同样保护。

## URL Admission

每个初始 URL、redirect、browser request 和 archive fallback MUST：

1. 只允许 HTTP/HTTPS，拒绝 userinfo。
2. 解析 hostname 或 literal IP。
3. 将 `IPv6Address.ipv4_mapped` 归一化为 IPv4。
4. 要求每个解析地址为 global；拒绝 loopback、private、link-local、CGNAT、multicast、reserved、documentation 和 metadata 地址。
5. 实际连接到已验证地址，保留原 hostname 作为 Host/TLS SNI。

验证后又按 hostname 重新解析的 HTTP fallback MUST 默认关闭或删除。若以后保留，必须证明实际连接仍固定到已验证 IP。

## External Response Limits

- document、search provider、SearXNG 和公开搜索 HTML 在解析前流式读取。
- 读取到 `max_bytes + 1` 立即中止并返回明确错误。
- crawler link parser 使用 set 去重，并在达到配置上限后停止收集。
- RunCreate、ResearchScope、问题/URL列表、SSE retained events 和终态 Run 数量必须有硬上限。
- 单个 provider 超限只造成该渠道 degraded，不阻断其他渠道。

## Agent Authorization

- AgentDeps 由服务器注入 `bound_task_id` 和 `run_id`。
- Task-scoped 工具从 deps 推导 Task；兼容参数与绑定不同时返回 `INVALID_INPUT`。
- Fact、Evidence、Document、Plan、Checkpoint 和 Report 的 task ownership 在领域函数/StateStore 中验证，不依赖系统提示或 UUID 难猜。
- 外部网页、搜索标题、snippet 和 provider extra 是不可信数据；不得改变工具权限或 Task binding。

## Secrets and URLs

- 模型和搜索密钥只从环境变量读取。
- API key、Authorization、Cookie、token 和 secret 不得进入模型参数、trace、SSE、日志、状态或报告。
- 对包含 `token`、`key`、`signature` 等敏感查询参数的 URL，公开信息模式应拒绝；若业务必须访问，则仅在内存使用原值，所有持久化/日志/报告使用统一脱敏 URL。

## Required Regression Cases

1. literal、DNS answer、redirect 和 browser request 均拒绝 IPv4-mapped loopback/private/metadata 地址。
2. DNS 首次 public、第二次 private 时不会产生第二个 hostname-resolved 连接。
3. 超限正文最多读取 `limit + 1` 字节。
4. 默认 host 为 `0.0.0.0` 且无认证启动会输出警告；启用认证后所有受保护路径无 token 返回 401，错误 Host 返回 400。
5. 绑定 Task A 的 Agent 对 Task B 及其资产的所有读写被拒绝。
6. trace、SSE、文档 metadata、日志和报告不包含测试 secret。
