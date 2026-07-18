"""SymlinkHandler, FIFODirectoryWalker, and pre-walk counting.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 1390-1455, 1610-1738, 1741-1824. Only import wiring and shared-state references
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

from .constants import logger, is_windows
from .patterns import CompiledPatternMatcher, _should_include_file_simple
from . import state


def count_dirs_and_files(root_path: Path, include_patterns, exclude_patterns,
                        follow_symlinks=False, recursive=True) -> Tuple[int, int]:
    """Pre-walk directory tree to count directories and files.
    
    Args:
        root_path: Root directory to count from
        include_patterns: Patterns for files to include
        exclude_patterns: Patterns for files to exclude  
        follow_symlinks: Whether to follow symbolic links
        recursive: Whether to count subdirectories recursively
        
    Returns:
        Tuple of (directory_count, file_count)
    """
    symlink_handler = SymlinkHandler()
    total_dirs = 0
    total_files = 0

    # Use a simple queue for counting
    dirs_to_visit = deque([root_path])

    while dirs_to_visit:
        current_dir = dirs_to_visit.popleft()

        # Skip if already visited (loop detection)
        if symlink_handler.is_visited(current_dir):
            continue
        symlink_handler.mark_visited(current_dir)

        # Skip if we shouldn't follow this link
        if not symlink_handler.should_follow_link(current_dir, follow_symlinks):
            continue

        try:
            total_dirs += 1

            # Periodic progress during counting (every 500 dirs)
            if total_dirs % 500 == 0:
                print(f"\r  Counting... {total_dirs:,} dirs, {total_files:,} files", end="", flush=True)

            # Count files in this directory
            for item in current_dir.iterdir():
                if item.is_file():
                    # Apply same filtering logic as main processor
                    if _should_include_file_simple(item, include_patterns, exclude_patterns):
                        total_files += 1
                elif item.is_dir() and not symlink_handler.is_visited(item):
                    if recursive:
                        # Skip excluded directories (same patterns used for files)
                        dir_name = item.name
                        skip = False
                        for pattern in exclude_patterns:
                            if dir_name == pattern or item.match(pattern):
                                skip = True
                                break
                        if not skip:
                            dirs_to_visit.append(item)
        except Exception:
            # Skip directories we can't access
            continue

    # Clear the counting line if we printed any updates
    if total_dirs >= 100:
        print("\r" + " " * 60 + "\r", end="", flush=True)

    return total_dirs, total_files


class SymlinkHandler:
    """Handles symlink and junction detection with loop prevention."""

    def __init__(self):
        self.visited_inodes = set()
        self.visited_paths = set()

    def is_symlink_or_junction(self, path: Path) -> Tuple[bool, Optional[str]]:
        """Detect symlinks and Windows junctions."""
        try:
            # Standard symlink detection
            if path.is_symlink():
                return True, 'symlink'

            # Windows junction detection
            if is_windows() and path.is_dir() and self._is_junction(path):
                return True, 'junction'

        except Exception as e:
            logger.debug(f"Error checking symlink status for {path}: {e}")

        return False, None

    def _is_junction(self, path: Path) -> bool:
        """Detect Windows junctions via reparse-point attributes.

        Pure lstat -- no subprocess, no resolve(). The previous implementation
        shelled out to `dir /AL` for every NON-junction directory (~60ms each,
        hours at library scale) and misclassified any directory reached
        through a junction ancestor because resolve() != path for all of them.
        """
        try:
            # Python 3.12+ has a dedicated check (reparse tag == mount point)
            if hasattr(path, 'is_junction'):
                return path.is_junction()

            stat_info = os.lstat(str(path))
            attrs = getattr(stat_info, 'st_file_attributes', 0)
            reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x0400)
            # Symlinks were already handled by the caller; any remaining
            # directory reparse point (junction, mount point) should not be
            # traversed by default.
            return bool(attrs & reparse)
        except OSError as e:
            logger.debug(f"Error detecting junction for {path}: {e}")
            return False

    def should_follow_link(self, path: Path, follow_symlinks: bool = False) -> bool:
        """Determine if we should follow this link."""
        is_link, link_type = self.is_symlink_or_junction(path)

        if not is_link:
            return True  # Regular file/directory

        if not follow_symlinks:
            return False  # User doesn't want to follow links

        # Additional safety checks for links
        try:
            target = path.resolve()
            # Ensure target exists and isn't pointing to parent
            return target.exists() and not self._is_parent_loop(path, target)
        except (OSError, RuntimeError):
            return False  # Broken or dangerous link

    def _is_parent_loop(self, link_path: Path, target_path: Path) -> bool:
        """Check if target is a parent of the link (potential loop)."""
        try:
            link_path.relative_to(target_path)
            return True  # link is inside target - potential loop
        except ValueError:
            return False  # No parent relationship

    def check_and_mark_walk_path(self, path: Path) -> bool:
        """Cheap duplicate guard for physical (non-link-following) walks.

        Returns True if the path was already seen. Keys by the walk path
        STRING only -- no resolve(), no stat(). When links are not followed,
        a BFS over physical directories cannot revisit a directory except by
        being enqueued twice with the same path, so inode tracking (which
        cost 4 syscalls per directory AND caused real directories to be
        skipped when a junction elsewhere in the tree pointed at them --
        their inodes got marked through the junction) is wrong here. Inode
        loop-protection belongs only to link-FOLLOWING walks.
        """
        key = str(path)
        if key in self.visited_paths:
            return True
        self.visited_paths.add(key)
        return False

    def mark_visited(self, path: Path):
        """Mark a path as visited for loop detection."""
        # Mark by resolved path
        try:
            resolved_path = str(path.resolve())
            self.visited_paths.add(resolved_path)
        except Exception:
            self.visited_paths.add(str(path))

        # Mark by inode (if available)
        try:
            stat_info = path.stat()
            inode_key = (stat_info.st_dev, stat_info.st_ino)
            self.visited_inodes.add(inode_key)
        except (OSError, AttributeError):
            pass  # Can't get inode info, path marking is sufficient

    def is_visited(self, path: Path) -> bool:
        """Check if we've already visited this path/inode."""
        # Check by resolved path
        try:
            resolved_path = str(path.resolve())
            if resolved_path in self.visited_paths:
                return True
        except Exception:
            if str(path) in self.visited_paths:
                return True

        # Check by inode (if available)
        try:
            stat_info = path.stat()
            inode_key = (stat_info.st_dev, stat_info.st_ino)
            if inode_key in self.visited_inodes:
                return True
        except (OSError, AttributeError):
            pass

        return False


