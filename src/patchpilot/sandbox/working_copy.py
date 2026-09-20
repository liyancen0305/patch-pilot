"""Isolated fixture copies with Git checkpoints."""

import shutil
import subprocess
import tempfile
from pathlib import Path


class Sandbox:
    """Own one temporary working copy; all Git operations stay inside it."""

    def __init__(self, canonical: Path, parent: Path | None = None) -> None:
        self.canonical = canonical.resolve(strict=True)
        if not self.canonical.is_dir():
            raise ValueError("canonical fixture must be a directory")
        self._temporary = tempfile.TemporaryDirectory(prefix="patchpilot-", dir=parent)
        self.path = Path(self._temporary.name) / "repo"
        shutil.copytree(self.canonical, self.path, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "*.egg-info"))
        self._git("init", "-q")
        self._git("config", "user.name", "PatchPilot Sandbox")
        self._git("config", "user.email", "sandbox@patchpilot.invalid")
        self._git("add", "-A")
        self._git("commit", "-qm", "Canonical baseline")
        self.original_snapshot = self._git("rev-parse", "HEAD").strip()
        self._set_stable(self.original_snapshot)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.path, text=True, capture_output=True, check=False
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    def _safe_path(self, relative: str) -> Path:
        candidate = (self.path / relative).resolve()
        if not candidate.is_relative_to(self.path) or candidate == self.path:
            raise ValueError("file path must remain inside sandbox")
        return candidate

    @property
    def last_stable_snapshot(self) -> str:
        """Code-changing callers must inspect this before each modification."""
        return self._git("rev-parse", "refs/patchpilot/stable").strip()

    def _set_stable(self, revision: str) -> None:
        self._git("update-ref", "refs/patchpilot/stable", revision)

    def changed_files(self) -> tuple[str, ...]:
        tracked = self._git("diff", "--name-only", "HEAD").splitlines()
        untracked = self._git("ls-files", "--others", "--exclude-standard").splitlines()
        return tuple(sorted(set(tracked + untracked)))

    def diff(self) -> str:
        """Return tracked changes plus diffs for untracked text files."""
        output = self._git("diff", "HEAD")
        for name in self._git("ls-files", "--others", "--exclude-standard").splitlines():
            path = self._safe_path(name)
            result = subprocess.run(
                ["git", "diff", "--no-index", "--", "/dev/null", str(path)],
                cwd=self.path, text=True, capture_output=True, check=False,
            )
            if result.returncode not in (0, 1):
                raise RuntimeError(result.stderr.strip())
            output += result.stdout
        return output

    def original_file(self, relative: str) -> str:
        self._safe_path(relative)
        return self._git("show", f"{self.original_snapshot}:{relative}")

    def current_file(self, relative: str) -> str:
        return self._safe_path(relative).read_text()

    def checkpoint(self, message: str) -> str:
        if not message.strip():
            raise ValueError("checkpoint message is required")
        self._git("add", "-A")
        if self._git("status", "--porcelain").strip():
            self._git("commit", "-qm", message)
        revision = self._git("rev-parse", "HEAD").strip()
        self._set_stable(revision)
        return revision

    def rollback(self) -> None:
        """Restore the last stable commit, including removal of untracked files."""
        stable = self.last_stable_snapshot
        self._git("reset", "--hard", stable)
        self._git("clean", "-fd")

    def reset(self) -> None:
        """Restore the canonical baseline within this sandbox."""
        self._set_stable(self.original_snapshot)
        self.rollback()

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> "Sandbox":  # noqa: PYI034
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
