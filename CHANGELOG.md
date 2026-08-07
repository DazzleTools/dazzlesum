# Changelog

All notable changes to dazzlesum will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Future features and improvements will be listed here

## [1.5.1] - 2026-08-07

### Documentation
- The optional `[directory]` argument is now shown in examples across the README, usage guide, and command reference. It has always worked on every command -- `dazzlesum create -r /srv/archive`, a quoted path with spaces, a UNC share, or a relative path -- but every example used the current directory, so nothing advertised it
- Platform support moved to `docs/platforms.md` with a verification matrix (what is verified versus designed-for-but-unverified), the fallback tools probed per platform, junction and symlink policy, line-ending behavior, and the reasoning behind the Python-first hashing order. The platform badge now links there
- README corrected where it still described the pre-1.5.0 world: two separate blocks claimed "Dependencies: None (pure Python standard library)" plus optional unctools, which stopped being true when the DazzleLib stack became a hard dependency. The distinction that actually matters -- the pip package has dependencies, the standalone `dazzlesum.py` has none -- is now stated in both places
- License section names the copyright holder, as GPL-3.0 expects
- "Future Possible Features" no longer lists incremental updates, which shipped in v1.4.0
- CONTRIBUTING branch strategy corrected to the flow actually in use (feature branches from `main`, merged back with `--no-ff`); it described a `dev` branch that does not exist
- Ship-readiness checklist notes that the `-V` comparison in HV.1b requires a clean tree: the post-commit hook restamps `_version.py` after each commit, so in a dirty tree a source build and the committed artifact legitimately disagree

### Removed
- `--force-python`. Python `hashlib` became the engine for every algorithm the CLI offers in 1.5.0, so the flag had nothing left to force -- it set an already-empty native-tool selection and logged "Forcing Python implementation" for a run that was already pure Python. Honouring it could only *remove* capability: on a restricted-crypto (FIPS) build where `hashlib` cannot construct md5 or sha1, the native tool is the only working path, and suppressing it would turn a working run into a crash. **If a script passes the flag, delete it** -- the behavior it described is now unconditional. The native-tool machinery is retained for the restricted-crypto case

### Changed
- repokit-common subtree updated v0.2.7 -> v0.2.8 (pre-commit word-split path handling; hooks reach subtrees outside `scripts/`)

## [1.5.0] - 2026-08-02

Dazzlesum is now a proper Python package, and scanning is roughly seven times faster. Two long-standing silent failures were also found and fixed: native checksum-tool detection had been rejecting every tool it probed, and the optional UNC integration had been dead since a dependency dropped the APIs it relied on.

### Added
- `src/dazzlesum/` package structure: the 4,300-line monolith is now 12 focused modules (`cli`, `engine`, `hashing`, `manifest`, `output`, `patterns`, `results`, `shadow`, `state`, `statecache`, `walk`, `constants`), installable with `pip install dazzlesum` and runnable via `python -m dazzlesum`
- The single-file `dazzlesum.py` continues to work for portable, dependency-free use. It is now a **generated artifact**, stitched from the package at build time with the library objects it uses inlined under provenance comments, so it runs on the standard library alone. The test suite runs against both the package and the artifact, so the two cannot silently diverge
- `DazzleHashCalculator.calculate_hashes()`: returns hex digests keyed by algorithm as `dazzle_lib.HashResultDict`, the shape the DazzleLib stack produces and consumes

### Performance
**Full-library steady-state sweep: 32.83 min (v1.4.4) -> 4.45 min (7.4x)** on a 3.38M-file reference library.

- Junction and symlink policy moved to discovery: child directories are filtered from the parent scandir's cached reparse data at zero extra syscalls, instead of two lstat calls per directory at processing time
- Compiled string-level pattern matching: basename include/exclude patterns compile once into a single regex matched against entry names, eliminating per-file `Path` construction and per-pattern `Path.match` in the scan hot loop (profiled at ~330 us/file). Multi-component patterns keep exact `Path.match` semantics via fallback, with equivalence pinned by a corpus test
- Per-directory `Path.resolve()` eliminated: the old code made four `_getfinalpathname` syscalls per directory (~45s per 20K directories)
- Threaded scanning: `update --threads N`, default `min(16, 2 x cores)`. Workers perform scandir/stat/junction syscalls while the cache, hashing, manifest writes, and totals stay on the coordinating thread; `--threads 1` is the unchanged serial path. Scan workers are I/O-bound, so oversubscription keeps the disk queue full -- 4.45 min at 16 workers versus 8.82 at 8
- Visited-set redesign: physical walks use a string-key duplicate guard rather than resolve-and-stat inode marking -- four fewer syscalls per directory, and a syscall-free critical section under threading

