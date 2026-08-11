# Source Architecture

`src/intel_agent` 是公开来源情报收集代理的 Python 包。依赖方向保持单向：入口层调用代理编排层，编排层组合搜索、抓取和领域工作流，领域模块最终通过存储层持久化数据。

```text
main → agent → search/fetch → task/fact/evidence
                              ↓
                    audit/conflicts/coverage
                              ↓
                    package/assess/challenge
                              ↓
                           storage
```

## Module Responsibilities

| 文件 | 主要功能 |
| --- | --- |
| `__init__.py` | 暴露包版本以及主要配置、依赖和代理构建接口。 |
| `__main__.py` | 支持通过 `python -m intel_agent` 启动 CLI。 |
| `agent.py` | 配置 Pydantic AI Agent、系统提示词、依赖对象和 15 个工具。 |
| `assess.py` | 校验结构化结论并生成研判报告。 |
| `audit.py` | 使用独立 judge 审核事实与支持证据之间的语义关系。 |
| `challenge.py` | 创建、确认和收敛红队挑战轮次。 |
| `config.py` | 定义 Pydantic 配置模型并加载 YAML、环境变量。 |
| `conflicts.py` | 登记、验证和消解相互冲突的证据。 |
| `coverage.py` | 计算问题及事实覆盖度，判断充分性与停止条件。 |
| `document_extract.py` | 解码响应正文，从 HTML、PDF、DOCX 中提取文本、日期和外链。 |
| `evidence.py` | 保存、加载和校验证据以及引文行号。 |
| `fact.py` | 管理事实生命周期、替换关系和循环检测。 |
| `fetch.py` | 执行安全网络抓取、重定向校验、HTTP 解析及文档归档；继续重新导出提取函数以兼容既有调用方。 |
| `main.py` | 解析 CLI 参数、构造任务提示词并运行 Agent。 |
| `runner.py` | 定义任务输入、统一提示词，并向 CLI 与 Web 推送 Agent 事件。 |
| `models.py` | 集中定义任务、事实、证据、审核、覆盖度等 Pydantic 模型。 |
| `package.py` | 将事实、审核结果和来源信息生成 Markdown 证据包。 |
| `search.py` | 适配 Bing、百度、百度新闻和 SearXNG，合并、排序搜索结果；继续重新导出查询辅助函数。 |
| `search_queries.py` | 分词、宽泛查询检测、相似度判断及查询词变体生成。 |
| `security.py` | 阻止私网 URL，执行 DNS 解析校验和来源域归组。 |
| `source.py` | 按域名识别政府、媒体、百科、社交等来源类型。 |
| `storage.py` | 提供安全路径、原子文件写入、JSON 读写和 SHA-256 完整性校验。 |
| `task.py` | 管理任务、预算、阶段转换、输出绑定和状态摘要。 |
| `web/` | 提供 FastAPI API、单进程运行注册表、SSE 进度和前端读模型。 |

新增模块时，应保持职责单一，避免从底层模块反向导入 `agent.py` 或 `main.py`。公共函数迁移后，应在原模块保留重新导出，避免破坏现有调用方。
