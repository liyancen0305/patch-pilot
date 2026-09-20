import sqlite3
import subprocess
from pathlib import Path

from patchpilot.sandbox import Sandbox
from patchpilot.storage import initialize_database
from patchpilot.tools.repository import discover_files, inspect_python, search_text

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "pydantic_v1_app"


def test_sandbox_isolation_and_diff() -> None:
    original = (FIXTURE / "src/shop/users.py").read_text()
    with Sandbox(FIXTURE) as sandbox:
        target = sandbox.path / "src/shop/users.py"
        target.write_text(original + "\n# sandbox change\n")
        assert sandbox.changed_files() == ("src/shop/users.py",)
        assert "+# sandbox change" in sandbox.diff()
        assert sandbox.original_file("src/shop/users.py") == original
        assert sandbox.current_file("src/shop/users.py").endswith("# sandbox change\n")
    assert (FIXTURE / "src/shop/users.py").read_text() == original


def test_checkpoint_rollback_and_reset() -> None:
    with Sandbox(FIXTURE) as sandbox:
        target = sandbox.path / "src/shop/users.py"
        baseline = sandbox.last_stable_snapshot
        target.write_text(target.read_text() + "\n# stable\n")
        stable = sandbox.checkpoint("Stable edit")
        assert stable != baseline
        assert sandbox.last_stable_snapshot == stable
        target.write_text(target.read_text() + "# unstable\n")
        extra = sandbox.path / "extra.py"
        extra.write_text("unstable\n")
        sandbox.rollback()
        assert target.read_text().endswith("# stable\n")
        assert not extra.exists()
        assert sandbox.changed_files() == ()
        sandbox.reset()
        assert sandbox.last_stable_snapshot == baseline
        assert "# stable" not in target.read_text()


def test_rejects_paths_outside_sandbox() -> None:
    with Sandbox(FIXTURE) as sandbox:
        try:
            sandbox.current_file("../outside")
        except ValueError:
            pass
        else:
            raise AssertionError("path traversal allowed")


def test_repository_inspection() -> None:
    files = discover_files(FIXTURE)
    assert Path("src/shop/users.py") in files["source"]
    assert Path("tests/test_shop.py") in files["test"]
    assert Path("pyproject.toml") in files["dependency"]
    assert any("root_validator" in match for match in search_text(FIXTURE, "root_validator"))
    structure = inspect_python(FIXTURE / "src/shop/orders.py")
    assert ("Order", ("ShopModel",)) in structure.classes
    assert any(name == "total_matches_items" and "root_validator" in decorators
               for name, decorators in structure.functions)


def test_storage_initialization(tmp_path: Path) -> None:
    database = tmp_path / "metadata.db"
    initialize_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)


def test_prompt_metadata() -> None:
    text = (ROOT / "docs/prompts/01_environment_fixture.md").read_text()
    assert "Prompt: 01_environment_fixture" in text
    assert "Version: v1" in text
    assert "Purpose: Environment, fixture repository, sandbox, verification, and snapshot foundation" in text


def test_canonical_fixture_verification() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts/verify_fixture.sh")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