### Fixed
- **Coverage hole**: inode-based visited marking stat'ed *through* junctions and recorded target inodes before the follow-policy check, so any junction pointing into a subtree caused the real subtree to be skipped as an already-visited loop. This was silent and deterministic in every scan since the feature existed -- a ~16K-file subtree was invisible to all previous scans of the reference library, including its committed baseline. Physical walks no longer consult inodes
- **Native checksum-tool detection** now reads both output streams and no longer trusts exit codes. Real tools disagree wildly here: certutil prints its usage text to stdout with return code 1, and fsum 2.51 prints its banner to stderr. The old stdout-only and `rc==0` checks rejected every native tool, silently forcing the pure-Python fallback on every machine tested
- **The optional unctools integration had been silently dead** since unctools 0.2.0 removed the APIs it soft-imported; the graceful fallback masked the ImportError, so the advertised UNC handling never ran. UNC-aware path handling now flows through dazzle-filekit, whose path-identity layer is unctools-backed by hard dependency, and a guard test asserts the layer is genuinely wired
- StateCache batches flush on a 5-second interval as well as by folder count, bounding cache loss from a hard kill in time as well as volume (previously a forced termination on a tree smaller than 200 directories forfeited the whole run's cache). Ctrl-C always flushed

### Changed
- `--version` / `-V` now reports the build provenance, not just the release number: `dazzlesum 1.5.0 (1.5.0_main_99-20260802-8387f603)` -- release, branch, build number, date, and commit. A pip install, a clone, and a working tree can all report the same release number while being different code, and the parenthetical is what tells them apart. The project phase is shown ahead of the version while a project is pre-stable (`BETA 0.7.5 (...)`), matching the convention used across the DazzleTools projects; output degrades to the bare version when no build stamp is present
- **Hashing engine is Python-first**: hashlib (in-process, OpenSSL-backed) handles every algorithm it supports, and native tools are reserved for algorithms it lacks. With detection fixed, native-first would have engaged a subprocess spawn per file (~75ms for certutil; a ~130-file tree took 16.7s versus 0.62s) *and* broken verification of existing manifests, since native tools hash raw bytes and bypass the line-ending normalization every existing manifest was built with. `--force-python` is unchanged
- dazzlesum now depends on the DazzleLib stack: `dazzle-lib>=0.6.7` and `dazzle-filekit>=0.3.2` are hard install dependencies (reuse over rewrite, no fallback shims). The single-file artifact remains dependency-free
- `.shasum` writes go through filekit `operations.atomic_write_text` -- the same tmp-sibling and `os.replace` idiom previously inlined, with byte-identical output
- Monolithic-file relative paths are computed via filekit `paths.compute_relative_path`, preserving the cross-drive fallback and warning
- Compat helpers `is_windows`, `safe_open`, and `file_exists` delegate to dazzle-filekit; `is_unc_path` joins the public surface
- Packaging reads the version from the standard-library-only `dazzlesum._version` submodule rather than importing the whole package, which would fail in isolated build environments

### Removed
- `normalize_path` from the public surface: a retired unctools-era compat name whose behavior was always the no-op fallback. Filekit's `normalize_cross_platform_path` serves the real use case, and hot paths deliberately do not normalize
- The hand-rolled `hooks/` directory, superseded by the repokit-common hook system in use since v1.4.2

### Documentation
- Ship-readiness checklist under `tests/checklists/`: artifact self-containment proven in a dependency-free virtualenv, real native-tool behavior, UNC layer, and regression spot-checks -- the verification a mocked suite structurally cannot perform
- Exit-codes reference now documents the full verify severity ladder (0-7 graded by verified percentage); the old table listed only 0, 1, and 130, leaving the rest undiscoverable to scripts
- README, installation guide, `requirements.txt`, and CONTRIBUTING corrected for the 1.5.0 reality: Python floor 3.9 (was claiming 3.7), real package dependencies (was claiming none), the Python-first engine, and `src/` as the development surface with `dazzlesum.py` as a generated artifact (was instructing "keep as single file")

## [1.4.5] - 2026-07-17

### Changed
- Python floor raised from 3.7 to 3.9, aligning with the DazzleLib stack (dazzle-lib, dazzle-filekit, dazzle-linklib, dazzle-preservelib, dazzle-tree-lib all require >=3.9) in preparation for the src/ refactor; 3.13 added to the CI matrix and classifiers; dead 3.7-conditional dev dependencies removed

## [1.4.4] - 2026-07-17

### Fixed
- Silent mode (-6 / `-qqqqqq`) was unreachable: verbosity clamped to -5 at all three parse sites while `is_silent()` tested `<= -6`, so "silent" runs still printed the banner and grand totals
- Silent mode returned exit code 0 regardless of verification failures: the aggregate exit code was computed as a side effect of *displaying* grand totals, which silent mode skipped; `finalize_exit_code()` now runs unconditionally (silent mode is exit-codes-only, not exit-code-less)
- Level -1 hid extras-only directory status lines, contradicting its documented "EXTRA + MISSING + FAIL" semantics (`EXTRA_SUMMARY` was baked into the level's defaults; it remains available as an explicit `--squelch` category)
- Directories whose only issues were all squelched still displayed when they had zero verified files (extras-only dirs paradoxically appeared at MORE-squelched levels)
- Verbosity disclosure is now cumulative: levels -3 and -2 keep -4's `FORCE_SUMMARY` status lines, so raising verbosity can no longer remove information
- `--squelch` categories absent from the active level's default squelch dict were silently ignored (e.g. `--squelch EXTRA_SUMMARY` no-op'd at most levels); explicit categories now always apply. Found by the v1.4.4 human test checklist.
- Test suite fully green for the first time since v1.3.6: the two remaining test failures were filter bugs counting the grand-totals `Files:` summary line (added in v1.3.6) as a per-directory status line

## [1.4.3] - 2026-07-17

### Performance
- StateCache writes are batched (commit every 200 folders) with `synchronous=OFF` and an in-memory journal -- the cache is a disposable accelerator, so per-folder journal fsyncs bought nothing and cost hours at library scale. Measured on the write path: 94 -> 9,945 folders/s (105x). A 2.5M-file library bootstrap that projected ~7.5 hours (12% CPU, 88% fsync-blocked) now completes in a fraction of that.
- Cache schema v2: folder paths are interned into an integer-keyed `folders` table instead of being repeated in every file row, shrinking the cache and keeping the `(folder_id, name)` primary-key b-tree small. Old-schema caches are dropped and rebuilt automatically (the cache is regenerable by design; no migration path needed).
- Steady-state fast path: a folder whose live files exactly match the cache (name set, size, mtime_ns, algorithm) skips both the manifest parse and the cache rewrite -- an unchanged sweep costs one `scandir` and one indexed SELECT per folder. Trade-off: externally edited manifests are not detected on this path; `--paranoid` (or `verify`) re-establishes truth.
- Progress logging every 5,000 directories during long updates.

### Documentation
- usage-examples.md: explained that `manage backup`/`restore` copy only the `.shasum` manifests (relative structure preserved, data untouched) and how that differs from shadow-dir workflows; fixed examples using comma-joined `--include`/`--exclude` lists (never supported -- repeat the flag per pattern) and the pre-subcommand `--manage`/`--verify` flag forms

## [1.4.2] - 2026-07-17

### Added
- `git-repokit-common` integrated as a subtree at `scripts/repokit-common/` (shared DazzleTools project tooling: `sync-versions.py`, hooks, `gh_issue_full.py`, and more); update with `git subtree pull --prefix=scripts/repokit-common repokit-common main --squash`
- `[tool.repokit-common]` section in `pyproject.toml` wiring `version-source` to `dazzlesum.py`

### Changed
- Version stamping now uses repokit-common's `sync-versions.py` via its git hooks (pre-commit/post-commit/pre-push); the `__version__` build string carries branch, build count, current date, and parent hash (the previous hand-rolled hook reused stale date/hash fields)
- Version components use the repokit component-per-line convention (`MAJOR = 1` ...) instead of the tuple form

### Removed
- Hand-rolled `scripts/install-hooks.sh` and `scripts/hooks/` (superseded by the subtree's hook system; `check_lint.sh`, `check_tests.sh`, and the dazzlesum-specific `check_dist_no_leak.py` remain)

## [1.4.1] - 2026-07-17

### Added
- `-V` short form for `--version`

### Fixed
- `--version` printed the static hook-stamped build string, which goes stale on machines without the git hooks installed (showed 1.3.6 while the package was 1.4.0); it now derives from MAJOR/MINOR/PATCH. Version-stamp correctness is the job of the git hooks / repokit tooling, not runtime code.

### Removed
- `setup.py`: fully superseded by `pyproject.toml` (dynamic version from `dazzlesum.get_package_version`); removing it eliminates the last duplicate version parser and duplicated metadata

### Changed
- README badge order: PyPI version and release date now lead, CI follows

## [1.4.0] - 2026-07-17

### Added
- Incremental update mode: `dazzlesum update` now rehashes only changed files instead of silently performing a full create (the `update_mode` parameter was previously dead code)
- Per-machine SQLite state cache (`.dazzle-cache.sqlite` at the shadow root, or target root without `--shadow-dir`) recording (size, mtime_ns) per file at last hash; disposable accelerator, never part of the checksum record -- do not sync or commit it
- Change detection by stat EQUALITY against recorded state (not "mtime newer"), so content synced in with older origin mtimes (e.g. Resilio Sync) is still detected
- `update --dirs-from FILE|-` to update only nominated folders, letting external change detectors (git hooks, filesystem watchers) drive incremental work
- `update --bootstrap {hash,trust}` for manifest trees with no cache: re-verify (default) or seed the cache from existing manifests without rehashing
- `update --paranoid` (ignore cache, rehash everything) and `update --keep-missing` (retain manifest entries for deleted files)
- Update statistics report: unchanged / rehashed / added / removed / manifests rewritten / failed
- `dazzlesum --detailed-help update` topic documenting incremental semantics
- Module-level `parse_shasum_file()` shared by verify and update paths
- PyPI publishing workflow (`.github/workflows/publish.yml`): building a GitHub Release triggers an automatic upload via trusted publishing (OIDC, no stored tokens); manual dispatch and local `twine upload` remain available
- `scripts/check_dist_no_leak.py`: refuses to publish any artifact containing `private/` paths or local state files (depth-proof component matching)
- README: documented the standalone no-install path (copy `dazzlesum.py`, run directly)

### Fixed
- `--exclude` patterns now prune directory TRAVERSAL, not just file matching: the walker previously descended into excluded directories (`.git`, `.private`, `.sync`, ...) and checksummed all their contents, because files inside an excluded directory don't themselves match the directory's pattern (v1.3.6 fixed this for the progress counter but not for the walk itself)
- Windows junction detection no longer spawns a `dir /AL` subprocess per NON-junction directory (~60ms per folder -- hours of pure process creation on large trees); detection is now a pure lstat reparse-point check
- Directories reached through a junction ancestor are no longer misclassified as junctions (the old `resolve() != path` heuristic flagged every such directory, silently skipping whole trees when links weren't followed)
- `--dirs-from` input is now BOM-tolerant: PowerShell pipes prepend a UTF-8 BOM to stdin (and Windows editors to files), which silently corrupted the first folder name into a nonexistent path

### Changed
- `.shasum` writes are now atomic (temp file + rename), so an interrupted run never leaves a truncated manifest
- Update rewrites a `.shasum` file only when its checksum content actually changed; unchanged manifests stay byte-identical (no version-control churn)
- External edits to a manifest (stored hash disagreeing with the state cache) trigger a rehash to re-establish truth

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
- Added UTF-8 encoding with replace error handling to all 7 subprocess calls (prevents crashes on non-ASCII filenames)
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