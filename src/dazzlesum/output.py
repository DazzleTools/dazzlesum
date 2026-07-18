"""DazzleLogger, ColorFormatter, verbosity/squelch configuration, logging setup.

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 101-236, 243-395, 411-484, 487-506, 4767-4805. Only import wiring and shared-state references
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
from . import state


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
        if state.color_formatter:
            # Only colorize if message doesn't already have color codes
            if '\033[' not in msg:
                msg = state.color_formatter.error(msg)
        logger.error(msg)

    def warning(self, msg):
        """Always show warnings."""
        if state.color_formatter:
            # Only colorize if message doesn't already have color codes
            if '\033[' not in msg:
                msg = state.color_formatter.warning(msg)
        logger.warning(msg)

    def info(self, msg, level=1):
        """Info messages with verbosity level."""
        # Check for silent mode first
        if self.verbosity_config and self.verbosity_config.is_silent():
            return  # No output at all in silent mode
            
        if self._should_log(level):
            if state.color_formatter and level == 0:
                # Only colorize level 0 info messages (important info)
                if '\033[' not in msg:
                    msg = state.color_formatter.info(msg)
            
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
                # Clamp to valid range (-6 = silent mode is the floor)
                level = max(-6, min(4, level))
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
            level = max(-6, min(4, args.verbosity))
            return cls(level=level, quiet_count=quiet_count, verbose_count=verbose_count)
        
        # Calculate level from -q/-v counts: base + verbose - quiet
        level = verbose_count - quiet_count
        level = max(-6, min(4, level))  # Clamp to valid range (-6 = silent floor)
        
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
            -3: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': False, 'SUMMARY': False, 'FORCE_SUMMARY': True},  # FAIL + info/status + grand total (cumulative: keeps -4's status lines)  # noqa: E241
            -2: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': False, 'FAILS': False, 'SUMMARY': False, 'FORCE_SUMMARY': True},  # MISSING + FAIL + info/status + grand total (cumulative)  # noqa: E241
            -1: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # EXTRA + MISSING + FAIL + info/status + grand total (EXTRA_SUMMARY stays a --squelch opt-in, not a level default)  # noqa: E241
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
    
    if state.verbosity_config:
        state.squelch_settings = state.verbosity_config.get_squelch_settings()
    else:
        # Fallback if verbosity_config not available
        # Note: True means squelched (hidden), False means shown
        VERBOSITY_SQUELCH_MAP = {
            -6: {'show_output': False},
            -5: {'INFO': True,  'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': True,  'SUMMARY': True},  # noqa: E241
            -4: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': True,  'SUMMARY': False, 'FORCE_SUMMARY': True},  # noqa: E241
            -3: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': True,  'FAILS': False, 'SUMMARY': False, 'FORCE_SUMMARY': True},  # noqa: E241
            -2: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': True,  'MISSING': False, 'FAILS': False, 'SUMMARY': False, 'FORCE_SUMMARY': True},  # noqa: E241
            -1: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': True,  'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # noqa: E241
             0: {'INFO': False, 'SUCCESS': True,  'NO_SHASUM': False, 'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},  # noqa: E241,E131
            +1: {'INFO': False, 'SUCCESS': False, 'NO_SHASUM': False, 'EXTRA': False, 'MISSING': False, 'FAILS': False, 'SUMMARY': False},
        }
        state.squelch_settings = VERBOSITY_SQUELCH_MAP.get(verbosity_level, VERBOSITY_SQUELCH_MAP[0])


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