class FIFODirectoryWalker:
    """FIFO directory processor for memory-efficient traversal."""

    def __init__(self, follow_symlinks=False, exclude_patterns=None):
        self.processing_queue = deque()
        self.symlink_handler = SymlinkHandler()
        self.follow_symlinks = follow_symlinks
        self.exclude_patterns = exclude_patterns or []
        self._exclude_matcher = CompiledPatternMatcher(self.exclude_patterns)
        self.processed_count = 0

    def _is_excluded_dir(self, item: Path) -> bool:
        """Match a directory against exclude patterns (same Path.match
        semantics as file exclusion). Historically --exclude only filtered
        FILES by name -- traversal descended into .git, .private, etc. and
        checksummed their contents, since files inside an excluded directory
        don't themselves match the directory's pattern.

        v1.5.0: basename patterns via one compiled regex on the dir NAME;
        multi-component patterns keep exact Path.match semantics."""
        m = self._exclude_matcher
        if m.matches_name(item.name):
            return True
        if m.multi and m.matches_multi(item):
            return True
        return False

    def walk_and_process(self, root_path: Path, processor_func, recursive=True):
        """
        FIFO directory processing with callback.

        Args:
            root_path: Starting directory
            processor_func: Function to call for each directory
            recursive: Whether to process subdirectories
        """
        self.processing_queue.append(root_path)

        while self.processing_queue:
            current_dir = self.processing_queue.popleft()

            # Duplicate/loop guard. Physical walks (follow_symlinks=False)
            # use the cheap string-key guard: inode marking followed links
            # via stat() and caused real directories to be skipped whenever a
            # junction elsewhere pointed at them (coverage hole, found
            # 2026-07-17: an entire venv subtree invisible to every scan),
            # and cost 4 syscalls per directory.
            if self.follow_symlinks:
                if self.symlink_handler.is_visited(current_dir):
                    logger.warning(f"Skipping {current_dir} - already visited (loop detected)")
                    continue
                self.symlink_handler.mark_visited(current_dir)
            elif self.symlink_handler.check_and_mark_walk_path(current_dir):
                continue

            # Check if we should follow this directory (symlink safety)
            if not self.symlink_handler.should_follow_link(current_dir, self.follow_symlinks):
                logger.debug(f"Skipping {current_dir} - symlink/junction not followed")
                continue

            # Process current directory
            try:
                if state.dazzle_logger:
                    state.dazzle_logger.directory_start(current_dir)
                else:
                    logger.info(f"Processing directory: {current_dir}")
                processor_func(current_dir)
                self.processed_count += 1
            except Exception as e:
                logger.error(f"Error processing directory {current_dir}: {e}")
                continue

            # Add subdirectories to queue if recursive
            if recursive:
                try:
                    subdirs = [item for item in current_dir.iterdir()
                              if item.is_dir()
                              and not self._is_excluded_dir(item)
                              and not self.symlink_handler.is_visited(item)]
                    for subdir in subdirs:
                        self.processing_queue.append(subdir)
                        logger.debug(f"Added to queue: {subdir}")
                except Exception as e:
                    logger.warning(f"Error listing subdirectories of {current_dir}: {e}")
