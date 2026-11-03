"""Detect Pydantic v1 usage that must change for Pydantic v2.

Two passes over the repository:

1. **Symbols.** Every file's ``pydantic`` imports (with aliases), class
   definitions with their bases, field annotations of model classes, and
   function return annotations. Model classes are then resolved to a fixed
   point, so ``class Admin(User)`` in another file counts as a model when
   ``User`` subclasses ``BaseModel``.
2. **Findings.** Each file is walked once and every rule is checked with that
   repository-wide context.

The context is what lets the analyzer tell ``user.dict()`` (a model, HIGH)
from ``response.json()`` (an HTTP client, LOW: reported, never auto-fixed).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from tree_sitter import Node

from patchpilot.analyzer.parser import (
    ParsedFile,
    enclosing,
    enclosing_statement,
    end_line,
    start_line,
    text,
    walk,
)
from patchpilot.models import Confidence, Finding

PYDANTIC_MODEL_BASES = frozenset({"BaseModel", "GenericModel", "BaseSettings"})

# v1 model methods and their v2 replacements.
DEPRECATED_METHODS: dict[str, str] = {
    "dict": "model_dump()",
    "json": "model_dump_json()",
    "copy": "model_copy()",
    "parse_obj": "model_validate()",
    "parse_raw": "model_validate_json()",
    "parse_file": "model_validate_json(Path(...).read_text())",
    "from_orm": "model_validate() with from_attributes=True",
    "schema": "model_json_schema()",
    "schema_json": "json.dumps(model_json_schema())",
    "construct": "model_construct()",
    "update_forward_refs": "model_rebuild()",
    "validate": "model_validate()",
}
# Names that, in practice, only Pydantic models have: an unknown receiver is MEDIUM.
PYDANTIC_ONLY_METHODS = frozenset(
    {"parse_obj", "parse_raw", "parse_file", "from_orm", "schema_json", "update_forward_refs"}
)
# Methods that return another model instance (for receiver type inference).
MODEL_RETURNING = frozenset(
    {
        "parse_obj",
        "parse_raw",
        "parse_file",
        "from_orm",
        "construct",
        "copy",
        "validate",
        "model_validate",
        "model_validate_json",
        "model_construct",
        "model_copy",
    }
)

CONFIG_RENAMED: dict[str, str] = {
    "orm_mode": "from_attributes",
    "allow_population_by_field_name": "populate_by_name",
    "anystr_lower": "str_to_lower",
    "anystr_upper": "str_to_upper",
    "anystr_strip_whitespace": "str_strip_whitespace",
    "min_anystr_length": "str_min_length",
    "max_anystr_length": "str_max_length",
    "schema_extra": "json_schema_extra",
    "validate_all": "validate_default",
    "allow_mutation": "frozen (inverted)",
    "keep_untouched": "ignored_types",
    "copy_on_model_validation": "revalidate_instances",
}
CONFIG_REMOVED = frozenset(
    {
        "smart_union",
        "underscore_attrs_are_private",
        "error_msg_templates",
        "fields",
        "getter_dict",
        "json_loads",
        "json_dumps",
        "post_init_call",
        "json_encoders",  # deprecated: use @field_serializer
    }
)

FIELD_KWARGS: dict[str, str] = {
    "regex": "pattern",
    "min_items": "min_length",
    "max_items": "max_length",
    "allow_mutation": "frozen",
    "const": "removed: use typing.Literal",
    "unique_items": "removed: use a set type",
    "env": "removed: use validation_alias (pydantic-settings)",
}
CONSTRAINED_FACTORIES = frozenset({"Field", "constr", "conlist", "conset", "confrozenset"})

MOVED_IMPORTS: dict[str, str] = {
    "BaseSettings": "moved to the pydantic-settings package (from pydantic_settings import BaseSettings)",
    "validate_arguments": "renamed to validate_call",
    "parse_obj_as": "deprecated: use TypeAdapter(T).validate_python(data)",
    "parse_raw_as": "deprecated: use TypeAdapter(T).validate_json(data)",
    "schema_of": "deprecated: use TypeAdapter(T).json_schema()",
    "Extra": "deprecated: use the string literals 'allow' / 'forbid' / 'ignore'",
    "PyObject": "renamed to ImportString",
    "Color": "moved to pydantic-extra-types",
    "PaymentCardNumber": "moved to pydantic-extra-types",
}
MOVED_MODULES: dict[str, str] = {
    "pydantic.generics": "GenericModel is gone: subclass BaseModel and typing.Generic[T]",
    "pydantic.error_wrappers": "ValidationError now lives at pydantic.ValidationError",
    "pydantic.utils": "pydantic.utils was removed",
    "pydantic.typing": "pydantic.typing was removed",
    "pydantic.json": "pydantic.json was removed: use model_dump(mode='json') or pydantic_core.to_jsonable_python",
    "pydantic.class_validators": "import validators from pydantic directly",
    "pydantic.datetime_parse": "pydantic.datetime_parse was removed",
}
# pydantic.fields still exists in v2: only these names survive in it.
V2_FIELDS_NAMES = frozenset(
    {"Field", "FieldInfo", "PrivateAttr", "ModelPrivateAttr", "computed_field",
     "ComputedFieldInfo", "AliasChoices", "AliasPath"}
)  # fmt: skip

_LITERALS = frozenset(
    {
        "dictionary",
        "list",
        "set",
        "tuple",
        "string",
        "dictionary_comprehension",
        "list_comprehension",
    }
)
_COMPREHENSIONS = frozenset(
    {"list_comprehension", "set_comprehension", "dictionary_comprehension", "generator_expression"}
)
_CONTAINER_RE = re.compile(
    r"^(?:typing\.)?(?:List|list|Sequence|Iterable|Iterator|Set|set|FrozenSet|frozenset|Collection)\[(.+)\]$"
)
_OPTIONAL_RE = re.compile(
    r"^(typing\.)?Optional\[|\|\s*None\b|\bNone\s*\||^(typing\.)?Union\[.*\bNone\b"
)


@dataclass
class _ClassInfo:
    name: str
    file: str
    bases: list[str]
    fields: dict[str, str] = field(default_factory=dict)  # field name -> annotation text
    methods: dict[str, int] = field(default_factory=dict)  # method name -> 1-based line


@dataclass
class _FileSymbols:
    # local name -> pydantic attribute it refers to ("BaseModel", "validator", ...)
    pydantic_names: dict[str, str] = field(default_factory=dict)
    pydantic_modules: set[str] = field(default_factory=set)  # local aliases of `pydantic`
    # local name -> (absolute module, attribute) for every `from X import a [as b]`
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    modules: dict[str, str] = field(default_factory=dict)  # `import a.b as c`: "c" -> "a.b"


@dataclass
class RepoContext:
    symbols: dict[str, _FileSymbols]
    classes: dict[str, list[_ClassInfo]]
    models: set[str]  # names of model classes anywhere in the repository
    returns: dict[str, str]  # function name -> model class it returns
    # Per file: names that refer to a model *there*. A name is only dropped when the
    # file's own imports or definitions prove it is some other class (e.g. a
    # SQLAlchemy `Service` while a Pydantic `Service` exists elsewhere).
    visible: dict[str, set[str]] = field(default_factory=dict)

    def models_in(self, path: str) -> set[str]:
        return self.visible.get(path, self.models)

    def override(self, model: str, method: str) -> tuple[str, str, int] | None:
        """Where `model` or a repository ancestor defines `method` itself, if anywhere:
        (class, file, line). Prefect's `PrefectBaseModel.dict(json_compatible=...)` is one."""
        todo, seen = [model], set()
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            for info in self.classes.get(name, []):
                if method in info.methods:
                    return info.name, info.file, info.methods[method]
                todo.extend(_last(b) for b in info.bases)
        return None


