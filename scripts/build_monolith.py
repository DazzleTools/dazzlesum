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
* DazzleLib imports (``from dazzle_filekit... import``, ``from dazzle_lib
  import``) are HARD dependencies of the src/ package (Phase 2 lib
  integration -- pyproject pins minimum versions; there are no fallback
  code paths in the package). For the artifact, these imports are stripped
  and the exact objects used are INLINED at build time from the installed
  library source (``inspect.getsource``), each under a provenance comment
  naming the library, version, and object. This keeps the single-file
  artifact self-contained without maintaining a parallel stdlib
  reimplementation inside dazzlesum. Consequence: building the artifact
  requires dazzle-lib/dazzle-filekit to be installed (they are install
  dependencies anyway), and vendored code binds free module-level names
  (e.g. ``logger``) to the artifact's globals.
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
LIB_IMPORT_RE = re.compile(r'^from (dazzle_lib|dazzle_filekit)((?:\.\w+)*) import (.+)$')
IMPORT_LINE_RE = re.compile(r'^(?:import [A-Za-z_]|from [A-Za-z_][\w.]* import\b)')

# Distribution names (for version lookup in provenance comments).
LIB_DISTS = {'dazzle_lib': 'dazzle-lib', 'dazzle_filekit': 'dazzle-filekit'}

# Objects that have no retrievable source (typing aliases etc.) are inlined
# from this table instead of inspect.getsource.
NON_SOURCE_SNIPPETS = {
    ('dazzle_lib', 'HashResultDict'):
        'HashResultDict = Dict[str, str]\n'
        '"""Hash results keyed by algorithm name, hex digests as values\n'
        '(alias of dazzle_lib.payloads.HashResultDict)."""\n',
    # The four a7 filekit delegations below get SELF-CONTAINED artifact
    # equivalents instead of inspect.getsource: their real implementations
    # chain into filekit's resolver stack (PathVariantResolver protocol,
    # unctools-backed variant resolution), which would drag half the library
    # into the artifact. The package uses the real filekit implementations;
    # the artifact gets stdlib behavior -- exactly what the artifact always
    # had historically (the old unctools soft-import never activated).
    ('dazzle_filekit', 'is_windows'):
        'def is_windows():\n'
        '    """Self-contained artifact equivalent of dazzle_filekit.is_windows."""\n'
        "    return os.name == 'nt'\n",
    ('dazzle_filekit.paths', 'is_unc_path'):
        'def is_unc_path(path):\n'
        '    """Self-contained artifact equivalent of dazzle_filekit.paths.is_unc_path\n'
        '    (approximation: UNC = leading double separator; the package uses the\n'
        '    real resolver-aware implementation)."""\n'
        '    s = str(path)\n'
        "    return s.startswith('\\\\\\\\') or s.startswith('//')\n",
    ('dazzle_filekit.operations', 'open_file'):
        'def open_file(path, mode=\'r\', *args, **kwargs):\n'
        '    """Self-contained artifact equivalent of dazzle_filekit.operations.open_file\n'
        '    (plain open; the package version adds UNC variant-resolution fallback)."""\n'
        '    return open(path, mode, *args, **kwargs)\n',
    ('dazzle_filekit.utils.compat', 'path_exists_cross_platform'):
        'def path_exists_cross_platform(path):\n'
        '    """Self-contained artifact equivalent of\n'
        '    dazzle_filekit.utils.compat.path_exists_cross_platform."""\n'
        '    return Path(path).exists()\n',
}

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
    """Return (stdlib_import_lines, lib_objects, provenance, body_text).

    The module docstring is dropped from the artifact (its provenance line
    is hoisted into the section delimiter); intra-package imports are
    stripped; column-0 stdlib imports are collected for the shared header.
    DazzleLib imports are stripped and returned as ``lib_objects`` --
    ``(module, name)`` pairs in first-seen order -- for build-time inlining
    (see the module docstring).
    """
    provenance = ''
    m = DOCSTRING_RE.match(text)
    if m:
        pm = PROVENANCE_RE.search(m.group(0))
        if pm:
            provenance = pm.group(1).strip()
        text = text[m.end():]
    stdlib = []
    lib_objects = []
    body = []
    continuation = None  # 'intra' | 'lib' inside a parenthesized import
    lib_module = None

    def _parse_import_names(names_part):
        """Yield (object_name, bound_alias) from an import name list.

        Handles trailing ``# noqa`` comments and ``x as y`` aliasing --
        both introduced by the a7 filekit delegation imports; the naive
        whitespace split previously treated '#' as an imported name.
        """
        names_part = names_part.split('#', 1)[0]
        for chunk in names_part.replace('(', ' ').replace(')', ' ').split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ' as ' in chunk:
                obj, alias = (s.strip() for s in chunk.split(' as ', 1))
            else:
                obj = alias = chunk
            if obj:
                yield obj, alias

    for line in text.splitlines(keepends=True):
        if continuation:
            if continuation == 'lib':
                for obj, alias in _parse_import_names(line):
                    lib_objects.append((lib_module, obj, alias))
            if ')' in line:
                continuation = None
            continue
        if INTRA_IMPORT_RE.match(line):
            if '(' in line and ')' not in line:
                continuation = 'intra'
            continue
        lm = LIB_IMPORT_RE.match(line)
        if lm:
            lib_module = lm.group(1) + lm.group(2)
            names_part = lm.group(3)
            if '(' in names_part and ')' not in names_part:
                continuation = 'lib'
            for obj, alias in _parse_import_names(names_part):
                lib_objects.append((lib_module, obj, alias))
            continue
        if IMPORT_LINE_RE.match(line):
            stdlib.append(line if line.endswith('\n') else line + '\n')
            continue
        body.append(line)
    body_text = ''.join(body).strip('\n')
    return stdlib, lib_objects, provenance, body_text


