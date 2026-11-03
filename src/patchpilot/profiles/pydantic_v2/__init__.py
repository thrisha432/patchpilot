"""Pydantic v1 -> v2 migration profile."""

from __future__ import annotations

from pathlib import Path

from patchpilot.profiles.base import Profile
from patchpilot.profiles.pydantic_v2.detector import detect

PROFILE = Profile(
    name="pydantic-v2",
    title="Pydantic v1 -> v2",
    detect=detect,
    guides_dir=Path(__file__).parent / "guides",
    target_image="patchpilot-sandbox:pydantic-v2",
    source_image="patchpilot-sandbox:pydantic-v1",
    # Pydantic v2 still *runs* most v1 code through deprecated shims. Turning its
    # deprecation warnings into errors is what makes "tests pass" mean "migrated".
    pytest_args=("-W", "error::pydantic.warnings.PydanticDeprecatedSince20"),
    system_hint=(
        "The target environment has pydantic 2.x and pydantic-settings installed. "
        "Deprecated v1 APIs count as failures, even though v2 still accepts some of them."
    ),
)
