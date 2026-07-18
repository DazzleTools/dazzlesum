#!/usr/bin/env python3
"""One-off: mechanically split dazzlesum.py (v1.5.0-alpha.2, commit 3511c56)
into the src/dazzlesum/ package (Phase 1 of the src/ refactor, S-A layout).

Move-don't-rewrite discipline: every module body is a verbatim line-range
slice of the monolith. The ONLY transformations applied are:

1. Import wiring: each module gets the monolith's stdlib import block
   verbatim plus explicit intra-package imports (F401 is globally ignored
   in .flake8, so the uniform stdlib block is safe and keeps the move
   mechanical).
2. Shared mutable globals (dazzle_logger, color_formatter,
   verification_exit_code, is_auto_detected_command, verbosity_config,
   grand_totals, squelch_settings) move to src/dazzlesum/state.py; every
   bare reference to them is rewritten to ``state.<name>`` via a
   tokenize-based pass (strings and comments untouched), and the
   now-redundant ``global <name>`` statements are dropped.
3. constants.py: ``logging.getLogger(__name__)`` becomes
   ``logging.getLogger(__name__.split('.')[0])`` so the logger keeps its
   monolith-era name ('dazzlesum' when imported, '__main__' when the
   stitched artifact runs as a script) instead of 'dazzlesum.constants'.

Run from the repo root while dazzlesum.py is still the original monolith:
    python tests/one-offs/split_monolith_v150a3.py

Provenance (monolith line ranges) is embedded in each module's docstring
and echoed to stdout for the commit message.
"""

import io
import re
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / 'src' / 'dazzlesum'
# Read the archived pre-split monolith once the root dazzlesum.py has been
# replaced by the stitched artifact; fall back to the root file on the very
# first run (when it is still the original monolith).
_LEGACY = REPO / 'legacy' / 'dazzlesum-monolith-1.5.0a2.py'
MONOLITH = _LEGACY if _LEGACY.exists() else REPO / 'dazzlesum.py'
COMMIT = '3511c56'

# Mutable module-level globals that move to state.py
TARGETS = {
    'dazzle_logger', 'color_formatter', 'verification_exit_code',
    'is_auto_detected_command', 'verbosity_config', 'grand_totals',
    'squelch_settings',
}

# Monolith stdlib import block (lines 31-48), reproduced verbatim in every
# module that carries moved code. F401 (unused import) is globally ignored.
STDLIB_BLOCK = """\
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
"""

# module name -> (description, [ (start, end) 1-based inclusive ], [intra-package import lines])
MODULES = {
    'constants': (
        'Shared constants, optional unctools integration, and base logging setup',
        [(66, 98)],
        [],
    ),
    'state': (
        'Shared mutable runtime state (the monolith\'s module-level globals)',
        [(239, 240), (398, 399), (401, 402), (404, 405), (407, 408),
         (718, 719), (721, 722)],
        [],
    ),
    'output': (
        'DazzleLogger, ColorFormatter, verbosity/squelch configuration, logging setup',
        [(101, 236), (243, 395), (411, 484), (487, 506), (4767, 4805)],
        ['from .constants import logger, is_windows',
         'from . import state'],
    ),
    'patterns': (
        'Compiled include/exclude pattern matching',
        [(1458, 1503), (1506, 1509), (1512, 1533)],
        ['from .constants import SHASUM_FILENAME, STATE_FILENAME, CACHE_FILENAME'],
    ),
    'results': (
        'GrandTotals, ProgressTracker, SummaryCollector, verification status calc',
        [(509, 715), (1193, 1306), (1309, 1387), (4868, 4921), (4924, 4952)],
        ['from .constants import logger',
         'from . import state'],
    ),
    'hashing': (
        'DazzleHashCalculator and LineEndingHandler',
        [(1536, 1607), (1827, 2055)],
        ['from .constants import (logger, is_windows, HAVE_UNCTOOLS, normalize_path,',
         '                        safe_open, DEFAULT_ALGORITHM, DEFAULT_CHUNK_SIZE)',
         'from . import state'],
    ),
    'walk': (
        'SymlinkHandler, FIFODirectoryWalker, and pre-walk counting',
        [(1390, 1455), (1610, 1738), (1741, 1824)],
        ['from .constants import logger, is_windows',
         'from .patterns import CompiledPatternMatcher, _should_include_file_simple',
         'from . import state'],
    ),
    'manifest': (
        'ShasumManager, MonolithicWriter, and .shasum parsing/detection',
        [(725, 952), (955, 1190), (2058, 2086), (2089, 2104)],
        ['from ._version import __version__',
         'from .constants import logger, is_windows, SHASUM_FILENAME',
         'from . import state'],
    ),
    'shadow': (
        'ShadowPathResolver (parallel shadow-directory path mapping)',
        [(2107, 2187)],
        ['from .constants import SHASUM_FILENAME, MONOLITHIC_DEFAULT_NAME'],
    ),
    'statecache': (
        'StateCache: per-machine SQLite (size, mtime_ns) state backing incremental updates',
        [(2190, 2344)],
        [],
    ),
    'engine': (
        'ChecksumGenerator: create/verify/update orchestration incl. threaded walk',
        [(2347, 3577)],
        ['from ._version import __version__',
         'from .constants import (logger, DEFAULT_ALGORITHM, SHASUM_FILENAME,',
         '                        STATE_FILENAME, CACHE_FILENAME, MONOLITHIC_DEFAULT_NAME)',
         'from . import state',
         'from .output import initialize_squelch_from_verbosity',
         'from .patterns import (CompiledPatternMatcher, _always_excluded_name,',
         '                       _should_include_file_simple)',
         'from .results import (GrandTotals, ProgressTracker, SummaryCollector,',
         '                      calculate_verification_status, format_status_with_colors)',
         'from .hashing import DazzleHashCalculator',
         'from .walk import SymlinkHandler, FIFODirectoryWalker, count_dirs_and_files',
         'from .manifest import MonolithicWriter, parse_shasum_file, is_monolithic_file',
         'from .shadow import ShadowPathResolver',
         'from .statecache import StateCache'],
    ),
    'cli': (
        'Argument parsers, help topics/actions, execute_* dispatch, and main()',
        [(3580, 4006), (4009, 4066), (4069, 4136), (4139, 4173), (4175, 4385),
         (4388, 4398), (4400, 4447), (4449, 4511), (4513, 4545), (4548, 4559),
         (4561, 4600), (4602, 4658), (4660, 4725), (4727, 4765), (4808, 4856),
         (4858, 4865), (4954, 5147)],
        ['from ._version import __version__, get_package_version',
         'from .constants import (logger, SUPPORTED_ALGORITHMS, DEFAULT_ALGORITHM,',
         '                        SHASUM_FILENAME, HAVE_UNCTOOLS, is_windows)',
         'from . import state',
         'from .output import (DazzleLogger, ColorFormatter, VerbosityConfig,',
         '                     initialize_squelch_from_verbosity, setup_logging)',
         'from .manifest import ShasumManager, is_monolithic_file',
         'from .engine import ChecksumGenerator'],
    ),
}

