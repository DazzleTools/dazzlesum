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


# Try to import unctools for enhanced path handling
try:
    import unctools
    from unctools import normalize_path, convert_to_local, is_unc_path
    from unctools.utils import is_windows as unctools_is_windows, get_platform_info
    from unctools.operations import safe_open, file_exists
    HAVE_UNCTOOLS = True
    # Use unctools function
    def is_windows(): return unctools_is_windows
except ImportError:
    HAVE_UNCTOOLS = False
    # Fallback implementations
    def is_windows(): return os.name == 'nt'
    def normalize_path(p): return Path(p)
    def safe_open(p, *args, **kwargs): return open(p, *args, **kwargs)
    def file_exists(p): return Path(p).exists()

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
