# JS 动态网页采集设计

## 目标

在现有公开信息调研流程中补充 JavaScript 动态网页采集能力，使 Agent 能够读取依赖前端渲染、XHR/Fetch 请求或 JavaScript Cookie 挑战的公开页面，并继续复用现有正文提取、递归链接发现、原件归档、证据审核和调研报告生成能力。

本设计面向无需登录即可访问的公开网页。浏览器允许直接访问公网，以保留真实 Chromium 的协议、Cookie、重定向和脚本执行行为；浏览器必须与主机和内网隔离，不能访问回环、局域网、链路本地地址、云元数据地址或非 HTTP(S) 协议。

## 为什么允许浏览器直接访问公网

静态抓取器代理浏览器全部请求虽然可以完整复用 DNS pinning，但会改变真实浏览器行为：HTTP/2、缓存、Cookie、跨域请求、压缩、内容协商和部分前端挑战都可能失效，还需要重新实现浏览器的请求语义。它会降低动态网页覆盖率，并产生一套难以维护的代理层。

浏览器直接访问公网更符合“尽可能广泛采集公开信息”的目标。安全问题不通过削弱浏览器功能解决，而通过两层边界解决：

1. Playwright 在每个请求发出前校验协议、目标主机和解析地址，阻断明确的非公网请求。
2. 生产环境把 Chromium 放入独立渲染沙箱，由网络层阻断私网和主机访问，消除 DNS rebinding 在校验与连接之间的时间差风险。

仅使用 Playwright 请求拦截不能完全替代网络隔离，因为校验后的域名仍可能在 Chromium 实际连接时解析到不同地址。因此，未启用网络隔离的本机模式只用于受控开发和测试，生产配置不得静默降级到该模式。

## 本轮范围

首版交付以下能力：

1. 静态 HTML 正文为空、明显过少或显示 JavaScript 占位提示时，自动使用 Chromium 重新采集。
2. Agent 定向 `web_fetch` 和递归 `crawl_collect` 使用相同的动态渲染判断和渲染器。
3. 支持页面脚本、样式表、公开 XHR/Fetch、重定向和当前页面上下文内的临时 Cookie。
4. 允许真实浏览器自然通过无需用户交互的 JavaScript/Cookie 挑战。
5. 渲染后的 DOM 继续进入现有 HTML 提取、链接发现、哈希、引文和材料推荐流程。
6. 保存服务器原始 HTML 和渲染后 DOM，能够区分静态采集与浏览器采集。
7. 继续执行 robots、任务取消、并发、域名间隔、请求数量、时间和字节预算。

首版不支持：

- 登录、账号 Cookie 导入和跨任务浏览器状态复用；
- 第三方验证码打码服务、OCR 猜测验证码、滑块自动化或人工接管；
- 指纹伪装、代理池轮换、住宅代理和隐藏自动化特征；
- 绕过付费墙、访问控制或站点明确拒绝的自动采集；
- 自动填写或提交业务表单；
- 无限滚动、复杂点击路径和通用浏览器操作规划。

图形、滑块、Turnstile、reCAPTCHA 等交互式挑战记录为 `challenge_required`。只有能够由 Chromium 正常执行页面脚本并自行完成的非交互挑战才属于首版兼容范围。

## 总体流程

```text
搜索结果或递归 URL
  → 现有 DNS-pinned 静态抓取
  → 内容类型与安全检查
  → 静态 HTML 提取
  → 动态页面判定
      ├─ 正文有效：沿用静态结果
      └─ 正文无效：提交隔离 Chromium
          → 公网直连并执行 JavaScript
          → 请求与响应预算控制
          → DOM 稳定或到达超时
          → 保存渲染后 HTML
          → 复用现有 HTML 提取和链接发现
  → 归档、证据审核、材料评价和报告
```

静态抓取始终优先。普通 HTML、PDF、Office、图片、音频和视频不启动浏览器，避免增加延迟和资源消耗。

## 动态页面判定

新增一个无网络副作用的共享判断函数。仅当响应为 HTML 且满足以下任一情况时建议渲染：

- 提取正文为空，同时页面包含脚本或前端挂载节点；
- 正文明显少于页面标题、导航和脚本结构所反映的内容量；
- 出现“enable JavaScript”“正在加载”等典型占位提示；
- 页面存在 `app`、`root`、`__next` 等挂载节点且节点内无有效正文。

判断结果包含机器可读原因，如 `empty_body`、`javascript_required` 或 `app_shell`。首版使用少量稳定信号，不维护框架专用解析器。静态提取已有完整正文时不因页面包含 React、Vue 或 Next.js 脚本而启动浏览器。

浏览器渲染失败后不得循环回退。该资源保留静态归档，并把动态提取失败原因写入采集状态。