def _last(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1]


def _strip_generic(base: str) -> str:
    return base.split("[", 1)[0].strip()


def _absolute_module(module: str, path: str) -> str:
    """`.models` imported from `pkg/sub/x.py` -> `pkg.sub.models` (dotted, from the repo root)."""
    if not module.startswith("."):
        return module
    dots = len(module) - len(module.lstrip("."))
    package = path.split("/")[:-1]
    if dots > 1:
        package = package[: len(package) - (dots - 1)]
    rest = module[dots:]
    return ".".join([*package, *([rest] if rest else [])])


def _collect_symbols(pf: ParsedFile) -> tuple[_FileSymbols, list[_ClassInfo], dict[str, str]]:
    syms = _FileSymbols()
    classes: list[_ClassInfo] = []
    returns: dict[str, str] = {}
    for node in walk(pf.root):
        if node.type == "import_from_statement":
            module = text(node.child_by_field_name("module_name"))
            absolute = _absolute_module(module, pf.path)
            for name_node in node.children_by_field_name("name"):
                if name_node.type == "aliased_import":
                    real = text(name_node.child_by_field_name("name"))
                    local = text(name_node.child_by_field_name("alias"))
                else:
                    real = local = text(name_node)
                syms.imports[local] = (absolute, real)
            if module == "pydantic" or module.startswith("pydantic."):
                for name_node in node.children_by_field_name("name"):
                    if name_node.type == "aliased_import":
                        real = text(name_node.child_by_field_name("name"))
                        local = text(name_node.child_by_field_name("alias"))
                    else:
                        real = local = text(name_node)
                    syms.pydantic_names[local] = _last(real)
        elif node.type == "import_statement":
            for name_node in node.children_by_field_name("name"):
                if name_node.type == "aliased_import":
                    real = text(name_node.child_by_field_name("name"))
                    local = text(name_node.child_by_field_name("alias"))
                else:
                    real = local = text(name_node)
                if real == "pydantic":
                    syms.pydantic_modules.add(local)
                syms.modules[
                    local if name_node.type == "aliased_import" else real.split(".")[0]
                ] = real if name_node.type == "aliased_import" else real.split(".")[0]
        elif node.type == "class_definition":
            name = text(node.child_by_field_name("name"))
            supers = node.child_by_field_name("superclasses")
            bases = (
                [
                    _strip_generic(text(a))
                    for a in supers.named_children
                    if a.type != "keyword_argument"
                ]
                if supers is not None
                else []
            )
            info = _ClassInfo(name, pf.path, bases)
            body = node.child_by_field_name("body")
            for stmt in body.named_children if body is not None else []:
                if stmt.type == "expression_statement" and stmt.named_children:
                    assign = stmt.named_children[0]
                    if (
                        assign.type == "assignment"
                        and assign.child_by_field_name("type") is not None
                    ):
                        left = text(assign.child_by_field_name("left"))
                        info.fields[left] = text(assign.child_by_field_name("type"))
                fn = (
                    stmt.child_by_field_name("definition")
                    if stmt.type == "decorated_definition"
                    else stmt
                )
                if fn is not None and fn.type == "function_definition":
                    info.methods[text(fn.child_by_field_name("name"))] = start_line(fn)
            classes.append(info)
        elif node.type == "function_definition":
            ret = node.child_by_field_name("return_type")
            if ret is not None:
                returns[text(node.child_by_field_name("name"))] = text(ret)
    return syms, classes, returns


