"""DazzleHashCalculator and LineEndingHandler.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 1536-1607, 1827-2055. Only import wiring and shared-state references
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

from dazzle_lib import HashResultDict

from .constants import (logger, is_windows,
                        DEFAULT_ALGORITHM, DEFAULT_CHUNK_SIZE)
from . import state


class LineEndingHandler:
    """Handles line ending normalization for consistent checksums across platforms."""

    def __init__(self, strategy='auto'):
        """
        Initialize line ending handler.

        Args:
            strategy: 'auto', 'unix', 'windows', 'preserve'
        """
        self.strategy = strategy
        self.text_extensions = {
            '.txt', '.py', '.js', '.html', '.css', '.xml', '.json', '.yaml', '.yml',
            '.md', '.rst', '.cfg', '.ini', '.conf', '.log', '.sql', '.sh', '.bat',
            '.cmd', '.ps1', '.php', '.rb', '.pl', '.java', '.c', '.cpp', '.h',
            '.hpp', '.cs', '.vb', '.go', '.rs', '.swift', '.kt', '.scala'
        }

    def should_normalize(self, file_path: Path) -> bool:
        """Determine if a file should have line ending normalization."""
        if self.strategy == 'preserve':
            return False

        # Check file extension
        if file_path.suffix.lower() in self.text_extensions:
            return True

        # Auto-detect by reading first few bytes
        try:
            with open(file_path, 'rb') as f:
                sample = f.read(1024)
                if not sample:
                    return False

                # Check for null bytes (indicates binary)
                if b'\x00' in sample:
                    return False

                # Check for text-like content
                try:
                    sample.decode('utf-8')
                    return True
                except UnicodeDecodeError:
                    try:
                        sample.decode('latin-1')
                        return True
                    except UnicodeDecodeError:
                        return False
        except Exception:
            return False

    def normalize_content(self, content: bytes) -> bytes:
        """Normalize line endings in content."""
        if self.strategy == 'preserve':
            return content

        try:
            # Decode to string
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text = content.decode('latin-1')
            except UnicodeDecodeError:
                return content  # Can't decode, return as-is

        # Normalize line endings
        if self.strategy == 'unix' or self.strategy == 'auto':
            text = text.replace('\r\n', '\n').replace('\r', '\n')
        elif self.strategy == 'windows':
            text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')

        return text.encode('utf-8')


class DazzleHashCalculator:
    """Main hash calculator with normalization and native tool integration."""

    def __init__(self, algorithm=DEFAULT_ALGORITHM, line_ending_strategy='auto',
                 chunk_size=DEFAULT_CHUNK_SIZE):
        self.algorithm = algorithm.lower()
        self.chunk_size = chunk_size
        self.line_handler = LineEndingHandler(line_ending_strategy)
        # Python hashlib is the primary engine: it is in-process (native
        # tools cost a per-file subprocess spawn -- ~75ms measured for
        # certutil, a >100x slowdown on small files) and it is the only
        # engine that applies line-ending normalization, so it is the
        # engine every existing manifest was built with. Native tools are
        # probed only when hashlib lacks the algorithm.
        self._hashlib_supported = self._hashlib_supports(self.algorithm)
        if self._hashlib_supported:
            self.native_tool = None
            if state.dazzle_logger:
                state.dazzle_logger.tool_selection(None, self.algorithm)
            else:
                logger.debug(f"Using Python implementation for {self.algorithm}")
        else:
            self.native_tool = self._detect_native_tool()

    @staticmethod
    def _hashlib_supports(algorithm: str) -> bool:
        """True when hashlib can construct this algorithm."""
        try:
            hashlib.new(algorithm)
            return True
        except (ValueError, TypeError):
            return False

    def _detect_native_tool(self) -> Optional[str]:
        """Detect available native checksum tools."""
        tools_to_try = []

        if is_windows():
            tools_to_try = ['fsum', 'certutil']
        else:
            if self.algorithm == 'sha256':
                tools_to_try = ['sha256sum', 'shasum']
            elif self.algorithm == 'sha1':
                tools_to_try = ['sha1sum', 'shasum']
            elif self.algorithm == 'md5':
                tools_to_try = ['md5sum', 'md5']
            elif self.algorithm == 'sha512':
                tools_to_try = ['sha512sum', 'shasum']

        for tool in tools_to_try:
            if self._tool_available(tool):
                if state.dazzle_logger:
                    state.dazzle_logger.tool_selection(tool, self.algorithm)
                else:
                    logger.debug(f"Using native tool: {tool}")
                return tool

        if state.dazzle_logger:
            state.dazzle_logger.tool_selection(None, self.algorithm)
        else:
            logger.debug("No native tools available, using Python implementation")
        return None

    def _tool_available(self, tool: str) -> bool:
        """Check if a native tool is available.

        Detection reads BOTH output streams and does not trust exit codes:
        real tools disagree wildly here -- certutil prints its usage text to
        STDOUT with returncode 1, and fsum 2.51 prints its banner to STDERR
        (both verified on real machines; the old stdout-only and
        rc==0-or-usage-in-stderr checks rejected every native tool, silently
        forcing the pure-Python hashing fallback everywhere).
        """
        try:
            # Special handling for fsum: invoked bare, banner identifies it
            if tool == 'fsum':
                result = subprocess.run([tool], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
                combined = (result.stdout + result.stderr).lower()
                return 'slavasoft' in combined or 'fsum' in combined

            # For other tools, try --help or --version; usage text or the
            # tool's own name in EITHER stream counts
            for flag in ['--help', '--version', '-h']:
                try:
                    result = subprocess.run([tool, flag], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
                    combined = (result.stdout + result.stderr).lower()
                    if result.returncode == 0 or 'usage' in combined or tool.lower() in combined:
                        return True
                except FileNotFoundError:
                    return False  # tool absent -- no point trying more flags
                except Exception:
                    continue

            return False
        except Exception:
            return False

    def _calculate_with_native_tool(self, file_path: Path) -> str:
        """Calculate hash using native tool."""
        if not self.native_tool:
            raise ValueError("No native tool available")

        # Handle different tools
        if self.native_tool == 'fsum':
            return self._calculate_with_fsum(file_path)
        elif self.native_tool == 'certutil':
            return self._calculate_with_certutil(file_path)
        elif self.native_tool.endswith('sum'):
            return self._calculate_with_hashsum(file_path)
        elif self.native_tool == 'shasum':
            return self._calculate_with_shasum(file_path)
        else:
            raise ValueError(f"Unsupported native tool: {self.native_tool}")

    def calculate_file_hash(self, file_path: Path) -> str:
        """Calculate hash for a single file."""
        # (The old HAVE_UNCTOOLS normalize_path gate was dead code: the flag
        # was always False on modern unctools, and the fallback was a no-op.
        # Hot paths deliberately do not normalize paths -- v1.5.0.)

        # Python hashlib first: in-process (no per-file subprocess spawn)
        # and the only engine that applies line-ending normalization, so
        # a native tool's raw-byte digest would not even match existing
        # manifests for CRLF text files.
        if self._hashlib_supported:
            return self._calculate_with_python(file_path)

        # Algorithm outside hashlib: fall back to a native tool (raw-byte
        # hashing, no normalization).
        if self.native_tool:
            try:
                return self._calculate_with_native_tool(file_path)
            except Exception as e:
                # Only log warning in debug mode to reduce noise
                logger.debug(f"Native tool {self.native_tool} failed for {file_path}, using Python: {e}")

        # Last resort: lets hashlib raise its informative unsupported-algorithm error
        return self._calculate_with_python(file_path)

    def calculate_hashes(self, file_path: Path) -> HashResultDict:
        """Calculate this file's hash in the DazzleLib cross-layer shape.

        The ecosystem-boundary form of :meth:`calculate_file_hash`: the same
        computation (normalized Python hashlib first, native tool only for
        algorithms hashlib lacks), returned as ``dazzle_lib.HashResultDict``
        -- hex digests keyed by algorithm name, e.g. ``{'sha256': 'ab12...'}``
        -- the shape produced by filekit ``verification.calculate_file_hash``
        and consumed across the stack.
        """
        return {self.algorithm: self.calculate_file_hash(file_path)}

    def _calculate_with_fsum(self, file_path: Path) -> str:
        """Calculate hash using Windows fsum tool."""
        cmd = ['fsum', f'-{self.algorithm}', str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)

        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)

        # Parse fsum output - skip header lines and comments
        lines = result.stdout.splitlines()
        for line in lines:
            line = line.strip()
            # Skip empty lines, comment lines, and header lines
            if not line or line.startswith(';') or line.startswith('SlavaSoft'):
                continue

            # Look for hash lines - they contain the filename with * prefix
            if ' *' in line:
                hash_value = line.split(' *')[0].strip()
                return hash_value.lower()

            # Alternative format: hash followed by space and filename
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) in [32, 40, 64, 128]:  # Common hash lengths
                return parts[0].lower()

        raise ValueError(f"Could not parse fsum output: {result.stdout}")

    def _calculate_with_certutil(self, file_path: Path) -> str:
        """Calculate hash using Windows certutil."""
        algo_map = {'md5': 'MD5', 'sha1': 'SHA1', 'sha256': 'SHA256', 'sha512': 'SHA512'}
        certutil_algo = algo_map.get(self.algorithm)

        if not certutil_algo:
            raise ValueError(f"Unsupported algorithm for certutil: {self.algorithm}")

        cmd = ['certutil', '-hashfile', str(file_path), certutil_algo]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)

        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)

        # Parse certutil output - hash is typically on the second non-empty line
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        for line in lines[1:]:  # Skip first line (filename)
            # Remove spaces and check if it looks like a hash
            clean_line = line.replace(' ', '').replace('\t', '')
            if len(clean_line) in [32, 40, 64, 128] and all(c in '0123456789abcdefABCDEF' for c in clean_line):
                return clean_line.lower()

        raise ValueError(f"Could not parse certutil output: {result.stdout}")

    def _calculate_with_hashsum(self, file_path: Path) -> str:
        """Calculate hash using Unix *sum tools."""
        cmd = [self.native_tool, str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)

        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)

        # Parse output (first field is hash)
        first_line = result.stdout.strip().split('\n')[0]
        hash_value = first_line.split()[0]
        return hash_value.lower()

    def _calculate_with_shasum(self, file_path: Path) -> str:
        """Calculate hash using shasum tool."""
        algo_map = {'sha1': '1', 'sha256': '256', 'sha512': '512'}
        shasum_algo = algo_map.get(self.algorithm)

        if not shasum_algo:
            raise ValueError(f"Unsupported algorithm for shasum: {self.algorithm}")

        cmd = ['shasum', f'-a{shasum_algo}', str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)

        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stderr)

        # Parse output (first field is hash)
        first_line = result.stdout.strip().split('\n')[0]
        hash_value = first_line.split()[0]
        return hash_value.lower()

    def _calculate_with_python(self, file_path: Path) -> str:
        """Calculate hash using Python hashlib."""
        try:
            hasher = hashlib.new(self.algorithm)
        except ValueError:
            raise ValueError(f"Unsupported hash algorithm: {self.algorithm}")

        # Plain open: the old HAVE_UNCTOOLS/safe_open branch was dead code
        # (the unctools API it soft-imported no longer exists, so the flag
        # was always False; safe_open's local fallback was open anyway).
        # UNC-path handling now flows through dazzle-filekit (v1.5.0).
        try:
            with open(file_path, 'rb') as f:
                return self._hash_file_content(f, hasher)
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            raise

    def _hash_file_content(self, file_obj, hasher) -> str:
        """Hash file content with optional normalization."""
        # Check if we should normalize line endings
        first_chunk = file_obj.read(self.chunk_size)
        if not first_chunk:
            return hasher.hexdigest()

        # Reset file pointer
        file_obj.seek(0)

        # Determine if we should normalize
        temp_path = Path(file_obj.name) if hasattr(file_obj, 'name') else None
        should_normalize = (temp_path and
                          self.line_handler.should_normalize(temp_path))

        if should_normalize:
            # Read entire file and normalize
            content = file_obj.read()
            normalized_content = self.line_handler.normalize_content(content)
            hasher.update(normalized_content)
        else:
            # Stream processing for large files
            file_obj.seek(0)
            while True:
                chunk = file_obj.read(self.chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)

        return hasher.hexdigest()
