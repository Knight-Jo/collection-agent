"""Agent layer: role-based research agents on pydantic-ai."""

from .models import build_model
from .roles import build_roles

__all__ = ["build_model", "build_roles"]
