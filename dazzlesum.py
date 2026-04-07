#!/usr/bin/env python3
"""
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
import subprocess
import shutil
from collections import deque
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Union, Any

# Version information
# Base semantic version (manually maintained for git hooks)
MAJOR, MINOR, PATCH = 1, 3, 6

# Static version string (updated automatically by git hooks)
__version__ = "1.3.6_64-20250630-e132532f"

def get_package_version():
    """Return PEP 440 compliant version for packaging (uses MAJOR.MINOR.PATCH)."""
    return f"{MAJOR}.{MINOR}.{PATCH}"

__author__ = "Dustin Darcy"

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
MONOLITHIC_DEFAULT_NAME = 'checksums'

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class DazzleLogger:
    """Enhanced logger with DOS-compatible verbosity levels and visual separation."""

    def __init__(self, verbosity=0, quiet=False, summary_mode=False, show_log_types=None):
        self.verbosity = verbosity
        self.quiet = quiet
        self.summary_mode = summary_mode
        self.last_was_directory = False
        self.verbosity_config = None  # Will be set by set_verbosity_config
        
        # Determine if we should show log type prefixes
        # Priority: explicit parameter > environment variable > verbosity-based default
        if show_log_types is not None:
            self.show_log_types = show_log_types
        elif os.environ.get('DAZZLESUM_SHOW_LOG_TYPES', '').lower() in ('1', 'true', 'yes'):
            self.show_log_types = True
        else:
            # Clean output by default (verbosity 0), show log types for higher verbosity
            self.show_log_types = verbosity >= 1

    def set_verbosity_config(self, verbosity_config):
        """Update logger with new verbosity configuration."""
        self.verbosity_config = verbosity_config
        # Update show_log_types based on verbosity config
        if self.verbosity_config:
            self.show_log_types = self.verbosity_config.should_show_log_types()

    def _should_log(self, level):
        """Check if we should log at this verbosity level."""
        if self.quiet:
            return level <= 0  # Only errors/warnings in quiet mode
        if self.summary_mode:
            return level <= 1  # Reduced output in summary mode
        return self.verbosity >= level

    def _add_spacing_if_needed(self):
        """Add blank line for directory separation."""
        # Don't add spacing in summary mode as it interferes with progress bar
        if self.summary_mode:
            return
        if self.last_was_directory and self._should_log(1):
            print()

    def error(self, msg):
        """Always show errors."""
        if color_formatter:
            # Only colorize if message doesn't already have color codes
            if '\033[' not in msg:
                msg = color_formatter.error(msg)
        logger.error(msg)

    def warning(self, msg):
        """Always show warnings."""
        if color_formatter:
            # Only colorize if message doesn't already have color codes
            if '\033[' not in msg:
                msg = color_formatter.warning(msg)
        logger.warning(msg)

    def info(self, msg, level=1):
        """Info messages with verbosity level."""
        # Check for silent mode first
        if self.verbosity_config and self.verbosity_config.is_silent():
            return  # No output at all in silent mode
            
        if self._should_log(level):
            if color_formatter and level == 0:
                # Only colorize level 0 info messages (important info)
                if '\033[' not in msg:
                    msg = color_formatter.info(msg)
            
            # In quiet mode, use print for level 0 messages since logger.info() is suppressed
            if self.quiet and level == 0:
                print(msg, file=sys.stderr)
            else:
                logger.info(msg)

    def debug(self, msg):
        """Debug messages (verbosity level 3)."""
        if self._should_log(3):
            logger.debug(msg)

    def directory_start(self, path):
        """Log directory processing start with spacing."""
        if self._should_log(1):
            self._add_spacing_if_needed()
            logger.info(f"Processing directory: {path}")

    def directory_complete(self, path, processed, skipped, failed, elapsed_time):
        """Log directory completion with consistent formatting."""
        if self._should_log(1):
            if failed > 0:
                logger.info(f"Directory {path}: {processed} processed, "
                           f"{skipped} skipped, {failed} failed in {elapsed_time:.2f}s")
            else:
                logger.info(f"Directory {path}: {processed} processed, "
                           f"{skipped} skipped in {elapsed_time:.2f}s")
            self.last_was_directory = True  # Mark that we completed a directory

    def file_processed(self, file_path, level=2):
        """Log individual file processing (verbosity level 2+)."""
        if self._should_log(level):
            logger.info(f"  Processed: {file_path.name}")

    def file_skipped(self, file_path, reason="", level=2):
        """Log skipped files (verbosity level 2+)."""
        if self._should_log(level):
            if reason:
                logger.info(f"  Skipped: {file_path.name} ({reason})")
            else:
                logger.info(f"  Skipped: {file_path.name}")

    def verification_status(self, filename, status, details="", level=2):
        """Log verification results with DOS-compatible indicators."""
        if not self._should_log(level):
            return

        status_indicators = {
            'verified': 'OK',
            'failed': 'FAIL',
            'missing': 'MISS',
            'extra': 'EXTRA'
        }

        indicator = status_indicators.get(status, 'INFO')
        if details:
            logger.info(f"  {indicator} {filename} - {details}")
        else:
            logger.info(f"  {indicator} {filename}")

    def tool_selection(self, tool_name, algorithm):
        """Log native tool selection (debug level)."""
        if tool_name:
            self.debug(f"Using native tool: {tool_name} for {algorithm}")
        else:
            self.debug(f"Using Python implementation for {algorithm}")


# Global logger instance - will be set up in main()
dazzle_logger = None


class ColorFormatter:
    """Cross-platform color formatter for terminal output."""
    
    def __init__(self, use_colors=None):
        """Initialize color formatter.
        
        Args:
            use_colors: If None, auto-detect terminal support. Otherwise bool.
        """
        self.colorama_available = False
        self.use_colors = False
        
        # Try to import and initialize colorama for Windows support
        try:
            import colorama
            colorama.init()  # Enable ANSI escape sequences on Windows
            self.colorama_available = True
        except ImportError:
            pass
        
        if use_colors is None:
            self.use_colors = self._supports_color()
        else:
            self.use_colors = use_colors
    
    def _supports_color(self):
        """Check if terminal supports ANSI colors."""
        import sys
        
        # Check environment variable to disable colors
        if os.environ.get('NO_COLOR') or os.environ.get('DAZZLESUM_NO_COLOR'):
            return False
        
        # Check if stdout is a terminal
        if not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty():
            return False
        
        # If we have colorama, Windows should work
        if is_windows() and self.colorama_available:
            return True
        
        # Check environment variables for Unix-like systems
        term = os.environ.get('TERM', '').lower()
        colorterm = os.environ.get('COLORTERM', '').lower()
        
        # Explicit color support indicators
        if os.environ.get('FORCE_COLOR') or os.environ.get('DAZZLESUM_FORCE_COLOR'):
            return True
        
        # Most modern terminals support color
        if any(x in term for x in ['color', 'xterm', 'screen', 'tmux']):
            return True
        if colorterm:
            return True
        
        # Windows 10+ with ANSI support (without colorama)
        if is_windows():
            try:
                # Try to enable ANSI escape sequences
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
                mode = ctypes.c_ulong()
                kernel32.GetConsoleMode(handle, ctypes.byref(mode))
                # Enable VIRTUAL_TERMINAL_PROCESSING
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
            except Exception:
                # Fallback: for older Windows or restricted environments
                return False
        
        return False
    
    # ANSI color codes
    COLORS = {
        'red': '\033[91m',
        'green': '\033[92m', 
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'light_blue': '\033[96m',
        'light_green': '\033[92m',
        'light_red': '\033[91m',
        'light_yellow': '\033[93m',
        'white': '\033[97m',
        'light_gray': '\033[90m',
        'purple': '\033[38;2;186;128;187m',  # Custom purple #ba80bb (brighter)
        'bold': '\033[1m',
        'reset': '\033[0m'
    }
    
    def colorize(self, text, color=None, bold=False):
        """Apply color and formatting to text.
        
        Args:
            text: Text to colorize
            color: Color name from COLORS dict
            bold: Whether to make text bold
            
        Returns:
            Formatted text with ANSI codes or plain text if colors disabled
        """
        if not self.use_colors:
            return text
        
        codes = []
        if bold:
            codes.append(self.COLORS['bold'])
        if color and color in self.COLORS:
            codes.append(self.COLORS[color])
        
        if codes:
            return ''.join(codes) + text + self.COLORS['reset']
        return text
    
    def success(self, text, bold=False):
        """Format success text (green)."""
        return self.colorize(text, 'green', bold)
    
    def error(self, text, bold=False):
        """Format error text (red)."""
        return self.colorize(text, 'light_red', bold)
    
    def warning(self, text, bold=False):
        """Format warning text (yellow)."""
        return self.colorize(text, 'light_yellow', bold)
    
    def info(self, text, bold=False):
        """Format info text (light green)."""
        return self.colorize(text, 'light_green', bold)
    
    def extra(self, text, bold=False):
        """Format extra files text (light blue)."""
        return self.colorize(text, 'light_blue', bold)
    
    def bold_number(self, number):
        """Format a number in bold."""
        return self.colorize(str(number), bold=True)
    
    def filename(self, text):
        """Format filename text (bold white)."""
        return self.colorize(text, 'white', bold=True)
    
    def hash_value(self, text):
        """Format hash value text (light gray)."""
        return self.colorize(text, 'light_gray')
    
    def info_secondary(self, text):
        """Format secondary info text (light blue/cyan) for informational messages."""
        return self.colorize(text, 'light_blue')
    
    def grand_totals(self, text, bold=False):
        """Format grand totals text (purple) to distinguish from success states."""
        return self.colorize(text, 'purple', bold)


# Global color formatter instance - will be set up in main()
color_formatter = None

# Global exit code for verification operations - will be set by verification results
verification_exit_code = 0

# Global flag to track if this is an auto-detected command
is_auto_detected_command = False

# Global verbosity configuration instance
verbosity_config = None


class VerbosityConfig:
    """Handles verbosity level configuration and environment variables."""
    
    def __init__(self, level=0, quiet_count=0, verbose_count=0):
        self.level = level
        self.quiet_count = quiet_count
        self.verbose_count = verbose_count
    
    @classmethod
    def from_environment(cls):
        """Create config from environment variables."""
        env_verbosity = os.environ.get('DAZZLESUM_VERBOSITY')
        if env_verbosity:
            try:
                level = int(env_verbosity)
                # Clamp to reasonable range
                level = max(-5, min(4, level))
                return cls(level=level)
            except ValueError:
                # Invalid value, use default
                pass
        return cls()
    
    @classmethod
    def from_args(cls, args):
        """Create config from command line arguments."""
        quiet_count = getattr(args, 'quiet', 0)
        verbose_count = getattr(args, 'verbose', 0)
        
        # Handle explicit --verbosity flag
        if hasattr(args, 'verbosity') and args.verbosity is not None:
            level = max(-5, min(4, args.verbosity))
            return cls(level=level, quiet_count=quiet_count, verbose_count=verbose_count)
        
        # Calculate level from -q/-v counts: base + verbose - quiet
        level = verbose_count - quiet_count
        level = max(-5, min(4, level))  # Clamp to valid range
        
        return cls(level=level, quiet_count=quiet_count, verbose_count=verbose_count)
    
    def get_effective_level(self):
        """Calculate final verbosity level."""
        return self.level
    
    def get_squelch_settings(self):
        """Map verbosity level to squelch configuration."""
        # Note: True means squelched (hidden), False means shown
        VERBOSITY_SQUELCH_MAP = {
            -6: {'show_output': False},  # Special case: no output at all, only exit codes
            -5: {'INFO': True,  'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': True,  'SUMMARY': True},   # Only grand total summary  # noqa: E241
            -4: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': True,  'SUMMARY': False, 'FORCE_SUMMARY': True},  # info/status line + grand total  # noqa: E241
            -3: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': False, 'SUMMARY': False},  # FAIL + info/status + grand total  # noqa: E241
            -2: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # MISSING + FAIL + info/status + grand total  # noqa: E241
            -1: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False, 'EXTRA_SUMMARY': True},  # EXTRA + MISSING + FAIL + info/status + grand total  # noqa: E241
             0: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': False, 'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # Current default  # noqa: E241,E131
            +1: {'INFO': False, 'SUCCESS': False, 'NO_SHASUM': False, 'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # Show everything
            # +2 and above: controlled by logger verbosity, not squelch
        }
        
        return VERBOSITY_SQUELCH_MAP.get(self.level, VERBOSITY_SQUELCH_MAP[0])
    
    def should_show_log_types(self):
        """Determine if log type prefixes should be shown."""
        # Check explicit environment variable first
        env_show_types = os.environ.get('DAZZLESUM_SHOW_LOG_TYPES', '').lower()
        if env_show_types in ('1', 'true', 'yes'):
            return True
        
        # For debug levels (+2 and above), show log types by default
        return self.level >= 2
    
    def is_silent(self):
        """Check if we're in silent mode (-6)."""
        return self.level <= -6


