"""Network policy and fetch service tests (T05)."""

from __future__ import annotations

import asyncio

import pytest

from intel_agent.contracts.errors import DomainError
from intel_agent.contracts.resources import FetchRequest
from intel_agent.fetch.security import is_public_address, validate_public_url
from intel_agent.fetch.service import FetchService
from intel_agent.runtime.config import FetchConfig


async def test_private_resolution_is_rejected():
    async def resolver(host):
        return ["127.0.0.1"]

    with pytest.raises(DomainError) as raised:
        await validate_public_url("https://source.example/report", resolver)
    assert raised.value.code == "UNSAFE_URL"


async def test_scheme_and_credentials_are_rejected():
    async def resolver(host):
        return ["93.184.216.34"]

    with pytest.raises(DomainError):
        await validate_public_url("file:///etc/passwd", resolver)
    with pytest.raises(DomainError):
        await validate_public_url("https://user:pass@example.org/x", resolver)


def test_public_address_classification():
    assert is_public_address("93.184.216.34")
    assert not is_public_address("127.0.0.1")
    assert not is_public_address("10.0.0.1")
    assert not is_public_address("192.168.1.1")
    assert not is_public_address("169.254.169.254")
    assert not is_public_address("::1")
    assert not is_public_address("::ffff:127.0.0.1")


def test_local_hostnames_are_rejected():
    async def run():
        async def resolver(host):
            return ["93.184.216.34"]

        with pytest.raises(DomainError):
            await validate_public_url("https://localhost/x", resolver)
        with pytest.raises(DomainError):
            await validate_public_url("https://foo.localhost/x", resolver)

    asyncio.run(run())


async def test_unsafe_url_from_transport(material_store, resource_store):
    from intel_agent.fetch.transport import build_client

    async def resolver(host):
        return ["127.0.0.1"]

    client = build_client(resolver=resolver)
    service = FetchService(client, resource_store, FetchConfig())
    with pytest.raises(DomainError) as raised:
        await service.fetch(FetchRequest(url="https://source.example/report"))
    assert raised.value.code == "UNSAFE_URL"
    await client.aclose()
