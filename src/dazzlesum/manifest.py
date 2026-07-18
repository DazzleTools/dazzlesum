"""ShasumManager, MonolithicWriter, and .shasum parsing/detection.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 725-952, 955-1190, 2058-2086, 2089-2104. Only import wiring and shared-state references
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

from ._version import __version__
from .constants import logger, is_windows, SHASUM_FILENAME
from . import state


class ShasumManager:
    """Manages .shasum files with backup, remove, restore, and list operations."""

    def __init__(self, root_dir: Path, backup_dir: Optional[Path] = None, dry_run: bool = False):
        self.root_dir = Path(root_dir)
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self.dry_run = dry_run
        self.logger = state.dazzle_logger if state.dazzle_logger else logger

    def find_shasum_files(self) -> List[Path]:
        """Find all .shasum files in the directory tree."""
        shasum_files = []

        try:
            for root, dirs, files in os.walk(self.root_dir):
                if SHASUM_FILENAME in files:
                    shasum_path = Path(root) / SHASUM_FILENAME
                    shasum_files.append(shasum_path)

        except Exception as e:
            self.logger.error(f"Error scanning directory tree: {e}")

        return sorted(shasum_files)

    def backup_shasums(self) -> Dict[str, Any]:
        """Backup all .shasum files to parallel directory structure."""
        if not self.backup_dir:
            raise ValueError("backup_dir is required for backup operation")

        shasum_files = self.find_shasum_files()
        if not shasum_files:
            self.logger.info("No .shasum files found to backup")
            return {'files_backed_up': 0, 'errors': []}

        self.logger.info(f"Found {len(shasum_files)} .shasum files to backup")

        if self.dry_run:
            self.logger.info("DRY RUN - would backup:")
            for shasum_file in shasum_files:
                rel_path = shasum_file.relative_to(self.root_dir)
                backup_path = self.backup_dir / rel_path
                self.logger.info(f"  {shasum_file} -> {backup_path}")
            return {'files_backed_up': len(shasum_files), 'errors': []}

        # Create backup directory
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        backed_up = 0
        errors = []

        for shasum_file in shasum_files:
            try:
                # Calculate relative path from root
                rel_path = shasum_file.relative_to(self.root_dir)
                backup_path = self.backup_dir / rel_path

                # Create backup directory structure
                backup_path.parent.mkdir(parents=True, exist_ok=True)

                # Copy file to backup location
                shutil.copy2(shasum_file, backup_path)

                self.logger.debug(f"Backed up: {rel_path}")
                backed_up += 1

            except Exception as e:
                error_msg = f"Failed to backup {shasum_file}: {e}"
                self.logger.error(error_msg)
                errors.append(error_msg)

        self.logger.info(f"Successfully backed up {backed_up} .shasum files to {self.backup_dir}")
        if errors:
            self.logger.warning(f"Encountered {len(errors)} errors during backup")

        return {'files_backed_up': backed_up, 'errors': errors}

    def remove_shasums(self, force: bool = False) -> Dict[str, Any]:
        """Remove all .shasum files from directory tree."""
        shasum_files = self.find_shasum_files()
        if not shasum_files:
            self.logger.info("No .shasum files found to remove")
            return {'files_removed': 0, 'errors': []}

        self.logger.info(f"Found {len(shasum_files)} .shasum files to remove")

        if self.dry_run:
            self.logger.info("DRY RUN - would remove:")
            for shasum_file in shasum_files:
                self.logger.info(f"  {shasum_file}")
            return {'files_removed': len(shasum_files), 'errors': []}

        # Confirmation prompt unless forced
        if not force:
            try:
                response = input(f"Remove {len(shasum_files)} .shasum files? [y/N]: ").strip().lower()
                if response not in ['y', 'yes']:
                    self.logger.info("Operation cancelled by user")
                    return {'files_removed': 0, 'errors': ['Operation cancelled by user']}
            except (EOFError, KeyboardInterrupt):
                self.logger.info("Operation cancelled by user")
                return {'files_removed': 0, 'errors': ['Operation cancelled by user']}

        removed = 0
        errors = []

        for shasum_file in shasum_files:
            try:
                shasum_file.unlink()
                self.logger.debug(f"Removed: {shasum_file}")
                removed += 1

            except Exception as e:
                error_msg = f"Failed to remove {shasum_file}: {e}"
                self.logger.error(error_msg)
                errors.append(error_msg)

        self.logger.info(f"Successfully removed {removed} .shasum files")
        if errors:
            self.logger.warning(f"Encountered {len(errors)} errors during removal")

        return {'files_removed': removed, 'errors': errors}

    def restore_shasums(self) -> Dict[str, Any]:
        """Restore .shasum files from backup directory."""
        if not self.backup_dir:
            raise ValueError("backup_dir is required for restore operation")

        if not self.backup_dir.exists():
            raise FileNotFoundError(f"Backup directory does not exist: {self.backup_dir}")

        # Find .shasum files in backup directory
        backup_files = []
        try:
            for root, dirs, files in os.walk(self.backup_dir):
                if SHASUM_FILENAME in files:
                    backup_path = Path(root) / SHASUM_FILENAME
                    backup_files.append(backup_path)
        except Exception as e:
            self.logger.error(f"Error scanning backup directory: {e}")
            return {'files_restored': 0, 'errors': [f"Error scanning backup directory: {e}"]}

        if not backup_files:
            self.logger.info("No .shasum files found in backup directory")
            return {'files_restored': 0, 'errors': []}

        self.logger.info(f"Found {len(backup_files)} .shasum files to restore")

        if self.dry_run:
            self.logger.info("DRY RUN - would restore:")
            for backup_file in backup_files:
                rel_path = backup_file.relative_to(self.backup_dir)
                target_path = self.root_dir / rel_path
                self.logger.info(f"  {backup_file} -> {target_path}")
            return {'files_restored': len(backup_files), 'errors': []}

        restored = 0
        errors = []

        for backup_file in backup_files:
            try:
                # Calculate target path in original tree
                rel_path = backup_file.relative_to(self.backup_dir)
                target_path = self.root_dir / rel_path

                # Create target directory if needed
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # Copy file from backup to target location
                shutil.copy2(backup_file, target_path)

                self.logger.debug(f"Restored: {rel_path}")
                restored += 1

            except Exception as e:
                error_msg = f"Failed to restore {backup_file}: {e}"
                self.logger.error(error_msg)
                errors.append(error_msg)

        self.logger.info(f"Successfully restored {restored} .shasum files from {self.backup_dir}")
        if errors:
            self.logger.warning(f"Encountered {len(errors)} errors during restore")

        return {'files_restored': restored, 'errors': errors}

    def list_shasums(self) -> List[Dict[str, Any]]:
        """List all .shasum files with detailed information."""
        shasum_files = self.find_shasum_files()

        if not shasum_files:
            self.logger.info("No .shasum files found")
            return []

        file_info = []

        for shasum_file in shasum_files:
            try:
                stat_info = shasum_file.stat()

                # Count checksums in file
                checksum_count = 0
                try:
                    with open(shasum_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                checksum_count += 1
                except Exception:
                    checksum_count = "?"

                info = {
                    'path': shasum_file,
                    'size': stat_info.st_size,
                    'modified': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_info.st_mtime)),
                    'checksums': checksum_count
                }
                file_info.append(info)

            except Exception as e:
                self.logger.error(f"Error reading {shasum_file}: {e}")

        # Display information
        self.logger.info(f"Found {len(file_info)} .shasum files:")
        for info in file_info:
            rel_path = info['path'].relative_to(self.root_dir)
            self.logger.info(f"  {rel_path}")
            self.logger.info(f"    Size: {info['size']} bytes, Modified: {info['modified']}, Checksums: {info['checksums']}")

        return file_info


class MonolithicWriter:
    """Handles streaming writes to monolithic checksum files."""

    def __init__(self, output_path: Path, root_path: Path, algorithm: str, resume_mode=False, yes_to_all=False):
        self.output_path = Path(output_path)
        self.temp_path = Path(str(output_path) + '.tmp')
        self.root_path = Path(root_path)
        self.algorithm = algorithm
        self.file_handle = None
        self.entries_written = 0
        self._is_open = False
        self._last_progress_report = 0
        self.resume_mode = resume_mode
        self.yes_to_all = yes_to_all

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        if exc_type is not None:
            # Error occurred, clean up temp file
            self.close(success=False)
        else:
            # Normal completion
            self.close(success=True)

    def open(self):
        """Open the monolithic file for writing."""
        try:
            # Ensure output directory exists
            self.output_path.parent.mkdir(parents=True, exist_ok=True)

            # Check for existing file (but not in resume mode - that's handled separately)
            if not self.resume_mode and self.output_path.exists():
                if not self._check_overwrite_permission():
                    print("Operation cancelled.")
                    raise KeyboardInterrupt("User cancelled overwrite operation")

            if self.resume_mode and self.output_path.exists():
                # Resume mode: copy existing file to temp and append
                shutil.copy2(self.output_path, self.temp_path)
                # Open in append mode, but first remove the footer if it exists
                with open(self.temp_path, 'r+', encoding='utf-8', buffering=1024) as f:
                    content = f.read()
                    # Remove existing footer
                    if content.endswith('# End of checksums\n'):
                        f.seek(0)
                        f.write(content[:-len('# End of checksums\n')])
                        f.truncate()
                # Now open for appending
                self.file_handle = open(self.temp_path, 'a', encoding='utf-8', buffering=1024)
                logger.info(f"Resume mode: Appending to existing monolithic file: {self.output_path}")
            else:
                # Normal mode: create new file
                self.file_handle = open(self.temp_path, 'w', encoding='utf-8', buffering=1024)
                # Write header
                timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                self.file_handle.write(f"# Dazzle monolithic checksum file v{__version__} - {self.algorithm} - {timestamp}\n")
                self.file_handle.write(f"# Root directory: {self.root_path}\n")
                
            self._is_open = True
            self.file_handle.flush()

            logger.debug(f"Opened monolithic file for writing: {self.temp_path}")

        except Exception as e:
            logger.error(f"Failed to open monolithic file {self.temp_path}: {e}")
            self._cleanup_temp()
            raise

    def append_directory_checksums(self, directory: Path, checksums: Dict[str, Any]):
        """Append checksums from a directory to the monolithic file."""
        if not self._is_open or not self.file_handle:
            raise RuntimeError("MonolithicWriter is not open")

        try:
            for filename, checksum_info in sorted(checksums.items()):
                # Calculate relative path from root
                file_path = directory / filename
                try:
                    relative_path = os.path.relpath(file_path, self.root_path)
                    # Use forward slashes for cross-platform compatibility
                    relative_path = relative_path.replace('\\', '/')
                except ValueError:
                    # Handle cases where paths are on different drives (Windows)
                    relative_path = str(file_path)
                    logger.warning(f"Could not create relative path for {file_path}, using absolute path")

                # Write in standard format: hash  filename
                self.file_handle.write(f"{checksum_info['hash']}  {relative_path}\n")
                self.entries_written += 1

            # Flush to ensure data is written immediately
            self.file_handle.flush()
            # Force OS to write to disk (for real-time monitoring on large operations)
            try:
                os.fsync(self.file_handle.fileno())
            except (OSError, AttributeError):
                # fsync might not be available on all platforms/filesystems
                pass
            
            # Report progress periodically for large operations
            if self.entries_written > 0 and self.entries_written % 10000 == 0:
                if self.entries_written != self._last_progress_report:
                    logger.info(f"Monolithic file: {self.entries_written:,} entries written")
                    self._last_progress_report = self.entries_written

        except Exception as e:
            logger.error(f"Failed to append checksums for {directory}: {e}")
            raise

    def close(self, success: bool = True):
        """Close the monolithic file and finalize."""
        if not self._is_open:
            return

        try:
            if self.file_handle:
                if success:
                    # Write footer
                    self.file_handle.write("# End of checksums\n")
                    self.file_handle.flush()

                # Close file handle
                self.file_handle.close()
                self.file_handle = None

            if success and self.temp_path.exists():
                # Cross-platform atomic replacement
                self._atomic_replace(self.temp_path, self.output_path)
                logger.info(f"Wrote {self.entries_written} checksums to monolithic file: {self.output_path}")
            else:
                # Cleanup temp file on failure
                self._cleanup_temp()

        except Exception as e:
            logger.error(f"Error closing monolithic file: {e}")
            self._cleanup_temp()
            raise
        finally:
            self._is_open = False

    def _cleanup_temp(self):
        """Clean up temporary file."""
        try:
            if self.temp_path.exists():
                os.remove(self.temp_path)
        except Exception as e:
            logger.warning(f"Could not remove temp file {self.temp_path}: {e}")

    def _atomic_replace(self, src: Path, dst: Path):
        """Cross-platform atomic file replacement."""
        if is_windows():
            # Windows: requires removing target first
            if dst.exists():
                backup_path = dst.with_suffix(dst.suffix + '.bak')
                # Remove any existing backup
                if backup_path.exists():
                    backup_path.unlink()
                # Move current file to backup
                dst.rename(backup_path)
                try:
                    # Move temp file to final location
                    src.rename(dst)
                    # Remove backup on success
                    backup_path.unlink()
                except Exception:
                    # Restore backup on failure
                    if backup_path.exists():
                        backup_path.rename(dst)
                    raise
            else:
                # No existing file, simple rename
                src.rename(dst)
        else:
            # Unix: atomic rename (overwrites existing file)
            src.rename(dst)

    def _check_overwrite_permission(self) -> bool:
        """Check if user wants to overwrite existing monolithic file."""
        # Auto-accept if --yes flag was used
        if self.yes_to_all:
            print(f"Overwriting existing file: {self.output_path.name}")
            return True
        
        # Get file info
        try:
            stat_info = self.output_path.stat()
            file_size = stat_info.st_size
            mod_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_info.st_mtime))
            
            # Count entries (quick check)
            entry_count = 0
            try:
                with open(self.output_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip() and not line.startswith('#') and '  ' in line:
                            entry_count += 1
            except Exception:
                entry_count = "unknown"
            
        except Exception:
            file_size = 0
            mod_time = "unknown"
            entry_count = "unknown"
        
        # Show file information and prompt
        print(f"\nFile '{self.output_path.name}' already exists:")
        if entry_count != "unknown":
            print(f"  Entries: {entry_count:,}")
        if file_size > 0:
            print(f"  Size: {self._format_size(file_size)}")
        print(f"  Modified: {mod_time}")
        
        print(f"\nAlternatives:")
        print(f"  - Use 'dazzlesum update -r .' for incremental updates")
        print(f"  - Use 'dazzlesum create -r --output different-name.{self.algorithm}' for different filename")
        print(f"  - Use '-y' flag to auto-overwrite in scripts")
        
        try:
            response = input(f"\nOverwrite '{self.output_path.name}'? (y/N): ").strip().lower()
            return response in ['y', 'yes']
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return False

    def _format_size(self, bytes_count: int) -> str:
        """Format bytes in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_count < 1024:
                return f"{bytes_count:.1f} {unit}"
            bytes_count /= 1024
        return f"{bytes_count:.1f} TB"


