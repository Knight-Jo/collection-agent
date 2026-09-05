"""Backend registry (spec §5, §8.1)."""

from __future__ import annotations

from ..contracts.errors import DomainError
from .models import Backend, BackendDescriptor


class BackendRegistry:
    """Explicit registration of extraction backends; no import side effects."""

    def __init__(self) -> None:
        self._backends: dict[str, Backend] = {}

    def register(self, backend_id: str, backend: Backend) -> None:
        if backend_id in self._backends:
            raise DomainError(
                "INVALID_REQUEST",
                f"backend already registered: {backend_id}",
                stage="extraction",
            )
        self._backends[backend_id] = backend

    def get(self, backend_id: str) -> Backend:
        backend = self._backends.get(backend_id)
        if backend is None:
            raise DomainError(
                "BACKEND_UNAVAILABLE",
                f"unknown backend: {backend_id}",
                stage="extraction",
            )
        return backend

    def list_capabilities(self) -> list[BackendDescriptor]:
        return [
            BackendDescriptor(
                backend_id=backend_id,
                version=backend.version,
                capabilities=list(backend.capabilities),
                supported_media_types=list(backend.media_types),
                availability=backend.availability(),
            )
            for backend_id, backend in sorted(self._backends.items())
        ]

    def available(self, backend_id: str) -> bool:
        backend = self._backends.get(backend_id)
        return backend is not None and backend.availability() == "available"
