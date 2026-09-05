"""Shared backend base: controlled resource access."""

from __future__ import annotations

from abc import abstractmethod

from ..models import Backend, BackendRequest, BackendOutput


class BaseBackend(Backend):
    def __init__(self, resource_store) -> None:
        self.resource_store = resource_store

    def read_bytes(self, resource_id: str) -> bytes:
        with self.resource_store.open(resource_id) as fh:
            return fh.read()

    def blob_path(self, resource_id: str):
        return self.resource_store.blob_path(resource_id)

    @abstractmethod
    async def run(self, request: BackendRequest) -> BackendOutput: ...
