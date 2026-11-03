"""A migration profile bundles everything specific to one library migration.

The pipeline (analyze -> retrieve -> patch -> validate -> repair) is generic;
a profile supplies the detector, the documentation, the sandbox images, and
how tests must be run for "migrated" to mean something.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from patchpilot.analyzer.parser import ParsedFile
from patchpilot.models import Finding

DetectFn = Callable[[list[ParsedFile]], tuple[list[Finding], list[str]]]


@dataclass(frozen=True)
class Profile:
    name: str
    title: str  # "Pydantic v1 -> v2"
    detect: DetectFn
    guides_dir: Path
    target_image: str  # sandbox image with the *target* library version
    source_image: str  # sandbox image with the *source* version (benchmark task validation)
    # Extra pytest arguments. For Pydantic: deprecation warnings are errors, so
    # code that merely still *runs* on v2 through compatibility shims fails.
    pytest_args: tuple[str, ...] = ()
    system_hint: str = ""
