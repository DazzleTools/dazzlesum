"""ShadowPathResolver (parallel shadow-directory path mapping).

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 2107-2187. Only import wiring and shared-state references
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

from .constants import SHASUM_FILENAME, MONOLITHIC_DEFAULT_NAME


class ShadowPathResolver:
    """Resolves paths between source directories and shadow directory structure.
    
    The shadow directory feature allows keeping source directories clean by storing
    all .shasum files in a parallel shadow directory structure.
    
    Example:
        source_root: /data/projects/myproject/
        shadow_root: /checksums/myproject/
        
        Source file: /data/projects/myproject/subdir/file.txt
        Shadow .shasum: /checksums/myproject/subdir/.shasum
    """
    
    def __init__(self, source_root: Path, shadow_root: Path):
        self.source_root = Path(source_root).resolve()
        self.shadow_root = Path(shadow_root).resolve()
        
        # Ensure shadow root directory exists
        self.shadow_root.mkdir(parents=True, exist_ok=True)
    
    def get_shadow_shasum_path(self, source_dir: Path) -> Path:
        """Get the shadow .shasum file path for a source directory.

        Args:
            source_dir: Source directory that would contain .shasum file

        Returns:
            Path to .shasum file in shadow directory structure

        v1.5.0: fast path avoids the per-call Path.resolve() (an expensive
        _getfinalpathname syscall, profiled at ~12s per 20K dirs) -- walker
        paths already descend from the resolved source root. The resolve()
        fallback keeps external callers with unnormalized paths correct.
        """
        try:
            rel_path = Path(source_dir).relative_to(self.source_root)
        except ValueError:
            source_dir = Path(source_dir).resolve()
            try:
                rel_path = source_dir.relative_to(self.source_root)
            except ValueError:
                raise ValueError(
                    f"Source directory {source_dir} is not under source root {self.source_root}")

        # Create corresponding shadow directory path
        shadow_dir = self.shadow_root / rel_path
        return shadow_dir / SHASUM_FILENAME
    
    def get_source_file_path(self, shadow_relative_path: str) -> Path:
        """Resolve a shadow-relative file path to the corresponding source file.
        
        Args:
            shadow_relative_path: Relative path as stored in shadow .shasum file
            
        Returns:
            Path to actual source file
        """
        return self.source_root / shadow_relative_path
    
    def ensure_shadow_directory(self, shadow_shasum_path: Path) -> None:
        """Ensure the directory for a shadow .shasum file exists.
        
        Args:
            shadow_shasum_path: Path to shadow .shasum file
        """
        shadow_shasum_path.parent.mkdir(parents=True, exist_ok=True)
    
    def get_shadow_monolithic_path(self, algorithm: str, output_filename: Optional[str] = None) -> Path:
        """Get path for monolithic checksum file in shadow directory.
        
        Args:
            algorithm: Hash algorithm for default filename
            output_filename: Optional custom filename
            
        Returns:
            Path to monolithic checksum file in shadow root
        """
        if output_filename:
            return self.shadow_root / output_filename
        return self.shadow_root / f"{MONOLITHIC_DEFAULT_NAME}.{algorithm}"
