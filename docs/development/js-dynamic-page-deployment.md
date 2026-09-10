# JS 动态网页采集：当前能力与部署边界

> 2026-09-09 按当前 FetchService / BrowserFetcher 核对。浏览器渲染已接入，
> 自动回退与完整网络出口隔离尚未实现；本页不作为生产安全验收证明。

## 安装与调用

在项目 Python 3.12 环境安装可选依赖及匹配的 Chromium：

```bash
mamba activate collection-agent-pydantic
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev --extra browser
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run playwright install chromium
```

当前 [FetchService](../../src/intel_agent/fetch/service.py) 仅在
`FetchRequest.mode="browser"` 时调用注入的
[BrowserFetcher](../../src/intel_agent/fetch/browser.py)。其他模式走 HTTP；
HTTP 获取到空壳页面不会自动转入浏览器。普通研究任务不能仅靠安装 Playwright
就被视作已启用动态网页回退。

旧说明中的 `enable_browser_fallback`、`browser_network_mode`、
`browser_max_requests` 和 `browser_max_bytes` 不属于当前配置模型，
不得继续用这些字段宣称能力已开启。

## 已有行为

- 对入口 URL 执行公网地址校验，然后用 Chromium 加载页面并获取渲染后的 DOM。
- 页面加载使用请求中的超时；DOM 编码后按资源大小限制写入 ResourceStore。
- 保存请求 URL、最终 URL 和渲染 HTML 资源，返回 `FetchResult.method="browser"`。
- 页面加载结束或失败后关闭浏览器。

当前没有旧版 `raw_path/rendered_path` 双文件契约，也没有基于渲染结果的递归
链接队列。DOM 保存时的大小检查不等于浏览器所有网络请求的累计下载限额。

## 未完成的安全边界

入口 URL 校验不覆盖 Chromium 后续自行建立的所有连接，也不能证明
子资源、重定向、DNS 重绑定、WebSocket 或下载均受控。当前实现没有提供
受控代理、出口防火墙或完整的请求拦截规则。

不要将当前浏览器直接用于可访问内部服务、凭证或敏感文件的环境中处理任意
不可信网页。生产使用前必须提供并验证独立网络隔离、受限出站、最小文件访问、
Chromium sandbox 与资源限制；隔离失败时应拒绝运行，而不是回退直连。
这些仍是交付前置要求，不是已经实现的保障。

## 验证范围

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/e2e/test_browser_render.py -m real_backend -q
```

该测试访问公开静态页面，只证明浏览器能返回 HTML 快照，不证明 JS 空壳自动
回退或出口隔离。缺依赖或跳过测试不能计为通过。
`GET /api/system` 当前没有浏览器就绪状态，CLI 的 `preflight` 也不能替代真实
浏览器启动与网络隔离检查。完整要求见[基础引擎规格](../../specs/2026-09-05-search-agent-design.md)。
