# Changelog

All notable changes to dazzlesum will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Future features and improvements will be listed here

### Changed
- Future changes will be listed here

## [1.3.6] - 2026-04-07

### Added
- verify command now supports --include/--exclude flags (parity with create command)
- Progress reporting during directory counting stage (updates every 100 dirs for large trees)
- "Scanning directory tree..." status with final dir/file count summary
- Throughput metric (files/sec) in grand totals processing summary

### Fixed
- Directory counting stage now respects --exclude patterns (excluded dirs were inflating progress totals)
- Fixed shadow-dir verify resolving filenames against source root instead of current directory (100% false "missing" failures)
- Replaced Unicode box-drawing and progress bar characters with ASCII equivalents for Windows codepage compatibility
- Removed stale .repokit.json and root-level install-hooks.sh (replaced by scripts/install-hooks.sh)

## [1.3.5] - 2025-06-29

### Fixed
- Fixed exit code calculation bug where individual directory codes overrode aggregate results
- Resolved flake8 complexity warnings in verification result printing (_print_verification_results method)
- Fixed CI/CD alignment issues between local lint checks and GitHub Actions (added --count flag)
- Fixed Unicode encoding issue in setup.py for Windows installations (explicit UTF-8 encoding)
- Corrected test assertions for aggregate-based exit code behavior in test_squelch_and_grand_totals.py
- Fixed pre-push hook to use same test runner as CI/CD pipeline

### Technical
- Exit code determination now based on aggregate verification results across all directories
- Pre-push hooks enhanced with tiered validation: strict mode for main branch, standard for others
- Local lint checks now match CI behavior with --count flag for consistent error reporting
- All unit tests pass in both local and CI environments with proper aggregate exit code logic

## [1.3.4] - 2025-06-29

### Added
- Interactive monolithic file overwrite handling with detailed file information display
- Helpful user guidance for monolithic mode operations
- Auto-overwrite support with --yes flag for automation and scripting
- Cross-platform atomic file replacement (Windows vs Unix compatibility)

### Changed
- Enhanced monolithic mode user experience with interactive guidance prompts
- Improved error messages and user guidance for common scenarios
- Fixed auto-detected verify mode to show SUCCESS summaries appropriately

### Fixed
- Fixed Windows-specific [WinError 183] file overwrite errors with atomic replacement
- Resolved missing yes_to_all parameter in execute_create_action()
- Corrected monolithic temp file inclusion in checksum generation
- Fixed argument filtering issues in interactive prompts
- Updated CLI tests to reflect new interactive prompt behavior

### Technical
- Removed 187 lines of dead code including duplicate command handlers
- Eliminated orphaned dispatch_command() and handle_*_command() functions
- Simplified execution flow: main() → execute_main_action() → execute_*_action()
- Reduced codebase by ~4% with no functionality loss
- All tests pass with improved coverage

## [1.3.3] - 2025-06-29

### Added
- Smart static versioning system with git hook automation (format: MAJOR.MINOR.PATCH_BuildNumber-YYYYMMDD-CommitHash)
- Modern Python packaging with pyproject.toml for PEP 517/518 compliance
- 11-level verbosity system (-6 to +4) replacing binary quiet/verbose flags
- Intelligent squelch system with configurable output categories (SUCCESS, NO_SHASUM, etc.)
- Context-aware CLI with pure subparser architecture (create, verify, update, manage commands)
- Complete shadow directory support (Phase 1+2) for keeping source directories clean
- Enhanced verification with percentage-based status system (e.g., "99%/1% ALMOST PERFECT")
- Grand totals system with cross-directory statistics aggregation for recursive operations
- Auto-detection for monolithic checksum files with smart behavior selection
- Resume functionality for interrupted operations

### Changed
- Replaced binary --quiet/--verbose with 11-level spectrum system with arithmetic calculation
- Progressive information disclosure design with smart defaults to reduce noise
- Enhanced help system with better topic coverage and dedicated help commands
- Improved output formatting with compact mode for large datasets
- Semantic clarity improvements: --output renamed to --checksum-file in verify command
- Clean output mode with optional log type prefixes
- Prettified color system with cross-platform ANSI support

