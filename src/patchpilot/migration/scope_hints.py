"""Where a repair may edit, beyond the findings: the code the failing tests point at.

Round 0 edits are confined to the analyzer's findings (and imports). That is
what keeps a model from "improving" unrelated code. But some failures live
elsewhere: a deprecated call the analyzer could not see, or a lookup table
whose v1 error-message keys no longer match. During repair the failing tests
are the evidence, so the scope widens to exactly what they implicate:

1. lines named in a failing test's traceback (in the file being repaired);
2. the definitions of functions/classes that failing tests import from that
   file and use, plus the module-level names those definitions read.

Anything else stays out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from tree_sitter import Node

from patchpilot.analyzer.parser import end_line, parse, start_line, text, walk
from patchpilot.migration.edits import LineRange
from patchpilot.models import ValidationResult

_FRAME = re.compile(r"^(?P<path>[\w./-]+\.py):(?P<line>\d+):", re.M)


def _module_name(path: str) -> str:
    p = PurePosixPath(path)
    parts = [*p.parent.parts, p.stem]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _test_file(nodeid: str) -> str | None:
    """JUnit classname "tests.test_api::test_x" -> "tests/test_api.py"."""
    head = nodeid.split("::", 1)[0]
    if not head or head.startswith("<"):
        return None
    return head.replace(".", "/") + ".py"


def _imported_names(test_source: bytes, module: str) -> set[str]:
    names: set[str] = set()
    for node in walk(parse(test_source).root_node):
        if (
            node.type == "import_from_statement"
            and text(node.child_by_field_name("module_name")) == module
        ):
            for n in node.children_by_field_name("name"):
                real = n.child_by_field_name("name") if n.type == "aliased_import" else n
                names.add(text(real))
    return names


def _top_level(root: Node) -> dict[str, Node]:
    """Module-level definitions and assignments, by name."""
    out: dict[str, Node] = {}
    for stmt in root.named_children:
        node = stmt
        if node.type == "decorated_definition":
            inner = node.child_by_field_name("definition")
            name = text(inner.child_by_field_name("name")) if inner is not None else ""
        elif node.type in ("function_definition", "class_definition"):
            name = text(node.child_by_field_name("name"))
        elif (
            node.type == "expression_statement"
            and node.named_children
            and node.named_children[0].type == "assignment"
        ):
            name = text(node.named_children[0].child_by_field_name("left"))
        else:
            continue
        if name:
            out[name] = node
    return out


def repair_ranges(
    root: Path, validation: ValidationResult, path: str, content: str
) -> list[LineRange]:
    """Current-content line ranges in `path` that the failing tests implicate."""
    failing = [t for t in validation.tests if t.outcome in ("failed", "error")]
    if not failing:
        return []
    ranges: list[LineRange] = []
    total = content.count("\n") + 1
    for t in failing:
        for m in _FRAME.finditer(t.message):
            if m["path"] == path and int(m["line"]) <= total:
                n = int(m["line"])
                ranges.append(LineRange(n, n))

    tree = parse(content.encode()).root_node
    defs = _top_level(tree)
    module = _module_name(path)
    used: set[str] = set()
    for t in failing:
        test_path = _test_file(t.nodeid)
        if test_path is None or not (root / test_path).is_file():
            continue
        used |= _imported_names((root / test_path).read_bytes(), module)
    # The definitions the tests use, plus the module-level names *those* read directly.
    # One level only: following references transitively would pull in most of a module.
    direct = {n for n in used if n in defs}
    referenced = {
        ref
        for name in direct
        for ident in walk(defs[name])
        if ident.type == "identifier" and (ref := text(ident)) in defs
    }
    for name in sorted(direct | referenced):
        node = defs[name]
        ranges.append(LineRange(start_line(node), end_line(node)))
    return ranges
