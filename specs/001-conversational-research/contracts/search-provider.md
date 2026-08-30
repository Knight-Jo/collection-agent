# Contract: AI-native Search Provider

## Purpose

定义 Exa、Brave、Tavily 及未来搜索工具接入现有搜索 Module 的最小 Interface。该契约是应用内部 Adapter 契约，不改变 Web API。

## Interface

```python
class SearchProvider(Protocol):
    metadata: ProviderMetadata

    async def search(
        self,
        client: httpx.AsyncClient,
        request: SearchRequest,
    ) -> list[SearchResult]: ...
```

Adapter MUST：

1. 使用调用方提供的 AsyncClient，不自行创建未关闭的 client。
2. 将官方响应映射到现有 SearchResult，保留 provider provenance。
3. 只返回合法的公开 `http`/`https` URL；后续 fetch 仍执行 SSRF 和公开地址验证。
4. 遵守 `max_results`，不因供应商默认值返回无限结果。
5. 不把 answer、summary、snippet、highlight 或 raw content 标记为已归档证据。
6. 不在异常、结果、日志或 `extra` 中包含 API key、Authorization 或订阅 token。
7. 对无效响应抛出可归类异常；组合层负责降级，不在 Adapter 内吞掉所有错误。
8. 在解析 JSON/HTML 前流式执行响应字节上限；不得先读取完整 body 再检查大小。

## Provider Mapping

### Exa

- Endpoint: 官方 Search API。
- Auth: `x-api-key`，值来自配置指定的环境变量。
- Query: 映射 `query`、结果数量、时间/域名过滤；搜索类型使用部署默认值，不让 Agent 任意选择计费级别。
- Result: `title`、`url`、可用的 published date/author/score；文本或 highlight 仅作为 snippet。

### Brave

- Endpoint: 官方 Web Search API。
- Auth: `X-Subscription-Token`，值来自环境变量。
- Query: 映射 `q`、`count`、语言和支持的 freshness/filter。
- Result: 映射 web results 的 title/url/description、age 或 page age 元数据。

### Tavily

- Endpoint: 官方 Search endpoint。
- Auth: Bearer API key，值来自环境变量。
- Query: 映射 query、max_results、search_depth 和已验证的时间/域名过滤。
- Result: 映射 title/url/content/score；`answer` 和 raw content 不直接成为 Evidence。

## Composition Contract

通用 `web_search` MUST：

1. 从配置构建本次可用 Adapter 集合；disabled 或缺失密钥的 Adapter 不发请求。
2. 与现有可用国内外公开渠道并发搜索，并复用运行预算。
3. 使用现有规范化 URL 逻辑跨渠道去重。
4. 记录实际产生结果的渠道和安全的降级原因。
5. 单个渠道超时、401/403、429、5xx、解析失败或空结果时继续其他渠道。
6. 所有渠道都无结果时返回空结果和可操作的错误信息，不伪造结果。
7. 返回候选后仍要求 Agent 调用现有 fetch/archive 流程；不得由组合层直接创建 Fact 或 Evidence。

## Admission Contract

- 当前匿名 Provider 的静态 admission 规则保持不变。
- AI-native Adapter 必须显式启用，并且其 `api_key_env` 在运行时存在，才可加入 credentialed 调用集合。
- 允许 credentialed 的路径不得成为所有 Provider 的全局默认值。
- 付费/配额行为必须在配置文档说明；系统不得在缺省配置下静默产生第三方费用。

## Error Semantics

| Condition | Adapter/Composition behavior | User-visible effect |
|---|---|---|
| Disabled | Skip without HTTP call | 不视为运行错误 |
| Missing key | Mark provider degraded | 展示配置缺口，其他渠道继续 |
| 401/403 | Mark authentication failure | 不输出 token，其他渠道继续 |
| 429 | Mark rate-limited | 本次降级；遵守现有重试/预算策略 |
| Timeout/5xx | Mark temporary failure | 其他渠道继续，可在续研重试 |
| Invalid JSON/schema | Mark invalid response | 不返回半解析、无 provenance 结果 |
| Empty results | Valid empty outcome | 继续其他查询或披露覆盖缺口 |

## Compatibility

- Agent-visible tool name and primary input fields remain unchanged。
- Existing `results` and `engineUsed` fields remain available；`degraded` 为向后兼容的新增字段。
- 本 Provider 契约自身不要求数据库迁移；committed-state 加固另见 [committed-state.md](./committed-state.md)。
- Existing anonymous and vertical Providers continue to pass their admission tests。