### Fixed
- Fixed progress bar scrolling and accurate counting issues
- Resolved Python 3.7 compatibility by removing walrus operator usage
- Corrected verification workflow for clone scenarios
- Enhanced error handling and graceful degradation
- Fixed CI/CD integration with automatic version injection

### Technical
- Modular architecture with proper separation of concerns
- VerbosityConfig class for centralized verbosity management
- GrandTotals class for cross-directory statistics tracking
- ColorFormatter with cross-platform support
- Test suite with 45+ tests and full CI/CD integration
- Documentation overhaul with 400+ lines of new shadow directory guide
- Eliminates pip install deprecation warnings with future-proof packaging
- Standalone files maintain complete version information without git dependencies

## [1.1.0] - 2025-06-27

### Added
- Enhanced logging system with verbosity levels (`-v`, `-vv`, `-vvv`)
- .shasum management operations (backup/remove/restore/list)
- Dual-mode generation (individual/monolithic/both)
- Smart monolithic detection and recursive verification suggestions
- DOS compatibility improvements
- Problems-only verification output (shows only failed, missing, or extra files by default)
- Visual directory separation in output
- Progress tracking for large operations
- Comprehensive statistics for verification operations

### Changed
- Verification now shows only problems by default (use `--show-all-verifications` for full output)
- Improved cross-platform compatibility
- Enhanced error handling and user feedback
- Better integration with native system tools (certutil, shasum, fsum)

### Fixed
- Line ending normalization for consistent checksums across platforms
- Symlink/junction loop detection
- Memory efficiency improvements for large directory trees

## [1.0.0] - Initial Release

### Added
- Cross-platform file checksum generation
- Support for multiple hash algorithms (MD5, SHA1, SHA256, SHA512)
- Individual and monolithic checksum file modes
- Recursive directory processing
- Checksum verification functionality
- Incremental update capability
- File filtering with include/exclude patterns
- Native tool integration with Python fallback
- FIFO directory processing for memory efficiency
- Compatible output format with standard tools

### Features
- Windows, macOS, Linux, and BSD support
- DOS shell compatibility
- UNC path handling (with optional unctools package)
- Symlink and junction detection
- Progress tracking and verbose output options
- Configurable line ending strategies
- Backup and restore functionality for checksum files

---

## Future Planned Features

### Shadow Directory Support
Parallel verification directories for clean source verification without "dirtying" source directories with `.shasum` files.

### Incremental Updates
Smart update detection that only processes changed files while maintaining consistency.

### Compression Support
Archive support for checksum collections to reduce storage overhead.

### Remote Storage Integration
Potential cloud backup integration for checksum files (under consideration).

---

## Migration Notes

### From 1.3.4 to 1.3.5
- No breaking changes
- Fixed exit code calculation to use aggregate results instead of individual directory codes
- Improved CI/CD alignment between local pre-push hooks and GitHub Actions
- Fixed Unicode encoding issues for Windows pip installations
- All 77 unit tests now passing with corrected exit code logic

### From 1.3.3 to 1.3.4
- No breaking changes
- Enhanced monolithic file handling with interactive prompts
- Use --yes flag for automation to auto-overwrite existing files
- Improved user experience with better guidance messages

### From 1.3.x to 1.3.3
- Minor breaking changes: --output parameter renamed to --checksum-file in verify command
- Removed default exclusion of *.tmp and *.log files (now configurable)
- New 11-level verbosity system available (-6 to +4) replaces simple -q/-v flags
- Enhanced squelch filtering options with category-based control
- Shadow directory support available for cleaner source directory management

### From 1.0.x to 1.1.x
- No breaking changes
- New verbosity options available
- Enhanced verification output (problems-only by default)
- New management operations for `.shasum` files

### License Change Notice
Starting with version 1.1.0, dazzlesum is licensed under GPL-3.0. Previous versions were under MIT license.