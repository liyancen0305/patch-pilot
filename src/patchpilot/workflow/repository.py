"""Deterministic capability checks, repository analysis, and snippet context."""

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:
    import tomli as tomllib  # type: ignore[import-not-found]

from patchpilot.tools.repository import discover_files, inspect_python, search_text

from .schema import (
    CapabilityDecision,
    ContextBundle,
    ContextItem,
    MigrationRequest,
    RepositoryAnalysis,
)

V1_PATTERN = re.compile(
    r"\b(?:validator|root_validator|parse_obj|anystr_strip_whitespace)\b|\.dict\(|class Config\b"
)
SEARCH_PATTERN = r"pydantic|validator|parse_obj|\.dict\(|Config|model_validate|model_dump"


def capability(request: MigrationRequest, target: Path,
               verification_python: Path | None = None) -> CapabilityDecision:
    """Check the tools through the interpreter that will run verification."""
    reasons: list[str] = []
    if request.language != "Python" or "Pydantic v1 to Pydantic v2" not in request.migration_goal:
        reasons.append("unsupported language or migration")
    if not target.is_dir() or not (target / "src").is_dir():
        reasons.append("target or sandbox source missing")
    if not (target / "pyproject.toml").is_file() or not (target / "tests").is_dir():
        reasons.append("dependency or verification files missing")
    if not (target / ".git").is_dir() or shutil.which("git") is None:
        reasons.append("target branch operations unavailable")
    python = verification_python or Path(sys.executable)
    for module in ("pytest", "mypy", "ruff"):
        try:
            result = subprocess.run(
                [str(python), "-m", module, "--version"], text=True,
                capture_output=True, check=False, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            reasons.append(f"{module} unavailable in verification environment")
        else:
            if result.returncode != 0:
                reasons.append(f"{module} unavailable in verification environment")
    return CapabilityDecision(
        supported=not reasons,
        reasons=reasons or ["supported migration and verification environment"],
    )


def _match_path(match: str) -> str:
    return match.split(":", 1)[0].removeprefix("./")


def analyze(root: Path) -> RepositoryAnalysis:
    """Combine filesystem, TOML, AST, rg, and symbol references into evidence."""
    files = discover_files(root)
    dependencies = files["dependency"]
    if not dependencies:
        raise ValueError("dependency file missing")
    dependency_file = str(dependencies[0])
    data = tomllib.loads((root / dependency_file).read_text())
    declared = data.get("project", {}).get("dependencies", [])
    version = next(
        (str(item).removeprefix("pydantic") for item in declared
         if str(item).startswith("pydantic")), "unknown",
    )
    sources = [str(path) for path in files["source"]]
    tests = [str(path) for path in files["test"]]
    imports: dict[str, list[str]] = {}
    classes: dict[str, list[str]] = {}
    decorators: dict[str, list[str]] = {}
    usages: dict[str, list[str]] = {}
    related: dict[str, list[str]] = {}
    evidence: dict[str, list[str]] = {name: [] for name in [dependency_file, *sources, *tests]}
    evidence[dependency_file].append(f"TOML dependency: pydantic{version}")

    # Prompt 1's search primitive uses rg when installed and a deterministic fallback otherwise.
    for match in search_text(root, SEARCH_PATTERN):
        name = _match_path(match)
        if name in evidence:
            evidence[name].append(f"rg:{match}")

    for name in sources:
        path = root / name
        structure = inspect_python(path)
        imports[name] = list(structure.imports)
        classes[name] = [f"{symbol}:{','.join(bases)}" for symbol, bases in structure.classes]
        decorators[name] = [f"{symbol}:{','.join(decs)}" for symbol, decs in structure.functions if decs]
        usages[name] = sorted(set(V1_PATTERN.findall(path.read_text())))
        for symbol, bases in structure.classes:
            evidence[name].append(f"AST class {symbol} inherits {', '.join(bases) or 'object'}")
        for imported in structure.imports:
            if "pydantic" in imported:
                evidence[name].append(f"AST import {imported}")
        for symbol, decs in structure.functions:
            if decs:
                evidence[name].append(f"AST decorator {symbol}: {', '.join(decs)}")
        related[name] = []
        for symbol, _bases in structure.classes:
            for match in search_text(root, rf"\b{re.escape(symbol)}\b"):
                reference = _match_path(match)
                if reference in tests:
                    if reference not in related[name]:
                        related[name].append(reference)
                    evidence[reference].append(f"rg reference to {symbol}: {match}")
        related[name].sort()
    for name in tests:
        structure = inspect_python(root / name)
        evidence[name].append(f"AST tests: {', '.join(symbol for symbol, _ in structure.functions)}")
    return RepositoryAnalysis(
        dependency_file=dependency_file, pydantic_version=version,
        source_files=sources, test_files=tests,
        configuration_files=[str(path) for path in files["configuration"]],
        imports=imports, classes=classes, decorators=decorators,
        v1_usages=usages, related_tests=related, evidence=evidence,
    )


def _candidate(path: str, lines: list[str], start: int, end: int,
               symbol: str, kind: str, analysis: RepositoryAnalysis) -> ContextItem:
    content = "\n".join(lines[start - 1:end]) + "\n"
    reasons: list[str] = []
    score = 0
    if path == analysis.dependency_file and "pydantic" in content:
        score += 120
        reasons.append("Pydantic dependency declaration")
    if V1_PATTERN.search(content):
        score += 115
        reasons.append("direct migrated API usage")
    if "pydantic" in content and kind == "import":
        score += 80
        reasons.append("direct Pydantic import")
    if "ShopModel" in content and kind == "class":
        score += 75
        reasons.append("shared model inheritance or configuration")
    if path in analysis.test_files:
        related = any(path in refs for refs in analysis.related_tests.values())
        score += 65 if related else 5
        reasons.append("test exercising affected model" if related else "test discovery")
    if kind == "function" and "validator" in content:
        score += 20
        reasons.append("validator function")
    if not reasons:
        reasons.append(f"{kind} near migration evidence" if analysis.evidence.get(path)
                       else f"{kind} candidate")
    return ContextItem(
        path=path, location=f"{start}-{end}", symbol=symbol,
        start_line=start, end_line=end, content=content, score=score,
        reason="; ".join(reasons), token_estimate=max(1, len(content) // 4),
    )


def _snippets(root: Path, path: str, analysis: RepositoryAnalysis) -> list[ContextItem]:
    lines = (root / path).read_text().splitlines()
    if path == analysis.dependency_file or path in analysis.configuration_files:
        return [_candidate(path, lines, index, index, "dependency/configuration", "config", analysis)
                for index, line in enumerate(lines, 1) if line.strip() and not line.lstrip().startswith("#")]
    tree = ast.parse("\n".join(lines), filename=path)
    items: list[ContextItem] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            items.append(_candidate(path, lines, node.lineno, node.end_lineno or node.lineno,
                                    ast.unparse(node), "import", analysis))
        elif isinstance(node, ast.ClassDef):
            first_method = next((child.lineno for child in node.body
                                 if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))),
                                (node.end_lineno or node.lineno) + 1)
            header_end = min(first_method - 1, node.end_lineno or node.lineno)
            if header_end >= node.lineno:
                items.append(_candidate(path, lines, node.lineno, header_end,
                                        node.name, "class", analysis))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min((dec.lineno for dec in child.decorator_list), default=child.lineno)
                    items.append(_candidate(path, lines, start, child.end_lineno or child.lineno,
                                            f"{node.name}.{child.name}", "function", analysis))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min((dec.lineno for dec in node.decorator_list), default=node.lineno)
            items.append(_candidate(path, lines, start, node.end_lineno or node.lineno,
                                    node.name, "function", analysis))
    return items


