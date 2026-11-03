"""Registry of migration profiles."""

from __future__ import annotations

from patchpilot.profiles.base import Profile


def get_profile(name: str) -> Profile:
    if name == "pydantic-v2":
        from patchpilot.profiles.pydantic_v2 import PROFILE

        return PROFILE
    raise KeyError(f"unknown migration profile {name!r}; available: {', '.join(available())}")


def available() -> list[str]:
    return ["pydantic-v2"]


__all__ = ["Profile", "available", "get_profile"]
