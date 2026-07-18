"""ChecksumGenerator: create/verify/update orchestration incl. threaded walk.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 2347-3577. Only import wiring and shared-state references
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
from .constants import (logger, DEFAULT_ALGORITHM, SHASUM_FILENAME,
                        STATE_FILENAME, CACHE_FILENAME, MONOLITHIC_DEFAULT_NAME)
from . import state
from .output import initialize_squelch_from_verbosity
from .patterns import (CompiledPatternMatcher, _always_excluded_name,
                       _should_include_file_simple)
from .results import (GrandTotals, ProgressTracker, SummaryCollector,
                      calculate_verification_status, format_status_with_colors)
from .hashing import DazzleHashCalculator
from .walk import SymlinkHandler, FIFODirectoryWalker, count_dirs_and_files
from .manifest import MonolithicWriter, parse_shasum_file, is_monolithic_file
from .shadow import ShadowPathResolver
from .statecache import StateCache


class ChecksumGenerator:
    """Main checksum generator orchestrator."""

    def __init__(self, algorithm=DEFAULT_ALGORITHM, line_ending_strategy='auto',
                 include_patterns=None, exclude_patterns=None, follow_symlinks=False,
                 log_file=None, summary_mode=False, generate_individual=True,
                 generate_monolithic=False, output_file=None, show_all_verifications=False,
                 shadow_dir=None, resume_mode=False, yes_to_all=False):
        self.algorithm = algorithm.lower()
        self.calculator = DazzleHashCalculator(algorithm, line_ending_strategy)
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or [SHASUM_FILENAME, STATE_FILENAME]
        
        # For monolithic mode, also exclude the temporary file that will be created
        if generate_monolithic:
            if output_file:
                temp_filename = Path(output_file).name + '.tmp'
            else:
                temp_filename = f"{MONOLITHIC_DEFAULT_NAME}.{self.algorithm}.tmp"
            self.exclude_patterns.append(temp_filename)
        
        self.follow_symlinks = follow_symlinks
        self.log_file = log_file
        self.summary_mode = summary_mode
        self.generate_individual = generate_individual
        self.generate_monolithic = generate_monolithic
        self.output_file = output_file
        self.show_all_verifications = show_all_verifications
        self.resume_mode = resume_mode
        self.yes_to_all = yes_to_all
        self.summary_collector = SummaryCollector()
        self.progress_tracker = None
        
        # Shadow directory support
        self.shadow_dir = Path(shadow_dir) if shadow_dir else None
        self.shadow_resolver = None

        # Compiled string-level matchers for the per-file hot loops (v1.5.0):
        # equivalence with the legacy per-pattern Path.match loop is pinned by
        # tests/test_update_mode.py::TestPatternMatcherEquivalence
        self._exclude_matcher = CompiledPatternMatcher(self.exclude_patterns)
        self._include_matcher = CompiledPatternMatcher(self.include_patterns)
        
        # Resume support - track processed directories
        self.processed_directories = set()
        self.existing_monolithic_entries = set() if resume_mode else None

        # Set up log file if specified
        if self.log_file:
            self._setup_log_file()
    
    def _initialize_resume_state(self, root_directory: Path):
        """Initialize resume state by scanning existing checksum files."""
        if not self.resume_mode:
            return
            
        logger.info("Resume mode: Scanning for existing checksums...")
        
        # For individual mode, find existing .shasum files
        if self.generate_individual:
            if self.shadow_resolver:
                # Check shadow directory for existing .shasum files
                for shadow_file in self.shadow_resolver.shadow_root.rglob('.shasum'):
                    # Map back to source directory
                    rel_path = shadow_file.parent.relative_to(self.shadow_resolver.shadow_root)
                    if rel_path == Path('.'):
                        source_dir = self.shadow_resolver.source_root
                    else:
                        source_dir = self.shadow_resolver.source_root / rel_path
                    self.processed_directories.add(str(source_dir.resolve()))
            else:
                # Check source directories for existing .shasum files
                for shasum_file in root_directory.rglob('.shasum'):
                    self.processed_directories.add(str(shasum_file.parent.resolve()))
        
        # For monolithic mode, parse existing monolithic file
        if self.generate_monolithic and self.existing_monolithic_entries is not None:
            monolithic_path = self._get_monolithic_path(root_directory)
            if monolithic_path and monolithic_path.exists():
                try:
                    with open(monolithic_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                parts = line.split('  ', 1)
                                if len(parts) == 2:
                                    _, relative_path = parts
                                    # Convert back to directory path
                                    file_path = Path(relative_path)
                                    dir_path = str((root_directory / file_path.parent).resolve())
                                    self.existing_monolithic_entries.add(relative_path)
                                    self.processed_directories.add(dir_path)
                except Exception as e:
                    logger.warning(f"Could not parse existing monolithic file for resume: {e}")
        
        if self.processed_directories:
            logger.info(f"Resume mode: Found {len(self.processed_directories)} directories with existing checksums")
        else:
            logger.info("Resume mode: No existing checksums found, starting fresh")
    
    def _get_monolithic_path(self, root_directory: Path) -> Optional[Path]:
        """Get the path where monolithic file would be/is stored."""
        if self.shadow_resolver:
            return self.shadow_resolver.get_shadow_monolithic_path(self.algorithm, self.output_file)
        elif self.output_file:
            output_path = Path(self.output_file)
            if not output_path.is_absolute():
                output_path = root_directory / output_path
            return output_path
        else:
            ext = f".{self.algorithm}"
            return root_directory / f"{MONOLITHIC_DEFAULT_NAME}{ext}"
    
    def _should_skip_directory(self, directory: Path) -> bool:
        """Check if directory should be skipped in resume mode."""
        if not self.resume_mode:
            return False
            
        dir_str = str(directory.resolve())
        return dir_str in self.processed_directories

    def _setup_log_file(self):
        """Set up detailed logging to file."""
        log_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler = logging.FileHandler(self.log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(logging.DEBUG)

        # Add to root logger
        logging.getLogger().addHandler(file_handler)
        logger.info(f"Detailed logging enabled to: {self.log_file}")

    def should_include_file(self, file_path: Path) -> bool:
        """Determine if a file should be included in checksums."""
        return _should_include_file_simple(file_path, self.include_patterns, self.exclude_patterns)

    def _include_entry(self, name: str, path_factory) -> bool:
        """String-first inclusion check for scandir hot loops.

        Semantics identical to should_include_file/_should_include_file_simple
        but avoids constructing a Path (and running per-pattern Path.match)
        for the overwhelmingly common case of basename-only patterns.
        `path_factory` is called lazily only when multi-component patterns
        need exact Path.match semantics.
        """
        if _always_excluded_name(name):
            return False
        ex = self._exclude_matcher
        if ex.matches_name(name):
            return False
        if ex.multi and ex.matches_multi(path_factory()):
            return False
        inc = self._include_matcher
        if inc.patterns:
            if inc.matches_name(name):
                return True
            if inc.multi and inc.matches_multi(path_factory()):
                return True
            return False
        return True

    def generate_checksums_for_directory(self, directory: Path) -> Dict[str, Any]:
        """Generate checksums for all files in a directory (non-recursive)."""
        checksums = {}
        files_processed = 0
        files_skipped = 0
        files_failed = 0
        total_bytes = 0
        start_time = time.time()

        try:
            # Get all files in directory
            files = [f for f in directory.iterdir() if f.is_file()]

            # Use DazzleLogger for consistent output
            if state.dazzle_logger:
                state.dazzle_logger.info(f"Found {len(files)} files in {directory}", level=1)
            else:
                # Fallback for direct calls
                if self.log_file:
                    logger.debug(f"Found {len(files)} files in {directory}")
                elif not self.summary_mode:
                    logger.info(f"Found {len(files)} files in {directory}")

            for file_path in files:
                if not self.should_include_file(file_path):
                    files_skipped += 1
                    if state.dazzle_logger:
                        state.dazzle_logger.file_skipped(file_path)
                    elif self.log_file:
                        logger.debug(f"Skipped: {file_path}")
                    continue

                try:
                    if state.dazzle_logger:
                        state.dazzle_logger.file_processed(file_path)
                    elif self.log_file:
                        logger.debug(f"Processing file: {file_path}")

                    hash_value = self.calculator.calculate_file_hash(file_path)

                    # Get file stats
                    stat_info = file_path.stat()
                    file_size = stat_info.st_size
                    total_bytes += file_size

                    checksums[file_path.name] = {
                        'hash': hash_value,
                        'size': file_size,
                        'mtime': stat_info.st_mtime,
                        'algorithm': self.algorithm
                    }
                    files_processed += 1

                    # Update progress tracker
                    if self.progress_tracker:
                        self.progress_tracker.update_files(1, file_size)

                    if self.log_file:
                        logger.debug(f"Completed: {file_path} -> {hash_value}")

                except Exception as e:
                    files_failed += 1
                    if self.log_file:
                        logger.error(f"Error processing {file_path}: {e}")
                    elif not self.summary_mode:
                        logger.error(f"Error processing {file_path}: {e}")

        except Exception as e:
            if self.log_file:
                logger.error(f"Error listing directory {directory}: {e}")
            elif not self.summary_mode:
                logger.error(f"Error listing directory {directory}: {e}")

        elapsed_time = time.time() - start_time

        # Log results using DazzleLogger
        if state.dazzle_logger:
            state.dazzle_logger.directory_complete(directory, files_processed, files_skipped, files_failed, elapsed_time)
        else:
            # Fallback for direct calls
            if self.log_file:
                logger.info(f"Directory {directory}: {files_processed} processed, "
                           f"{files_skipped} skipped, {files_failed} failed in {elapsed_time:.2f}s")
            elif not self.summary_mode:
                logger.info(f"Directory {directory}: {files_processed} processed, "
                           f"{files_skipped} skipped in {elapsed_time:.2f}s")

        # Add to summary
        self.summary_collector.add_directory(files_processed, files_skipped, files_failed, total_bytes)

        return checksums

    def write_shasum_file(self, directory: Path, checksums: Dict[str, Any]):
        """Write checksums to .shasum file in native-compatible format."""
        # Use shadow path if shadow mode is active
        if self.shadow_resolver:
            shasum_path = self.shadow_resolver.get_shadow_shasum_path(directory)
            # Ensure shadow directory exists
            self.shadow_resolver.ensure_shadow_directory(shasum_path)
        else:
            shasum_path = directory / SHASUM_FILENAME

        try:
            # Write to a temp file then atomically replace, so an interrupted
            # run never leaves a truncated .shasum behind.
            temp_path = shasum_path.with_name(shasum_path.name + '.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                # Write header comment
                f.write(f"# Dazzle checksum tool v{__version__} - {self.algorithm} - {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")

                # Write checksums in standard format
                for filename, info in sorted(checksums.items()):
                    f.write(f"{info['hash']}  {filename}\n")

                # Write end marker
                f.write("# End of checksums\n")
            os.replace(temp_path, shasum_path)

            if self.log_file:
                logger.info(f"Wrote {len(checksums)} checksums to {shasum_path}")
            elif not self.summary_mode:
                logger.info(f"Wrote {len(checksums)} checksums to {shasum_path}")

        except Exception as e:
            if self.log_file:
                logger.error(f"Error writing .shasum file to {directory}: {e}")
            elif not self.summary_mode:
                logger.error(f"Error writing .shasum file to {directory}: {e}")

    def scan_directory_files(self, directory: Path):
        """One scandir pass over a directory: {name: stat} for included files.

        Returns None on OSError (caller counts a failure). Thread-safe: uses
        only the compiled matchers (read-only after init) and syscalls, so
        worker threads can run it concurrently (scandir/stat release the GIL).
        """
        live = {}
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=self.follow_symlinks) \
                            and self._include_entry(
                                entry.name,
                                lambda e=entry: Path(e.path)):
                        live[entry.name] = entry.stat(follow_symlinks=self.follow_symlinks)
        except OSError as e:
            logger.error(f"Error listing directory {directory}: {e}")
            return None
        return live

    def update_checksums_for_directory(self, directory: Path, state_cache: 'StateCache',
                                       root_directory: Path, bootstrap='hash',
                                       paranoid=False, keep_missing=False,
                                       pre_scanned=None) -> Dict[str, int]:
        """Incrementally update one directory's .shasum, rehashing only what changed.

        Comparison is EQUALITY against recorded per-file state (size, mtime_ns),
        not "is mtime newer" -- synced trees (e.g. Resilio) deliver content
        changes carrying origin mtimes that can be OLDER than the last scan.

        Returns stats: {unchanged, rehashed, added, removed, failed, rewritten}.
        """
        stats = {'unchanged': 0, 'rehashed': 0, 'added': 0,
                 'removed': 0, 'failed': 0, 'rewritten': 0}

        # Resolve manifest path (shadow or local)
        if self.shadow_resolver:
            shasum_path = self.shadow_resolver.get_shadow_shasum_path(directory)
        else:
            shasum_path = directory / SHASUM_FILENAME

        folder = StateCache.folder_key(directory, root_directory)
        cached = state_cache.get_folder(folder)

        # One scandir pass: live files + their stat info. String-first
        # inclusion check -- no Path construction in the common case (v1.5.0).
        # Threaded mode passes pre_scanned from a worker thread.
        live = pre_scanned if pre_scanned is not None else self.scan_directory_files(directory)
        if live is None:
            stats['failed'] += 1
            return stats

        # FAST PATH: folder unchanged since last update. When every live file
        # matches the cache exactly (same name set, same size + mtime_ns, same
        # algorithm) and the manifest file is present, skip the manifest parse
        # AND the cache rewrite entirely -- a steady-state sweep then costs one
        # scandir and one indexed SELECT per folder. Trade-off: an externally
        # edited manifest is not detected on this path; `--paranoid` (or
        # `verify`) re-establishes truth.
        if (not paranoid and cached and set(live) == set(cached)
                and all(c['algo'] == self.algorithm
                        and c['size'] == st.st_size
                        and c['mtime_ns'] == st.st_mtime_ns
                        for name, st in live.items()
                        for c in (cached[name],))
                and shasum_path.exists()):
            stats['unchanged'] = len(live)
            if self.progress_tracker:
                for st in live.values():
                    self.progress_tracker.update_files(1, st.st_size)
            return stats

        stored = {}
        if shasum_path.exists():
            try:
                stored = parse_shasum_file(shasum_path)
            except Exception as e:
                logger.error(f"Error reading {shasum_path}: {e} -- skipping directory")
                stats['failed'] += 1
                return stats

        new_checksums = {}
        cache_entries = {}

        for name, st in sorted(live.items()):
            size, mtime_ns = st.st_size, st.st_mtime_ns
            c = cached.get(name)
            cache_valid = (not paranoid and c is not None
                           and c['algo'] == self.algorithm
                           and c['size'] == size
                           and c['mtime_ns'] == mtime_ns)
            # A manifest hash that disagrees with our own cache means the
            # manifest was modified externally -- rehash to re-establish truth.
            if cache_valid and name in stored and stored[name] != c['hash']:
                cache_valid = False

            if cache_valid:
                hash_value = c['hash']
                stats['unchanged'] += 1
                if name not in stored:
                    stats['added'] += 1  # manifest gains entry from cache, no rehash
            elif (not paranoid and c is None and name in stored
                    and bootstrap == 'trust'):
                # Bootstrap-trust: seed cache from current stat + stored hash
                # without rehashing. Only sound against a freshly generated
                # manifest (the caller asserts that by choosing trust).
                hash_value = stored[name]
                stats['unchanged'] += 1
            else:
                try:
                    hash_value = self.calculator.calculate_file_hash(Path(directory) / name)
                    stats['rehashed'] += 1
                    if name not in stored:
                        stats['added'] += 1
                except Exception as e:
                    stats['failed'] += 1
                    logger.error(f"Error processing {directory / name}: {e}")
                    # Keep the previous manifest entry if one existed; skip caching.
                    if name in stored:
                        new_checksums[name] = {'hash': stored[name]}
                    continue

            new_checksums[name] = {'hash': hash_value, 'size': size,
                                   'mtime': st.st_mtime, 'algorithm': self.algorithm}
            cache_entries[name] = {'size': size, 'mtime_ns': mtime_ns,
                                   'algo': self.algorithm, 'hash': hash_value}

            if self.progress_tracker:
                self.progress_tracker.update_files(1, size)

        # Entries in the manifest whose files no longer exist
        for name in stored:
            if name not in live:
                if keep_missing:
                    new_checksums[name] = {'hash': stored[name]}
                else:
                    stats['removed'] += 1

        # Rewrite the manifest ONLY if its checksum content actually changed --
        # unchanged manifests stay byte-identical (no git churn, mtime preserved).
        new_content = {name: info['hash'].lower() for name, info in new_checksums.items()}
        if new_content != stored and (new_checksums or stored):
            self.write_shasum_file(directory, new_checksums)
            stats['rewritten'] += 1

        state_cache.replace_folder(folder, cache_entries)
        return stats

    def _threaded_update_walk(self, root_directory: Path, handle_result, workers: int):
        """Parallel BFS for update mode: worker threads perform the syscall
        work (scandir + stat + junction checks -- all GIL-releasing) and feed
        results to the CALLING thread, which owns every piece of mutable
        state (SQLite cache, totals, manifest writes) exactly as in serial
        mode. handle_result(directory, live_or_None) runs on the caller.

        Traversal semantics mirror FIFODirectoryWalker: visited-set loop
        protection, symlink/junction policy, and exclusion pruning at
        enqueue time.
        """
        work_q = queue_module.SimpleQueue()
        results_q = queue_module.SimpleQueue()
        lock = threading.Lock()
        symlink_handler = SymlinkHandler()
        matcher = self._exclude_matcher
        state = {'discovered': 1, 'stop': False}
        work_q.put(root_directory)

        def _excluded_dir(item: Path) -> bool:
            if matcher.matches_name(item.name):
                return True
            return bool(matcher.multi and matcher.matches_multi(item))

        def worker():
            while True:
                try:
                    d = work_q.get(timeout=0.1)
                except queue_module.Empty:
                    if state['stop']:
                        return
                    continue
                # Cheap string-key duplicate guard (see FIFODirectoryWalker
                # note); keeps the locked section syscall-free so workers
                # don't serialize on it. Link-following walks use the serial
                # engine (threaded mode requires follow_symlinks=False).
                with lock:
                    if symlink_handler.check_and_mark_walk_path(d):
                        results_q.put((d, 'skip', None))
                        continue
                # Link policy: children are pre-filtered at DISCOVERY below
                # using the parent scandir's cached reparse data (zero extra
                # syscalls, v1.5.0a2; was 2 lstats per dir here at pop).
                # Only the walk ROOT still needs the explicit check -- it was
                # never anyone's child entry.
                if d is root_directory and not symlink_handler.should_follow_link(
                        d, self.follow_symlinks):
                    results_q.put((d, 'skip', None))
                    continue
                # One scandir yields BOTH included files and child dirs
                live = {}
                subdirs = []
                try:
                    with os.scandir(d) as it:
                        for entry in it:
                            if entry.is_dir(follow_symlinks=False):
                                # DirEntry reparse data is already in hand:
                                # skip symlinked/junction children lstat-free
                                if entry.is_symlink():
                                    continue
                                is_junc = getattr(entry, 'is_junction', None)
                                if is_junc is not None and is_junc():
                                    continue
                                child = Path(entry.path)
                                if not _excluded_dir(child):
                                    subdirs.append(child)
                            elif entry.is_file(follow_symlinks=self.follow_symlinks) \
                                    and self._include_entry(
                                        entry.name,
                                        lambda e=entry: Path(e.path)):
                                live[entry.name] = entry.stat(
                                    follow_symlinks=self.follow_symlinks)
                except OSError as e:
                    logger.error(f"Error listing directory {d}: {e}")
                    results_q.put((d, 'error', None))
                    continue
                if subdirs:
                    with lock:
                        state['discovered'] += len(subdirs)
                    for child in subdirs:
                        work_q.put(child)
                results_q.put((d, 'ok', live))

        threads = [threading.Thread(target=worker, daemon=True,
                                    name=f"dzsum-scan-{i}")
                   for i in range(workers)]
        for t in threads:
            t.start()

        processed = 0
        while True:
            with lock:
                discovered = state['discovered']
            if processed >= discovered:
                break
            d, kind, live = results_q.get()
            processed += 1
            if kind == 'ok':
                handle_result(d, live)
            elif kind == 'error':
                handle_result(d, None)
            # 'skip' (visited/link-policy) produces no totals, matching serial

        state['stop'] = True
        for t in threads:
            t.join(timeout=2.0)

    def run_update(self, root_directory: Path, recursive=True, dirs=None,
                   bootstrap='hash', paranoid=False, keep_missing=False,
                   threads=None) -> Dict[str, int]:
        """Orchestrate an incremental update over a tree or an explicit folder list.

        `dirs` (iterable of paths under root_directory) is the universal
        change-detection adapter: any external source (git hook, USN watcher,
        cron sweep) can nominate suspect folders. Without it, the full tree is
        swept -- complete, stat-bound, no daemon required.
        """
        root_directory = Path(root_directory).resolve()
        if not root_directory.exists() or not root_directory.is_dir():
            logger.error(f"Directory does not exist or is not a directory: {root_directory}")
            return {}

        if self.shadow_dir:
            self.shadow_resolver = ShadowPathResolver(
                source_root=root_directory, shadow_root=self.shadow_dir)
            cache_path = self.shadow_resolver.shadow_root / CACHE_FILENAME
        else:
            cache_path = root_directory / CACHE_FILENAME

        totals = {'dirs': 0, 'unchanged': 0, 'rehashed': 0, 'added': 0,
                  'removed': 0, 'failed': 0, 'rewritten': 0}
        start_time = time.time()

        # Worker count: default auto = min(16, 2 x cores) -- scan workers are
        # I/O-bound (idle in scandir/stat syscalls), so oversubscribing cores
        # keeps the disk queue full: 16 workers measured 4.45 min vs 8.82 at
        # 8 on the 3.38M-file reference library. 1 = the serial walker,
        # byte-for-byte the pre-threading code path (escape hatch).
        if threads is None:
            threads = min(16, 2 * (os.cpu_count() or 4))

        with StateCache(cache_path) as cache:
            def update_single_directory(directory: Path, pre_scanned=None):
                stats = self.update_checksums_for_directory(
                    directory, cache, root_directory, bootstrap=bootstrap,
                    paranoid=paranoid, keep_missing=keep_missing,
                    pre_scanned=pre_scanned)
                totals['dirs'] += 1
                for key, value in stats.items():
                    totals[key] += value
                if self.progress_tracker:
                    self.progress_tracker.update_dirs(1)
                if totals['dirs'] % 5000 == 0:
                    logger.info(
                        f"...{totals['dirs']} dirs so far -- "
                        f"{totals['unchanged']} unchanged, {totals['rehashed']} rehashed, "
                        f"{totals['added']} added, {totals['removed']} removed")

            def handle_scanned(directory: Path, live):
                if live is None:
                    totals['dirs'] += 1
                    totals['failed'] += 1
                    return
                update_single_directory(directory, pre_scanned=live)

            if dirs is not None:
                for d in dirs:
                    d = Path(d)
                    if not d.is_absolute():
                        d = root_directory / d
                    # Containment check without per-entry resolve() (v1.5.0:
                    # resolving each listed dir cost one _getfinalpathname
                    # syscall per entry -- ~9s per 20K dirs profiled).
                    # resolve() only as fallback for unnormalized input.
                    try:
                        d.relative_to(root_directory)
                    except ValueError:
                        d = d.resolve()
                        try:
                            d.relative_to(root_directory)
                        except ValueError:
                            logger.warning(f"Skipping {d}: not under {root_directory}")
                            continue
                    if not d.is_dir():
                        logger.warning(f"Skipping {d}: not a directory")
                        continue
                    update_single_directory(d)
            elif recursive and threads > 1 and not self.follow_symlinks:
                self._threaded_update_walk(root_directory, handle_scanned, threads)
            else:
                walker = FIFODirectoryWalker(self.follow_symlinks, self.exclude_patterns)
                walker.walk_and_process(root_directory, update_single_directory, recursive)

        elapsed = time.time() - start_time
        logger.info(
            f"Update complete: {totals['dirs']} dirs in {elapsed:.2f}s -- "
            f"{totals['unchanged']} unchanged, {totals['rehashed']} rehashed, "
            f"{totals['added']} added, {totals['removed']} removed, "
            f"{totals['rewritten']} manifests rewritten, {totals['failed']} failed")
        return totals

    def verify_checksums_in_directory(self, directory: Path) -> Dict[str, Any]:
        """Verify checksums in a directory against its .shasum file."""
        # Use shadow path if shadow mode is active
        if self.shadow_resolver:
            shasum_path = self.shadow_resolver.get_shadow_shasum_path(directory)
        else:
            shasum_path = directory / SHASUM_FILENAME

        if not shasum_path.exists():
            return {'error': f"No {SHASUM_FILENAME} file found in {shasum_path}"}

        results = {
            'verified': [],
            'failed': [],
            'missing': [],
            'extra': []
        }

        # Read existing checksums
        try:
            stored_checksums = parse_shasum_file(shasum_path)
        except Exception as e:
            return {'error': f"Error reading {shasum_path}: {e}"}

        # Check each stored checksum
        for filename, expected_hash in stored_checksums.items():
            # Filenames in .shasum are relative to the directory being verified
            file_path = directory / filename

            if not file_path.exists():
                results['missing'].append(filename)
                continue

            try:
                actual_hash = self.calculator.calculate_file_hash(file_path)
                if actual_hash.lower() == expected_hash.lower():
                    results['verified'].append(filename)
                    if self.log_file:
                        logger.debug(f"Verified: {filename}")
                else:
                    results['failed'].append({
                        'filename': filename,
                        'expected': expected_hash,
                        'actual': actual_hash
                    })
                    if self.log_file:
                        logger.error(f"Hash mismatch: {filename} - expected {expected_hash[:16]}... got {actual_hash[:16]}...")

                # Update progress tracker
                if self.progress_tracker:
                    try:
                        fsize = file_path.stat().st_size
                    except OSError:
                        fsize = 0
                    self.progress_tracker.update_files(1, fsize)

            except Exception as e:
                results['failed'].append({
                    'filename': filename,
                    'error': str(e)
                })
                if self.log_file:
                    logger.error(f"Error verifying {filename}: {e}")

        # Check for extra files
        current_files = {f.name for f in directory.iterdir()
                        if f.is_file() and self.should_include_file(f)}
        stored_files = set(stored_checksums.keys())
        results['extra'] = list(current_files - stored_files)

        # Add to summary
        self.summary_collector.add_verification(results)

        return results

    def verify_monolithic_file(self, monolithic_file: Path, root_directory: Path) -> Dict[str, Any]:
        """Verify checksums from a monolithic file."""
        if not monolithic_file.exists():
            return {'error': f"Monolithic file not found: {monolithic_file}"}

        results = {
            'verified': [],
            'failed': [],
            'missing': [],
            'extra': []
        }

        # Read monolithic checksums
        stored_checksums = {}
        file_root = None

        try:
            with open(monolithic_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('# Root directory:'):
                        # Extract root directory from header
                        file_root = line.split(':', 1)[1].strip()
                    elif line and not line.startswith('#'):
                        parts = line.split('  ', 1)
                        if len(parts) == 2:
                            hash_value, relative_path = parts
                            # Convert to platform-appropriate path separators
                            relative_path = relative_path.replace('/', os.sep)
                            stored_checksums[relative_path] = hash_value.lower()
        except Exception as e:
            return {'error': f"Error reading monolithic file: {e}"}

        # Determine base path for verification
        # Always use the user-specified directory for verification
        # The stored root directory is only for reference/documentation
        base_path = root_directory
        
        # Inform user if verifying against different directory than stored
        if file_root and str(Path(file_root).resolve()) != str(base_path.resolve()):
            if state.dazzle_logger and not state.dazzle_logger.quiet:
                state.dazzle_logger.info(f"Clone verification: Checking {base_path} against checksums from {file_root}", level=1)
            else:
                logger.info(f"Clone verification: Checking {base_path} against checksums from {file_root}")

        # Check each stored checksum
        for relative_path, expected_hash in stored_checksums.items():
            file_path = base_path / relative_path

            if not file_path.exists():
                results['missing'].append(relative_path)
                continue

            try:
                actual_hash = self.calculator.calculate_file_hash(file_path)
                if actual_hash.lower() == expected_hash.lower():
                    results['verified'].append(relative_path)
                    if self.log_file:
                        logger.debug(f"Verified: {relative_path}")
                else:
                    results['failed'].append({
                        'filename': relative_path,
                        'expected': expected_hash,
                        'actual': actual_hash
                    })
                    if self.log_file:
                        logger.error(f"Hash mismatch: {relative_path} - expected {expected_hash[:16]}... got {actual_hash[:16]}...")

                # Update progress tracker
                if self.progress_tracker:
                    try:
                        fsize = file_path.stat().st_size
                    except OSError:
                        fsize = 0
                    self.progress_tracker.update_files(1, fsize)

            except Exception as e:
                results['failed'].append({
                    'filename': relative_path,
                    'error': str(e)
                })
                if self.log_file:
                    logger.error(f"Error verifying {relative_path}: {e}")

        # Note: Extra file detection is more complex for monolithic mode
        # We would need to recursively scan the directory tree and compare
        # This is left as a future enhancement

        # Add to summary
        self.summary_collector.add_verification(results)

        return results

    def process_directory_tree(self, root_directory: Path, recursive=True,
                             verify_only=False, update_mode=False):
        """Process an entire directory tree."""

        if update_mode:
            # Incremental update path (see run_update). Historically this
            # parameter was accepted but ignored, silently doing a full create.
            return self.run_update(root_directory, recursive=recursive)

        if not root_directory.exists():
            logger.error(f"Directory does not exist: {root_directory}")
            return

        if not root_directory.is_dir():
            logger.error(f"Path is not a directory: {root_directory}")
            return

        # Initialize shadow resolver if shadow directory is specified
        if self.shadow_dir:
            self.shadow_resolver = ShadowPathResolver(
                source_root=root_directory,
                shadow_root=self.shadow_dir
            )
            if state.dazzle_logger:
                state.dazzle_logger.info(f"Using shadow directory: {self.shadow_dir}", level=1)
            else:
                logger.info(f"Using shadow directory: {self.shadow_dir}")
        
        # Initialize resume state if resume mode is enabled
        if not verify_only:  # Only for generation, not verification
            self._initialize_resume_state(root_directory)

        # Check for monolithic verification mode
        if verify_only and self.generate_monolithic:
            # Look for monolithic file
            if self.output_file:
                monolithic_file = Path(self.output_file)
            else:
                # Try default monolithic filename
                ext = f".{self.algorithm}"
                monolithic_file = root_directory / f"{MONOLITHIC_DEFAULT_NAME}{ext}"

            if monolithic_file.exists():
                results = self.verify_monolithic_file(monolithic_file, root_directory)
                if not self.summary_mode and not self.log_file:
                    self._print_verification_results(monolithic_file, results, self.show_all_verifications)
                elif self.log_file and 'error' not in results:
                    logger.info(f"Verified monolithic file: {monolithic_file}")
                return
            else:
                logger.error(f"Monolithic file not found: {monolithic_file}")
                return

        # Check for individual file verification of a potential monolithic file
        if verify_only and not recursive and not self.generate_monolithic:
            shasum_file = root_directory / SHASUM_FILENAME
            if shasum_file.exists() and is_monolithic_file(shasum_file):
                logger.info("Detected monolithic checksum file, using monolithic verification mode")
                results = self.verify_monolithic_file(shasum_file, root_directory)
                if not self.summary_mode and not self.log_file:
                    self._print_verification_results(shasum_file, results, self.show_all_verifications)
                return

        # Initialize progress tracking if summary mode
        if self.summary_mode:
            # Don't print info messages that interfere with progress bar
            print("Scanning directory tree...", end="", flush=True)
            total_dirs, total_files = count_dirs_and_files(
                root_directory, self.include_patterns, self.exclude_patterns, self.follow_symlinks, recursive
            )
            print(f" found {total_dirs:,} dirs, {total_files:,} files")
            self.progress_tracker = ProgressTracker(total_dirs, total_files, True)

        # Set up monolithic writer if needed
        monolithic_writer = None
        if self.generate_monolithic and not verify_only:
            if not recursive:
                logger.error("Monolithic mode requires --recursive flag")
                return

            # Determine output file path
            if self.shadow_resolver:
                # Use shadow directory for monolithic file
                output_path = self.shadow_resolver.get_shadow_monolithic_path(
                    self.algorithm, 
                    self.output_file
                )
                if state.dazzle_logger:
                    state.dazzle_logger.info(f"Using shadow directory for monolithic file: {output_path}", level=1)
                else:
                    logger.info(f"Using shadow directory for monolithic file: {output_path}")
            elif self.output_file:
                output_path = Path(self.output_file)
                if not output_path.is_absolute():
                    output_path = root_directory / output_path
            else:
                # Default monolithic filename
                ext = f".{self.algorithm}"
                output_path = root_directory / f"{MONOLITHIC_DEFAULT_NAME}{ext}"

            monolithic_writer = MonolithicWriter(output_path, root_directory, self.algorithm, self.resume_mode, self.yes_to_all)

        walker = FIFODirectoryWalker(self.follow_symlinks, self.exclude_patterns)

        def process_single_directory(directory: Path):
            # Skip directory if in resume mode and already processed
            if self._should_skip_directory(directory):
                if state.dazzle_logger:
                    state.dazzle_logger.info(f"Resume mode: Skipping already processed directory: {directory}", level=1)
                else:
                    logger.info(f"Resume mode: Skipping already processed directory: {directory}")
                return
                
            if verify_only:
                if self.generate_monolithic:
                    # This shouldn't happen as we handle it above
                    logger.error("Monolithic verification should be handled before directory walking")
                else:
                    results = self.verify_checksums_in_directory(directory)
                    if not self.summary_mode and not self.log_file:
                        self._print_verification_results(directory, results, self.show_all_verifications)
                    elif self.log_file and 'error' not in results:
                        logger.info(f"Verified directory: {directory}")
            else:
                checksums = self.generate_checksums_for_directory(directory)
                if checksums:
                    # Write to monolithic file if enabled
                    if monolithic_writer and self.generate_monolithic:
                        monolithic_writer.append_directory_checksums(directory, checksums)

                    # Write individual .shasum file if enabled
                    if self.generate_individual:
                        self.write_shasum_file(directory, checksums)

            # Update progress tracker
            if self.progress_tracker:
                self.progress_tracker.update_dirs(1)

        # Initialize grand totals for recursive verification
        if verify_only and recursive:
            state.grand_totals = GrandTotals()
            state.grand_totals.start_timing()

        if not self.summary_mode:
            logger.info(f"Starting {'recursive ' if recursive else ''}processing of {root_directory}")

        start_time = time.time()

        try:
            if monolithic_writer:
                with monolithic_writer:
                    walker.walk_and_process(root_directory, process_single_directory, recursive)
            else:
                walker.walk_and_process(root_directory, process_single_directory, recursive)
        except Exception as e:
            logger.error(f"Error during directory processing: {e}")
            if monolithic_writer and monolithic_writer._is_open:
                monolithic_writer.close(success=False)
            raise

        # Finish progress tracking
        if self.progress_tracker:
            self.progress_tracker.finish()

        elapsed_time = time.time() - start_time

        if not self.summary_mode:
            logger.info(f"Completed processing {walker.processed_count} directories in {elapsed_time:.2f}s")

        # Display grand totals for recursive verification
        if verify_only and recursive and state.grand_totals:
            state.grand_totals.end_timing()
            # Exit code must be finalized even when silent mode suppresses
            # the display -- silent mode is exit-codes-only, not exit-code-less
            state.grand_totals.finalize_exit_code()
            # Check for silent mode (-6) - no output at all
            if not (state.verbosity_config and state.verbosity_config.is_silent()):
                state.grand_totals.display_grand_totals()

        # Print summary if in summary mode
        if self.summary_mode:
            self.summary_collector.print_summary()

    def _print_verification_results(self, path: Path, results: Dict[str, Any], show_all=False):  # noqa: C901
        """Print verification results for a directory or monolithic file."""
        
        # Check for silent mode first - no output at all
        if state.verbosity_config and state.verbosity_config.is_silent():
            # Still add to grand totals if tracking, but no output
            if state.grand_totals:
                state.grand_totals.add_directory_result(results)
            return
        
        # Check for ultra-quiet modes - only grand totals and maybe summary
        if state.verbosity_config and state.verbosity_config.get_effective_level() <= -5:
            # Still add to grand totals but skip all directory output
            if state.grand_totals:
                state.grand_totals.add_directory_result(results)
            return
        
        if 'error' in results:
            # Check if this is a "No .shasum file found" informational message
            error_msg = results['error']
            if "No .shasum file found" in error_msg:
                # Check squelch settings for NO_SHASUM messages
                if state.squelch_settings and state.squelch_settings.get('NO_SHASUM', False):
                    # Skip displaying this message due to squelch
                    pass
                else:
                    # Use info_secondary color for missing .shasum files (not a failure, just informational)
                    if state.color_formatter:
                        colored_msg = state.color_formatter.info_secondary(f"{path}: {error_msg}")
                    else:
                        colored_msg = f"{path}: {error_msg}"
                    
                    if state.dazzle_logger:
                        state.dazzle_logger.info(colored_msg, level=0)
                    else:
                        logger.info(colored_msg)
            else:
                # Regular error - use error formatting
                if state.dazzle_logger:
                    state.dazzle_logger.error(f"{path}: {error_msg}")
                else:
                    logger.error(f"{path}: {error_msg}")
            
            # Add error results to grand totals if tracking
            if state.grand_totals:
                state.grand_totals.add_directory_result(results)
            return

        verified_count = len(results['verified'])
        failed_count = len(results['failed'])
        missing_count = len(results['missing'])
        extra_count = len(results['extra'])

        # Show individual file results if requested or verbose
        if show_all or (state.dazzle_logger and state.dazzle_logger.verbosity >= 2):
            # Show all verification results
            for filename in results['verified']:
                if state.color_formatter:
                    logger.info(f" {state.color_formatter.success('OK')} {state.color_formatter.filename(filename)}")
                else:
                    logger.info(f" OK {filename}")

        # Show individual failure details - check squelch settings
        if failed_count > 0 and not (state.squelch_settings and state.squelch_settings.get('FAILS', False)):
            for item in results['failed']:
                if isinstance(item, dict):
                    if 'error' in item:
                        if state.color_formatter:
                            error_text = f" {state.color_formatter.error('ERROR')} {state.color_formatter.filename(item['filename'])}: {item['error']}"
                        else:
                            error_text = f" ERROR {item['filename']}: {item['error']}"
                        
                        if state.dazzle_logger:
                            state.dazzle_logger.error(error_text)
                        else:
                            logger.error(error_text)
                    else:
                        # Always show hash mismatches with new format: expected HASH... got HASH... | filename
                        if state.color_formatter:
                            expected_hash = state.color_formatter.hash_value(f"expected {item['expected'][:16]}...")
                            got_hash = state.color_formatter.hash_value(f"got {item['actual'][:16]}...")
                            filename_part = state.color_formatter.filename(item['filename'])
                            fail_text = f" {state.color_formatter.error('FAIL')} {expected_hash} {got_hash} | {filename_part}"
                        else:
                            fail_text = f" FAIL expected {item['expected'][:16]}... got {item['actual'][:16]}... | {item['filename']}"
                        
                        if state.dazzle_logger:
                            logger.error(fail_text)
                        else:
                            logger.error(fail_text)

        # Show individual missing files - check squelch settings
        if missing_count > 0 and not (state.squelch_settings and state.squelch_settings.get('MISSING', False)):
            for filename in results['missing']:
                # Show missing files (problems)
                if state.color_formatter:
                    miss_text = f" {state.color_formatter.warning('MISS')} {state.color_formatter.filename(filename)}"
                else:
                    miss_text = f" MISS {filename}"
                logger.warning(miss_text)

        # Show individual extra files - check squelch settings
        if extra_count > 0 and not (state.squelch_settings and state.squelch_settings.get('EXTRA', False)):
            for filename in results['extra']:
                # Show extra files
                # In quiet mode, show directory context for EXTRA files
                if state.dazzle_logger and state.dazzle_logger.quiet:
                    if state.color_formatter:
                        extra_text = f" {state.color_formatter.extra('EXTRA')} {state.color_formatter.filename(filename)} | {path}"
                    else:
                        extra_text = f" EXTRA {filename} | {path}"
                else:
                    if state.color_formatter:
                        extra_text = f" {state.color_formatter.extra('EXTRA')} {state.color_formatter.filename(filename)}"
                    else:
                        extra_text = f" EXTRA {filename}"
                logger.warning(extra_text)

        # Calculate intelligent status with percentages
        status_text, exit_code, success_pct, failure_pct = calculate_verification_status(
            verified_count, failed_count, missing_count, extra_count
        )
        
        # Apply colors to the status text
        colored_status = format_status_with_colors(status_text, success_pct, failure_pct)
        
        # Format count details with colors and bold numbers
        if state.color_formatter:
            verified_text = f"{state.color_formatter.bold_number(verified_count)} {state.color_formatter.success('verified')}"
            failed_text = f"{state.color_formatter.bold_number(failed_count)} {state.color_formatter.error('failed')}"
            missing_text = f"{state.color_formatter.bold_number(missing_count)} {state.color_formatter.warning('missing')}"
            extra_text = f"{state.color_formatter.bold_number(extra_count)} {state.color_formatter.extra('extra')}"
        else:
            verified_text = f"{verified_count} verified"
            failed_text = f"{failed_count} failed"
            missing_text = f"{missing_count} missing"
            extra_text = f"{extra_count} extra"

        # Build complete summary line
        summary = f"{colored_status} {path}: {verified_text}, {failed_text}, {missing_text}, {extra_text}"
        
        # Check squelch settings before displaying
        should_display = True
        
        if state.squelch_settings:
            # Check if FORCE_SUMMARY is set - this overrides hiding logic but respects category filtering
            if state.squelch_settings.get('FORCE_SUMMARY', False):
                # FORCE_SUMMARY overrides visibility hiding but respects category filtering
                # Category filtering takes absolute priority - check independently
                should_display = True  # Default to force display
                
                # Check SUCCESS squelching first (highest priority)
                # SUCCESS includes both exit_code=0 (perfect) and exit_code=2 (with extras)
                if 'SUCCESS' in status_text and state.squelch_settings.get('SUCCESS', False):
                    should_display = False  # SUCCESS always squelched when SUCCESS=True
                
                # Check pure EXTRA-only squelching (if not already squelched by SUCCESS)
                if should_display and (extra_count > 0 and failed_count == 0 and missing_count == 0 and verified_count == 0 and state.squelch_settings.get('EXTRA', False)):
                    should_display = False  # Pure EXTRA-only squelched when EXTRA=True
                
                # Check EXTRA_SUMMARY squelching (if not already squelched)
                if should_display and (extra_count > 0 and failed_count == 0 and missing_count == 0 and state.squelch_settings.get('EXTRA_SUMMARY', False)):
                    should_display = False  # EXTRA_SUMMARY compressed display
            # Check if SUMMARY (directory status lines) should be squelched
            elif state.squelch_settings.get('SUMMARY', False):
                should_display = False
            # Check if this is a SUCCESS message that should be squelched
            elif 'SUCCESS' in status_text and state.squelch_settings.get('SUCCESS', False):
                # This is a SUCCESS (perfect or with extras) and SUCCESS is squelched
                # But for auto-detected commands, always show the summary
                if not state.is_auto_detected_command:
                    should_display = False
            else:
                # Check if directory has only issues that are being squelched
                # If all the issues in this directory are squelched, don't show status line
                has_displayed_fails = failed_count > 0 and not state.squelch_settings.get('FAILS', False)
                has_displayed_missing = missing_count > 0 and not state.squelch_settings.get('MISSING', False)
                has_displayed_extra = extra_count > 0 and not state.squelch_settings.get('EXTRA', False)
                
                # If directory has no displayed issues, don't show status line (unless show_all is True or auto-detected)
                # For auto-detected commands, always show the summary even for pure SUCCESS
                # Note: no verified_count requirement -- a directory whose ONLY
                # issues are all squelched must hide too (e.g. extras-only dir
                # with 0 verified at level -2), otherwise squelched levels
                # paradoxically show MORE than less-squelched ones.
                if not has_displayed_fails and not has_displayed_missing and not has_displayed_extra and not show_all and not state.is_auto_detected_command:
                    should_display = False
                # Special case: if directory only has EXTRA files and EXTRA_SUMMARY is squelched, hide status line
                elif (has_displayed_extra and not has_displayed_fails and not has_displayed_missing and 
                      failed_count == 0 and missing_count == 0 and state.squelch_settings.get('EXTRA_SUMMARY', False)):
                    should_display = False
        
        # Log with appropriate level based on severity
        if should_display:
            if exit_code <= 2:  # Perfect or almost perfect
                if state.dazzle_logger:
                    state.dazzle_logger.info(summary, level=0)
                else:
                    logger.info(summary)
            else:  # Has issues
                if state.dazzle_logger:
                    state.dazzle_logger.error(summary)
                else:
                    logger.error(summary)
        
        # Store exit code for main function to return
        # We'll add this to a global variable or pass it through the call stack
        # Only set individual directory exit code if we're not tracking grand totals
        # If we have grand totals, they will set the final exit code
        if not state.grand_totals:
            state.verification_exit_code = exit_code
        
        # Add results to grand totals if tracking
        if state.grand_totals:
            state.grand_totals.add_directory_result(results)
        
        # In quiet mode, add spacing after directories that produce output
        if state.dazzle_logger and state.dazzle_logger.quiet:
            # Check if this directory produced any output in quiet mode
            # Consider squelch settings when determining what constitutes "problems"
            showed_fails = failed_count > 0 and not (state.squelch_settings and state.squelch_settings.get('FAILS', False))
            showed_missing = missing_count > 0 and not (state.squelch_settings and state.squelch_settings.get('MISSING', False))
            showed_extra = extra_count > 0 and not (state.squelch_settings and state.squelch_settings.get('EXTRA', False))
            has_problems = showed_fails or showed_missing or showed_extra
            showed_summary = should_display and (exit_code > 2 or exit_code == 0 and not (state.squelch_settings and state.squelch_settings.get('SUCCESS', False)))
            
            if has_problems or showed_summary:
                # This directory produced output, add spacing after it
                print(file=sys.stderr)
        
        # Mark that we just processed a directory for spacing
        if state.dazzle_logger:
            state.dazzle_logger.last_was_directory = True