def build_context(files: Iterable[ParsedFile]) -> RepoContext:
    symbols: dict[str, _FileSymbols] = {}
    classes: dict[str, list[_ClassInfo]] = {}
    raw_returns: dict[str, str] = {}
    for pf in files:
        syms, file_classes, returns = _collect_symbols(pf)
        symbols[pf.path] = syms
        for c in file_classes:
            classes.setdefault(c.name, []).append(c)
        raw_returns.update(returns)

    def is_pydantic_base(base: str, path: str) -> bool:
        syms = symbols[path]
        if "." in base:
            module, attr = base.rsplit(".", 1)
            return module in syms.pydantic_modules and attr in PYDANTIC_MODEL_BASES
        return syms.pydantic_names.get(base) in PYDANTIC_MODEL_BASES

    resolver = _Resolver(symbols, classes)
    # Model identity is (file, class name): two classes may share a name.
    qmodels: set[tuple[str, str]] = {
        (c.file, c.name)
        for infos in classes.values()
        for c in infos
        if any(is_pydantic_base(b, c.file) for b in c.bases)
    }
    # Fixed point: subclasses of models are models, across files. A base is resolved
    # through the file's imports; only when that is impossible, by name.
    changed = True
    while changed:
        changed = False
        names = {n for _, n in qmodels}
        for infos in classes.values():
            for c in infos:
                if (c.file, c.name) in qmodels:
                    continue
                for b in c.bases:
                    targets = resolver.base(b, c.file)
                    hit = _last(b) in names if targets is None else bool(targets & qmodels)
                    if hit:
                        qmodels.add((c.file, c.name))
                        changed = True
                        break
    models = {n for _, n in qmodels}

    visible: dict[str, set[str]] = {}
    for path, syms in symbols.items():
        seen = set(models)
        local_names = {c.name for infos in classes.values() for c in infos if c.file == path}
        for local in local_names | set(syms.imports):
            targets = resolver.name(local, path)
            if targets is None:
                continue
            if targets & qmodels:
                seen.add(local)  # also covers `from x import User as U`
            else:
                seen.discard(local)
        visible[path] = seen

    returns = {fn: m for fn, ann in raw_returns.items() if (m := _model_in_annotation(ann, models))}
    return RepoContext(symbols, classes, models, returns, visible)


