"""Migration-agnostic test preservation and repository file-scope checks."""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path, PurePosixPath

from .benchmarks import MigrationFamily
from .schema import (
    AllowedFileRule,
    AllowedModificationScope,
    AllowedTestRewrite,
    MigrationPlan,
    RepositoryAnalysis,
)

_SENSITIVE = re.compile(r"(?:^|/)(?:\.env(?:\.|$)|credentials?(?:\.|/)|secrets?(?:\.|/))",
                        re.IGNORECASE)
_DEPLOYMENT = re.compile(r"(?:^|/)(?:deploy|deployment|production)(?:/|\.|$)", re.IGNORECASE)


class _NormalizeConfiguredAPIs(ast.NodeTransformer):
    """Map permitted new API spellings back to their old spelling for AST comparison."""

    def __init__(self, rewrites: tuple[AllowedTestRewrite, ...]) -> None:
        self.reverse = {rule.new_api: rule.old_api for rule in rewrites}
        self.used: set[str] = set()

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if node.attr in self.reverse:
            self.used.add(node.attr)
            node.attr = self.reverse[node.attr]
        return node

    def visit_keyword(self, node: ast.keyword) -> ast.AST:
        self.generic_visit(node)
        if node.arg is not None and node.arg in self.reverse:
            self.used.add(node.arg)
            node.arg = self.reverse[node.arg]
        return node


def validate_test_change(original: str, proposed: str,
                         rewrites: tuple[AllowedTestRewrite, ...] = ()
                         ) -> list[AllowedTestRewrite]:
    """Accept only configured API spelling changes with identical test AST semantics."""
    old_tree = ast.parse(original)
    new_tree = ast.parse(proposed)
    normalizer = _NormalizeConfiguredAPIs(rewrites)
    normalized = normalizer.visit(new_tree)
    if ast.dump(old_tree, include_attributes=False) != ast.dump(normalized, include_attributes=False):
        raise ValueError("regression test behavior or expectations changed")
    return [rule for rule in rewrites if rule.new_api in normalizer.used]


def normalized_file(root: Path, path: str) -> Path | None:
    """Reject traversal, alternate separators, symlinks, and repository escapes."""
    relative = PurePosixPath(path)
    if (not path or "\\" in path or relative.is_absolute() or
            any(part in (".", "..") for part in relative.parts) or
            str(relative) != path):
        return None
    resolved_root = root.resolve()
    candidate = root / path
    if candidate.is_symlink() or not candidate.is_file():
        return None
    resolved = candidate.resolve()
    return resolved if resolved.is_relative_to(resolved_root) else None


def hard_path_reason(path: str) -> str | None:
    if _SENSITIVE.search(path):
        return "credential or secret file modification is prohibited"
    if _DEPLOYMENT.search(path):
        return "production or deployment file modification is prohibited"
    return None


def build_allowed_scope(root: Path, analysis: RepositoryAnalysis,
                        family: MigrationFamily, plan: MigrationPlan | None = None,
                        approved_expansions: tuple[str, ...] = (),
                        failure_evidence: str = "") -> AllowedModificationScope:
    """Rank discovered categories by migration evidence; approve only planned changes."""
    dependencies = set(analysis.dependency_files or [analysis.dependency_file])
    sources = set(analysis.source_files)
    tests = set(analysis.test_files)
    configurations = set(analysis.configuration_files)
    related_tests = {item for references in analysis.related_tests.values() for item in references}
    discovered = dependencies | sources | tests | configurations
    files: dict[str, AllowedFileRule] = {}
    for path in sorted(discovered):
        if hard_path_reason(path) or normalized_file(root, path) is None:
            continue
        configured = any(fnmatch.fnmatch(path, pattern) or
                         fnmatch.fnmatch(Path(path).name, pattern)
                         for pattern in family.migration_config_files)
        if path in dependencies:
            category = "dependency"
            relevant = family.dependency_name.lower() in (root / path).read_text().lower()
            reason = f"dependency declaration for {family.dependency_name}"
        elif configured or path in configurations:
            category = "configuration"
            content = (root / path).read_text()
            relevant = configured or family.dependency_name.lower() in content.lower()
            reason = ("migration-family configuration file" if configured else
                      f"configuration references {family.dependency_name}")
        elif path in tests:
            category = "test"
            relevant = path in related_tests or any(
                evidence.startswith("rg:") for evidence in analysis.evidence.get(path, []))
            reason = "regression test referencing affected code or migration API"
        else:
            category = "source"
            relevant = bool(analysis.migration_api_usages.get(path)) or any(
                evidence.startswith("rg:") or
                (evidence.startswith("AST import") and
                 family.dependency_name.lower() in evidence.lower())
                for evidence in analysis.evidence.get(path, []))
            reason = "source has migration API, import, or symbol-search evidence"
        if path in approved_expansions and path in failure_evidence:
            relevant = True
            reason += "; referenced by failing verification evidence"
        if relevant:
            files[path] = AllowedFileRule(path=path, category=category,
                                          reason=reason, migration_relevant=True)
    approved = (set(plan.affected_files) if plan is not None else set(files))
    approved.update(approved_expansions)
    return AllowedModificationScope(migration_family=family.name, files=files,
                                    approved_files=sorted(approved & files.keys()))


def file_scope_reason(root: Path, scope: AllowedModificationScope,
                      path: str, require_approval: bool = True) -> str | None:
    if normalized_file(root, path) is None:
        return "path traversal, absent file, or repository escape"
    prohibited = hard_path_reason(path)
    if prohibited:
        return prohibited
    if path not in scope.files:
        return "file lacks deterministic migration relevance or configured category"
    if require_approval and path not in scope.approved_files:
        return "file is outside the approved migration plan or scope expansion"
    return None