def initialize_squelch_from_verbosity(verbosity_level):
    """Set global squelch_settings based on verbosity level."""
    global squelch_settings  # noqa: F824
    
    if verbosity_config:
        squelch_settings = verbosity_config.get_squelch_settings()
    else:
        # Fallback if verbosity_config not available
        # Note: True means squelched (hidden), False means shown
        VERBOSITY_SQUELCH_MAP = {
            -6: {'show_output': False},
            -5: {'INFO': True,  'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': True,  'SUMMARY': True},  # noqa: E241
            -4: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': True,  'SUMMARY': False, 'FORCE_SUMMARY': True},  # noqa: E241
            -3: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': False, 'SUMMARY': False},  # noqa: E241
            -2: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # noqa: E241
            -1: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False, 'EXTRA_SUMMARY': True},  # noqa: E241
             0: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': False, 'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # noqa: E241,E131
            +1: {'INFO': False, 'SUCCESS': False, 'NO_SHASUM': False, 'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},
        }
        squelch_settings = VERBOSITY_SQUELCH_MAP.get(verbosity_level, VERBOSITY_SQUELCH_MAP[0])


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
    
    def display_grand_totals(self):
        """Display the grand totals summary."""
        global verbosity_config  # noqa: F824
        if not dazzle_logger:
            return
            
        # Check if we're in silent mode - no output at all
        if verbosity_config and verbosity_config.is_silent():
            return
        
        # Calculate overall statistics
        success_pct = self.get_overall_success_percentage()
        failure_pct = self.get_overall_failure_percentage()
        processing_time = self.get_processing_time()
        throughput = self.get_throughput()
        
        # Determine overall status using same logic as individual directories
        status_text, exit_code, _, _ = calculate_verification_status(
            self.files_verified, self.files_failed, self.files_missing, self.files_extra
        )
        
        # Update global exit code
        global verification_exit_code
        # For recursive operations, the grand totals exit code should override individual directory codes
        # This ensures the exit code reflects overall repository health, not worst individual directory
        verification_exit_code = exit_code
        
        # Display header
        dazzle_logger.info("", level=0)  # Blank line
        if color_formatter:
            header = color_formatter.grand_totals("=== GRAND TOTALS ===", bold=True)
        else:
            header = "=== GRAND TOTALS ==="
        dazzle_logger.info(header, level=0)
        
        # Directory summary with colored status words
        if color_formatter:
            processed_text = f"{color_formatter.bold_number(self.directories_processed)} processed"
        else:
            processed_text = f"{self.directories_processed} processed"
        
        dir_summary = f"Directories: {processed_text}"
        
        if self.directories_processed > 0:
            parts = []
            if self.directories_success > 0:
                if color_formatter:
                    parts.append(f"{color_formatter.bold_number(self.directories_success)} {color_formatter.success('success')}")
                else:
                    parts.append(f"{self.directories_success} success")
            if self.directories_no_shasum > 0:
                if color_formatter:
                    parts.append(f"{color_formatter.bold_number(self.directories_no_shasum)} {color_formatter.info_secondary('no-shasum')}")
                else:
                    parts.append(f"{self.directories_no_shasum} no-shasum")
            if self.directories_partial > 0:
                if color_formatter:
                    parts.append(f"{color_formatter.bold_number(self.directories_partial)} {color_formatter.extra('partial')}")
                else:
                    parts.append(f"{self.directories_partial} partial")
            if self.directories_failed > 0:
                if color_formatter:
                    parts.append(f"{color_formatter.bold_number(self.directories_failed)} {color_formatter.error('failed')}")
                else:
                    parts.append(f"{self.directories_failed} failed")
            
            if parts:
                dir_summary += f" ({', '.join(parts)})"
        
        dazzle_logger.info(dir_summary, level=0)
        
        # File summary with colored status
        total_files = self.files_verified + self.files_failed + self.files_missing + self.files_extra
        if total_files > 0:
            colored_status = format_status_with_colors(status_text, success_pct, failure_pct)
            
            if color_formatter:
                verified_text = f"{color_formatter.bold_number(self.files_verified)} {color_formatter.success('verified')}"
                failed_text = f"{color_formatter.bold_number(self.files_failed)} {color_formatter.error('failed')}"
                missing_text = f"{color_formatter.bold_number(self.files_missing)} {color_formatter.warning('missing')}"
                extra_text = f"{color_formatter.bold_number(self.files_extra)} {color_formatter.extra('extra')}"
            else:
                verified_text = f"{self.files_verified} verified"
                failed_text = f"{self.files_failed} failed"
                missing_text = f"{self.files_missing} missing"
                extra_text = f"{self.files_extra} extra"
            
            file_summary = f"Files: {verified_text}, {failed_text}, {missing_text}, {extra_text} ({colored_status})"
            dazzle_logger.info(file_summary, level=0)
        
        # Processing time and throughput
        if processing_time > 0:
            time_summary = f"Processing: {processing_time:.2f} seconds"
            if throughput > 0:
                time_summary += f" ({throughput} files/sec)"
            if color_formatter:
                colored_time_summary = color_formatter.grand_totals(time_summary)
            else:
                colored_time_summary = time_summary
            dazzle_logger.info(colored_time_summary, level=0)


# Global grand totals instance for recursive operations
grand_totals = None

# Global squelch settings for output filtering (initialized by verbosity system)
squelch_settings = None


class ShasumManager:
    """Manages .shasum files with backup, remove, restore, and list operations."""

    def __init__(self, root_dir: Path, backup_dir: Optional[Path] = None, dry_run: bool = False):
        self.root_dir = Path(root_dir)
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self.dry_run = dry_run
        self.logger = dazzle_logger if dazzle_logger else logger

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


def _should_include_file_simple(file_path: Path, include_patterns, exclude_patterns) -> bool:
    """Simplified version of file inclusion check for counting."""
    filename = file_path.name

    # Always exclude our own files
    if filename in [SHASUM_FILENAME, STATE_FILENAME]:
        return False

    # Apply exclude patterns
    for pattern in exclude_patterns:
        if file_path.match(pattern):
            return False

    # Apply include patterns (if any)
    if include_patterns:
        for pattern in include_patterns:
            if file_path.match(pattern):
                return True
        return False

    return True


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
            if is_windows() and path.is_dir():
                return self._is_junction(path), 'junction'

        except Exception as e:
            logger.debug(f"Error checking symlink status for {path}: {e}")

        return False, None

    def _is_junction(self, path: Path) -> bool:
        """Detect Windows junctions using various methods."""
        try:
            # Method 1: Check file attributes
            if hasattr(os, 'lstat'):
                stat_info = os.lstat(str(path))
                if hasattr(stat, 'S_ISLNK') and stat.S_ISLNK(stat_info.st_mode):
                    return True

            # Method 2: Try to resolve and check if different
            try:
                resolved = path.resolve()
                if str(resolved) != str(path):
                    return True
            except Exception:
                pass

            # Method 3: Use dir command as fallback
            try:
                result = subprocess.run(
                    ['dir', '/AL', str(path.parent)],
                    capture_output=True, text=True, encoding='utf-8', errors='replace', shell=True
                )
                if result.returncode == 0:
                    return '<JUNCTION>' in result.stdout and path.name in result.stdout
            except Exception:
                pass

        except Exception as e:
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

    def __init__(self, follow_symlinks=False):
        self.processing_queue = deque()
        self.symlink_handler = SymlinkHandler()
        self.follow_symlinks = follow_symlinks
        self.processed_count = 0

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

            # Safety check for loops
            if self.symlink_handler.is_visited(current_dir):
                logger.warning(f"Skipping {current_dir} - already visited (loop detected)")
                continue

            # Mark as visited
            self.symlink_handler.mark_visited(current_dir)

            # Check if we should follow this directory (symlink safety)
            if not self.symlink_handler.should_follow_link(current_dir, self.follow_symlinks):
                logger.debug(f"Skipping {current_dir} - symlink/junction not followed")
                continue

            # Process current directory
            try:
                if dazzle_logger:
                    dazzle_logger.directory_start(current_dir)
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
                              if item.is_dir() and not self.symlink_handler.is_visited(item)]
                    for subdir in subdirs:
                        self.processing_queue.append(subdir)
                        logger.debug(f"Added to queue: {subdir}")
                except Exception as e:
                    logger.warning(f"Error listing subdirectories of {current_dir}: {e}")