class _Resolver:
    """Resolve a name used in one file to the repository class(es) it denotes.

    Returns a set of (file, class) pairs, an empty set when the name provably refers to
    something outside the repository (e.g. `pendulum.DateTime`), or None when it cannot
    tell (star imports, dynamic tricks): callers then fall back to matching by name.
    """

    def __init__(self, symbols: dict[str, _FileSymbols], classes: dict[str, list[_ClassInfo]]):
        self.symbols = symbols
        self.defined = {(c.file, c.name) for infos in classes.values() for c in infos}
        self.by_suffix: dict[str, list[str]] = {}
        for path in symbols:
            parts = path.removesuffix(".py").split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for i in range(len(parts)):
                self.by_suffix.setdefault(".".join(parts[i:]), []).append(path)

    def module_files(self, module: str) -> list[str]:
        return self.by_suffix.get(module, [])

    def name(self, local: str, path: str, depth: int = 0) -> set[tuple[str, str]] | None:
        if (path, local) in self.defined:
            return {(path, local)}
        syms = self.symbols.get(path)
        if syms is None or local not in syms.imports:
            return None
        module, attr = syms.imports[local]
        if module == "pydantic" or module.startswith("pydantic."):
            return set()  # pydantic's own classes are handled as bases, not here
        files = self.module_files(module)
        if not files:
            # `from pkg import mod` where pkg/mod.py exists is a module, not a class.
            return None if self.module_files(f"{module}.{attr}") else set()
        found: set[tuple[str, str]] = set()
        unknown = False
        for f in files:
            if (f, attr) in self.defined:
                found.add((f, attr))
            elif depth < 3:  # re-exported, e.g. from a package __init__
                sub = self.name(attr, f, depth + 1)
                if sub is None:
                    unknown = True
                else:
                    found |= sub
            else:
                unknown = True
        return None if unknown and not found else found

    def base(self, base: str, path: str) -> set[tuple[str, str]] | None:
        if "." not in base:
            return self.name(base, path)
        head, rest = base.split(".", 1)
        syms = self.symbols.get(path)
        if syms is None:
            return None
        if head in syms.modules:
            module = syms.modules[head]
        elif head in syms.imports:
            module = ".".join(syms.imports[head])  # `from pkg import mod` then `mod.Cls`
        else:
            return None
        if module == "pydantic" or module.startswith("pydantic."):
            return set()
        mod_path, _, attr = f"{module}.{rest}".rpartition(".")
        files = self.module_files(mod_path)
        if not files:
            return set()  # a class from an installed package, not this repository
        return {(f, attr) for f in files if (f, attr) in self.defined} or None


def _model_in_annotation(annotation: str, models: set[str]) -> str | None:
    """`User`, `Optional[User]`, `User | None`, `"User"` -> "User"; containers -> None."""
    ann = annotation.strip().strip("'\"")
    for wrapper in ("Optional[", "typing.Optional["):
        if ann.startswith(wrapper) and ann.endswith("]"):
            ann = ann[len(wrapper) : -1].strip()
    parts = [p.strip() for p in ann.split("|")]
    parts = [p for p in parts if p != "None"]
    if len(parts) == 1:
        base = _last(_strip_generic(parts[0]))  # Page[Item] -> Page (a generic model)
        if base in models:
            return base
    return None


