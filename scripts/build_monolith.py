#!/usr/bin/env python3
"""Stitch the src/dazzlesum package back into a single self-contained
dazzlesum.py artifact at the repo root.

Since the Phase 1 src/ split (v1.5.0-alpha.3), the package under
src/dazzlesum/ is the SOURCE OF TRUTH and the repo-root dazzlesum.py is a
generated build product -- never edit it by hand; edit the package and
rerun this script:

    python scripts/build_monolith.py

How it works
------------
* Modules are concatenated in topological (dependency) order.
* Intra-package imports (``from .x import``, ``from . import state``) are
  stripped -- in a single file every name is already a module global.
* Column-0 stdlib import lines are collected, deduplicated preserving
  first-seen order, and emitted once at the top.
* The shared-state module (src/dazzlesum/state.py) collapses into the
  artifact's own globals; ``state = sys.modules[__name__]`` is emitted so
  every ``state.<name>`` reference in the stitched code reads and writes
  those globals -- byte-for-byte the behavior of the pre-split monolith's
  ``global`` variables (dazzlesum.dazzle_logger, .verification_exit_code,
  etc. stay live attributes of the module).
* A ``if __name__ == '__main__'`` guard is appended.

Verifying the artifact (Phase 1 gate AC-R1)
-------------------------------------------
The test suite runs against BOTH import targets, selected by the
DAZZLESUM_TEST_TARGET environment variable (see tests/conftest.py):

    python -m pytest tests/ -q --ignore=tests/one-offs
        'package' (default): conftest pre-imports src/dazzlesum so the
        in-process tests exercise the package. (Subprocess-based CLI
        tests always invoke the repo-root dazzlesum.py, i.e. this
        artifact -- the two targets are covered in one run.)

    DAZZLESUM_TEST_TARGET=stitched python -m pytest tests/ -q --ignore=tests/one-offs
        conftest skips the src/ preload, so the tests' own
        ``sys.path.insert(0, repo_root); import dazzlesum`` resolves the
        stitched artifact for the in-process tests as well.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / 'src' / 'dazzlesum'
OUT = REPO / 'dazzlesum.py'

# Topological order: each module only depends on earlier ones.
MODULE_ORDER = [
    '_version',
    'constants',
    'state',
    'output',
    'patterns',
    'results',
    'hashing',
    'walk',
    'shadow',
    'statecache',
    'manifest',
    'engine',
    'cli',
]

INTRA_IMPORT_RE = re.compile(r'^(?:from \.|from dazzlesum[\s.]|import dazzlesum)')
IMPORT_LINE_RE = re.compile(r'^(?:import [A-Za-z_]|from [A-Za-z_][\w.]* import\b)')

HEADER_DOCSTRING = '''"""
dazzle-checksum.py - Cross-Platform Checksum Tool

A comprehensive tool for generating folder-specific checksum files (.shasum) that enables
data integrity verification across different machines and operating systems.

Features:
- Cross-platform compatibility (Windows, macOS, Linux, BSD)
- FIFO directory processing for memory efficiency
- Native tool integration with Python fallback
- Line ending normalization for consistent checksums
- Symlink/junction loop detection
- Incremental updates and change tracking
- Compatible output format with standard tools
- Monolithic checksum files for entire directory trees

Usage:
    dazzle-checksum.py [OPTIONS] [DIRECTORY]

Examples:
    dazzle-checksum.py                           # Current directory
    dazzle-checksum.py --recursive /path/to/dir  # Recursive processing
    dazzle-checksum.py --algorithm sha512        # Different algorithm
    dazzle-checksum.py --verify                  # Verify existing checksums
    dazzle-checksum.py --update                  # Incremental update
    dazzle-checksum.py --monolithic --recursive  # Single checksum file for tree
    dazzle-checksum.py --monolithic --output checksums.sha256  # Custom output
"""
'''

GENERATED_BANNER = """\
# ===========================================================================
# GENERATED FILE -- DO NOT EDIT BY HAND.
#
# This single-file artifact is stitched from the src/dazzlesum/ package by
# scripts/build_monolith.py. Edit the package modules and rerun:
#     python scripts/build_monolith.py
# ===========================================================================
"""

STATE_BINDING = """\
# In this stitched single-file build, the package's shared-state module
# (src/dazzlesum/state.py) collapses into this module's own globals; binding
# `state` to the module object makes every `state.<name>` reference below
# read and write those globals, exactly as the pre-split monolith did.
state = sys.modules[__name__]
"""

MAIN_GUARD = """\
if __name__ == '__main__':
    sys.exit(main())
"""


DOCSTRING_RE = re.compile(r'\A"""[\s\S]*?"""\n')
PROVENANCE_RE = re.compile(r'lines ([0-9, -]+)\.')


def split_module(text):
    """Return (stdlib_import_lines, provenance, body_text) for one module.

    The module docstring is dropped from the artifact (its provenance line
    is hoisted into the section delimiter); intra-package imports are
    stripped; column-0 stdlib imports are collected for the shared header.
    """
    provenance = ''
    m = DOCSTRING_RE.match(text)
    if m:
        pm = PROVENANCE_RE.search(m.group(0))
        if pm:
            provenance = pm.group(1).strip()
        text = text[m.end():]
    stdlib = []
    body = []
    continuation = False  # inside a parenthesized intra-package import
    for line in text.splitlines(keepends=True):
        if continuation:
            if ')' in line:
                continuation = False
            continue
        if INTRA_IMPORT_RE.match(line):
            if '(' in line and ')' not in line:
                continuation = True
            continue
        if IMPORT_LINE_RE.match(line):
            stdlib.append(line if line.endswith('\n') else line + '\n')
            continue
        body.append(line)
    body_text = ''.join(body).strip('\n')
    return stdlib, provenance, body_text


def main():
    stdlib_seen = []
    sections = []
    for name in MODULE_ORDER:
        path = SRC / f'{name}.py'
        text = path.read_text(encoding='utf-8')
        stdlib, prov, body = split_module(text)
        for line in stdlib:
            if line not in stdlib_seen:
                stdlib_seen.append(line)
        prov_note = (f'#      (monolith 3511c56 lines {prov})\n' if prov else '')
        delimiter = (
            '# ' + '=' * 74 + '\n'
            f'# ---- src/dazzlesum/{name}.py ' + '-' * max(1, 45 - len(name)) + '\n'
            + prov_note +
            '# ' + '=' * 74 + '\n'
        )
        # No blank line between the delimiter comment and the body:
        # pycodestyle sums blank lines across comment blocks, so a blank
        # here plus the two between sections would trip E303.
        sections.append(delimiter + body)

    parts = [
        '#!/usr/bin/env python3\n',
        HEADER_DOCSTRING,
        '\n',
        GENERATED_BANNER,
        '\n',
        ''.join(stdlib_seen),
        '\n',
        STATE_BINDING,
        '\n\n',
        '\n\n\n'.join(sections),
        '\n\n\n',
        MAIN_GUARD,
    ]
    OUT.write_text(''.join(parts), encoding='utf-8', newline='\n')
    line_count = OUT.read_text(encoding='utf-8').count('\n')
    print(f'Wrote {OUT} ({line_count} lines) from {len(MODULE_ORDER)} modules.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
