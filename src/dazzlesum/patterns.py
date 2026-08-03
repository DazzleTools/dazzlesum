"""Compiled include/exclude pattern matching.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 1458-1503, 1506-1509, 1512-1533. Only import wiring and shared-state references
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

from .constants import SHASUM_FILENAME, STATE_FILENAME, CACHE_FILENAME


class CompiledPatternMatcher:
    """String-level fast path for include/exclude pattern matching.

    Path.match() in the per-file hot loop costs a Path allocation plus a
    per-pattern parse for every file (3.37M files x 8 patterns on the
    reference library). This compiles all BASENAME patterns (no '/') into one
    alternation regex matched against the entry name string; multi-component
    patterns (e.g. "Vault/Restricted/00 NO SCAN") are rare, sit outside
    the per-file hot path, and keep exact Path.match semantics via fallback.

    Case behavior mirrors pathlib: case-insensitive on Windows (Path.match
    uses normcase), case-sensitive elsewhere. Equivalence with the legacy
    per-pattern Path.match loop is pinned by tests.
    """

    def __init__(self, patterns):
        import fnmatch as _fnmatch
        self.patterns = list(patterns or [])
        self.multi = [p for p in self.patterns if '/' in p.replace('\\', '/')]
        basename = [p for p in self.patterns if p not in self.multi]
        if basename:
            joined = '|'.join(f'(?:{_fnmatch.translate(p)})' for p in basename)
            flags = re.IGNORECASE if os.name == 'nt' else 0
            self._name_re = re.compile(joined, flags)
        else:
            self._name_re = None

    def matches_name(self, name: str) -> bool:
        """True if the basename matches any basename pattern."""
        return bool(self._name_re and self._name_re.match(name))

    def matches_path(self, path: Path) -> bool:
        """Full check: basename regex first, then multi-component fallback."""
        if self._name_re and self._name_re.match(path.name):
            return True
        for pattern in self.multi:
            if path.match(pattern):
                return True
        return False

    def matches_multi(self, path: Path) -> bool:
        """Check only the multi-component patterns (exact Path.match semantics)."""
        for pattern in self.multi:
            if path.match(pattern):
                return True
        return False


def _always_excluded_name(filename: str) -> bool:
    """Tool-owned files that must never be checksummed (string-only check)."""
    return (filename in (SHASUM_FILENAME, STATE_FILENAME, SHASUM_FILENAME + '.tmp')
            or filename.startswith(CACHE_FILENAME))


def _should_include_file_simple(file_path: Path, include_patterns, exclude_patterns) -> bool:
    """Simplified version of file inclusion check for counting."""
    filename = file_path.name

    # Always exclude our own files (CACHE_FILENAME prefix also covers
    # SQLite sidecars like .dazzle-cache.sqlite-journal)
    if _always_excluded_name(filename):
        return False

    # Apply exclude patterns
    for pattern in exclude_patterns:
        if file_path.match(pattern):
            return False

    # Apply include patterns (if any)
    if include_patterns:
        for pattern in include_patterns:
            if file_path.match(pattern):
                return True
        return False

    return True