GLOBAL_LINE_RE = re.compile(
    r'^\s*global\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*(#.*)?$')


def strip_global_lines(text):
    """Drop 'global X[, Y]' lines whose names all moved to state.py."""
    out = []
    for line in text.splitlines(keepends=True):
        m = GLOBAL_LINE_RE.match(line)
        if m:
            names = [n.strip() for n in m.group(1).split(',')]
            if all(n in TARGETS for n in names):
                continue
        out.append(line)
    return ''.join(out)


def rewrite_state_refs(text):
    """Prefix bare references to TARGETS with 'state.' (tokenize-based:
    strings and comments are never touched; attribute accesses and
    def/class names are skipped)."""
    edits = []
    prev_sig = None
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        ttype, tstr, start, _end, line = tok
        if ttype == tokenize.NAME and tstr in TARGETS:
            skip = False
            if prev_sig is not None:
                pt, ps = prev_sig
                if pt == tokenize.OP and ps == '.':
                    skip = True          # attribute access (self.x, state.x)
                if pt == tokenize.NAME and ps in ('def', 'class'):
                    skip = True          # definition name
            # DazzleLogger.set_verbosity_config's PARAMETER shadows the
            # global intentionally -- leave that function's bare name alone.
            if ('def set_verbosity_config' in line
                    or line.strip() == 'self.verbosity_config = verbosity_config'):
                skip = True
            if not skip:
                edits.append(start)
        if ttype not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                         tokenize.INDENT, tokenize.DEDENT):
            prev_sig = (ttype, tstr)

    lines = text.splitlines(keepends=True)
    by_row = {}
    for row, col in edits:
        by_row.setdefault(row, []).append(col)
    for row, cols in by_row.items():
        line = lines[row - 1]
        for col in sorted(cols, reverse=True):
            line = line[:col] + 'state.' + line[col:]
        lines[row - 1] = line
    return ''.join(lines)


def slice_chunks(mono_lines, ranges):
    chunks = []
    for a, b in ranges:
        chunk = mono_lines[a - 1:b]
        # strip leading/trailing blank lines inside the slice
        while chunk and not chunk[0].strip():
            chunk.pop(0)
        while chunk and not chunk[-1].strip():
            chunk.pop()
        chunks.append(''.join(chunk))
    return chunks


def provenance(ranges):
    return ', '.join(f'{a}-{b}' for a, b in ranges)


def main():
    mono_lines = MONOLITH.read_text(encoding='utf-8').splitlines(keepends=True)
    SRC.mkdir(parents=True, exist_ok=True)

    for name, (desc, ranges, intra) in MODULES.items():
        chunks = slice_chunks(mono_lines, ranges)
        # chunks keep their trailing newline; joining with two more yields
        # exactly two blank lines between chunks (E303-safe).
        body = '\n\n'.join(chunks)

        if name == 'constants':
            old = 'logger = logging.getLogger(__name__)'
            new = ("logger = logging.getLogger(__name__.split('.')[0])"
                   "  # keep monolith-era logger name")
            assert old in body, 'constants logger line not found'
            body = body.replace(old, new)

        if name != 'state':
            body = strip_global_lines(body)
            body = rewrite_state_refs(body)

        header = (
            f'"""{desc}.\n\n'
            f'Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit '
            f'{COMMIT}),\nlines {provenance(ranges)}. Only import wiring and '
            f'shared-state references\n(``state.<name>``) were adjusted -- '
            f'no logic changes (Phase 1, AC-R4).\n"""\n'
        )
        parts = [header]
        if name not in ('state',):
            parts.append('\n' + STDLIB_BLOCK)
        if intra:
            parts.append('\n' + '\n'.join(intra) + '\n')
        parts.append('\n\n' + body.rstrip('\n') + '\n')
        out = SRC / f'{name}.py'
        out.write_text(''.join(parts), encoding='utf-8', newline='\n')
        print(f'{name}.py  <- lines {provenance(ranges)}')

    print('\nNOTE: _version.py, __init__.py, __main__.py are written by hand '
          '(new wiring files, plus PHASE/PRE_RELEASE_NUM lines for '
          'sync-versions.py).')


if __name__ == '__main__':
    sys.exit(main())
