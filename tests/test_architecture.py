"""The architecture is a contract — this test enforces it.

Each layer's ``__init__.py`` documents what it may and may not import.
Documentation rots; tests don't. This walks every module's import
statements (via ``ast``, without executing anything) and fails the build
if a dependency arrow points the wrong way — e.g. the domain importing
Qt, or the UI reaching straight into infrastructure.
"""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "eqgenius"

# layer package -> import prefixes it must never touch.
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "eqgenius.domain": (
        "PySide6",
        "scipy",
        "sqlalchemy",
        "eqgenius.application",
        "eqgenius.infrastructure",
        "eqgenius.ui",
    ),
    "eqgenius.dsp": (
        "PySide6",
        "sqlalchemy",
        "eqgenius.domain",
        "eqgenius.application",
        "eqgenius.infrastructure",
        "eqgenius.ui",
    ),
    "eqgenius.application": ("PySide6", "eqgenius.ui"),
    "eqgenius.infrastructure": ("PySide6", "eqgenius.ui"),
    "eqgenius.ui": ("scipy", "eqgenius.infrastructure"),
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(SRC.parent)  # e.g. eqgenius/dsp/engine.py
    parts = relative.with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports_of(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.add(node.module)
            else:
                # Resolve relative imports ("from ..infrastructure import x")
                # to absolute names so they can't dodge the rules.
                package_parts = module.split(".")
                base = package_parts[: len(package_parts) - node.level]
                found.add(".".join([*base, node.module] if node.module else base))
    return found


def test_layer_dependency_rules_hold() -> None:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        module = _module_name(path)
        rules = next(
            (banned for layer, banned in FORBIDDEN.items() if module.startswith(layer)),
            None,
        )
        if rules is None:  # composition roots (app.py, cli.py) are exempt
            continue
        for imported in _imports_of(path, module):
            if any(imported == b or imported.startswith(b + ".") for b in rules):
                violations.append(f"{module} imports {imported}")

    assert not violations, "layer rules violated:\n  " + "\n  ".join(sorted(violations))