class _Detector:
    def __init__(self, pf: ParsedFile, ctx: RepoContext) -> None:
        self.pf = pf
        self.ctx = ctx
        self.syms = ctx.symbols[pf.path]
        self.lines = pf.source.decode("utf-8", errors="replace").splitlines()
        self.findings: list[Finding] = []
        self._seen: dict[str, int] = {}
        self._resolving: set[tuple[str, int]] = set()  # cycle guard: `x = x.copy()`
        self.models = ctx.models_in(pf.path)  # model names as this file sees them

    # -- helpers ---------------------------------------------------------------

    def resolve(self, node: Node | None) -> str | None:
        """Which pydantic attribute an expression names: `validator`, `pd.validator` -> "validator"."""
        if node is None:
            return None
        if node.type == "identifier":
            return self.syms.pydantic_names.get(text(node))
        if node.type == "attribute":
            obj = node.child_by_field_name("object")
            if obj is not None and text(obj) in self.syms.pydantic_modules:
                return text(node.child_by_field_name("attribute"))
        return None

    def model_class_of(self, class_node: Node | None) -> str | None:
        if class_node is None:
            return None
        name = text(class_node.child_by_field_name("name"))
        return name if name in self.models else None

    def add(
        self,
        rule: str,
        title: str,
        node: Node,
        message: str,
        confidence: Confidence,
        symbols: Iterable[str] = (),
        span: Node | None = None,
    ) -> None:
        span = span or node
        line, last = start_line(span), end_line(span)
        base_id = f"{self.pf.path}:{start_line(node)}:{rule}"
        n = self._seen.get(base_id, 0) + 1
        self._seen[base_id] = n
        snippet_lines = self.lines[line - 1 : min(last, line + 14)]
        self.findings.append(
            Finding(
                id=base_id if n == 1 else f"{base_id}#{n}",
                rule=rule,
                title=title,
                file=self.pf.path,
                line=start_line(node),
                end_line=last,
                snippet="\n".join(snippet_lines),
                message=message,
                confidence=confidence,
                symbols=tuple(dict.fromkeys(symbols)),
            )
        )

    # -- rules -----------------------------------------------------------------

    def run(self) -> list[Finding]:
        for node in walk(self.pf.root):
            match node.type:
                case "import_from_statement":
                    self._imports(node)
                case "class_definition":
                    self._class(node)
                case "decorated_definition":
                    self._decorators(node)
                case "call":
                    self._call(node)
                case "attribute":
                    self._dunder_fields(node)
                    self._method_reference(node)
        return self.findings

    def _imports(self, node: Node) -> None:
        module = text(node.child_by_field_name("module_name"))
        if module in MOVED_MODULES:
            self.add(
                "moved-import",
                f"Import from removed module {module}",
                node,
                MOVED_MODULES[module],
                Confidence.HIGH,
                (module, *module.split(".")),
            )
            return
        if module == "pydantic.fields":
            names = [
                text(n.child_by_field_name("name") if n.type == "aliased_import" else n)
                for n in node.children_by_field_name("name")
            ]
            gone = [n for n in names if n not in V2_FIELDS_NAMES]
            if gone:
                self.add(
                    "moved-import",
                    "Import of removed pydantic.fields internals",
                    node,
                    f"removed from pydantic.fields in v2: {', '.join(gone)} "
                    "(field metadata is now `Model.model_fields[name]`, a FieldInfo)",
                    Confidence.HIGH,
                    ("pydantic.fields", *gone),
                )
            return
        if module != "pydantic":
            return
        for name_node in node.children_by_field_name("name"):
            real = text(
                name_node.child_by_field_name("name")
                if name_node.type == "aliased_import"
                else name_node
            )
            if real in MOVED_IMPORTS:
                self.add(
                    "moved-import",
                    f"`{real}` moved or deprecated in v2",
                    node,
                    f"`from pydantic import {real}`: {MOVED_IMPORTS[real]}",
                    Confidence.HIGH,
                    (real,),
                )

    def _class(self, node: Node) -> None:
        name = text(node.child_by_field_name("name"))
        outer = enclosing(node, "class_definition")
        # `class Config:` nested directly in a model class.
        if name == "Config" and self.model_class_of(outer):
            self._config(node, outer)
            return
        if name not in self.models:
            return
        supers = node.child_by_field_name("superclasses")
        for base in supers.named_children if supers is not None else []:
            if self.resolve(base) == "GenericModel" or text(base) == "GenericModel":
                self.add(
                    "generic-model",
                    "GenericModel subclass",
                    node,
                    "GenericModel was removed: subclass BaseModel and typing.Generic[T] instead",
                    Confidence.HIGH,
                    ("GenericModel", "Generic", "generics"),
                    span=supers,
                )
        body = node.child_by_field_name("body")
        for stmt in body.named_children if body is not None else []:
            if stmt.type != "expression_statement" or not stmt.named_children:
                continue
            assign = stmt.named_children[0]
            if assign.type != "assignment":
                continue
            left = text(assign.child_by_field_name("left"))
            ann = assign.child_by_field_name("type")
            if left == "__root__":
                self.add(
                    "custom-root",
                    "Custom root type (__root__)",
                    stmt,
                    "`__root__` fields were replaced by RootModel: `class X(RootModel[T])`, then `.root`",
                    Confidence.HIGH,
                    ("__root__", "RootModel", "root"),
                    span=node,
                )
            elif (
                ann is not None
                and assign.child_by_field_name("right") is None
                and _OPTIONAL_RE.search(text(ann))
            ):
                self.add(
                    "optional-no-default",
                    "Optional field without a default",
                    stmt,
                    f"`{left}: {text(ann)}` had an implicit default of None in v1; in v2 it is "
                    "REQUIRED. Add `= None` to keep the v1 behavior.",
                    Confidence.HIGH,
                    ("Optional", "required", "nullable", "default"),
                )

    def _config(self, node: Node, model_node: Node | None) -> None:
        body = node.child_by_field_name("body")
        keys: list[str] = []
        for stmt in body.named_children if body is not None else []:
            if stmt.type == "expression_statement" and stmt.named_children:
                assign = stmt.named_children[0]
                if assign.type == "assignment":
                    keys.append(text(assign.child_by_field_name("left")))
        notes = []
        for key in keys:
            if key in CONFIG_RENAMED:
                notes.append(f"`{key}` -> `{CONFIG_RENAMED[key]}`")
            elif key in CONFIG_REMOVED:
                notes.append(f"`{key}` was removed or deprecated")
        model = text(model_node.child_by_field_name("name")) if model_node is not None else "?"
        detail = "; ".join(notes) if notes else "keys unchanged"
        self.add(
            "config-class",
            "Nested `class Config`",
            node,
            f"`class Config` on {model} is deprecated: use `model_config = ConfigDict(...)`. {detail}",
            Confidence.HIGH,
            ("Config", "ConfigDict", "model_config", *keys),
        )

    def _decorators(self, node: Node) -> None:
        for dec in node.children:
            if dec.type != "decorator" or not dec.named_children:
                continue
            expr = dec.named_children[0]
            target = expr.child_by_field_name("function") if expr.type == "call" else expr
            what = self.resolve(target)
            args = text(expr.child_by_field_name("arguments")) if expr.type == "call" else ""
            if what == "validator":
                func = node.child_by_field_name("definition")
                params = text(func.child_by_field_name("parameters")) if func is not None else ""
                flags = [
                    k for k in ("pre", "each_item", "always", "allow_reuse") if f"{k}=" in args
                ]
                uses_values = "values" in params
                msg = "`@validator` is deprecated: use `@field_validator` (a @classmethod)"
                if flags:
                    msg += f"; arguments {flags} change (pre=True -> mode='before', always -> validate_default)"
                if uses_values:
                    msg += "; the `values` argument becomes `info: ValidationInfo` (use info.data)"
                self.add(
                    "validator",
                    "`@validator`",
                    dec,
                    msg,
                    Confidence.HIGH,
                    ("validator", "field_validator", *flags, *(["values"] if uses_values else [])),
                    span=node,
                )
            elif what == "root_validator":
                pre = "pre=True" in args.replace(" ", "")
                self.add(
                    "root-validator",
                    "`@root_validator`",
                    dec,
                    "`@root_validator` is deprecated: use `@model_validator(mode='before')` "
                    "(a @classmethod receiving raw data)"
                    if pre
                    else "`@root_validator` is deprecated: use `@model_validator(mode='after')` "
                    "(an instance method returning self)",
                    Confidence.HIGH,
                    ("root_validator", "model_validator", *(["pre"] if pre else [])),
                    span=node,
                )
            elif what == "validate_arguments":
                self.add(
                    "moved-import",
                    "`@validate_arguments`",
                    dec,
                    "`@validate_arguments` was renamed to `@validate_call`",
                    Confidence.HIGH,
                    ("validate_arguments", "validate_call"),
                )

    def _call(self, node: Node) -> None:
        func = node.child_by_field_name("function")
        if func is None:
            return
        what = self.resolve(func)
        if what in ("parse_obj_as", "parse_raw_as", "schema_of"):
            self.add(
                "parse-obj-as",
                f"`{what}()`",
                node,
                MOVED_IMPORTS[what],
                Confidence.HIGH,
                (what, "TypeAdapter"),
                span=enclosing_statement(node),
            )
            return
        if what in CONSTRAINED_FACTORIES:
            self._field_kwargs(node, what)
            return
        if what in ("validator", "root_validator") and (
            node.parent is None or node.parent.type != "decorator"
        ):
            # `_check = validator("a", allow_reuse=True)(fn)`: a reused validator, no `@`.
            self.add(
                "validator",
                f"`{what}(...)` applied without decorator syntax",
                node,
                f"`{what}(...)(fn)` (a reused validator) is deprecated: use "
                f"`{'field_validator' if what == 'validator' else 'model_validator'}(...)(fn)`; "
                "`allow_reuse` is no longer needed. One field_validator can name several fields.",
                Confidence.HIGH,
                (what, "field_validator", "allow_reuse", "reuse"),
                span=enclosing_statement(node),
            )
            return
        if func.type == "attribute":
            method = text(func.child_by_field_name("attribute"))
            if method in DEPRECATED_METHODS:
                self._method(node, func, method)

    def _field_kwargs(self, node: Node, factory: str) -> None:
        args = node.child_by_field_name("arguments")
        for arg in args.named_children if args is not None else []:
            if arg.type != "keyword_argument":
                continue
            key = text(arg.child_by_field_name("name"))
            if key in FIELD_KWARGS:
                self.add(
                    "field-kwargs",
                    f"`{factory}({key}=...)`",
                    arg,
                    f"`{factory}({key}=...)`: {key} -> {FIELD_KWARGS[key]}",
                    Confidence.HIGH,
                    (factory, key, FIELD_KWARGS[key].split(":")[0]),
                    span=enclosing_statement(node),
                )

    def _method(self, call: Node, func: Node, method: str) -> None:
        receiver = func.child_by_field_name("object")
        if receiver is None or receiver.type in _LITERALS or self._known_non_model(receiver, call):
            return  # {"a": 1}.copy(), resp.json() with `resp: HttpResponse`: not Pydantic
        model = self._receiver_model(receiver, call)
        # Also a repo class we can't prove is a model (dynamic base, e.g. `X.subclass()`).
        named = _last(text(receiver)) if receiver.type in ("identifier", "attribute") else ""
        owner = model or (named if named in self.ctx.classes else None)
        custom = self.ctx.override(owner, method) if owner is not None else None
        if custom is not None:
            owner, path, line = custom
            self.add(
                "deprecated-method",
                f"`.{method}()` (custom override)",
                call,
                f"`{owner}` defines its own `.{method}()` ({path}:{line}). Migrate that override; "
                f"renaming this call to `.{DEPRECATED_METHODS[method].split('(')[0]}` would bypass it "
                "(and its extra arguments may not exist there). Review by hand.",
                Confidence.LOW,
                (method, DEPRECATED_METHODS[method].split("(")[0]),
                span=enclosing_statement(call),
            )
            return
        if model is not None:
            confidence = Confidence.HIGH
            who = f"`{text(receiver)}` is a Pydantic model ({model})"
        elif method in PYDANTIC_ONLY_METHODS:
            confidence = Confidence.MEDIUM
            who = f"`.{method}()` exists only on Pydantic models"
        else:
            confidence = Confidence.LOW
            who = f"cannot tell whether `{text(receiver)}` is a Pydantic model; review by hand"
        self.add(
            "deprecated-method",
            f"`.{method}()`",
            call,
            f"`.{method}()` -> `.{DEPRECATED_METHODS[method]}` ({who})",
            confidence,
            (method, DEPRECATED_METHODS[method].split("(")[0]),
            span=enclosing_statement(call),
        )

    def _method_reference(self, node: Node) -> None:
        """`map(User.parse_obj, rows)`, `return event.json`: deprecated methods passed, not called."""
        method = text(node.child_by_field_name("attribute"))
        if method not in DEPRECATED_METHODS:
            return
        parent = node.parent
        if (
            parent is not None
            and parent.type == "call"
            and parent.child_by_field_name("function") == node
        ):
            return  # a call: handled by _method
        if (
            parent is not None
            and parent.type == "assignment"
            and parent.child_by_field_name("left") == node
        ):
            return  # assigning to an attribute that happens to be named `json`
        receiver = node.child_by_field_name("object")
        model = self._receiver_model(receiver, node)
        if model is None or self.ctx.override(model, method) is not None:
            return  # only when the receiver is provably a model: references are rarer, false positives costlier
        self.add(
            "deprecated-method",
            f"`.{method}` passed as a reference",
            node,
            f"`.{method}` (referenced, not called) -> `.{DEPRECATED_METHODS[method].split('(')[0]}` "
            f"(`{text(receiver)}` is a Pydantic model ({model}))",
            Confidence.HIGH,
            (method, DEPRECATED_METHODS[method].split("(")[0]),
            span=enclosing_statement(node),
        )

    def _dunder_fields(self, node: Node) -> None:
        attr = text(node.child_by_field_name("attribute"))
        if attr in ("__fields__", "__fields_set__", "__config__"):
            replacement = {
                "__fields__": "model_fields",
                "__fields_set__": "model_fields_set",
                "__config__": "model_config",
            }[attr]
            self.add(
                "deprecated-method",
                f"`{attr}`",
                node,
                f"`{attr}` -> `{replacement}`",
                Confidence.MEDIUM,
                (attr, replacement),
                span=enclosing_statement(node),
            )

    # -- receiver type inference -------------------------------------------------

    def _known_non_model(self, receiver: Node, call: Node) -> bool:
        """A repository class that is *not* a model (`Snapshot.parse_obj`), or a parameter
        annotated with one."""
        if receiver.type != "identifier":
            return False
        name = text(receiver)
        if name in self.ctx.classes and name not in self.models:
            return True
        scope = enclosing(call, "function_definition")
        params = scope.child_by_field_name("parameters") if scope is not None else None
        for p in params.named_children if params is not None else []:
            if p.type in ("typed_parameter", "typed_default_parameter"):
                pname = p.child_by_field_name("name") or (
                    p.named_children[0] if p.named_children else None
                )
                if text(pname) == text(receiver):
                    ann = _last(text(p.child_by_field_name("type")).strip("'\""))
                    return ann in self.ctx.classes and ann not in self.models
        return False

    def _receiver_model(self, receiver: Node | None, call: Node) -> str | None:
        if receiver is None:
            return None
        rtext = text(receiver)
        if receiver.type == "identifier":
            if rtext in self.models:
                return rtext  # classmethod style: User.parse_obj(...)
            if rtext in ("self", "cls"):
                return self.model_class_of(enclosing(call, "class_definition"))
            return self._binding_model(rtext, call)
        if receiver.type == "call":
            inner = receiver.child_by_field_name("function")
            if inner is None:
                return None
            if inner.type == "identifier":
                name = text(inner)
                if name in self.models:
                    return name  # User(...).dict()
                return self.ctx.returns.get(name)  # load_user().dict()
            if inner.type == "attribute":
                method = text(inner.child_by_field_name("attribute"))
                if method in MODEL_RETURNING:
                    return self._receiver_model(inner.child_by_field_name("object"), call)
        if receiver.type == "subscript":
            # Page[Product].parse_obj(...): a parametrized generic model.
            value = receiver.child_by_field_name("value")
            if value is not None and text(value) in self.models:
                return text(value)
        if receiver.type == "attribute":
            # order.customer.dict(): look up the field's annotation on the owner model.
            owner = self._receiver_model(receiver.child_by_field_name("object"), call)
            attr = text(receiver.child_by_field_name("attribute"))
            if owner is None and attr in self.models and attr[:1].isupper():
                return attr  # schemas.responses.FlowRunResponse.from_orm(...): via a module path
            for info in self.ctx.classes.get(owner or "", []):
                if attr in info.fields:
                    return _model_in_annotation(info.fields[attr], self.models)
        return None

    def _binding_model(self, name: str, at: Node) -> str | None:
        """Model type of a local name: annotated parameter, `x: M = ...`, `x = M(...)`."""
        scope = enclosing(at, "function_definition") or self.pf.root
        key = (name, scope.start_byte)
        if key in self._resolving:
            return None  # `flow = flow.copy()`: the name's type depends on itself
        self._resolving.add(key)
        try:
            return self._binding_model_in(name, at, scope)
        finally:
            self._resolving.discard(key)

    def _binding_model_in(self, name: str, at: Node, scope: Node) -> str | None:
        if scope.type == "function_definition":
            params = scope.child_by_field_name("parameters")
            for p in params.named_children if params is not None else []:
                if p.type in ("typed_parameter", "typed_default_parameter"):
                    pname = p.child_by_field_name("name") or (
                        p.named_children[0] if p.named_children else None
                    )
                    if text(pname) == name:
                        return _model_in_annotation(
                            text(p.child_by_field_name("type")), self.models
                        )
        loop = self._loop_variable_model(name, at, scope)
        if loop is not None:
            return loop
        found: str | None = None
        for node in _scope_assignments(scope):
            if text(node.child_by_field_name("left")) != name or start_line(node) > start_line(at):
                continue
            ann = node.child_by_field_name("type")
            if ann is not None:
                found = _model_in_annotation(text(ann), self.models) or found
                continue
            right = node.child_by_field_name("right")
            if right is not None and right.type == "call":
                found = self._receiver_model(right, at) or self._call_result_model(right) or found
        return found

    def _loop_variable_model(self, name: str, at: Node, scope: Node) -> str | None:
        """`for r in rows` / `[r.dict() for r in rows]` where `rows: List[Row]` -> Row."""
        loops: list[Node] = []
        for a in (at, *_ancestors_until(at, scope)):
            if a.type == "for_statement":
                loops.append(a)
            elif a.type in _COMPREHENSIONS:
                # The `for x in xs` clause is a sibling of the expression, not its parent.
                loops.extend(c for c in a.named_children if c.type == "for_in_clause")
        for loop in loops:
            if text(loop.child_by_field_name("left")) != name:
                continue
            iterable = loop.child_by_field_name("right")
            if iterable is None or iterable.type != "identifier":
                continue
            ann = self._param_annotation(text(iterable), scope)
            if ann is not None and (m := _CONTAINER_RE.match(ann.replace(" ", ""))):
                inner = _last(m.group(1).strip("'\""))
                if inner in self.models:
                    return inner
        return None

    def _param_annotation(self, name: str, scope: Node) -> str | None:
        if scope.type != "function_definition":
            return None
        params = scope.child_by_field_name("parameters")
        for p in params.named_children if params is not None else []:
            if p.type in ("typed_parameter", "typed_default_parameter"):
                pname = p.child_by_field_name("name") or (
                    p.named_children[0] if p.named_children else None
                )
                if text(pname) == name:
                    return text(p.child_by_field_name("type"))
        return None

    def _call_result_model(self, call: Node) -> str | None:
        func = call.child_by_field_name("function")
        if func is not None and func.type == "attribute":
            method = text(func.child_by_field_name("attribute"))
            if method in MODEL_RETURNING:
                obj = func.child_by_field_name("object")
                return self._receiver_model(obj, call) if obj is not None else None
        return None