class DazzleHashCalculator:
    """Main hash calculator with normalization and native tool integration."""

    def __init__(self, algorithm=DEFAULT_ALGORITHM, line_ending_strategy='auto',
                 chunk_size=DEFAULT_CHUNK_SIZE):
        self.algorithm = algorithm.lower()
        self.chunk_size = chunk_size
        self.line_handler = LineEndingHandler(line_ending_strategy)
        self.native_tool = self._detect_native_tool()

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
                if dazzle_logger:
                    dazzle_logger.tool_selection(tool, self.algorithm)
                else:
                    logger.debug(f"Using native tool: {tool}")
                return tool

        if dazzle_logger:
            dazzle_logger.tool_selection(None, self.algorithm)
        else:
            logger.debug("No native tools available, using Python implementation")
        return None

    def _tool_available(self, tool: str) -> bool:
        """Check if a native tool is available."""
        try:
            # Special handling for fsum
            if tool == 'fsum':
                result = subprocess.run([tool], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
                # fsum returns usage info when called without arguments
                return 'SlavaSoft' in result.stdout or 'fsum' in result.stdout.lower()

            # For other tools, try --help or --version
            for flag in ['--help', '--version', '-h']:
                try:
                    result = subprocess.run([tool, flag], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
                    if result.returncode == 0 or 'usage' in result.stderr.lower():
                        return True
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
        # Normalize path using unctools if available
        if HAVE_UNCTOOLS:
            file_path = normalize_path(file_path)

        # Try native tool first
        if self.native_tool:
            try:
                return self._calculate_with_native_tool(file_path)
            except Exception as e:
                # Only log warning in debug mode to reduce noise
                logger.debug(f"Native tool {self.native_tool} failed for {file_path}, using Python: {e}")

        # Fallback to Python implementation
        return self._calculate_with_python(file_path)

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

        # Use safe_open if available
        try:
            if HAVE_UNCTOOLS:
                with safe_open(file_path, 'rb') as f:
                    return self._hash_file_content(f, hasher)
            else:
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
        """
        source_dir = Path(source_dir).resolve()
        
        # Calculate relative path from source root
        try:
            rel_path = source_dir.relative_to(self.source_root)
        except ValueError:
            # source_dir is not under source_root
            raise ValueError(f"Source directory {source_dir} is not under source root {self.source_root}")
        
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
            if dazzle_logger:
                dazzle_logger.info(f"Found {len(files)} files in {directory}", level=1)
            else:
                # Fallback for direct calls
                if self.log_file:
                    logger.debug(f"Found {len(files)} files in {directory}")
                elif not self.summary_mode:
                    logger.info(f"Found {len(files)} files in {directory}")

            for file_path in files:
                if not self.should_include_file(file_path):
                    files_skipped += 1
                    if dazzle_logger:
                        dazzle_logger.file_skipped(file_path)
                    elif self.log_file:
                        logger.debug(f"Skipped: {file_path}")
                    continue

                try:
                    if dazzle_logger:
                        dazzle_logger.file_processed(file_path)
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
        if dazzle_logger:
            dazzle_logger.directory_complete(directory, files_processed, files_skipped, files_failed, elapsed_time)
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
            with open(shasum_path, 'w', encoding='utf-8') as f:
                # Write header comment
                f.write(f"# Dazzle checksum tool v{__version__} - {self.algorithm} - {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")

                # Write checksums in standard format
                for filename, info in sorted(checksums.items()):
                    f.write(f"{info['hash']}  {filename}\n")

                # Write end marker
                f.write("# End of checksums\n")

            if self.log_file:
                logger.info(f"Wrote {len(checksums)} checksums to {shasum_path}")
            elif not self.summary_mode:
                logger.info(f"Wrote {len(checksums)} checksums to {shasum_path}")

        except Exception as e:
            if self.log_file:
                logger.error(f"Error writing .shasum file to {directory}: {e}")
            elif not self.summary_mode:
                logger.error(f"Error writing .shasum file to {directory}: {e}")

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
        stored_checksums = {}
        try:
            with open(shasum_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split('  ', 1)
                        if len(parts) == 2:
                            hash_value, filename = parts
                            stored_checksums[filename] = hash_value.lower()
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
            if dazzle_logger and not dazzle_logger.quiet:
                dazzle_logger.info(f"Clone verification: Checking {base_path} against checksums from {file_root}", level=1)
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
        global grand_totals
        
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
            if dazzle_logger:
                dazzle_logger.info(f"Using shadow directory: {self.shadow_dir}", level=1)
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
                if dazzle_logger:
                    dazzle_logger.info(f"Using shadow directory for monolithic file: {output_path}", level=1)
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

        walker = FIFODirectoryWalker(self.follow_symlinks)

        def process_single_directory(directory: Path):
            # Skip directory if in resume mode and already processed
            if self._should_skip_directory(directory):
                if dazzle_logger:
                    dazzle_logger.info(f"Resume mode: Skipping already processed directory: {directory}", level=1)
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
            grand_totals = GrandTotals()
            grand_totals.start_timing()

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
        if verify_only and recursive and grand_totals:
            grand_totals.end_timing()
            # Check for silent mode (-6) - no output at all
            if not (verbosity_config and verbosity_config.is_silent()):
                grand_totals.display_grand_totals()

        # Print summary if in summary mode
        if self.summary_mode:
            self.summary_collector.print_summary()

    def _print_verification_results(self, path: Path, results: Dict[str, Any], show_all=False):  # noqa: C901
        """Print verification results for a directory or monolithic file."""
        global squelch_settings, verbosity_config  # noqa: F824
        
        # Check for silent mode first - no output at all
        if verbosity_config and verbosity_config.is_silent():
            # Still add to grand totals if tracking, but no output
            if grand_totals:
                grand_totals.add_directory_result(results)
            return
        
        # Check for ultra-quiet modes - only grand totals and maybe summary
        if verbosity_config and verbosity_config.get_effective_level() <= -5:
            # Still add to grand totals but skip all directory output
            if grand_totals:
                grand_totals.add_directory_result(results)
            return
        
        if 'error' in results:
            # Check if this is a "No .shasum file found" informational message
            error_msg = results['error']
            if "No .shasum file found" in error_msg:
                # Check squelch settings for NO_SHASUM messages
                if squelch_settings and squelch_settings.get('NO_SHASUM', False):
                    # Skip displaying this message due to squelch
                    pass
                else:
                    # Use info_secondary color for missing .shasum files (not a failure, just informational)
                    if color_formatter:
                        colored_msg = color_formatter.info_secondary(f"{path}: {error_msg}")
                    else:
                        colored_msg = f"{path}: {error_msg}"
                    
                    if dazzle_logger:
                        dazzle_logger.info(colored_msg, level=0)
                    else:
                        logger.info(colored_msg)
            else:
                # Regular error - use error formatting
                if dazzle_logger:
                    dazzle_logger.error(f"{path}: {error_msg}")
                else:
                    logger.error(f"{path}: {error_msg}")
            
            # Add error results to grand totals if tracking
            if grand_totals:
                grand_totals.add_directory_result(results)
            return

        verified_count = len(results['verified'])
        failed_count = len(results['failed'])
        missing_count = len(results['missing'])
        extra_count = len(results['extra'])

        # Show individual file results if requested or verbose
        if show_all or (dazzle_logger and dazzle_logger.verbosity >= 2):
            # Show all verification results
            for filename in results['verified']:
                if color_formatter:
                    logger.info(f" {color_formatter.success('OK')} {color_formatter.filename(filename)}")
                else:
                    logger.info(f" OK {filename}")

        # Show individual failure details - check squelch settings
        if failed_count > 0 and not (squelch_settings and squelch_settings.get('FAILS', False)):
            for item in results['failed']:
                if isinstance(item, dict):
                    if 'error' in item:
                        if color_formatter:
                            error_text = f" {color_formatter.error('ERROR')} {color_formatter.filename(item['filename'])}: {item['error']}"
                        else:
                            error_text = f" ERROR {item['filename']}: {item['error']}"
                        
                        if dazzle_logger:
                            dazzle_logger.error(error_text)
                        else:
                            logger.error(error_text)
                    else:
                        # Always show hash mismatches with new format: expected HASH... got HASH... | filename
                        if color_formatter:
                            expected_hash = color_formatter.hash_value(f"expected {item['expected'][:16]}...")
                            got_hash = color_formatter.hash_value(f"got {item['actual'][:16]}...")
                            filename_part = color_formatter.filename(item['filename'])
                            fail_text = f" {color_formatter.error('FAIL')} {expected_hash} {got_hash} | {filename_part}"
                        else:
                            fail_text = f" FAIL expected {item['expected'][:16]}... got {item['actual'][:16]}... | {item['filename']}"
                        
                        if dazzle_logger:
                            logger.error(fail_text)
                        else:
                            logger.error(fail_text)

        # Show individual missing files - check squelch settings
        if missing_count > 0 and not (squelch_settings and squelch_settings.get('MISSING', False)):
            for filename in results['missing']:
                # Show missing files (problems)
                if color_formatter:
                    miss_text = f" {color_formatter.warning('MISS')} {color_formatter.filename(filename)}"
                else:
                    miss_text = f" MISS {filename}"
                logger.warning(miss_text)

        # Show individual extra files - check squelch settings
        if extra_count > 0 and not (squelch_settings and squelch_settings.get('EXTRA', False)):
            for filename in results['extra']:
                # Show extra files
                # In quiet mode, show directory context for EXTRA files
                if dazzle_logger and dazzle_logger.quiet:
                    if color_formatter:
                        extra_text = f" {color_formatter.extra('EXTRA')} {color_formatter.filename(filename)} | {path}"
                    else:
                        extra_text = f" EXTRA {filename} | {path}"
                else:
                    if color_formatter:
                        extra_text = f" {color_formatter.extra('EXTRA')} {color_formatter.filename(filename)}"
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
        if color_formatter:
            verified_text = f"{color_formatter.bold_number(verified_count)} {color_formatter.success('verified')}"
            failed_text = f"{color_formatter.bold_number(failed_count)} {color_formatter.error('failed')}"
            missing_text = f"{color_formatter.bold_number(missing_count)} {color_formatter.warning('missing')}"
            extra_text = f"{color_formatter.bold_number(extra_count)} {color_formatter.extra('extra')}"
        else:
            verified_text = f"{verified_count} verified"
            failed_text = f"{failed_count} failed"
            missing_text = f"{missing_count} missing"
            extra_text = f"{extra_count} extra"

        # Build complete summary line
        summary = f"{colored_status} {path}: {verified_text}, {failed_text}, {missing_text}, {extra_text}"
        
        # Check squelch settings before displaying
        should_display = True
        
        if squelch_settings:
            # Check if FORCE_SUMMARY is set - this overrides hiding logic but respects category filtering
            if squelch_settings.get('FORCE_SUMMARY', False):
                # FORCE_SUMMARY overrides visibility hiding but respects category filtering
                # Category filtering takes absolute priority - check independently
                should_display = True  # Default to force display
                
                # Check SUCCESS squelching first (highest priority)
                # SUCCESS includes both exit_code=0 (perfect) and exit_code=2 (with extras)
                if 'SUCCESS' in status_text and squelch_settings.get('SUCCESS', False):
                    should_display = False  # SUCCESS always squelched when SUCCESS=True
                
                # Check pure EXTRA-only squelching (if not already squelched by SUCCESS)
                if should_display and (extra_count > 0 and failed_count == 0 and missing_count == 0 and verified_count == 0 and squelch_settings.get('EXTRA', False)):
                    should_display = False  # Pure EXTRA-only squelched when EXTRA=True
                
                # Check EXTRA_SUMMARY squelching (if not already squelched)
                if should_display and (extra_count > 0 and failed_count == 0 and missing_count == 0 and squelch_settings.get('EXTRA_SUMMARY', False)):
                    should_display = False  # EXTRA_SUMMARY compressed display
            # Check if SUMMARY (directory status lines) should be squelched
            elif squelch_settings.get('SUMMARY', False):
                should_display = False
            # Check if this is a SUCCESS message that should be squelched
            elif 'SUCCESS' in status_text and squelch_settings.get('SUCCESS', False):
                # This is a SUCCESS (perfect or with extras) and SUCCESS is squelched
                # But for auto-detected commands, always show the summary
                if not is_auto_detected_command:
                    should_display = False
            else:
                # Check if directory has only issues that are being squelched
                # If all the issues in this directory are squelched, don't show status line
                has_displayed_fails = failed_count > 0 and not squelch_settings.get('FAILS', False)
                has_displayed_missing = missing_count > 0 and not squelch_settings.get('MISSING', False)
                has_displayed_extra = extra_count > 0 and not squelch_settings.get('EXTRA', False)
                
                # If directory has no displayed issues, don't show status line (unless show_all is True or auto-detected)
                # For auto-detected commands, always show the summary even for pure SUCCESS
                if not has_displayed_fails and not has_displayed_missing and not has_displayed_extra and verified_count > 0 and not show_all and not is_auto_detected_command:
                    should_display = False
                # Special case: if directory only has EXTRA files and EXTRA_SUMMARY is squelched, hide status line
                elif (has_displayed_extra and not has_displayed_fails and not has_displayed_missing and 
                      failed_count == 0 and missing_count == 0 and squelch_settings.get('EXTRA_SUMMARY', False)):
                    should_display = False
        
        # Log with appropriate level based on severity
        if should_display:
            if exit_code <= 2:  # Perfect or almost perfect
                if dazzle_logger:
                    dazzle_logger.info(summary, level=0)
                else:
                    logger.info(summary)
            else:  # Has issues
                if dazzle_logger:
                    dazzle_logger.error(summary)
                else:
                    logger.error(summary)
        
        # Store exit code for main function to return
        # We'll add this to a global variable or pass it through the call stack
        global verification_exit_code
        # Only set individual directory exit code if we're not tracking grand totals
        # If we have grand totals, they will set the final exit code
        if not grand_totals:
            verification_exit_code = exit_code
        
        # Add results to grand totals if tracking
        if grand_totals:
            grand_totals.add_directory_result(results)
        
        # In quiet mode, add spacing after directories that produce output
        if dazzle_logger and dazzle_logger.quiet:
            # Check if this directory produced any output in quiet mode
            # Consider squelch settings when determining what constitutes "problems"
            showed_fails = failed_count > 0 and not (squelch_settings and squelch_settings.get('FAILS', False))
            showed_missing = missing_count > 0 and not (squelch_settings and squelch_settings.get('MISSING', False))
            showed_extra = extra_count > 0 and not (squelch_settings and squelch_settings.get('EXTRA', False))
            has_problems = showed_fails or showed_missing or showed_extra
            showed_summary = should_display and (exit_code > 2 or exit_code == 0 and not (squelch_settings and squelch_settings.get('SUCCESS', False)))
            
            if has_problems or showed_summary:
                # This directory produced output, add spacing after it
                print(file=sys.stderr)
        
        # Mark that we just processed a directory for spacing
        if dazzle_logger:
            dazzle_logger.last_was_directory = True


class DetailedHelpAction(argparse.Action):
    """Custom action to provide detailed help for specific topics."""
    
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs='?', const='general', **kwargs)
    
    def __call__(self, parser, namespace, values, option_string=None):
        topic = values or 'general'
        self.show_detailed_help(topic)
        parser.exit()
    
    def show_detailed_help(self, topic):
        """Show detailed help for specific topics."""
        help_topics = {
            'general': self._general_help,
            'mode': self._mode_help,
            'manage': self._manage_help,
            'verify': self._verify_help,
            'shadow': self._shadow_help,
            'resume': self._resume_help,
            'examples': self._examples_help
        }
        
        if topic in help_topics:
            help_topics[topic]()
        else:
            print(f"Unknown help topic: {topic}")
            print(f"Available topics: {', '.join(help_topics.keys())}")
    
    def _general_help(self):
        print("""
Dazzle Cross-Platform Checksum Tool v{version}

DESCRIPTION:
    Generate and verify checksums for data integrity verification across
    different machines and operating systems. Supports individual .shasum
    files per directory, monolithic files for entire trees, and shadow
    directories for clean source management.

BASIC USAGE:
    dazzlesum [OPTIONS] [DIRECTORY]

COMMON WORKFLOWS:
    dazzlesum                           # Generate checksums for current directory
    dazzlesum -r                        # Generate recursively
    dazzlesum -r --verify               # Verify existing checksums
    dazzlesum -r --mode monolithic      # Single file for entire tree
    dazzlesum -r --shadow-dir ./checks  # Keep source directories clean

DETAILED HELP:
    dazzlesum --detailed-help mode      # Help for --mode options
    dazzlesum --detailed-help manage    # Help for --manage operations  
    dazzlesum --detailed-help verify    # Help for verification options
    dazzlesum --detailed-help shadow    # Help for shadow directories
    dazzlesum --detailed-help resume    # Help for --resume feature
    dazzlesum --detailed-help examples  # Comprehensive examples

For complete argument list, use: dazzlesum --help
        """.format(version=__version__))
    
    def _mode_help(self):
        print(r"""
--mode OPTION: Choose checksum generation strategy

OPTIONS:
    individual   Generate .shasum files in each directory (default)
    monolithic   Generate single checksum file for entire tree
    both         Generate both individual and monolithic files

DETAILED EXPLANATION:

individual mode (default):
    Creates .shasum files in each processed directory
    +---- dir1/
    |   +---- file1.txt
    |   +---- file2.txt
    |   \---- .shasum          <-- checksums for file1.txt, file2.txt
    \---- dir2/
        +---- file3.txt
        \---- .shasum          <-- checksum for file3.txt

monolithic mode:
    Creates single checksum file with relative paths
    +---- dir1/
    |   +---- file1.txt
    |   \---- file2.txt
    +---- dir2/
    |   \---- file3.txt
    \---- checksums.sha256     <-- all checksums in one file
    
    Content format:
    hash1  dir1/file1.txt
    hash2  dir1/file2.txt  
    hash3  dir2/file3.txt

both mode:
    Combines individual and monolithic approaches
    Useful when you want flexibility for different verification scenarios

EXAMPLES:
    dazzlesum -r --mode individual      # Default behavior
    dazzlesum -r --mode monolithic      # Single file approach
    dazzlesum -r --mode both            # Maximum flexibility
    dazzlesum -r --mode monolithic --output my-checksums.sha256  # Custom name

REQUIREMENTS:
    - monolithic and both modes require --recursive flag
    - Use --output to specify custom monolithic filename
        """)
    
    def _manage_help(self):
        print(r"""
--manage OPERATION: Manage existing .shasum files

OPERATIONS:
    backup    Copy all .shasum files to parallel directory structure
    remove    Delete all .shasum files from directory tree
    restore   Copy .shasum files back from backup location  
    list      Show all .shasum files with details

DETAILED EXPLANATION:

backup operation:
    Creates parallel directory structure with only .shasum files
    Source:                    Backup:
    /data/                     /backup/
    +---- file1.txt              +---- .shasum
    +---- .shasum                \---- subdir/
    \---- subdir/                    \---- .shasum
        +---- file2.txt
        \---- .shasum

remove operation:
    Removes all .shasum files from directory tree
    - Prompts for confirmation (use -y to skip)
    - Use --dry-run to preview what would be removed
    - Cannot be undone without backup

restore operation:
    Copies .shasum files from backup back to source locations
    - Requires --backup-dir to specify backup location
    - Creates directories as needed
    - Overwrites existing .shasum files

list operation:
    Shows all .shasum files with metadata:
    - File path and size
    - Modification date
    - Number of checksums in each file
    - Summary statistics

EXAMPLES:
    dazzlesum -r --manage backup --backup-dir ./shasum-backup
    dazzlesum -r --manage list
    dazzlesum -r --manage remove --dry-run         # Preview only
    dazzlesum -r --manage remove -y                # Skip confirmation
    dazzlesum -r --manage restore --backup-dir ./shasum-backup

REQUIREMENTS:
    - backup and restore require --backup-dir
    - All operations require --recursive for subdirectories
        """)
    
    def _verify_help(self):
        print("""
VERIFICATION OPTIONS: Check data integrity

--verify:
    Verify existing checksums instead of generating new ones
    
--show-all-verifications:
    Show all verification results, not just problems (default: problems only)

VERIFICATION BEHAVIOR:

Default (problems only):
    Only shows failed, missing, or extra files
    ERROR -   FAIL file1.txt: expected abc123... got def456...
    WARNING - MISS file2.txt
    WARNING - EXTRA file3.txt
    INFO - OK /path: 98 verified, 1 failed, 1 missing, 1 extra

With --show-all-verifications:
    Shows every file verification result  
    INFO -    OK file1.txt
    INFO -    OK file2.txt
    ERROR -   FAIL file3.txt: expected abc123... got def456...
    INFO - OK /path: 2 verified, 1 failed, 0 missing, 0 extra

VERIFICATION TYPES:

Individual verification:
    dazzlesum -r --verify
    Looks for .shasum files in each directory

Monolithic verification:
    dazzlesum -r --verify --mode monolithic --output checksums.sha256
    Verifies against single monolithic file

Shadow directory verification:
    dazzlesum -r --verify --shadow-dir ./checksums
    Reads checksums from shadow directory structure

Clone verification:
    dazzlesum -r --verify --output ./backup/checksums.sha256 ./restored-data
    Verify copied/restored data against original checksums
    (Shows "Clone verification" message when source differs)

EXAMPLES:
    dazzlesum -r --verify                              # Standard verification
    dazzlesum -r --verify --show-all-verifications     # Show all results
    dazzlesum -r --verify -v                           # Verbose output
    dazzlesum -r --verify --shadow-dir ./checksums     # Shadow verification
        """)
    
    def _shadow_help(self):
        print(r"""
--shadow-dir DIRECTORY: Keep source directories clean

CONCEPT:
    Store checksum files in parallel "shadow" directory structure
    instead of mixing them with your source files

DIRECTORY STRUCTURE:

Source (stays clean):        Shadow (contains checksums):
/project/                    /checksums/
+---- src/                     +---- .shasum
|   +---- main.py              +---- checksums.sha256      (if monolithic)
|   \---- utils.py             +---- src/
+---- docs/                    |   \---- .shasum
|   \---- readme.md            \---- docs/
\---- tests/                       \---- .shasum
    \---- test_main.py

BENEFITS:
    - Source directories remain completely clean
    - No .shasum files mixed with your data
    - Perfect for version control (add shadow dir to .gitignore)
    - Easy to backup checksums separately from data
    - Supports all modes: individual, monolithic, both

USE CASES:

Git repositories:
    dazzlesum -r --shadow-dir ./.checksums
    echo ".checksums/" >> .gitignore

Data backup workflows:
    dazzlesum -r --mode both --shadow-dir ./verification
    # Backup data separately from verification info

Clone verification:
    dazzlesum -r --mode monolithic --shadow-dir ./checks ./original
    cp -r ./original ./copy
    dazzlesum -r --verify --output ./checks/checksums.sha256 ./copy

Network drives:
    dazzlesum -r --shadow-dir ./local-checksums //server/share
    # Store checksums locally for faster access

EXAMPLES:
    dazzlesum -r --shadow-dir ./checksums                    # Individual mode
    dazzlesum -r --mode monolithic --shadow-dir ./checksums  # Monolithic mode
    dazzlesum -r --mode both --shadow-dir ./checksums        # Both modes
    dazzlesum -r --verify --shadow-dir ./checksums           # Verification
        """)
    
    def _resume_help(self):
        print("""
--resume: Continue interrupted operations

CONCEPT:
    Resume checksum generation that was interrupted by system shutdown,
    network issues, or user cancellation. Skips directories that have
    already been processed.

HOW IT WORKS:
    - Detects existing .shasum files or monolithic entries
    - Skips directories that appear complete
    - Continues from where the operation left off
    - Works with all modes: individual, monolithic, both

RESUME CONDITIONS:

Individual mode:
    Skips directories that have .shasum files with recent timestamps
    
Monolithic mode:
    Parses existing monolithic file and skips directories already included
    Appends new entries to existing file

Shadow directories:
    Checks shadow location for existing checksums
    Resumes based on shadow directory contents

EXAMPLES:
    dazzlesum -r --resume                               # Resume individual
    dazzlesum -r --resume --mode monolithic             # Resume monolithic  
    dazzlesum -r --resume --shadow-dir ./checksums      # Resume with shadow
    dazzlesum -r --resume --mode both                   # Resume both modes

SAFETY FEATURES:
    - Never overwrites existing good checksums
    - Validates partial files before resuming
    - Can detect and handle corrupted resume state
    - Use --verify after resume to ensure completeness

LIMITATIONS:
    - Cannot resume verification operations (only generation)
    - Requires same algorithm as original operation
    - Directory structure must not have changed significantly

NOTE: Very large operations (millions of files) benefit most from resume capability
        """)
    
    def _examples_help(self):
        print("""
COMPREHENSIVE EXAMPLES

BASIC OPERATIONS:
    dazzlesum                                    # Current directory
    dazzlesum /path/to/data                      # Specific directory
    dazzlesum -r                                 # Recursive processing
    dazzlesum -r --algorithm sha512              # Different algorithm

GENERATION MODES:
    dazzlesum -r --mode individual               # .shasum in each directory (default)
    dazzlesum -r --mode monolithic               # Single checksums.sha256 file  
    dazzlesum -r --mode both                     # Both individual and monolithic
    dazzlesum -r --mode monolithic --output my.sha256  # Custom monolithic name

SHADOW DIRECTORIES:
    dazzlesum -r --shadow-dir ./checksums        # Keep source clean
    dazzlesum -r --mode both --shadow-dir ./verification  # Both modes in shadow

VERIFICATION:
    dazzlesum -r --verify                        # Verify existing checksums
    dazzlesum -r --verify --show-all-verifications  # Show all files, not just problems
    dazzlesum -r --verify --shadow-dir ./checksums  # Verify from shadow directory

CLONE VERIFICATION:
    # Generate checksums for original
    dazzlesum -r --mode monolithic --shadow-dir ./backup-checks ./original-data
    
    # Create backup/copy  
    cp -r ./original-data ./backup-data
    
    # Verify copy matches original
    dazzlesum -r --verify --output ./backup-checks/checksums.sha256 ./backup-data

MANAGEMENT OPERATIONS:
    dazzlesum -r --manage backup --backup-dir ./shasum-archive    # Backup checksums
    dazzlesum -r --manage list                                    # List all .shasum files
    dazzlesum -r --manage remove --dry-run                       # Preview removal
    dazzlesum -r --manage remove -y                              # Remove without confirmation
    dazzlesum -r --manage restore --backup-dir ./shasum-archive  # Restore from backup

LARGE DATASET OPERATIONS:
    dazzlesum -r --mode monolithic --resume            # Resume interrupted operation
    dazzlesum -r --summary                             # Progress bar for large ops
    dazzlesum -r --quiet                               # Minimal output

FILTERING:
    dazzlesum -r --include "*.txt,*.doc"               # Only specific file types
    dazzlesum -r --exclude "*.tmp,*.log,node_modules/**"  # Exclude patterns

VERSION CONTROL INTEGRATION:
    dazzlesum -r --shadow-dir ./.checksums             # Generate in shadow
    echo ".checksums/" >> .gitignore                   # Ignore checksums in Git
    dazzlesum -r --verify --shadow-dir ./.checksums    # Verify in CI/CD

AUTOMATION:
    dazzlesum -r --log verify.log                      # Log to file
    dazzlesum -r -y --manage remove                    # Skip confirmations
    dazzlesum -r --dry-run --manage remove             # Preview operations
        """)


class VerbosityHelpAction(argparse.Action):
    """Custom action to provide detailed verbosity level explanation."""
    
    def __call__(self, parser, namespace, values, option_string=None):
        print("""
Verbosity Levels Explained:

ULTRA QUIET:
  -qqqqq (-5)  Silent mode - NO output, only exit codes
               Perfect for CI/CD systems that only need pass/fail status
  
  -qqqq  (-4)  Ultra quiet - only grand totals  
               Shows final summary statistics only
  
  -qqq   (-3)  Very quiet - only directory summaries
               Shows directory result lines but no individual file details
  
QUIET:  
  -qq    (-2)  Quiet - hide individual failure lines, show summaries only
               Shows directory summaries but hides individual FAIL/MISS lines
  
  -q     (-1)  Minimal - hide EXTRA files, show FAIL/MISS only
               Hides EXTRA files but shows failures and missing files
  
NORMAL:
         (0)   Default - hide SUCCESS, show problems (current behavior)
               Smart defaults: shows problems but hides successful verifications
  
VERBOSE:
  -v     (+1)  Informative - show all results including SUCCESS
               Shows everything including successful verifications
  
  -vv    (+2)  Verbose - show file processing + all results  
               Shows file-by-file processing details and all results
  
  -vvv   (+3)  Very verbose - show debug information + processing details
               Shows debug messages and internal processing information
  
  -vvvv  (+4)  Ultra verbose - show all internal operations
               Shows everything including low-level internal operations

EXAMPLES:
  dazzlesum verify -r -qq          # Only directory summaries
  dazzlesum verify -r -q -v        # -q + -v = 0 (default level)
  dazzlesum verify -r --verbosity=-3  # Same as -qqq
  dazzlesum verify -r -vv          # Show file processing details

ALTERNATIVE SYNTAX:
  --verbosity=-3    Same as -qqq
  --verbosity=2     Same as -vv

ENVIRONMENT VARIABLES:
  DAZZLESUM_VERBOSITY=-1     Set default verbosity level
  DAZZLESUM_SHOW_LOG_TYPES=1 Force log type prefixes to show

The verbosity level is calculated as: base_level + verbose_count - quiet_count
        """)
        parser.exit()


def show_verbosity_help():
    """Show verbosity help as a top-level command (dazzlesum verbosity)."""
    print("""
Verbosity Levels Explained:

ULTRA QUIET:
  -qqqqqq (-6)  Silent mode - NO output, only exit codes
                Perfect for CI/CD systems that only need pass/fail status
  
  -qqqqq  (-5)  Only grand totals - shows final summary statistics only
                Hides all directory output, shows only aggregate results
  
  -qqqq   (-4)  Only info/status lines + grand totals
                Shows directory summaries but no individual file details
  
  -qqq    (-3)  Shows FAIL + info/status lines + grand totals
                Hides EXTRA, MISSING files; shows only failures
  
QUIET:  
  -qq     (-2)  Shows MISSING + FAIL + info/status lines + grand totals
                Hides EXTRA files; shows missing files and failures
  
  -q      (-1)  Shows EXTRA + MISSING + FAIL + info/status lines + grand totals
                Shows all issues; hides only pure SUCCESS summaries (compressed EXTRA output)
  
NORMAL:
          (0)   Default - shows NO_SHASUM + EXTRA + MISSING + FAIL + info/status + grand totals
                Smart defaults: shows problems and "No .shasum file found" messages
  
VERBOSE:
  -v      (+1)  Shows SUCCESS + NO_SHASUM + EXTRA + MISSING + FAIL + info/status + grand totals
                Shows everything including successful directory verifications
  
  -vv     (+2)  Shows file processing details + all results + log type prefixes
                Shows file-by-file processing and internal operations
  
  -vvv    (+3)  Shows debug information + processing details + log type prefixes
                Shows debug messages and detailed internal information
  
  -vvvv   (+4)  Shows all internal operations + debug + log type prefixes
                Shows everything including low-level internal operations

EXAMPLES:
  dazzlesum verify -r -qq          # Only MISSING/FAIL + summaries
  dazzlesum verify -r -q -v        # -q + -v = 0 (default level)
  dazzlesum verify -r --verbosity=-3  # Same as -qqq
  dazzlesum verify -r -vv          # Show file processing details

ALTERNATIVE SYNTAX:
  --verbosity=-6    Same as -qqqqqq (silent mode)
  --verbosity=-3    Same as -qqq
  --verbosity=2     Same as -vv

FINE-GRAINED CONTROL:
  --squelch SUCCESS,EXTRA          # Manually hide specific categories
  --squelch EXTRA_SUMMARY          # Hide status lines for EXTRA-only directories

ENVIRONMENT VARIABLES:
  DAZZLESUM_VERBOSITY=-1     Set default verbosity level
  DAZZLESUM_SHOW_LOG_TYPES=1 Force log type prefixes to show

The verbosity level is calculated as: base_level + verbose_count - quiet_count

GLOBAL APPLICATION:
The verbosity system works across ALL commands (create, verify, update, manage),
not just verify. Each command may interpret verbosity levels slightly differently
based on what operations they perform.
    """)


def create_parent_parser():
    """Create parent parser with common arguments for all subcommands."""
    parent = argparse.ArgumentParser(add_help=False)
    
    # Positional arguments
    parent.add_argument('directory', nargs='?', default='.',
                       help='Directory to process (default: current directory)')
    
    # Options that all subcommands share
    parent.add_argument('-r', '--recursive', action='store_true',
                       help='Process directories recursively')
    parent.add_argument('-v', '--verbose', action='count', default=0,
                       help='Increase verbosity (can be used multiple times: -v, -vv, -vvv, -vvvv)')
    parent.add_argument('-q', '--quiet', action='count', default=0,
                       help='Decrease verbosity (can be used multiple times: -q, -qq, -qqq, -qqqq, -qqqqq)')
    parent.add_argument('--verbosity', type=int, metavar='LEVEL',
                       help='Set verbosity level directly (-5 to +4, overrides -q/-v). Use "dazzlesum verbosity" for detailed help.')
    parent.add_argument('--no-color', action='store_true',
                       help='Disable colored output')
    parent.add_argument('--show-log-types', action='store_true',
                       help='Show log type prefixes (INFO, ERROR, WARNING)')
    parent.add_argument('--algorithm', choices=SUPPORTED_ALGORITHMS,
                       default=DEFAULT_ALGORITHM, help=f'Hash algorithm (default: {DEFAULT_ALGORITHM})')
    parent.add_argument('--shadow-dir', metavar='DIR',
                       help='Store checksums in parallel shadow directory')
    parent.add_argument('--follow-symlinks', action='store_true',
                       help='Follow symbolic links and junctions')
    parent.add_argument('--line-endings', choices=['auto', 'unix', 'windows', 'preserve'],
                       default='auto', help='Line ending handling strategy')
    parent.add_argument('--force-python', action='store_true',
                       help='Force Python implementation (skip native tools)')
    parent.add_argument('-y', '--yes', action='store_true',
                       help='Answer yes to all prompts')
    
    return parent

def create_argument_parser():
    """Create main parser with subcommands."""
    # Create parent parser with common arguments
    parent = create_parent_parser()
    
    # Main parser WITHOUT promoted arguments (clean subparser approach)
    parser = argparse.ArgumentParser(
        prog='dazzlesum',
        description='Dazzle Cross-Platform Checksum Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s create -r                                    # Generate checksums recursively
  %(prog)s create -r --mode monolithic                  # Single checksum file for tree
  %(prog)s create -r --mode monolithic --output backup.sha256  # Custom monolithic name
  %(prog)s verify -r                                    # Verify existing checksums
  %(prog)s verify -r -v                                 # Show all verification results including SUCCESS
  %(prog)s verify -r -qq                                # Only show MISSING/FAIL + summaries
  %(prog)s verify -r -qqqq                              # Ultra quiet - only directories with problems
  %(prog)s update -r                                    # Update changed checksums
  %(prog)s manage -r backup --backup-dir ./backup       # Backup all .shasum files
  %(prog)s manage -r list                               # List all .shasum files
  
Verbosity Control (11 levels: -6 to +4):
  %(prog)s verify -r -qqqqq                             # Silent mode - exit codes only (CI/CD)
  %(prog)s verify -r -qqqq                              # Ultra quiet - only problem directories
  %(prog)s verify -r -qq                                # Quiet - hide EXTRA files, show problems
  %(prog)s verify -r                                    # Default - smart problem reporting
  %(prog)s verify -r -v                                 # Verbose - show all results including SUCCESS
  %(prog)s verify -r -vv                                # Show file-by-file processing details
  %(prog)s verify -r --verbosity=-3                     # Direct level setting (same as -qqq)
  
Clone Verification Workflow:
  %(prog)s create -r --mode monolithic /original/folder       # Generate checksums for original
  cp -r /original/folder /clone/folder                         # Create clone
  %(prog)s verify --checksum-file checksums.sha256 /clone/folder  # Verify clone matches original
  
Shadow Directory (keeps source clean):
  %(prog)s create -r --shadow-dir ./checksums /data           # Generate in shadow
  %(prog)s verify -r --shadow-dir ./checksums /data           # Verify from shadow

For detailed verbosity help: %(prog)s verbosity
For detailed help on any command: %(prog)s <command> --help
For comprehensive examples: %(prog)s examples
        """)
    
    # Version at main level
    parser.add_argument('--version', action='version', version=f'dazzlesum {__version__}')
    
    # Create subparsers
    subparsers = parser.add_subparsers(dest='command', help='Available commands',
                                     metavar='COMMAND', required=True)
    
    # CREATE subcommand with all its arguments
    create_parser = subparsers.add_parser('create', parents=[parent],
                                         help='Generate checksums for files',
                                         description='Generate checksum files for directory contents')
    create_parser.add_argument('--mode', choices=['individual', 'monolithic', 'both'],
                              default='individual', help='Checksum generation mode (default: individual)')
    create_parser.add_argument('--output', metavar='FILE',
                              help='Output filename for monolithic mode')
    create_parser.add_argument('--include', action='append', metavar='PATTERN',
                              help='Include files matching pattern (can be used multiple times)')
    create_parser.add_argument('--exclude', action='append', metavar='PATTERN',
                              help='Exclude files matching pattern (can be used multiple times)')
    create_parser.add_argument('--resume', action='store_true',
                              help='Resume interrupted checksum generation')
    create_parser.add_argument('--log', metavar='FILE',
                              help='Write detailed log to file')
    create_parser.add_argument('--summary', action='store_true',
                              help='Show summary progress instead of detailed output')
    
    # VERIFY subcommand
    verify_parser = subparsers.add_parser('verify', parents=[parent],
                                         help='Verify existing checksums',
                                         description='Verify file integrity against existing checksums')
    verify_parser.add_argument('--show-all-verifications', action='store_true',
                              help='Show all verification results, not just failures')
    verify_parser.add_argument('--checksum-file', metavar='FILE',
                              help='Monolithic checksum file to verify against')
    # Keep --output for backwards compatibility with deprecation warning
    verify_parser.add_argument('--output', metavar='FILE', dest='checksum_file',
                              help=argparse.SUPPRESS)  # Hidden deprecated option
    verify_parser.add_argument('--log', metavar='FILE',
                              help='Write detailed log to file')
    
    # Output control options
    verify_parser.add_argument('--squelch', metavar='CATEGORIES',
                              help='Hide output categories: SUCCESS,NO_SHASUM,INFO,EXTRA,MISSING,FAILS,SUMMARY,EXTRA_SUMMARY (comma-separated)')
    verify_parser.add_argument('--show-all', action='store_true',
                              help='Show all results including successful verifications (legacy behavior)')
    verify_parser.add_argument('--include', action='append', metavar='PATTERN',
                              help='Include files matching pattern (can be used multiple times)')
    verify_parser.add_argument('--exclude', action='append', metavar='PATTERN',
                              help='Exclude files/directories matching pattern (can be used multiple times)')

    # UPDATE subcommand
    update_parser = subparsers.add_parser('update', parents=[parent],
                                         help='Update existing checksums',
                                         description='Update checksums for changed files')
    update_parser.add_argument('--include', action='append', metavar='PATTERN',
                              help='Include files matching pattern (can be used multiple times)')
    update_parser.add_argument('--exclude', action='append', metavar='PATTERN',
                              help='Exclude files matching pattern (can be used multiple times)')
    update_parser.add_argument('--log', metavar='FILE',
                              help='Write detailed log to file')
    
    # MANAGE subcommand
    manage_parser = subparsers.add_parser('manage', parents=[parent],
                                         help='Manage existing checksum files',
                                         description='Backup, remove, restore, or list checksum files')
    manage_parser.add_argument('operation', choices=['backup', 'remove', 'restore', 'list'],
                              help='Management operation to perform')
    manage_parser.add_argument('--backup-dir', metavar='DIR',
                              help='Backup directory (required for backup/restore)')
    manage_parser.add_argument('--dry-run', action='store_true',
                              help='Show what would be done without making changes')
    
    # HELP-ONLY subcommands
    mode_parser = subparsers.add_parser('mode', help='Detailed help for --mode parameter')
    mode_parser.set_defaults(help_topic='mode')
    
    examples_parser = subparsers.add_parser('examples', help='Comprehensive usage examples')
    examples_parser.set_defaults(help_topic='examples')
    
    shadow_parser = subparsers.add_parser('shadow', help='Detailed help for shadow directories')
    shadow_parser.set_defaults(help_topic='shadow')
    
    verbosity_parser = subparsers.add_parser('verbosity', help='Detailed help for verbosity levels (-6 to +4)')
    verbosity_parser.set_defaults(help_topic='verbosity')
    
    # Override format_help to show all available options in main help
    original_format_help = parser.format_help
    
    def format_help_with_all_options():
        help_text = original_format_help()
        
        # Add comprehensive options section
        additional_help = """
Common Options (available for all commands):
  --algorithm {md5,sha1,sha256,sha512}
                        Hash algorithm (default: sha256)
  -r, --recursive       Process directories recursively
  --follow-symlinks     Follow symbolic links and junctions
  --shadow-dir DIR      Store checksums in parallel shadow directory
  --line-endings {auto,unix,windows,preserve}
                        Line ending handling strategy
  -v, --verbose         Increase verbosity (can be used multiple times: -v, -vv, -vvv, -vvvv)
  -q, --quiet           Decrease verbosity (can be used multiple times: -q, -qq, -qqq, -qqqq, -qqqqq)
  --verbosity LEVEL     Set verbosity level directly (-6 to +4, overrides -q/-v)
  --no-color            Disable colored output
  --show-log-types      Show log type prefixes (INFO, ERROR, WARNING)
  --force-python        Force Python implementation (skip native tools)
  -y, --yes             Answer yes to all prompts

Command-Specific Options:
  create:
    --mode {individual,monolithic,both}
                        Checksum generation mode (default: individual)
    --output FILE       Output filename for monolithic mode
    --include PATTERN   Include files matching pattern (can be used multiple times)
    --exclude PATTERN   Exclude files matching pattern (can be used multiple times)
    --resume            Resume interrupted checksum generation
    --log FILE          Write detailed log to file
    --summary           Show summary progress instead of detailed output
    
  verify:
    --show-all-verifications
                        Show all verification results, not just failures
    --checksum-file FILE    Monolithic checksum file to verify against
    --squelch CATEGORIES    Hide output categories: SUCCESS,NO_SHASUM,INFO,EXTRA,MISSING,FAILS,SUMMARY,EXTRA_SUMMARY
    --show-all          Show all results including successful verifications (legacy behavior)
    --log FILE          Write detailed log to file
    
  update:
    --include PATTERN   Include files matching pattern (can be used multiple times)
    --exclude PATTERN   Exclude files matching pattern (can be used multiple times)
    --log FILE          Write detailed log to file
    
  manage:
    --backup-dir DIR    Backup directory (required for backup/restore)
    --dry-run           Show what would be done without making changes
"""
        # Insert before the positional arguments section
        return help_text.replace("\npositional arguments:", 
                                additional_help + "\npositional arguments:")
    
    parser.format_help = format_help_with_all_options
    return parser


def show_detailed_help(topic):
    """Show detailed help for specific topics."""
    if topic == 'mode':
        print(get_mode_help())
    elif topic == 'examples':
        print(get_examples_help())
    elif topic == 'shadow':
        print(get_shadow_help())
    else:
        print(f"Unknown help topic: {topic}")
        print("Available topics: mode, examples, shadow")

def get_mode_help():
    """Get detailed help for --mode parameter."""
    return r"""--mode OPTION: Choose checksum generation strategy

OPTIONS:
    individual   Generate .shasum files in each directory (default)
    monolithic   Generate single checksum file for entire tree
    both         Generate both individual and monolithic files

DETAILED EXPLANATION:

individual mode (default):
    Creates .shasum files in each processed directory
    +---- dir1/
    |   +---- file1.txt
    |   +---- file2.txt
    |   \---- .shasum          <-- checksums for file1.txt, file2.txt
    \---- dir2/
        +---- file3.txt
        \---- .shasum          <-- checksum for file3.txt

monolithic mode:
    Creates single checksum file with relative paths
    +---- dir1/
    |   +---- file1.txt
    |   \---- file2.txt
    +---- dir2/
    |   \---- file3.txt
    \---- checksums.sha256     <-- all checksums in one file
    
    Content format:
    hash1  dir1/file1.txt
    hash2  dir1/file2.txt  
    hash3  dir2/file3.txt

both mode:
    Combines individual and monolithic approaches
    Useful when you want flexibility for different verification scenarios

EXAMPLES:
    dazzlesum create -r --mode individual      # Default behavior
    dazzlesum create -r --mode monolithic      # Single file approach
    dazzlesum create -r --mode both            # Maximum flexibility
    dazzlesum create -r --mode monolithic --output my-checksums.sha256  # Custom name

REQUIREMENTS:
    - monolithic and both modes require --recursive flag
    - Use --output to specify custom monolithic filename"""

def get_examples_help():
    """Get comprehensive usage examples."""
    return """COMPREHENSIVE EXAMPLES

BASIC OPERATIONS:
    dazzlesum create                                    # Current directory
    dazzlesum create /path/to/data                      # Specific directory
    dazzlesum create -r                                 # Recursive processing
    dazzlesum create -r --algorithm sha512              # Different algorithm

GENERATION MODES:
    dazzlesum create -r --mode individual               # .shasum in each directory (default)
    dazzlesum create -r --mode monolithic               # Single checksums.sha256 file  
    dazzlesum create -r --mode both                     # Both individual and monolithic
    dazzlesum create -r --mode monolithic --output my.sha256  # Custom monolithic name

SHADOW DIRECTORIES:
    dazzlesum create -r --shadow-dir ./checksums        # Keep source clean
    dazzlesum create -r --mode both --shadow-dir ./verification  # Both modes in shadow

VERIFICATION:
    dazzlesum verify -r                                 # Verify all .shasum files
    dazzlesum verify -r --show-all-verifications        # Show all results, not just failures
    dazzlesum verify --output checksums.sha256 ./target # Verify against monolithic file

UPDATING:
    dazzlesum update -r                                 # Update changed files
    dazzlesum update -r --include "*.txt"               # Update only specific patterns

MANAGEMENT:
    dazzlesum manage backup --backup-dir ./backup      # Backup all .shasum files
    dazzlesum manage remove --dry-run                   # Preview removal
    dazzlesum manage restore --backup-dir ./backup     # Restore from backup
    dazzlesum manage list                               # List all .shasum files

LARGE DATASET OPERATIONS:
    dazzlesum create -r --mode monolithic --resume     # Resume interrupted operation
    dazzlesum create -r --summary                      # Progress bar for large ops
    dazzlesum create -r --quiet                        # Minimal output

FILTERING:
    dazzlesum create -r --include "*.txt,*.doc"        # Only specific file types
    dazzlesum create -r --exclude "*.tmp,*.log,node_modules/**"  # Exclude patterns

VERSION CONTROL INTEGRATION:
    dazzlesum create -r --shadow-dir ./.checksums      # Generate in shadow
    echo ".checksums/" >> .gitignore                   # Ignore checksums in Git
    dazzlesum verify -r --shadow-dir ./.checksums      # Verify in CI/CD

AUTOMATION:
    dazzlesum create -r --log create.log               # Log to file
    dazzlesum verify -r -y                             # Skip confirmations
    dazzlesum manage remove -r --dry-run               # Preview operations

MIGRATION FROM OLD SYNTAX:
    OLD: dazzlesum -r --verify
    NEW: dazzlesum verify -r
    
    OLD: dazzlesum -r --update  
    NEW: dazzlesum update -r
    
    OLD: dazzlesum -r --mode monolithic
    NEW: dazzlesum create -r --mode monolithic"""

def get_shadow_help():
    """Get detailed help for shadow directories."""
    return r"""SHADOW DIRECTORIES: Keep Source Clean

CONCEPT:
    Shadow directories store all checksum files in a parallel directory
    structure, keeping your source directories completely clean.

STRUCTURE:
    Source Directory (Clean)          Shadow Directory (Checksums)
    /data/                           /checksums/
    +---- file1.txt                    +---- .shasum                    
    +---- file2.txt                    +---- checksums.sha256          
    +---- folder1/                     +---- folder1/                   
    |   \---- file3.txt                |   \---- .shasum               
    \---- folder2/                     \---- folder2/                   
        \---- file4.txt                    \---- .shasum               

EXAMPLES:
    dazzlesum create -r --shadow-dir ./checksums       # Generate to shadow
    dazzlesum verify -r --shadow-dir ./checksums       # Verify from shadow
    dazzlesum create -r --mode both --shadow-dir ./verification  # Both modes

BENEFITS:
    - Source directories remain completely clean
    - Easy to backup/restore just checksums
    - Perfect for version control (add shadow dir to .gitignore)
    - Supports both individual and monolithic modes

CLONE VERIFICATION:
    dazzlesum create -r --shadow-dir ./checksums ./original
    cp -r ./original ./clone
    dazzlesum verify -r --shadow-dir ./checksums ./clone"""


def execute_main_action(args, action):
    """Execute the main action based on arguments and detected command."""
    directory = Path(args.directory).resolve()
    
    if action == 'verify':
        return execute_verify_action(args, directory)
    elif action == 'update':
        return execute_update_action(args, directory)
    elif action == 'manage':
        return execute_manage_action(args, directory)
    else:  # create (default)
        return execute_create_action(args, directory)

def execute_create_action(args, directory):
    """Execute create action."""
    # Determine generation modes based on --mode
    generate_individual = (args.mode in ['individual', 'both'])
    generate_monolithic = (args.mode in ['monolithic', 'both'])
    
    # Set up generator for create mode
    generator = ChecksumGenerator(
        algorithm=args.algorithm,
        line_ending_strategy=args.line_endings,
        include_patterns=args.include or [],
        exclude_patterns=args.exclude or [],
        follow_symlinks=args.follow_symlinks,
        log_file=args.log,
        summary_mode=args.summary,
        generate_individual=generate_individual,
        generate_monolithic=generate_monolithic,
        output_file=args.output,
        shadow_dir=args.shadow_dir,
        resume_mode=args.resume,
        yes_to_all=args.yes
    )
    
    # Force Python implementation if requested
    if args.force_python:
        generator.calculator.native_tool = None
        if not args.summary:
            logger.info("Forcing Python implementation")
    
    # Log generation mode
    mode_descriptions = {
        'individual': 'Individual .shasum files per directory',
        'monolithic': 'Single monolithic checksum file',
        'both': 'Both individual and monolithic files'
    }
    dazzle_logger.info(f"Mode: {mode_descriptions[args.mode]}", level=1)
    
    # Process directory tree
    generator.process_directory_tree(directory, recursive=args.recursive)
    return 0

def execute_verify_action(args, directory):
    """Execute verify action."""
    # Auto-detect verification mode if no checksum file specified
    output_file = getattr(args, 'checksum_file', None)
    if not output_file:
        # Use context detection to find appropriate checksum file
        detected_file = auto_detect_checksum_file(directory)
        if detected_file and is_monolithic_file(detected_file):
            output_file = str(detected_file)
            if dazzle_logger:
                dazzle_logger.info(f"Auto-detected monolithic checksum file: {detected_file}", level=1)
            else:
                logger.info(f"Auto-detected monolithic checksum file: {detected_file}")
    
    # Set up generator for verify mode
    generator = ChecksumGenerator(
        algorithm=args.algorithm,
        line_ending_strategy=args.line_endings,
        include_patterns=getattr(args, 'include', None) or [],
        exclude_patterns=getattr(args, 'exclude', None) or [],
        follow_symlinks=args.follow_symlinks,
        log_file=getattr(args, 'log', None),
        summary_mode=False,  # Verify mode doesn't use summary
        generate_individual=True,  # Verify needs to read individual files
        generate_monolithic=bool(output_file),
        output_file=output_file,
        show_all_verifications=getattr(args, 'show_all_verifications', False) or getattr(args, 'show_all', False),
        shadow_dir=args.shadow_dir,
        yes_to_all=args.yes
    )
    
    # Force Python implementation if requested
    if args.force_python:
        generator.calculator.native_tool = None
        logger.info("Forcing Python implementation")
    
    # Squelch settings are initialized by the verbosity system
    # Apply any explicit --squelch overrides on top of verbosity-based settings
    global squelch_settings  # noqa: F824
    
    # If --show-all is used WITHOUT explicit --squelch, override SUCCESS squelching
    if getattr(args, 'show_all', False) and not (hasattr(args, 'squelch') and args.squelch):
        if squelch_settings:
            squelch_settings['SUCCESS'] = False  # Show SUCCESS messages with --show-all
    
    # Apply explicit --squelch overrides (these take precedence over --show-all)
    if hasattr(args, 'squelch') and args.squelch and squelch_settings:
        squelch_categories = [cat.strip().upper() for cat in args.squelch.split(',')]
        for category in squelch_categories:
            if category in squelch_settings:
                squelch_settings[category] = True
    
    # Process directory tree in verify mode
    generator.process_directory_tree(directory, recursive=args.recursive, verify_only=True)
    return 0

def execute_update_action(args, directory):
    """Execute update action."""
    # Set up generator for update mode
    generator = ChecksumGenerator(
        algorithm=args.algorithm,
        line_ending_strategy=args.line_endings,
        include_patterns=args.include or [],
        exclude_patterns=args.exclude or [],
        follow_symlinks=args.follow_symlinks,
        log_file=args.log,
        summary_mode=False,
        generate_individual=True,  # Update implies individual files
        generate_monolithic=False,  # Update typically doesn't use monolithic
        shadow_dir=args.shadow_dir,
        yes_to_all=args.yes
    )
    
    # Force Python implementation if requested
    if args.force_python:
        generator.calculator.native_tool = None
        logger.info("Forcing Python implementation")
    
    # Process directory tree in update mode
    generator.process_directory_tree(directory, recursive=args.recursive, update_mode=True)
    return 0

def execute_manage_action(args, directory):
    """Execute manage action."""
    # For manage operations, we need to handle the operation from the parsed args
    # The manage subcommand structure should still work
    if hasattr(args, 'operation'):
        operation = args.operation
    else:
        # This shouldn't happen with proper subcommand structure
        logger.error("Manage operation not specified")
        return 1
        
    # Preserve existing manage functionality
    manager = ShasumManager(
        root_dir=directory,
        backup_dir=Path(args.backup_dir) if getattr(args, 'backup_dir', None) else None,
        dry_run=getattr(args, 'dry_run', False)
    )
    
    if operation == 'backup':
        if not getattr(args, 'backup_dir', None):
            logger.error("--backup-dir is required for backup operation")
            return 1
        results = manager.backup_shasums()
        return 1 if results.get('errors') else 0
    elif operation == 'remove':
        results = manager.remove_shasums(force=args.yes)
        return 1 if results.get('errors') else 0
    elif operation == 'restore':
        if not getattr(args, 'backup_dir', None):
            logger.error("--backup-dir is required for restore operation")
            return 1
        results = manager.restore_shasums()
        return 1 if results.get('errors') else 0
    elif operation == 'list':
        results = manager.list_shasums()
        # list_shasums returns a list, not a dict with errors
        return 0
    
    return 1

def setup_logging(verbosity=0, quiet=False, show_log_types=None):
    """Configure logging based on verbosity settings."""
    if quiet:
        level = logging.WARNING
    elif verbosity >= 3:
        level = logging.DEBUG
    else:
        level = logging.INFO

    # Configure root logger
    logging.getLogger().setLevel(level)

    # Determine if we should show log type prefixes
    # Priority: explicit parameter > environment variable > verbosity-based default
    if show_log_types is not None:
        use_log_types = show_log_types
    elif os.environ.get('DAZZLESUM_SHOW_LOG_TYPES', '').lower() in ('1', 'true', 'yes'):
        use_log_types = True
    else:
        # Clean output by default (verbosity 0), show log types for higher verbosity
        use_log_types = verbosity >= 1

    # Create formatter based on verbosity and log type preferences
    if verbosity >= 3:
        # Debug mode: full details including timestamps
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
    elif use_log_types:
        # Normal mode with log type prefixes
        formatter = logging.Formatter('%(levelname)s - %(message)s')
    else:
        # Clean mode: just the message
        formatter = logging.Formatter('%(message)s')

    # Update handler formatter
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
        handler.setLevel(level)


def auto_detect_checksum_file(directory_path):
    """Auto-detect the most appropriate checksum file in a directory.
    
    Returns:
        Path: Path to the detected checksum file, or None if none found
    """
    try:
        directory = Path(directory_path).resolve()
        if not directory.is_dir():
            return None
            
        # Priority 1: Check for individual .shasum files
        shasum_file = directory / SHASUM_FILENAME
        if shasum_file.exists():
            return shasum_file
            
        # Priority 2: Check for common monolithic checksum file patterns
        checksum_patterns = [
            f'checksums.{alg}' for alg in SUPPORTED_ALGORITHMS
        ] + [
            'checksums',
            'CHECKSUMS', 
            'SHA256SUMS', 
            'MD5SUMS',
            'SHA1SUMS',
            'SHA512SUMS'
        ]
        
        for pattern in checksum_patterns:
            potential_file = directory / pattern
            if potential_file.exists() and potential_file.is_file():
                # Use existing is_monolithic_file function to verify it's actually a checksum file
                if is_monolithic_file(potential_file):
                    return potential_file
                    
        # Priority 3: Check for any other files that might be monolithic checksum files
        # Look for common checksum file extensions
        for file_path in directory.iterdir():
            if file_path.is_file():
                name = file_path.name.lower()
                # Check files with common checksum extensions
                if (name.endswith(('.sha256', '.sha1', '.sha512', '.md5')) or
                        'checksum' in name or 'hash' in name):
                    if is_monolithic_file(file_path):
                        return file_path
                        
    except Exception:
        pass
    return None

def detect_context_command(directory_path='.'):
    """Detect the appropriate command based on existing files in directory.
    
    Returns:
        str: 'verify' if .shasum files or monolithic checksum files exist, 'create' otherwise
    """
    detected_file = auto_detect_checksum_file(directory_path)
    return 'verify' if detected_file else 'create'


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
    if not color_formatter or not color_formatter.use_colors:
        return status_text
    
    # Split the status text to colorize percentages
    parts = status_text.split('%')
    if len(parts) >= 3:
        # Format: "99%/1% STATUS"
        success_part = f"{parts[0]}%"
        failure_part = f"{parts[1].split('/')[1]}%"
        status_label = parts[2]
        
        colored_success = color_formatter.success(success_part)
        colored_failure = color_formatter.error(failure_part)
        
        return f"{colored_success}/{colored_failure}{status_label}"
    
    # Fallback to original text if parsing fails
    return status_text

def main():
    """Main entry point with subcommand handling and context detection."""
    global is_auto_detected_command
    try:
        parser = create_argument_parser()
        
        # Handle help-only commands early
        if len(sys.argv) > 1 and sys.argv[1] in ['mode', 'examples', 'shadow', 'verbosity']:
            if sys.argv[1] == 'verbosity':
                show_verbosity_help()
                return 0
            else:
                show_detailed_help(sys.argv[1])
                return 0
        
        # Handle default behavior with context detection
        if len(sys.argv) > 1:
            first_arg = sys.argv[1]
            
            if not first_arg.startswith('-') and first_arg not in ['create', 'verify', 'update', 'manage', 'mode', 'examples', 'shadow']:
                # First argument is likely a directory, detect appropriate command
                detected_command = detect_context_command(first_arg)
                sys.argv.insert(1, detected_command)
                logger.info(f"Context-aware: executing '{detected_command} {first_arg}'")
                is_auto_detected_command = True
        elif len(sys.argv) == 1:
            # No arguments at all, detect command for current directory
            detected_command = detect_context_command('.')
            sys.argv.extend([detected_command, '.'])
            logger.info(f"Context-aware: executing '{detected_command} .'")
            is_auto_detected_command = True
            if detected_command == 'verify':
                # Smart default: only show all verifications for small datasets
                # For large monolithic files, use compact format
                detected_file = auto_detect_checksum_file('.')
                if detected_file and is_monolithic_file(detected_file):
                    # Count entries in monolithic file to decide format
                    try:
                        with open(detected_file, 'r', encoding='utf-8') as f:
                            entry_count = 0
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith('#'):
                                    entry_count += 1
                                    if entry_count > 50:  # Stop counting after threshold
                                        break
                        
                        # Only add --show-all-verifications for small datasets
                        if entry_count <= 50:
                            sys.argv.append('--show-all-verifications')
                    except Exception:
                        # If we can't read the file, default to compact format
                        pass
                else:
                    # For individual .shasum files, always show all verifications
                    sys.argv.append('--show-all-verifications')
        
        # Parse arguments normally
        args = parser.parse_args()
        
        # Handle verbosity configuration early
        global verbosity_config
        verbosity_config = VerbosityConfig.from_environment()
        verbosity_config = VerbosityConfig.from_args(args)
        
        # Initialize squelch settings from verbosity
        initialize_squelch_from_verbosity(verbosity_config.get_effective_level())
        
        # Check if we have a command
        if not hasattr(args, 'command') or args.command is None:
            parser.print_help()
            return 1  # Informational
            
        # Handle help topics that set help_topic attribute
        if hasattr(args, 'help_topic'):
            show_detailed_help(args.help_topic)
            return 1  # Informational
        
        # Validate directory early
        directory = Path(args.directory).resolve()
        if not directory.exists():
            logger.error(f"Directory does not exist: {directory}")
            return 1
        if not directory.is_dir():
            logger.error(f"Path is not a directory: {directory}")
            return 1
        
        # Validate argument combinations based on command
        if args.command == 'create':
            if args.summary and args.verbose > 0:
                logger.error("Cannot use --summary and --verbose together")
                return 1
            if args.summary and args.quiet > 0:
                logger.error("Cannot use --summary and --quiet together")
                return 1
            
            # Validate mode requirements
            if args.mode in ['monolithic', 'both'] and not args.recursive:
                print(f"Monolithic mode works by creating a single checksum file for the entire directory tree.")
                print(f"This requires recursive processing of subdirectories.")
                print(f"")
                # Filter out problematic arguments for suggestions
                filtered_args = [arg for arg in sys.argv[2:] if arg not in ['--mode', 'monolithic']]
                # Remove any --mode argument and its value
                clean_args = []
                skip_next = False
                for arg in filtered_args:
                    if skip_next:
                        skip_next = False
                        continue
                    if arg == '--mode':
                        skip_next = True
                        continue
                    clean_args.append(arg)
                
                args_str = ' '.join(clean_args)
                print(f"If you want to create individual .shasum files per directory instead:")
                print(f"  dazzlesum create {args_str} --mode individual")
                print(f"")
                print(f"If you want a custom-named checksum file for just this directory:")
                print(f"  dazzlesum create {args_str} --output custom-name.sha256")
                print(f"")
                try:
                    response = input("Do you want to proceed with recursive monolithic mode? (y/N): ").strip().lower()
                    if response in ['y', 'yes']:
                        args.recursive = True
                        print("Proceeding with recursive monolithic mode...")
                    else:
                        print("Operation cancelled. Use --help for more options.")
                        return 0
                except (KeyboardInterrupt, EOFError):
                    print("\nOperation cancelled.")
                    return 0
        
        # Set up logging and global state
        # Only pass show_log_types if explicitly set, otherwise let verbosity config decide
        show_log_types = getattr(args, 'show_log_types', False) if hasattr(args, 'show_log_types') and args.show_log_types else None
        
        # Use verbosity config for logging setup
        effective_quiet = verbosity_config.get_effective_level() < 0 or (args.command == 'create' and args.summary)
        setup_logging(args.verbose, effective_quiet, show_log_types)
        
        global dazzle_logger, color_formatter
        dazzle_logger = DazzleLogger(
            verbosity=args.verbose,
            quiet=effective_quiet,
            summary_mode=(args.command == 'create' and args.summary),
            show_log_types=verbosity_config.should_show_log_types() if show_log_types is None else show_log_types
        )
        
        # Set verbosity config in logger
        dazzle_logger.set_verbosity_config(verbosity_config)
        
        # Initialize color formatter
        use_colors = None if not getattr(args, 'no_color', False) else False
        color_formatter = ColorFormatter(use_colors=use_colors)
        
        # Log startup info (skip in silent mode)
        if not (verbosity_config and verbosity_config.is_silent()):
            dazzle_logger.info(f"Dazzle Checksum Tool v{__version__}", level=0)
        
        if args.verbose >= 3:
            dazzle_logger.debug(f"Platform: {platform.platform()}")
            dazzle_logger.debug(f"Python: {platform.python_version()}")
            dazzle_logger.debug(f"UNCtools available: {HAVE_UNCTOOLS}")
            dazzle_logger.debug(f"is_windows(): {is_windows()}")
        
        # Execute the appropriate action based on command
        global verification_exit_code
        verification_exit_code = 0  # Reset for each run
        result = execute_main_action(args, args.command)
        
        # For verification commands, return the calculated exit code
        if args.command == 'verify' and verification_exit_code > 0:
            return verification_exit_code
        
        return result
        
    except KeyboardInterrupt:
        print()
        logger.info("Operation interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        # Show traceback in verbose mode if args is available
        try:
            if hasattr(locals().get('args'), 'verbose') and args.verbose >= 3:
                import traceback
                logger.debug(traceback.format_exc())
        except Exception:
            # Fallback for debugging
            import traceback
            logger.debug(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())