def select_context(root: Path, analysis: RepositoryAnalysis, max_files: int = 5,
                   max_snippets: int = 18, max_context_tokens: int = 5000) -> ContextBundle:
    """Rank individual syntax snippets, then enforce three independent budgets."""
    if min(max_files, max_snippets, max_context_tokens) < 1:
        raise ValueError("context budgets must be positive")
    paths = [analysis.dependency_file, *analysis.source_files, *analysis.test_files,
             *analysis.configuration_files]
    candidates = [item for path in dict.fromkeys(paths)
                  for item in _snippets(root, path, analysis)]
    candidates.sort(key=lambda item: (-item.score, item.path, item.start_line, item.symbol))
    selected: list[ContextItem] = []
    files: set[str] = set()
    total = 0
    # Reserve a first snippet for each high-evidence file before filling remaining slots.
    first_by_file: dict[str, ContextItem] = {}
    for item in candidates:
        first_by_file.setdefault(item.path, item)
    for item in first_by_file.values():
        if len(files) >= max_files or len(selected) >= max_snippets:
            break
        if total + item.token_estimate <= max_context_tokens:
            selected.append(item)
            files.add(item.path)
            total += item.token_estimate
    for item in candidates:
        if len(selected) >= max_snippets:
            break
        if item in selected or item.path not in files:
            continue
        if total + item.token_estimate > max_context_tokens:
            continue
        selected.append(item)
        total += item.token_estimate
    selected.sort(key=lambda item: (-item.score, item.path, item.start_line, item.symbol))
    if not selected:
        raise ValueError("context budget selected no snippets")
    return ContextBundle(items=selected, total_token_estimate=total,
                         max_files=max_files, max_snippets=max_snippets,
                         max_context_tokens=max_context_tokens)