def _ancestors_until(node: Node, stop: Node) -> Iterator[Node]:
    parent = node.parent
    while parent is not None and parent != stop:
        yield parent
        parent = parent.parent


def _scope_assignments(scope: Node) -> Iterator[Node]:
    """Assignments in this scope, not descending into nested functions or classes."""
    stack = list(reversed(scope.children))
    while stack:
        node = stack.pop()
        if node.type == "assignment":
            yield node
        if node.type in ("function_definition", "class_definition", "lambda") and node is not scope:
            continue
        stack.extend(reversed(node.children))


def _analysis_error(pf: ParsedFile, exc: Exception) -> Finding:
    return Finding(
        id=f"{pf.path}:1:analysis-error",
        rule="analysis-error",
        title="File could not be fully analyzed",
        file=pf.path,
        line=1,
        end_line=1,
        snippet="",
        message=f"The analyzer failed on this file ({type(exc).__name__}). Review it by hand.",
        confidence=Confidence.LOW,  # reported, never auto-fixed
    )


def detect(files: list[ParsedFile]) -> tuple[list[Finding], list[str]]:
    """Return (findings sorted by file and line, model class names)."""
    ctx = build_context(files)
    findings: list[Finding] = []
    for pf in files:
        try:
            findings.extend(_Detector(pf, ctx).run())
        except Exception as exc:  # one pathological file must not sink the whole analysis
            findings.append(_analysis_error(pf, exc))
    findings.sort(key=lambda f: (f.file, f.line, f.id))
    return findings, sorted(ctx.models)
