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