## 浏览器渲染器

使用 Playwright 异步 Python API 和 Chromium。一个任务运行期间复用浏览器进程，每个页面使用新的非持久化 BrowserContext；页面完成或取消后关闭上下文，Cookie、缓存和本地存储不跨资源复用。

上下文配置：

- JavaScript 启用；
- Service Worker 禁用，确保网络请求能够被观察和校验；
- 不接受下载，不授予摄像头、麦克风、定位、通知或剪贴板权限；
- 不忽略 TLS 证书错误；
- 使用 Chromium 默认 User-Agent，不加载 stealth 补丁或伪造浏览器指纹；
- 设置中文和英文语言偏好；
- 弹窗和新窗口默认关闭，允许同页正常导航。

渲染器等待主文档达到 `DOMContentLoaded`，随后观察 DOM 变更，在短暂稳定后读取 `page.content()`；整个渲染过程仍受硬超时约束。不使用 `networkidle`，避免分析埋点、长轮询和流式连接导致无限等待。

图片、字体和音视频网络响应默认不为正文渲染而下载，但 DOM 中发现的图片和媒体 URL仍作为普通采集候选进入现有队列，由多媒体处理器单独下载和提取。若页面脚本依赖特定资源才能生成正文，后续根据真实失败样本调整阻断策略。

## 网络与安全边界

浏览器请求拦截执行以下检查：

1. 仅允许 `http` 和 `https`，阻断 `file`、`data` 导航、`ftp`、浏览器内部协议和本地文件访问。
2. 对主文档、脚本、样式表、XHR、Fetch 和重定向目标调用现有公网地址解析规则；首版直接阻断 iframe 文档。
3. 阻断回环、私网、链路本地、保留地址、Unix socket 和云元数据目标。
4. 禁用 Service Worker，阻断 WebSocket 和 EventSource，避免未纳入首版预算的长连接。
5. 阻断非安全浏览方法。主文档只允许 GET；页面自动产生的 POST 默认阻断，避免采集过程产生外部写操作。
6. 每次主文档重定向继续检查 robots。站点被 robots 拒绝时不启动浏览器。

生产渲染沙箱必须：

- 使用非 root 用户和 Chromium sandbox；
- 禁止访问宿主网络命名空间；
- 在网络层拒绝 IPv4/IPv6 私网、回环、链路本地和云元数据网段；
- 只挂载只读运行文件和任务专用临时目录；
- 限制 CPU、内存、进程数和执行时间；
- 任务取消或超时时终止浏览器上下文，进程失去响应时终止浏览器进程。

Playwright 官方镜像不能直接视为不可信网页的安全边界；生产部署需要独立非 root 用户、Chromium sandbox、seccomp 和网络出站限制。

## 简单反爬兼容范围

首版允许以下兼容行为：

- 使用真实 Chromium 执行 JavaScript；
- 接受页面在当前隔离上下文中设置的临时 Cookie；
- 正常处理公开页面重定向、HTTP/2、内容协商和跨域资源；
- 对 429 和瞬时 5xx 沿用现有有限重试及 `Retry-After`；
- 等待无需点击或输入的 JavaScript Challenge 自然完成；
- 识别常见挑战页，并将未通过原因结构化记录。

首版不把交互式验证码称为“简单验证码”并自动破解。这样既避免主动规避站点访问控制，也避免引入验证码供应商、代理池、指纹维护和不可审计的外部数据流。真实实验若证明某类公开站点大量受同一种非登录挑战影响，再单独评估合规的站点适配器。

## 预算与调度

浏览器渲染继续占用当前 URL 的爬虫并发槽和域名并发槽，不另建调度系统。增加以下配置：

```yaml
fetch:
  enable_browser_fallback: false
  browser_concurrency: 1
  browser_timeout_seconds: 15
  browser_max_requests: 40
```

其余限制复用现有 `max_html_bytes`、`max_total_bytes`、`per_host_concurrency` 和 `per_host_delay_seconds`。浏览器收到的响应按响应事件累计字节；无法读取实际正文大小时使用响应头估算并在 DOM 大小上再次执行硬限制。超过任一限制立即关闭页面并标记 `skipped_limit`。

首版只开放一个浏览器并发，避免 Chromium 与 OCR、转写并行时耗尽本机资源。真实运行证明吞吐不足后再调高，不增加浏览器池抽象。

## 归档与数据模型

`IntelDocument` 增加向后兼容字段：

- `collection_method`: `http` 或 `browser`，默认 `http`；
- `rendered_url`: 浏览器完成重定向或前端路由后的 URL；
- `rendered_path`: 可选的渲染 DOM 路径；
- `rendered_sha256`: 可选的渲染 DOM SHA-256。

