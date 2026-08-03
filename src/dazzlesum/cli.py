"""Argument parsers, help topics/actions, execute_* dispatch, and main().

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 3580-4006, 4009-4066, 4069-4136, 4139-4173, 4175-4385, 4388-4398, 4400-4447, 4449-4511, 4513-4545, 4548-4559, 4561-4600, 4602-4658, 4660-4725, 4727-4765, 4808-4856, 4858-4865, 4954-5147. Only import wiring and shared-state references
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

from ._version import __version__, get_package_version
from .constants import (logger, SUPPORTED_ALGORITHMS, DEFAULT_ALGORITHM,
                        SHASUM_FILENAME, HAVE_UNCTOOLS, is_windows)
from . import state
from .output import (DazzleLogger, ColorFormatter, VerbosityConfig,
                     initialize_squelch_from_verbosity, setup_logging)
from .manifest import ShasumManager, is_monolithic_file
from .engine import ChecksumGenerator


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
            'update': self._update_help,
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
    dazzlesum --detailed-help update    # Help for incremental updates
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

    def _update_help(self):
        print("""
UPDATE -- INCREMENTAL CHECKSUM UPDATES

    dazzlesum update -r [directory]     # Rehash only what changed

HOW IT WORKS:
    A per-machine state cache (.dazzle-cache.sqlite at the shadow root, or the
    target root without --shadow-dir) records (size, mtime) per file at last
    hash. A file is rehashed only when its current stat differs from the
    recorded state -- an EQUALITY check, so content synced in with an OLDER
    mtime (e.g. Resilio preserving origin timestamps) is still detected.

    .shasum manifests are rewritten ONLY when their content actually changed;
    unchanged manifests stay byte-identical (no git churn).

    The cache is a disposable accelerator, never part of the record. Do NOT
    sync or commit it -- stat state is only meaningful on the machine that
    recorded it. Delete it freely; --bootstrap rebuilds it.

SEMANTICS PER FILE:
    unchanged  stat matches cache        -> keep hash, no I/O
    changed    stat differs              -> rehash, update manifest entry
    added      not in manifest           -> hash, add entry
    deleted    in manifest, not on disk  -> drop entry (or --keep-missing)

KEY OPTIONS:
    --bootstrap hash|trust   Manifest entries with no cached state:
                             'hash' re-verifies them (default);
                             'trust' seeds the cache from current stats +
                             stored hashes without rehashing (fast bootstrap
                             against a freshly generated manifest)
    --dirs-from FILE|-       Update only listed folders (one per line,
                             relative to target; '-' = stdin). External
                             change detectors (git hooks, filesystem
                             watchers) feed suspect folders through this.
    --paranoid               Ignore cache, rehash everything
    --keep-missing           Keep entries for files no longer on disk

EXAMPLES:
    dazzlesum update -r --shadow-dir /checksums /data     # library sweep
    git diff --name-only | xargs -n1 dirname | sort -u | \\
        dazzlesum update -r --dirs-from - /data           # hint-driven

EXIT CODES:
    0 success, 1 fatal error, 2 completed with per-file failures
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
    
    # Version at main level. get_package_version() derives from
    # MAJOR/MINOR/PATCH and is always current; __version__ is the git-hook
    # build stamp, which can be stale on machines without the hooks installed.
    parser.add_argument('--version', '-V', action='version',
                       version=f'dazzlesum {get_package_version()}')
    
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
                                         description='Incrementally update checksums, rehashing only changed files')
    update_parser.add_argument('--include', action='append', metavar='PATTERN',
                              help='Include files matching pattern (can be used multiple times)')
    update_parser.add_argument('--exclude', action='append', metavar='PATTERN',
                              help='Exclude files matching pattern (can be used multiple times)')
    update_parser.add_argument('--log', metavar='FILE',
                              help='Write detailed log to file')
    update_parser.add_argument('--dirs-from', metavar='FILE',
                              help='Update only the folders listed in FILE (one per line, '
                                   "relative to the target directory; '-' reads stdin). "
                                   'Lets external change detectors (git hooks, USN watchers) '
                                   'nominate suspect folders.')
    update_parser.add_argument('--bootstrap', choices=['hash', 'trust'], default='hash',
                              help='How to treat manifest entries with no cached state: '
                                   "'hash' rehashes them (default, verifying); 'trust' seeds "
                                   'the cache from current file stats + stored hashes without '
                                   'rehashing (fast; only sound against a freshly generated manifest)')
    update_parser.add_argument('--paranoid', action='store_true',
                              help='Ignore the state cache and rehash every file '
                                   '(still applies add/remove semantics)')
    update_parser.add_argument('--keep-missing', action='store_true',
                              help='Keep manifest entries whose files no longer exist on disk')
    update_parser.add_argument('--threads', type=int, metavar='N', default=None,
                              help='Scanning worker threads (default: auto = min(8, CPU cores); '
                                   '1 = single-threaded walker). Cache and manifest writes '
                                   'always stay on one thread.')
    
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
    state.dazzle_logger.info(f"Mode: {mode_descriptions[args.mode]}", level=1)
    
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
            if state.dazzle_logger:
                state.dazzle_logger.info(f"Auto-detected monolithic checksum file: {detected_file}", level=1)
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
    
    # If --show-all is used WITHOUT explicit --squelch, override SUCCESS squelching
    if getattr(args, 'show_all', False) and not (hasattr(args, 'squelch') and args.squelch):
        if state.squelch_settings:
            state.squelch_settings['SUCCESS'] = False  # Show SUCCESS messages with --show-all
    
    # Apply explicit --squelch overrides (these take precedence over --show-all)
    if hasattr(args, 'squelch') and args.squelch and state.squelch_settings:
        squelch_categories = [cat.strip().upper() for cat in args.squelch.split(',')]
        for category in squelch_categories:
            # Set unconditionally: requiring the key to pre-exist in the
            # level's default dict silently no-op'd any category absent from
            # that level's defaults (e.g. --squelch EXTRA_SUMMARY).
            state.squelch_settings[category] = True
    
    # Process directory tree in verify mode
    generator.process_directory_tree(directory, recursive=args.recursive, verify_only=True)
    return 0


