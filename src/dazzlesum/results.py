"""GrandTotals, ProgressTracker, SummaryCollector, verification status calc.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 509-715, 1193-1306, 1309-1387, 4868-4921, 4924-4952. Only import wiring and shared-state references
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

from .constants import logger
from . import state


class GrandTotals:
    """Aggregate statistics across multiple directory verifications."""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset all counters for a new verification run."""
        # Directory categorization
        self.directories_processed = 0
        self.directories_success = 0      # 100% success
        self.directories_no_shasum = 0    # No .shasum file found
        self.directories_partial = 0     # Mixed results but no failures
        self.directories_failed = 0      # Has failures or missing files
        
        # File statistics
        self.files_verified = 0
        self.files_failed = 0
        self.files_missing = 0
        self.files_extra = 0
        
        # Performance tracking
        self.start_time = None
        self.end_time = None
    
    def start_timing(self):
        """Start timing the verification process."""
        import time
        self.start_time = time.time()
    
    def end_timing(self):
        """End timing the verification process."""
        import time
        self.end_time = time.time()
    
    def add_directory_result(self, results):
        """Add results from a single directory verification.
        
        Args:
            results: Dictionary with verification results from _print_verification_results
        """
        self.directories_processed += 1
        
        if 'error' in results:
            # Check if this is a "No .shasum file found" case
            if "No .shasum file found" in results['error']:
                self.directories_no_shasum += 1
            else:
                self.directories_failed += 1
        else:
            # Count files
            verified = len(results.get('verified', []))
            failed = len(results.get('failed', []))
            missing = len(results.get('missing', []))
            extra = len(results.get('extra', []))
            
            self.files_verified += verified
            self.files_failed += failed
            self.files_missing += missing
            self.files_extra += extra
            
            # Categorize directory based on results
            if failed == 0 and missing == 0:
                if extra == 0:
                    self.directories_success += 1
                else:
                    self.directories_partial += 1  # Has extra files but no failures
            else:
                self.directories_failed += 1
    
    def get_overall_success_percentage(self):
        """Calculate overall success percentage across all files."""
        total_expected = self.files_verified + self.files_failed + self.files_missing
        if total_expected == 0:
            return 100 if self.files_extra == 0 else 0
        
        return round((self.files_verified / total_expected) * 100)
    
    def get_overall_failure_percentage(self):
        """Calculate overall failure percentage across all files."""
        return 100 - self.get_overall_success_percentage()
    
    def get_processing_time(self):
        """Get total processing time in seconds."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0
    
    def get_throughput(self):
        """Get files per second throughput."""
        processing_time = self.get_processing_time()
        total_files = self.files_verified + self.files_failed + self.files_missing + self.files_extra
        
        if processing_time > 0 and total_files > 0:
            return round(total_files / processing_time)
        return 0
    
    def finalize_exit_code(self):
        """Compute the aggregate verification exit code and set the global.

        Kept separate from display_grand_totals() so silent mode (-6, exit
        codes only) still produces the correct exit code -- historically the
        code was set as a side effect of displaying, so skipping the display
        silently reported success regardless of failures.
        """
        status_text, exit_code, _, _ = calculate_verification_status(
            self.files_verified, self.files_failed, self.files_missing, self.files_extra
        )
        # For recursive operations, the grand totals exit code should override
        # individual directory codes: overall repository health, not the worst
        # individual directory.
        state.verification_exit_code = exit_code
        return status_text, exit_code

    def display_grand_totals(self):
        """Display the grand totals summary."""
        if not state.dazzle_logger:
            return
            
        # Check if we're in silent mode - no output at all
        if state.verbosity_config and state.verbosity_config.is_silent():
            return
        
        # Calculate overall statistics
        success_pct = self.get_overall_success_percentage()
        failure_pct = self.get_overall_failure_percentage()
        processing_time = self.get_processing_time()
        throughput = self.get_throughput()
        
        # Determine overall status (also sets the global exit code)
        status_text, exit_code = self.finalize_exit_code()

        # Display header
        state.dazzle_logger.info("", level=0)  # Blank line
        if state.color_formatter:
            header = state.color_formatter.grand_totals("=== GRAND TOTALS ===", bold=True)
        else:
            header = "=== GRAND TOTALS ==="
        state.dazzle_logger.info(header, level=0)
        
        # Directory summary with colored status words
        if state.color_formatter:
            processed_text = f"{state.color_formatter.bold_number(self.directories_processed)} processed"
        else:
            processed_text = f"{self.directories_processed} processed"
        
        dir_summary = f"Directories: {processed_text}"
        
        if self.directories_processed > 0:
            parts = []
            if self.directories_success > 0:
                if state.color_formatter:
                    parts.append(f"{state.color_formatter.bold_number(self.directories_success)} {state.color_formatter.success('success')}")
                else:
                    parts.append(f"{self.directories_success} success")
            if self.directories_no_shasum > 0:
                if state.color_formatter:
                    parts.append(f"{state.color_formatter.bold_number(self.directories_no_shasum)} {state.color_formatter.info_secondary('no-shasum')}")
                else:
                    parts.append(f"{self.directories_no_shasum} no-shasum")
            if self.directories_partial > 0:
                if state.color_formatter:
                    parts.append(f"{state.color_formatter.bold_number(self.directories_partial)} {state.color_formatter.extra('partial')}")
                else:
                    parts.append(f"{self.directories_partial} partial")
            if self.directories_failed > 0:
                if state.color_formatter:
                    parts.append(f"{state.color_formatter.bold_number(self.directories_failed)} {state.color_formatter.error('failed')}")
                else:
                    parts.append(f"{self.directories_failed} failed")
            
            if parts:
                dir_summary += f" ({', '.join(parts)})"
        
        state.dazzle_logger.info(dir_summary, level=0)
        
        # File summary with colored status
        total_files = self.files_verified + self.files_failed + self.files_missing + self.files_extra
        if total_files > 0:
            colored_status = format_status_with_colors(status_text, success_pct, failure_pct)
            
            if state.color_formatter:
                verified_text = f"{state.color_formatter.bold_number(self.files_verified)} {state.color_formatter.success('verified')}"
                failed_text = f"{state.color_formatter.bold_number(self.files_failed)} {state.color_formatter.error('failed')}"
                missing_text = f"{state.color_formatter.bold_number(self.files_missing)} {state.color_formatter.warning('missing')}"
                extra_text = f"{state.color_formatter.bold_number(self.files_extra)} {state.color_formatter.extra('extra')}"
            else:
                verified_text = f"{self.files_verified} verified"
                failed_text = f"{self.files_failed} failed"
                missing_text = f"{self.files_missing} missing"
                extra_text = f"{self.files_extra} extra"
            
            file_summary = f"Files: {verified_text}, {failed_text}, {missing_text}, {extra_text} ({colored_status})"
            state.dazzle_logger.info(file_summary, level=0)
        
        # Processing time and throughput
        if processing_time > 0:
            time_summary = f"Processing: {processing_time:.2f} seconds"
            if throughput > 0:
                time_summary += f" ({throughput} files/sec)"
            if state.color_formatter:
                colored_time_summary = state.color_formatter.grand_totals(time_summary)
            else:
                colored_time_summary = time_summary
            state.dazzle_logger.info(colored_time_summary, level=0)


class ProgressTracker:
    """Track progress with percentage completion and ETA."""

    def __init__(self, total_dirs=0, total_files=0, show_progress=True):
        self.total_dirs = total_dirs
        self.total_files = total_files
        self.processed_dirs = 0
        self.processed_files = 0
        self.processed_bytes = 0
        self.show_progress = show_progress
        self.start_time = time.time()
        self.last_update = 0
        self.update_interval = 0.5  # Update every 500ms

    def update_dirs(self, count=1):
        """Update directory progress."""
        self.processed_dirs += count
        self._maybe_display_progress()

    def update_files(self, count=1, file_size=0):
        """Update file progress."""
        self.processed_files += count
        self.processed_bytes += file_size
        self._maybe_display_progress()

    def _maybe_display_progress(self):
        """Display progress if enough time has passed."""
        if not self.show_progress:
            return

        now = time.time()
        if now - self.last_update >= self.update_interval:
            self.last_update = now
            self._display_progress()

    def _display_progress(self):
        """Display current progress."""
        if self.total_dirs == 0 and self.total_files == 0:
            return

        # Calculate overall progress
        dir_weight = 0.1  # Directories are 10% of the work
        file_weight = 0.9  # Files are 90% of the work

        if self.total_dirs > 0 and self.total_files > 0:
            dir_progress = (self.processed_dirs / self.total_dirs) * dir_weight
            file_progress = (self.processed_files / self.total_files) * file_weight
            overall_progress = dir_progress + file_progress
        elif self.total_dirs > 0:
            overall_progress = self.processed_dirs / self.total_dirs
        else:
            overall_progress = self.processed_files / self.total_files if self.total_files > 0 else 0

        percentage = min(100, overall_progress * 100)

        # Calculate ETA
        elapsed = time.time() - self.start_time
        if percentage > 0 and elapsed > 0:
            eta_seconds = (elapsed / (percentage / 100)) - elapsed
            eta_str = self._format_duration(eta_seconds) if eta_seconds > 0 else "calculating..."
        else:
            eta_str = "calculating..."

        # Create progress bar
        bar_width = 30
        filled = int(bar_width * (percentage / 100))
        bar = '#' * filled + '-' * (bar_width - filled)

        # Format data throughput
        data_str = self._format_bytes(self.processed_bytes)
        if elapsed > 0 and self.processed_bytes > 0:
            mbps = (self.processed_bytes / (1024 * 1024)) / elapsed
            throughput_str = f"{mbps:.1f} MB/s"
        else:
            throughput_str = "-- MB/s"

        # Print progress (overwrite previous line)
        print(f"\r[{bar}] {percentage:5.1f}% | "
              f"Dirs: {self.processed_dirs}/{self.total_dirs} | "
              f"Files: {self.processed_files}/{self.total_files} | "
              f"{data_str} ({throughput_str}) | "
              f"ETA: {eta_str}", end='', flush=True)

    @staticmethod
    def _format_bytes(num_bytes):
        """Format bytes in human-readable format."""
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"

    def _format_duration(self, seconds):
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.0f}m {seconds % 60:.0f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def finish(self):
        """Complete the progress display."""
        if self.show_progress and (self.total_dirs > 0 or self.total_files > 0):
            # Force final 100% display
            self.processed_dirs = self.total_dirs
            self.processed_files = self.total_files
            self._display_progress()
            
            print()  # New line after progress bar
            elapsed = time.time() - self.start_time
            logger.info(f"Completed {self.processed_dirs} directories, {self.processed_files} files in {self._format_duration(elapsed)}")


class SummaryCollector:
    """Collect summary statistics during processing."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all counters."""
        self.dirs_processed = 0
        self.files_processed = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.total_bytes = 0
        self.verification_results = {
            'verified': 0,
            'failed': 0,
            'missing': 0,
            'extra': 0
        }

    def add_directory(self, file_count, skip_count, fail_count, total_bytes):
        """Add statistics from a directory."""
        self.dirs_processed += 1
        self.files_processed += file_count
        self.files_skipped += skip_count
        self.files_failed += fail_count
        self.total_bytes += total_bytes

    def add_verification(self, results):
        """Add verification results."""
        if 'error' not in results:
            self.verification_results['verified'] += len(results.get('verified', []))
            self.verification_results['failed'] += len(results.get('failed', []))
            self.verification_results['missing'] += len(results.get('missing', []))
            self.verification_results['extra'] += len(results.get('extra', []))

    def get_summary(self):
        """Get summary statistics."""
        return {
            'directories': self.dirs_processed,
            'files_processed': self.files_processed,
            'files_skipped': self.files_skipped,
            'files_failed': self.files_failed,
            'total_bytes': self.total_bytes,
            'verification': self.verification_results
        }

    def print_summary(self):
        """Print a summary of operations."""
        summary = self.get_summary()

        print("\n" + "="*60)
        print("OPERATION SUMMARY")
        print("="*60)
        print(f"Directories processed: {summary['directories']}")
        print(f"Files processed:       {summary['files_processed']}")
        if summary['files_skipped'] > 0:
            print(f"Files skipped:         {summary['files_skipped']}")
        if summary['files_failed'] > 0:
            print(f"Files failed:          {summary['files_failed']}")
        print(f"Total data processed:  {self._format_bytes(summary['total_bytes'])}")

        # Verification summary
        if any(summary['verification'].values()):
            print(f"\nVerification results:")
            print(f"  Verified:  {summary['verification']['verified']}")
            print(f"  Failed:    {summary['verification']['failed']}")
            print(f"  Missing:   {summary['verification']['missing']}")
            print(f"  Extra:     {summary['verification']['extra']}")

        print("="*60)

    def _format_bytes(self, bytes_count):
        """Format bytes in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_count < 1024:
                return f"{bytes_count:.1f} {unit}"
            bytes_count /= 1024
        return f"{bytes_count:.1f} PB"


def calculate_verification_status(verified_count, failed_count, missing_count, extra_count):
    """Calculate status label and exit code based on verification results.
    
    Args:
        verified_count: Number of files that verified successfully
        failed_count: Number of files that failed checksum verification
        missing_count: Number of missing files
        extra_count: Number of extra files found
        
    Returns:
        tuple: (status_label, exit_code, success_percentage, failure_percentage)
    """
    total_expected = verified_count + failed_count + missing_count
    
    # Handle edge case where no files were expected
    if total_expected == 0:
        if extra_count > 0:
            return "0%/100% UNEXPECTED FILES", 4, 0, 100
        else:
            return "100%/0% SUCCESS", 0, 100, 0
    
    # Calculate success/failure percentages
    # Consider missing and failed files as failures
    failure_count = failed_count + missing_count
    success_percentage = round((verified_count / total_expected) * 100)
    failure_percentage = round((failure_count / total_expected) * 100)
    
    # Determine status label and exit code based on success rate
    if success_percentage == 100 and extra_count == 0:
        status_label = "SUCCESS"
        exit_code = 0
    elif success_percentage == 100 and extra_count > 0:
        status_label = "SUCCESS"  # All expected files verified, but has extras
        exit_code = 2  # Not perfect due to extra files
    elif success_percentage >= 99:
        status_label = "ALMOST PERFECT"
        exit_code = 2
    elif success_percentage >= 95:
        status_label = "SOME ISSUES"
        exit_code = 3
    elif success_percentage >= 80:
        status_label = "FAILS"
        exit_code = 4
    elif success_percentage >= 50:
        status_label = "MANY FAILS"
        exit_code = 5
    elif success_percentage > 0:
        status_label = "MOSTLY FAILS"
        exit_code = 6
    else:
        status_label = "FAILURE"
        exit_code = 7
    
    return f"{success_percentage}%/{failure_percentage}% {status_label}", exit_code, success_percentage, failure_percentage


def format_status_with_colors(status_text, success_percentage, failure_percentage):
    """Apply colors to status text with green success % and red failure %.
    
    Args:
        status_text: Full status text like "99%/1% ALMOST PERFECT"
        success_percentage: Success percentage (0-100)
        failure_percentage: Failure percentage (0-100)
        
    Returns:
        Colored status text if colors enabled, otherwise plain text
    """
    if not state.color_formatter or not state.color_formatter.use_colors:
        return status_text
    
    # Split the status text to colorize percentages
    parts = status_text.split('%')
    if len(parts) >= 3:
        # Format: "99%/1% STATUS"
        success_part = f"{parts[0]}%"
        failure_part = f"{parts[1].split('/')[1]}%"
        status_label = parts[2]
        
        colored_success = state.color_formatter.success(success_part)
        colored_failure = state.color_formatter.error(failure_part)
        
        return f"{colored_success}/{colored_failure}{status_label}"
    
    # Fallback to original text if parsing fails
    return status_text
