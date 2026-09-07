#!/usr/bin/env python3
"""
Persistent cache of per-file analyses for DynaMix.

Analysing a track takes seconds; a set is analysed many times (features, then
intro/outro profile, then mastering). This store keeps every result keyed by
the file's absolute path, size and modification time, so nothing is computed
twice unless the file changed or the analyser itself changed.

Location: %LOCALAPPDATA%\\DynaMix\\analysis.sqlite on Windows,
~/.dynamix/analysis.sqlite elsewhere, or $DYNAMIX_HOME/analysis.sqlite.
"""

import datetime as _dt
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Optional

import numpy as np

# Bump when an analyser changes in a way that makes old results wrong.
ANALYZER_VERSION = "2026.09.07"


def dynamix_home() -> str:
    """Folder holding DynaMix's user data (created on demand)."""
    home = os.environ.get("DYNAMIX_HOME")
    if not home:
        if sys.platform.startswith("win") and os.environ.get("LOCALAPPDATA"):
            home = os.path.join(os.environ["LOCALAPPDATA"], "DynaMix")
        else:
            home = os.path.join(os.path.expanduser("~"), ".dynamix")
    os.makedirs(home, exist_ok=True)
    return home


def _json_default(obj):
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (set, tuple)):
        return list(obj)
    return str(obj)


class AnalysisStore:
    """SQLite-backed cache: (file, kind) -> JSON document."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(dynamix_home(), "analysis.sqlite")
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS analyses ("
                " path TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL, mtime INTEGER NOT NULL,"
                " version TEXT NOT NULL, data TEXT NOT NULL, created TEXT NOT NULL,"
                " PRIMARY KEY (path, kind))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5.0)

    @staticmethod
    def _identity(path: str):
        abs_path = os.path.abspath(path)
        st = os.stat(abs_path)
        return abs_path, int(st.st_size), int(st.st_mtime_ns)

    def get(self, path: str, kind: str) -> Optional[Dict[str, Any]]:
        """Return the cached document, or None when absent or stale."""
        try:
            abs_path, size, mtime = self._identity(path)
        except OSError:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT size, mtime, version, data FROM analyses WHERE path = ? AND kind = ?",
                (abs_path, kind),
            ).fetchone()
            if row is None:
                return None
            if (row[0], row[1], row[2]) != (size, mtime, ANALYZER_VERSION):
                conn.execute("DELETE FROM analyses WHERE path = ? AND kind = ?", (abs_path, kind))
                return None
        return json.loads(row[3])

    def has(self, path: str, kind: str) -> bool:
        return self.get(path, kind) is not None

    def put(self, path: str, kind: str, data: Dict[str, Any]) -> None:
        abs_path, size, mtime = self._identity(path)
        payload = json.dumps(data, default=_json_default)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyses (path, kind, size, mtime, version, data, created)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (abs_path, kind, size, mtime, ANALYZER_VERSION, payload,
                 _dt.datetime.now().isoformat(timespec="seconds")),
            )

    def kinds_for(self, path: str) -> Dict[str, bool]:
        """Which kinds are cached and fresh for this file."""
        result = {}
        with self._connect() as conn:
            rows = conn.execute("SELECT kind FROM analyses WHERE path = ?", (os.path.abspath(path),)).fetchall()
        for (kind,) in rows:
            result[kind] = self.has(path, kind)
        return result

    def stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            entries = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
            files = conn.execute("SELECT COUNT(DISTINCT path) FROM analyses").fetchone()[0]
        size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return {"entries": int(entries), "files": int(files), "db_path": self.db_path, "size_bytes": int(size)}

    def clear(self, path: Optional[str] = None) -> int:
        """Forget everything (or everything about one file). Returns rows removed."""
        with self._connect() as conn:
            if path is None:
                cur = conn.execute("DELETE FROM analyses")
            else:
                cur = conn.execute("DELETE FROM analyses WHERE path = ?", (os.path.abspath(path),))
            return cur.rowcount


_STORE: Optional[AnalysisStore] = None


def get_store() -> AnalysisStore:
    """Process-wide store (honours DYNAMIX_HOME at first use)."""
    global _STORE
    if _STORE is None:
        _STORE = AnalysisStore()
    return _STORE


def reset_store() -> None:
    """Forget the singleton (tests, or after changing DYNAMIX_HOME)."""
    global _STORE
    _STORE = None