`final_url`、`raw_path` 和 `raw_sha256` 始终指向服务器返回的原始主文档。浏览器渲染时，将浏览器最终地址写入 `rendered_url`，将 `page.content()` 单独写入 `rendered_path`，正文和链接从渲染 DOM 提取。浏览器文档 ID 同时包含规范 URL、原始响应哈希、浏览器最终地址和渲染 DOM 哈希，避免浏览器重定向或前端路由后把原始字节错误归因。

`CrawlEntry` 增加可选的 `render_reason` 和 `render_error`，任务详情可以显示为什么启动浏览器以及失败原因。历史 JSON 缺少这些字段时继续使用默认值，无需迁移。

动态页面缓存继续使用现有任务缓存 TTL。服务器 ETag 只能验证 HTML 外壳，不能保证动态 API 数据未变化，因此浏览器文档过期后必须重新渲染，不能仅凭主文档 304 永久复用旧 DOM。

## 现有模块接入

- `fetch.py`：静态抓取完成后调用共享动态判定；定向抓取需要时调用渲染器。
- `crawl.py`：在 HTML 静态提取为不可用时调用同一渲染器；继续使用原队列、robots、缓存和 SSE 状态。
- `extract.py`：不增加浏览器逻辑，只接收渲染 HTML 并复用现有 HTML 提取和链接发现。
- `models.py`：增加向后兼容的采集方式和渲染归档字段。
- `config.py`：增加最少的浏览器开关和资源上限。
- `web/app.py`：`/api/system` 报告 Playwright、Chromium 和生产网络隔离配置状态。

不新增 Agent 工具。`web_fetch` 和 `crawl_collect` 内部自动选择静态或浏览器路径，避免模型需要理解底层渲染参数。

## 状态与错误

新增稳定错误原因：

- `browser_unavailable`：Playwright 或 Chromium 未安装；
- `browser_isolation_unavailable`：生产模式缺少所需网络隔离；
- `render_timeout`：页面未在预算内稳定；
- `render_limit`：请求数、响应字节或 DOM 大小超限；
- `challenge_required`：检测到需要人工交互的验证码或挑战；
- `unsafe_browser_request`：页面尝试访问被禁止的目标；
- `render_empty`：脚本执行后仍无有效正文。

动态渲染失败不删除静态原件。只有渲染正文通过现有提取状态和完整性校验后，才能作为证据支持报告事实。

## 测试与验收

后端测试覆盖：

- 有效静态 HTML 不启动浏览器；
- 空壳 SPA 自动触发浏览器并提取渲染正文；
- 动态生成的页面链接进入递归队列；
- 原始 HTML 与渲染 DOM 分别保存并验证哈希；
- 同一逻辑同时作用于定向抓取和深度抓取；
- 私网主文档、私网 iframe、重定向、XHR 和脚本请求被阻断；
- `file:`、WebSocket、EventSource、POST 和下载被阻断；
- robots 拒绝时不启动浏览器；
- 请求数、字节、超时和浏览器并发上限有效；
- 任务取消关闭页面、上下文和浏览器子进程；
- 非交互 JavaScript Challenge 可以自然完成；
- 交互式验证码标记为 `challenge_required`；
- 浏览器缺失或生产隔离缺失时明确降级；
- 历史文档和爬虫 JSON 继续读取；
- 渲染失败的材料不能创建证据。

测试使用本地假站点和 Playwright mock 隔离外网。生产隔离另提供启动前自检，验证渲染沙箱无法连接宿主、私网和云元数据地址。完成后运行 Ruff、Pyright、pytest、Python 构建及 Bun 前端测试、类型检查和构建。

## 实施顺序

1. 增加动态页面判定、渲染结果模型和单元测试。
2. 增加 Playwright 可选依赖与最小 Chromium 渲染器。
3. 接入定向抓取，完成原始 HTML/渲染 DOM 双归档。
4. 接入递归采集，复用 robots、队列、预算、取消和 SSE。
5. 增加生产渲染沙箱及启动安全自检。
6. 增加系统状态、任务资源展示和运维文档。
7. 使用已有实验主题执行新一轮基线，统计动态页面成功率、额外耗时、挑战页比例和新增有效材料数，再决定是否支持站点交互或 POST 型公开 API。

本轮不建设通用浏览器 Agent。只有真实实验明确显示“需要点击或滚动才能获得高价值公开信息”时，才新增受限交互动作。

## 参考资料

- [Playwright Python Library](https://playwright.dev/python/docs/library)
- [Playwright Network](https://playwright.dev/python/docs/network)
- [Playwright BrowserContext](https://playwright.dev/python/docs/api/class-browsercontext)
- [Playwright Docker](https://playwright.dev/python/docs/docker)