def execute_update_action(args, directory):
    """Execute update action (incremental: rehash only changed files)."""
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

    # Optional folder list from an external change-detection source
    dirs = None
    dirs_from = getattr(args, 'dirs_from', None)
    if dirs_from:
        try:
            if dirs_from == '-':
                # Read stdin as BYTES and decode utf-8-sig: PowerShell pipes
                # prepend a UTF-8 BOM (EF BB BF), and Python's default cp1252
                # stdin decoding mangles it into three junk chars that silently
                # corrupt the first folder name. utf-8-sig eats the BOM bytes.
                if hasattr(sys.stdin, 'buffer'):
                    raw = sys.stdin.buffer.read()
                    try:
                        text = raw.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        text = raw.decode(sys.stdin.encoding or 'utf-8',
                                          errors='replace')
                else:  # e.g. io.StringIO in tests
                    text = sys.stdin.read()
                lines = text.splitlines()
            else:
                # utf-8-sig: tolerate a BOM from Windows editors
                with open(dirs_from, 'r', encoding='utf-8-sig') as f:
                    lines = f.read().splitlines()
        except OSError as e:
            logger.error(f"Cannot read --dirs-from {dirs_from}: {e}")
            return 1
        # Per-line BOM strip as defense in depth (text-mode stdin sources)
        dirs = [line.strip().strip('\ufeff').strip() for line in lines]
        dirs = [line for line in dirs if line and not line.startswith('#')]
        if not dirs:
            logger.info("--dirs-from list is empty; nothing to update")
            return 0

    totals = generator.run_update(
        directory,
        recursive=args.recursive,
        dirs=dirs,
        bootstrap=getattr(args, 'bootstrap', 'hash'),
        paranoid=getattr(args, 'paranoid', False),
        keep_missing=getattr(args, 'keep_missing', False),
        threads=getattr(args, 'threads', None),
    )
    return 0 if totals and totals.get('failed', 0) == 0 else (1 if not totals else 2)


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


def main():
    """Main entry point with subcommand handling and context detection."""
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
                state.is_auto_detected_command = True
        elif len(sys.argv) == 1:
            # No arguments at all, detect command for current directory
            detected_command = detect_context_command('.')
            sys.argv.extend([detected_command, '.'])
            logger.info(f"Context-aware: executing '{detected_command} .'")
            state.is_auto_detected_command = True
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
        state.verbosity_config = VerbosityConfig.from_environment()
        state.verbosity_config = VerbosityConfig.from_args(args)
        
        # Initialize squelch settings from verbosity
        initialize_squelch_from_verbosity(state.verbosity_config.get_effective_level())
        
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
        effective_quiet = state.verbosity_config.get_effective_level() < 0 or (args.command == 'create' and args.summary)
        setup_logging(args.verbose, effective_quiet, show_log_types)
        
        state.dazzle_logger = DazzleLogger(
            verbosity=args.verbose,
            quiet=effective_quiet,
            summary_mode=(args.command == 'create' and args.summary),
            show_log_types=state.verbosity_config.should_show_log_types() if show_log_types is None else show_log_types
        )
        
        # Set verbosity config in logger
        state.dazzle_logger.set_verbosity_config(state.verbosity_config)
        
        # Initialize color formatter
        use_colors = None if not getattr(args, 'no_color', False) else False
        state.color_formatter = ColorFormatter(use_colors=use_colors)
        
        # Log startup info (skip in silent mode)
        if not (state.verbosity_config and state.verbosity_config.is_silent()):
            state.dazzle_logger.info(f"Dazzle Checksum Tool v{__version__}", level=0)
        
        if args.verbose >= 3:
            state.dazzle_logger.debug(f"Platform: {platform.platform()}")
            state.dazzle_logger.debug(f"Python: {platform.python_version()}")
            state.dazzle_logger.debug(f"UNCtools available: {HAVE_UNCTOOLS}")
            state.dazzle_logger.debug(f"is_windows(): {is_windows()}")
        
        # Execute the appropriate action based on command
        state.verification_exit_code = 0  # Reset for each run
        result = execute_main_action(args, args.command)
        
        # For verification commands, return the calculated exit code
        if args.command == 'verify' and state.verification_exit_code > 0:
            return state.verification_exit_code
        
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
