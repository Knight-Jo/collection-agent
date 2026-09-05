"""Fetch package: SSRF-safe HTTP transport and acquisition (spec §7)."""

from .security import is_public_address, validate_public_url

__all__ = ["is_public_address", "validate_public_url"]
