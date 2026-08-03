"""StateCache: per-machine SQLite (size, mtime_ns) state backing incremental updates.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 2190-2344. Only import wiring and shared-state references
(``state.<name>``) were adjusted -- no logic changes (Phase 1, AC-R4).
"""

import os
import sys
import re
import json
import time
import stat
import hashlib
import logging
import argparse
import platform
import queue as queue_module
import sqlite3
import subprocess
import shutil
import threading
from collections import deque
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Union, Any


class StateCache:
    """Per-machine (size, mtime_ns) state cache backing incremental updates.

    Lives in ONE SQLite file at the shadow root (or the scan root when no
    shadow dir is used). It is a disposable accelerator, NOT part of the
    checksum record: hashes in .shasum files remain the only durable truth.
    Delete the file and `update --bootstrap=...` rebuilds it.

    Never sync or commit this file. Stat state (mtime especially) is only
    meaningful on the machine that recorded it -- synced copies of a library
    (e.g. via Resilio) carry origin mtimes that would poison another peer's
    cache into silently skipping changed files.

    Folder keys are POSIX-style paths relative to the scan root, so the cache
    stays valid when the same tree is reached via different mounts
    (drive letter, subst, UNC).
    """

    # Schema v2: folder paths are interned into `folders` (an integer id)
    # instead of being repeated in every file row. On a multi-million-file
    # library this shrinks the cache ~35-40% and, more importantly, keeps the
    # (folder_id, name) primary-key b-tree far smaller than text keys.
    SCHEMA_VERSION = 2
    SCHEMA = """
        CREATE TABLE IF NOT EXISTS folders (
            id   INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS file_state (
            folder_id  INTEGER NOT NULL REFERENCES folders(id),
            name       TEXT NOT NULL,
            size       INTEGER NOT NULL,
            mtime_ns   INTEGER NOT NULL,
            algo       TEXT NOT NULL,
            hash       TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            PRIMARY KEY (folder_id, name)
        );
    """

    # Commit every N replace_folder() calls instead of every call. Each
    # commit is a journal fsync; per-folder commits cost hours at library
    # scale (measured: ~12% CPU, 88% fsync-blocked). The cache is a
    # disposable accelerator, so losing the tail of a batch in a crash just
    # means those folders re-seed on the next run. COMMIT_INTERVAL_S bounds
    # the loss window in TIME as well: without it, a hard kill on a tree
    # smaller than COMMIT_EVERY dirs forfeited the entire run's cache
    # (adversarial finding, 2026-07-17). Ctrl-C always flushes via close().
    COMMIT_EVERY = 200
    COMMIT_INTERVAL_S = 5.0

    def __init__(self, cache_path: Path):
        self.cache_path = Path(cache_path)
        self.conn = sqlite3.connect(str(self.cache_path), timeout=30.0)
        self.conn.execute("PRAGMA busy_timeout = 30000")
        # Disposable cache: durability guarantees are wasted on it (delete
        # and re-bootstrap is always safe), so skip the per-commit fsyncs
        # and keep the rollback journal in memory.
        self.conn.execute("PRAGMA synchronous = OFF")
        self.conn.execute("PRAGMA journal_mode = MEMORY")
        self._ensure_schema()
        self._pending = 0
        self._last_commit = time.monotonic()
        self._folder_ids: Dict[str, int] = {}

    def _ensure_schema(self):
        """Create the v2 schema; drop and rebuild any older layout (the cache
        is regenerable by design, so there is no migration path -- just a
        rebuild)."""
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version != self.SCHEMA_VERSION:
            self.conn.executescript(
                "DROP TABLE IF EXISTS file_state; DROP TABLE IF EXISTS folders;")
            self.conn.executescript(self.SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
            self.conn.commit()

    @staticmethod
    def folder_key(directory: Path, root: Path) -> str:
        """Stable per-tree key: POSIX relative path from scan root ('.' for root).

        v1.5.0: pure string computation (os.path.relpath) -- the previous
        Path.resolve().relative_to() cost TWO _getfinalpathname syscalls per
        call (profiled at ~20s per 20K directories). Callers pass directories
        descended from an already-resolved root (the walker guarantees this),
        so no filesystem round-trip is needed.
        """
        rel = os.path.relpath(str(directory), str(root))
        return '.' if rel == '.' else rel.replace('\\', '/')

    def _folder_id(self, folder: str, create: bool = False) -> Optional[int]:
        """Look up (optionally interning) the integer id for a folder path."""
        fid = self._folder_ids.get(folder)
        if fid is not None:
            return fid
        row = self.conn.execute(
            "SELECT id FROM folders WHERE path = ?", (folder,)).fetchone()
        if row is None:
            if not create:
                return None
            cur = self.conn.execute(
                "INSERT INTO folders (path) VALUES (?)", (folder,))
            fid = cur.lastrowid
        else:
            fid = row[0]
        self._folder_ids[folder] = fid
        return fid

    def get_folder(self, folder: str) -> Dict[str, Dict[str, Any]]:
        """Return {name: {'size', 'mtime_ns', 'algo', 'hash'}} for a folder."""
        fid = self._folder_id(folder)
        if fid is None:
            return {}
        rows = self.conn.execute(
            "SELECT name, size, mtime_ns, algo, hash FROM file_state WHERE folder_id = ?",
            (fid,))
        return {name: {'size': size, 'mtime_ns': mtime_ns, 'algo': algo, 'hash': hash_}
                for name, size, mtime_ns, algo, hash_ in rows}

    def replace_folder(self, folder: str, entries: Dict[str, Dict[str, Any]]):
        """Replace all rows for a folder with `entries`. Commits are batched
        (COMMIT_EVERY folders) -- call close() or flush() to persist the tail."""
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        fid = self._folder_id(folder, create=True)
        self.conn.execute("DELETE FROM file_state WHERE folder_id = ?", (fid,))
        self.conn.executemany(
            "INSERT INTO file_state (folder_id, name, size, mtime_ns, algo, hash, scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(fid, name, e['size'], e['mtime_ns'], e['algo'], e['hash'], now)
             for name, e in entries.items()])
        self._pending += 1
        if (self._pending >= self.COMMIT_EVERY
                or time.monotonic() - self._last_commit >= self.COMMIT_INTERVAL_S):
            self.flush()

    def flush(self):
        """Commit any batched writes."""
        if self.conn.in_transaction:
            self.conn.commit()
        self._pending = 0
        self._last_commit = time.monotonic()

    def close(self):
        try:
            self.flush()
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
