"""intel_agent package — pydantic-ai port of pi-prototype-collection."""

from .config import Settings, load_config
from .agent import AgentDeps, build_agent

__all__ = ["Settings", "load_config", "AgentDeps", "build_agent"]
__version__ = "0.1.0"