VENDOR_HEADER = """\
# ===========================================================================
# Vendored DazzleLib objects (generated -- see scripts/build_monolith.py)
#
# The src/ package imports these from the installed dazzle-lib /
# dazzle-filekit libraries (hard dependencies since v1.5.0-alpha.4). The
# single-file artifact must stay self-contained, so the exact objects used
# are inlined here at build time from the installed library source. Free
# module-level names they reference (e.g. ``logger``) bind to this
# artifact's globals.
# ===========================================================================
"""


def build_vendored_section(lib_objects):
    """Inline each (module, obj, alias) lib object with provenance.

    Each distinct (module, obj) is vendored once; every alias it was
    imported under gets a binding line after the snippet (``x as y``
    imports vendor ``def x`` then emit ``y = x``).
    """
    if not lib_objects:
        return ''
    import importlib
    import inspect
    from importlib.metadata import version as dist_version
    chunks = [VENDOR_HEADER]
    vendored = {}  # (module, obj) -> set of aliases needing bindings
    order = []
    for module_name, obj_name, alias in lib_objects:
        key = (module_name, obj_name)
        if key not in vendored:
            vendored[key] = set()
            order.append(key)
        if alias != obj_name:
            vendored[key].add(alias)
    for module_name, obj_name in order:
        dist = LIB_DISTS[module_name.split('.')[0]]
        prov = (f'# ---- vendored: {module_name}.{obj_name} '
                f'({dist} {dist_version(dist)}) ----\n')
        snippet = NON_SOURCE_SNIPPETS.get((module_name, obj_name))
        if snippet is None:
            mod = importlib.import_module(module_name)
            snippet = inspect.getsource(getattr(mod, obj_name))
        piece = prov + snippet.rstrip('\n') + '\n'
        for alias in sorted(vendored[(module_name, obj_name)]):
            piece += f'{alias} = {obj_name}\n'
        chunks.append(piece)
    return '\n\n'.join(chunks)


def main():
    stdlib_seen = []
    lib_objects_seen = []
    sections = []
    for name in MODULE_ORDER:
        path = SRC / f'{name}.py'
        text = path.read_text(encoding='utf-8')
        stdlib, lib_objects, prov, body = split_module(text)
        for line in stdlib:
            if line not in stdlib_seen:
                stdlib_seen.append(line)
        for pair in lib_objects:
            if pair not in lib_objects_seen:
                lib_objects_seen.append(pair)
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

    vendored = build_vendored_section(lib_objects_seen)
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
    ]
    if vendored:
        parts += [vendored, '\n\n']
    parts += [
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
