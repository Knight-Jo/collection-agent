# Agent.md

## Python 环境管理

本仓库采用 **conda/mamba 提供 Python 运行时 + uv 管理依赖** 的混合方案：

- **Python 运行时**：conda 环境 `collection-agent-pydantic`（Python 3.12）
- **依赖管理**：uv，以 `pyproject.toml` + `uv.lock` 为唯一事实来源
- 依赖被安装进 conda 环境而非 `.venv`，通过 `UV_PROJECT_ENVIRONMENT` 指定

### 日常命令

```bash
# 激活环境
mamba activate collection-agent-pydantic

# 安装/同步所有依赖（激活环境后执行）
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync

# 新增依赖（如 pydantic-ai-openai）
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv add <package>

# 移除依赖
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv remove <package>

# 运行脚本
python xxx.py
```

### 环境初始化（仅首次）

```bash
mamba create -n collection-agent-pydantic python=3.12 -y
UV_PROJECT_ENVIRONMENT=/home/guandewei/.conda/envs/collection-agent-pydantic uv sync
```

### 注意事项

- 不要用 `pip install` 直接装包，改动会丢失且不在 lock 文件中
- conda 环境内的 `setuptools`/`pip` 等 conda 包可能被 uv 卸载，属正常现象
- uv 自动生成 `uv.lock` 并提交到 git，保证可复现

## 情报收集智能体（pydantic-ai）

`src/intel_agent/` 是对 `pi-prototype-collection`（Pi 框架 / TypeScript）的 Python 移植，
使用 pydantic-ai 实现同样的 15 个工具、证据链数据模型、预算上限与阶段门控。

### 运行

```bash
mamba activate collection-agent-pydantic
export DEEPSEEK_API_KEY=<你的 key>   # 或配置其他 model.api_key_env

python -m intel_agent --topic "低空经济投资进展" \
  --questions "2026年融资规模" "头部企业商业化进展" "政策监管动态" \
  --config config.yaml --min-sources 2 --min-quality 1 --recency 90
```

### 配置

复制 `config.example.yaml` 为 `config.yaml` 并按需修改：

- `model`：主 agent 模型（默认 DeepSeek deepseek-chat，OpenAI 兼容 API）
- `audit_model`：语义审核独立模型（默认同主模型），审核结果不可重复抽样
- `search.searxng_url`：本地 SearXNG 地址，设为 `null` 则只用 Bing/Baidu 直连
- `budgets`：搜索/抓取预算上限（默认 6/6，与原项目一致）

### 测试

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
```

