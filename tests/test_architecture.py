"""The architecture is a contract — this test enforces it.

Each layer's ``__init__.py`` documents what it may and may not import.
Documentation rots; tests don't. This walks every module's import
statements (via ``ast``, without executing anything) and fails the build
if a dependency arrow points the wrong way — e.g. the domain importing
Qt, or the UI reaching straight into infrastructure.
"""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "trxmp"

# layer package -> import prefixes it must never touch.
# OS and vendor SDKs that only infrastructure may touch. If `winreg` or
# `pycaw` ever appear in the domain, the app has stopped being portable
# and testable in the same breath.
_PLATFORM = ("winreg", "pycaw", "comtypes")

FORBIDDEN: dict[str, tuple[str, ...]] = {
    "trxmp.domain": (
        "PySide6",
        "scipy",
        "sqlalchemy",
        "pydantic",  # Pydantic lives at the file boundary, never in the domain
        *_PLATFORM,
        "trxmp.application",
        "trxmp.infrastructure",
        "trxmp.ui",
    ),
    "trxmp.dsp": (
        "PySide6",
        "sqlalchemy",
        "pydantic",
        *_PLATFORM,
        "trxmp.domain",
        "trxmp.application",
        "trxmp.infrastructure",
        "trxmp.ui",
    ),
    # The application layer stays persistence-, serialization- and
    # OS-agnostic: it declares Protocols (PresetRepository,
    # AudioDeviceService) that infrastructure implements, so it must not
    # import sqlalchemy, pydantic, the Windows APIs, or the UI.
    "trxmp.application": ("PySide6", "sqlalchemy", "pydantic", *_PLATFORM, "trxmp.ui"),
    "trxmp.infrastructure": ("PySide6", "trxmp.ui"),
    # The UI may not reach the OS directly either — that's what the
    # injected services are for, and it's what keeps MainWindow testable
    # with fakes on a machine with no audio hardware at all.
    "trxmp.ui": ("scipy", *_PLATFORM, "trxmp.infrastructure"),
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(SRC.parent)  # e.g. trxmp/dsp/engine.py
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
