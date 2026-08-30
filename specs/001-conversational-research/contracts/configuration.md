# Contract: AI-native Search Configuration

## YAML Shape

```yaml
search:
  ai_native:
    exa:
      enabled: false
      api_key_env: EXA_API_KEY
      # base_url: https://api.exa.ai
      # rate_limit: 1.0
      # max_results: 10
      # cache_ttl: 3600
      # timeout_seconds: 15
    brave:
      enabled: false
      api_key_env: BRAVE_SEARCH_API_KEY
      # base_url: https://api.search.brave.com
      # rate_limit: 1.0
      # max_results: 10
      # cache_ttl: 3600
      # timeout_seconds: 15
    tavily:
      enabled: false
      api_key_env: TAVILY_API_KEY
      # base_url: https://api.tavily.com
      # rate_limit: 1.0
      # max_results: 10
      # cache_ttl: 3600
      # timeout_seconds: 15

fetch:
  enable_httpx_fallback: false

web:
  host: 0.0.0.0
  port: 6780
  auth_token_env: null
  trusted_hosts: []
```

## Rules

- 三个 Adapter 默认关闭，避免默认配置产生外部费用。
- 生产验收必须显式启用至少一个 Adapter，并设置其环境变量。
- `api_key_env` 是环境变量名，YAML 中不得出现真实密钥。
- 单个 Adapter 缺失密钥不会阻止应用启动；首次调研将其标记为 degraded，并继续其他渠道。
- `base_url` 只用于官方 endpoint、测试 server 或明确配置的可信代理，不接受来自用户消息或模型工具参数的 URL。
- `max_results`、timeout、rate limit 和 cache TTL 应受 Pydantic 字段约束。
- 环境变量值不得出现在 `/api` 响应、SSE、日志、trace、report 或 persisted task state。
- `enable_httpx_fallback` 默认 false；只有实际连接仍固定到已验证 IP且流式限额时才可启用。
- `web.host` 为方便开发默认 `0.0.0.0`。未配置 `auth_token_env` 时允许启动，但必须输出未认证网络暴露警告。
- 配置 `auth_token_env` 后，其环境变量必须存在，全部 API、SSE 和资源下载都必须验证 bearer token。
- 生产或外网暴露必须配置认证及非空、无通配符的 `trusted_hosts`；也可由受信反向代理执行等价认证与 Host 校验。
- Web bearer token 与模型/搜索密钥遵守相同的日志和持久化禁令。

## Deployment Acceptance

部署方应在不暴露密钥值的前提下验证：

1. 默认 Web 监听 `0.0.0.0`，无认证时启动日志包含明确警告；生产配置下未认证请求返回 401，错误 Host 返回 400。
2. 不安全 httpx fallback 保持关闭。
3. 至少一个 enabled Adapter 的环境变量存在。
4. 该 Adapter 能对固定 smoke query 返回带 provider provenance 的结果。
5. 关闭或破坏其中一个 Adapter 后，其他搜索渠道仍能完成请求。
6. 搜索结果只进入候选列表，报告引用来自随后归档的原始文档。