def is_monolithic_file(file_path: Path) -> bool:
    """Detect if a checksum file is in monolithic format."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Read first few lines to check for monolithic markers
            for i, line in enumerate(f):
                if i > 10:  # Only check first 10 lines
                    break

                line = line.strip()
                if not line or line.startswith('#'):
                    # Check for monolithic format indicators
                    if 'monolithic' in line.lower() or 'root directory:' in line.lower():
                        return True
                    continue
                else:
                    # Check if we have relative paths (indicating monolithic)
                    # Individual .shasum files should only have filenames, no paths
                    parts = line.split('  ', 1)
                    if len(parts) == 2:
                        filename = parts[1]
                        # If filename contains path separators, it's likely monolithic
                        if '/' in filename or '\\' in filename:
                            return True
                    break

        return False
    except Exception:
        return False


def parse_shasum_file(shasum_path: Path) -> Dict[str, str]:
    """Parse a .shasum file into {filename: hash} (hashes lowercased).

    Comment lines (#) and malformed lines are skipped. Raises OSError on
    read failure so callers can distinguish 'missing/unreadable' from 'empty'.
    """
    stored_checksums = {}
    with open(shasum_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split('  ', 1)
                if len(parts) == 2:
                    hash_value, filename = parts
                    stored_checksums[filename] = hash_value.lower()
    return stored_checksums
