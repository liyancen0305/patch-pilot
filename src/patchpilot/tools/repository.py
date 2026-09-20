"""Deterministic file discovery, search, and Python syntax inspection."""

import ast
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PythonStructure:
    imports: tuple[str, ...]
    classes: tuple[tuple[str, tuple[str, ...]], ...]
    functions: tuple[tuple[str, tuple[str, ...]], ...]


def discover_files(root: Path) -> dict[str, tuple[Path, ...]]:
    """Return relative source, test, configuration, and dependency paths."""
    categories: dict[str, list[Path]] = {
        "source": [], "test": [], "configuration": [], "dependency": []
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root)
        if path.name in {"pyproject.toml", "requirements.txt", "requirements-dev.txt"}:
            categories["dependency"].append(relative)
        elif path.suffix in {".toml", ".ini", ".cfg", ".yaml", ".yml"}:
            categories["configuration"].append(relative)
        elif path.suffix == ".py" and "tests" in relative.parts:
            categories["test"].append(relative)
        elif path.suffix == ".py":
            categories["source"].append(relative)
    return {key: tuple(value) for key, value in categories.items()}


def search_text(root: Path, pattern: str) -> tuple[str, ...]:
    """Search with rg if installed; return file:line:text matches."""
    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", "--line-number", "--no-heading", "--glob", "!.git/**", pattern, "."],
            cwd=root, text=True, capture_output=True, check=False,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip())
        return tuple(result.stdout.splitlines())
    import re

    regex = re.compile(pattern)
    matches = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            lines = path.read_text().splitlines()
        except (UnicodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append(f"{path.relative_to(root)}:{number}:{line}")
    return tuple(matches)


def inspect_python(path: Path) -> PythonStructure:
    """Describe imports, classes/bases, and functions/decorators using ast."""
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: list[str] = []
    classes: list[tuple[str, tuple[str, ...]]] = []
    functions: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append("." * node.level + (node.module or ""))
        elif isinstance(node, ast.ClassDef):
            classes.append((node.name, tuple(ast.unparse(base) for base in node.bases)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                (node.name, tuple(ast.unparse(dec) for dec in node.decorator_list))
            )
    return PythonStructure(tuple(imports), tuple(classes), tuple(functions))
