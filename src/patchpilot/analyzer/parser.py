"""Thin wrapper around tree-sitter's Python grammar.

tree-sitter (rather than the stdlib ``ast``) because it is error-tolerant: a
file that does not fully parse still yields a usable tree, so one broken file
does not hide findings in the rest of it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache

import tree_sitter_python
from tree_sitter import Language, Node, Parser, Tree


@cache
def _parser() -> Parser:
    return Parser(Language(tree_sitter_python.language()))


def parse(source: bytes) -> Tree:
    return _parser().parse(source)


def text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def start_line(node: Node) -> int:
    """1-based line number of the node's first character."""
    return int(node.start_point.row) + 1


def end_line(node: Node) -> int:
    """1-based line number of the node's last character."""
    return int(node.end_point.row) + 1


def walk(node: Node) -> Iterator[Node]:
    """Pre-order traversal without recursion (deeply nested code is legal Python)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def ancestors(node: Node) -> Iterator[Node]:
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def enclosing(node: Node, *types: str) -> Node | None:
    return next((a for a in ancestors(node) if a.type in types), None)


def enclosing_statement(node: Node) -> Node:
    """The smallest ancestor that is a whole statement (what an edit should replace)."""
    for a in (node, *ancestors(node)):
        parent = a.parent
        if parent is not None and parent.type in ("module", "block"):
            return a
    return node


@dataclass
class ParsedFile:
    path: str  # repository-relative POSIX path
    source: bytes
    root: Node
    is_test: bool
