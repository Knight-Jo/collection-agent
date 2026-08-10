"""Security tests: private address blocking, URL validation."""

import pytest

from intel_agent.models import IntelError
from intel_agent.security import is_public_address, resolve_public_url, source_group_of


def test_public_address_blocklist():
    assert not is_public_address("127.0.0.1")
    assert not is_public_address("10.0.0.5")
    assert not is_public_address("192.168.1.1")
    assert not is_public_address("172.16.0.1")
    assert not is_public_address("169.254.1.1")
    assert not is_public_address("::1")
    assert not is_public_address("fe80::1")
    assert not is_public_address("2001:db8::1")
    assert not is_public_address("100.64.0.1")
    assert is_public_address("8.8.8.8")
    assert is_public_address("1.1.1.1")


@pytest.mark.asyncio
async def test_resolve_public_url_rejects_bad_inputs():
    with pytest.raises(IntelError) as e:
        await resolve_public_url("file:///etc/passwd")
    assert e.value.code == "UNSAFE_URL"

    with pytest.raises(IntelError) as e:
        await resolve_public_url("https://user:pass@example.com/")
    assert e.value.code == "UNSAFE_URL"

    with pytest.raises(IntelError) as e:
        await resolve_public_url("https://localhost/x")
    assert e.value.code == "UNSAFE_URL"

    with pytest.raises(IntelError) as e:
        await resolve_public_url("https://foo.local/x")
    assert e.value.code == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_resolve_public_url_blocks_private_resolution():
    async def fake_resolver(hostname):
        return ["10.0.0.5"]

    with pytest.raises(IntelError) as e:
        await resolve_public_url("https://evil.example.com/", resolver=fake_resolver)
    assert e.value.code == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_resolve_public_url_accepts_public():
    async def fake_resolver(hostname):
        return ["93.184.216.34"]

    url, addresses = await resolve_public_url("https://example.com/a?b=1", resolver=fake_resolver)
    assert addresses == ["93.184.216.34"]


def test_source_group_of():
    assert source_group_of("https://www.example.com/news/1") == "example.com"
    assert source_group_of("https://news.people.com.cn/x") == "people.com.cn"
    with pytest.raises(IntelError):
        source_group_of("https://127.0.0.1/x")
