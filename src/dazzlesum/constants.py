"""Shared constants, optional unctools integration, and base logging setup.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 66-98. Only import wiring and shared-state references
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


# UNC-aware path handling comes THROUGH dazzle-filekit (a hard dependency
# since v1.5.0-alpha.4), whose path-identity layer is itself backed by
# unctools (filekit declares unctools>=0.2.2 as its L0). dazzlesum no longer
# imports unctools directly: the original soft-import targeted a pre-0.2.0
# unctools surface (normalize_path, unctools.operations.*) that later
# versions removed, so it failed silently and HAVE_UNCTOOLS was False on
# every modern install -- the "enhanced UNC handling" never actually ran
# (v1.5.0 fix).
from dazzle_filekit import is_windows  # noqa: F401
from dazzle_filekit.paths import is_unc_path  # noqa: F401
from dazzle_filekit.operations import open_file as safe_open  # noqa: F401
from dazzle_filekit.utils.compat import path_exists_cross_platform as file_exists  # noqa: F401

# Kept True for API compatibility: UNC support is now unconditionally
# available via filekit's unctools-backed layer.
HAVE_UNCTOOLS = True

# NOTE: normalize_path (a retired unctools-era compat name whose actual
# behavior was always the no-op fallback) is REMOVED from the public surface
# in 1.5.0; filekit's normalize_cross_platform_path serves the real use case
# (user-input path normalization) and hot paths deliberately do not
# normalize (see the v1.5.0 enumeration-optimization notes).

# Constants
DEFAULT_ALGORITHM = 'sha256'
DEFAULT_CHUNK_SIZE = 8192
SUPPORTED_ALGORITHMS = ['md5', 'sha1', 'sha256', 'sha512']
SHASUM_FILENAME = '.shasum'
STATE_FILENAME = '.dazzle-state.json'
CACHE_FILENAME = '.dazzle-cache.sqlite'
MONOLITHIC_DEFAULT_NAME = 'checksums'

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__.split('.')[0])  # keep monolith-era logger name
