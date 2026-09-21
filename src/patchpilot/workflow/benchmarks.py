"""Fixed migration-family data consumed by the generic workflow."""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .schema import AllowedTestRewrite

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:
    import tomli as tomllib  # type: ignore[import-not-found]


@dataclass(frozen=True)
class MigrationFamily:
    use_case: int
    name: str
    goal: str
    dependency_name: str
    source_version: str
    target_version: str
    source_pin: str
    target_pin: str
    runtime_import: str
    deprecated_api_pattern: str
    api_usage_pattern: str
    search_pattern: str
    shared_base_symbols: tuple[str, ...]
    runtime_check: str
    branch_slug: str
    commit_label: str
    dependency_check_name: str
    allowed_test_api_rewrites: tuple[AllowedTestRewrite, ...] = ()
    migration_config_files: tuple[str, ...] = ()

    @property
    def target_requirement(self) -> str:
        return self.target_pin[len(self.dependency_name):]

    @property
    def migration_check_name(self) -> str:
        return f"{self.commit_label} migration"


FAMILIES = (
    MigrationFamily(1, "pydantic", "Upgrade Pydantic v1 to Pydantic v2",
                    "pydantic", "1.10.26", "2", "pydantic==1.10.26", "pydantic>=2,<3",
                    "shop", r"@(?:root_validator|validator)\b|class Config\b|\.parse_obj\(|\.dict\(",
                    r"\b(?:validator|root_validator|parse_obj|anystr_strip_whitespace)\b|\.dict\(|class Config\b",
                    r"pydantic|validator|parse_obj|\.dict\(|Config|model_validate|model_dump",
                    ("ShopModel",), "import shop; assert shop.User and shop.Order",
                    "pydantic-v2", "Pydantic v2", "installed Pydantic v2",
                    (AllowedTestRewrite(old_api="parse_obj", new_api="model_validate",
                                        reason="Pydantic v2 model parsing API"),
                     AllowedTestRewrite(old_api="dict", new_api="model_dump",
                                        reason="Pydantic v2 serialization API")),
                    ("setup.cfg", "tox.ini")),
    MigrationFamily(2, "sqlalchemy", "Upgrade SQLAlchemy 1.4 to SQLAlchemy 2.0",
                    "SQLAlchemy", "1.4.54", "2.0.44", "SQLAlchemy==1.4.54", "SQLAlchemy==2.0.44",
                    "ledger", r"\.query\(", r"\.query\(",
                    r"sqlalchemy|\.query\(|select\(|scalars\(", ("Base",),
                    "import ledger; assert ledger", "sqlalchemy-2", "SQLAlchemy 2.0",
                    "installed SQLAlchemy 2.0", (),
                    ("alembic.ini", "setup.cfg", "tox.ini")),
    MigrationFamily(3, "httpx", "Upgrade HTTPX 0.27 to HTTPX 0.28",
                    "httpx", "0.27.2", "0.28.1", "httpx==0.27.2", "httpx==0.28.1",
                    "remote", r"\bproxies\s*=", r"\bproxies\s*=",
                    r"httpx|proxies\s*=|MockTransport|proxy\s*=", (),
                    "import remote; assert remote", "httpx-028", "HTTPX 0.28",
                    "installed HTTPX 0.28",
                    (AllowedTestRewrite(old_api="proxies", new_api="proxy",
                                        reason="HTTPX 0.28 proxy keyword API"),),
                    ("setup.cfg", "tox.ini")),
    MigrationFamily(4, "openai", "Upgrade OpenAI Python SDK 0.28 to 1.x",
                    "openai", "0.28.1", "1.109.1", "openai==0.28.1", "openai==1.109.1",
                    "assistant_app", r"openai\.ChatCompletion", r"openai\.ChatCompletion",
                    r"openai|ChatCompletion|chat\.completions|OpenAI\(", (),
                    "import assistant_app; assert assistant_app", "openai-sdk-1x",
                    "OpenAI Python SDK 1.x", "installed OpenAI Python SDK 1.x",
                    (), ("setup.cfg", "tox.ini")),
    MigrationFamily(5, "celery", "Upgrade Celery 4 to Celery 5",
                    "celery", "4.4.7", "5.5.3", "celery==4.4.7", "celery==5.5.3",
                    "jobs", r"\b(?:BROKER_URL|CELERY_RESULT_BACKEND|CELERY_ALWAYS_EAGER|CELERY_EAGER_PROPAGATES_EXCEPTIONS)\b",
                    r"\b(?:BROKER_URL|CELERY_RESULT_BACKEND|CELERY_ALWAYS_EAGER|CELERY_EAGER_PROPAGATES_EXCEPTIONS)\b",
                    r"celery|BROKER_URL|CELERY_|task_always_eager|broker_url", (),
                    "import jobs; assert jobs", "celery-5", "Celery 5",
                    "installed Celery 5", (),
                    ("celeryconfig.py", "**/celeryconfig.py", "setup.cfg", "tox.ini")),
)


def for_goal(goal: str) -> MigrationFamily | None:
    return next((family for family in FAMILIES if family.goal == goal), None)


def for_root(root: Path) -> MigrationFamily | None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    dependencies = tomllib.loads(path.read_text()).get("project", {}).get("dependencies", [])
    for family in FAMILIES:
        if any(re.match(rf"^{re.escape(family.dependency_name)}(?:[=<>!~]|$)",
                        str(item), re.IGNORECASE) for item in dependencies):
            return family
    return None


def declared_pin(root: Path, family: MigrationFamily) -> str | None:
    dependencies = tomllib.loads((root / "pyproject.toml").read_text()).get("project", {}).get("dependencies", [])
    return next((str(item) for item in dependencies
                 if re.match(rf"^{re.escape(family.dependency_name)}(?:[=<>!~]|$)",
                             str(item), re.IGNORECASE)), None)


def dependency_verification_command(python: Path, family: MigrationFamily) -> list[str]:
    """Check the configured target version in the actual verification interpreter."""
    return [str(python), "-c",
            ("import importlib.metadata,sys; from packaging.specifiers import SpecifierSet; "
             "sys.exit(importlib.metadata.version(sys.argv[1]) "
             "not in SpecifierSet(sys.argv[2]))"),
            family.dependency_name, family.target_requirement]
