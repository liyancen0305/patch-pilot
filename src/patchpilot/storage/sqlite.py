"""Minimal SQLite initialization for future workflow metadata."""

import sqlite3
from pathlib import Path


def initialize_database(path: Path) -> None:
    """Create a database with a schema version, without defining run state yet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")
