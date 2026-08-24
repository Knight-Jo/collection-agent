# JS 动态网页采集部署说明

## 启用方式

动态网页采集是可选能力。安装 Python 依赖和与 Playwright 匹配的 Chromium：

```bash
mamba activate collection-agent-pydantic
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev --extra browser
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run playwright install chromium
```

在 `config.yaml` 中开启：

```yaml
fetch:
  enable_browser_fallback: true
  browser_network_mode: validated
  browser_timeout_seconds: 15
  browser_max_requests: 40
  browser_max_bytes: 20971520
  browser_concurrency: 1
```

系统仍先使用静态 HTTP 抓取。只有 HTML 被识别为空壳、JavaScript 占位页或无正文的前端挂载页面时才启动 Chromium。PDF、Office、图片和音视频不经过浏览器。

`GET /api/system` 返回 Playwright、Chromium、开关和网络模式状态。Python 包存在但 Chromium 未安装时，`playwright=true`、`chromium=false`；需要浏览器的资源会保留静态原件并标记提取不可用。

## 网络模式

`validated` 模式在 Playwright 发出请求前复用应用的公网 URL 校验，阻断非 HTTP(S)、本机名、私网、链路本地、保留地址和云元数据地址。这适合开发环境及已有可信出站边界的受控环境。

应用层检查与 Chromium 实际 DNS 连接之间仍存在时间差，不能彻底消除 DNS rebinding。因此，面向任意不可信公网网页的生产环境必须额外提供网络层隔离，并把配置声明为：

```yaml
fetch:
  browser_network_mode: isolated
```

`isolated` 是部署声明，不会替代防火墙。发布前必须验证渲染进程：

- 使用非 root 用户并保持 Chromium sandbox 开启；程序会显式启用 sandbox，宿主不支持时失败关闭，不会自动降级为 `--no-sandbox`；
- 不共享宿主网络命名空间；
- 出站防火墙同时拒绝 IPv4 和 IPv6 的回环、RFC 1918、CGNAT、链路本地、IPv6 ULA、组播、保留网段和云元数据地址；
- 不得访问同一容器网络中的数据库、模型网关、SearXNG 管理端或其他内部服务；
- 文件系统只读，仅挂载任务专用临时目录；
- 配置 CPU、内存、进程数和执行时间限制；
- 使用适合 Chromium sandbox 的 seccomp 配置；
- 启动检查必须证明公网测试地址可访问，同时宿主地址、私网测试地址和元数据地址不可访问。

Playwright 官方容器镜像包含浏览器和系统依赖，但官方明确提示它本身不是访问不可信网页的完整安全边界。不能以“运行在容器中”代替上述非 root、sandbox、seccomp 和出站控制。

## 请求与反爬边界

首版允许 Chromium 正常执行公开页面 JavaScript、重定向、Cookie、XHR/Fetch、HTTP/2 和无需交互的 JavaScript/Cookie Challenge。Cookie 只保留在当前页面的临时 BrowserContext 中，不跨资源或任务复用。

以下行为会被阻断或标记为不可用：

- 登录、账号 Cookie 导入和付费墙绕过；
- POST 等可能产生外部写操作的请求；
- WebSocket、EventSource 和页面下载；
- 弹窗、新窗口和 iframe 文档，避免未纳入主页面计费会话的旁路下载；
- 图形验证码、滑块、Turnstile、reCAPTCHA 等交互式挑战；
- 打码平台、住宅代理、代理池轮换、stealth 插件和浏览器指纹伪装；
- 站点 robots.txt 明确拒绝的主文档。

无需输入的 JavaScript Challenge 可以由真实 Chromium 自然完成。检测到需要用户点击或输入的挑战时，资源记录 `CHALLENGE_REQUIRED`，系统不会反复重试或把挑战页文字作为证据。

## 资源与归档

每个页面受渲染超时、请求数、下载字节和 DOM 大小限制。下载字节通过 Chromium DevTools 网络事件流式累计，超限即关闭页面；失败、超时和取消前已接收的字节仍计入任务预算。递归采集还受任务总字节、URL 数、深度、全局并发、单域并发和单域延迟限制。任务取消会关闭 BrowserContext；同一采集调用中的页面复用一个 Chromium 进程，结束后关闭进程。

服务器返回的主文档地址和内容始终保存到 `final_url` 与 `raw_path`。浏览器重定向或前端路由后的地址保存到 `rendered_url`，JavaScript 执行后的 DOM 单独保存到 `rendered_path`，原始内容和渲染内容分别记录 SHA-256。正文和动态发现的链接来自渲染 DOM；只有正文提取完整且哈希校验通过的文档才能进入证据链。

## 验收检查

```bash
curl -s http://127.0.0.1:6780/api/system
```

确认返回的 `browser` 对象中 `enabled`、`playwright`、`chromium` 均为 `true`，生产环境的 `network_mode` 为 `isolated`。随后使用一个正文由 JavaScript 写入空挂载节点的公开测试页运行采集，并确认：

1. 文档 `collection_method` 为 `browser`；
2. `raw_path` 与 `rendered_path` 均存在且哈希校验通过；
3. 渲染正文可通过 `document_read` 读取；
4. 动态生成的公开链接可进入递归队列；
5. 私网、元数据和交互式验证码测试地址均无法成为证据。
