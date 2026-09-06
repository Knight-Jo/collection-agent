"""API route package (spec 002 §2.1)."""

from .settings import router as settings_router
from .workspace import router as workspace_router

__all__ = ["settings_router", "workspace_router"]
