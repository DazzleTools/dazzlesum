# Command Reference

This document provides an overview for all dazzlesum commands and options (v1.3.6+).

## Command Structure

Dazzlesum uses a subcommand-based structure:

```
dazzlesum <command> [options] [directory]
```

## Commands

### `create` - Generate Checksums

Generate checksum files for directory contents.

```bash
dazzlesum create [options] [directory]
```

**Command-specific options:**
- `--mode {individual,monolithic,both}` - Checksum generation mode (default: individual)
- `--output FILE` - Output filename for monolithic mode
- `--include PATTERN` - Include files matching pattern (can be used multiple times)
- `--exclude PATTERN` - Exclude files matching pattern (can be used multiple times)
- `--resume` - Resume interrupted checksum generation
- `--log FILE` - Write detailed log to file
- `--summary` - Show summary progress instead of detailed output

**Examples:**
```bash
dazzlesum create -r                           # Generate individual checksums recursively
dazzlesum create -r --mode monolithic         # Generate single checksum file
dazzlesum create -r --mode both               # Generate both individual and monolithic
dazzlesum create -r --resume                  # Resume interrupted operation
```

### `verify` - Verify Checksums

Verify file integrity against existing checksums.

```bash
dazzlesum verify [options] [directory]
```

**Command-specific options:**
- `--show-all-verifications` - Show all verification results, not just failures
- `--checksum-file FILE` - Monolithic checksum file to verify against  
- `--squelch CATEGORIES` - Hide output categories: SUCCESS,NO_SHASUM,INFO,EXTRA,MISSING,FAILS,SUMMARY,EXTRA_SUMMARY
- `--show-all` - Show all results including successful verifications (legacy behavior)
- `--log FILE` - Write detailed log to file

**Examples:**
```bash
dazzlesum verify -r                           # Verify all checksums recursively
dazzlesum verify -r --show-all-verifications  # Show all results
dazzlesum verify --output checksums.sha256    # Verify against monolithic file
```

### `update` - Update Checksums

Update checksums for changed files.

```bash
dazzlesum update [options] [directory]
```

**Command-specific options:**
- `--include PATTERN` - Include files matching pattern (can be used multiple times)
- `--exclude PATTERN` - Exclude files matching pattern (can be used multiple times)
- `--log FILE` - Write detailed log to file

**Examples:**
```bash
dazzlesum update -r                           # Update all changed files
dazzlesum update -r --include "*.txt"         # Update only text files
```

### `manage` - Manage Checksum Files

Backup, remove, restore, or list checksum files.

```bash
dazzlesum manage [options] [directory] {backup,remove,restore,list}
```

**Command-specific options:**
- `--backup-dir DIR` - Backup directory (required for backup/restore)
- `--dry-run` - Show what would be done without making changes

**Examples:**
```bash
dazzlesum manage -r backup --backup-dir ./backup  # Backup all .shasum files
dazzlesum manage -r list                          # List all .shasum files
dazzlesum manage -r remove --dry-run              # Preview removal
dazzlesum manage -r restore --backup-dir ./backup # Restore from backup
```

## Help Commands

### `mode` - Mode Parameter Help

Shows detailed help for the `--mode` parameter with examples and explanations.

```bash
dazzlesum mode
```

### `examples` - Usage Examples

Shows comprehensive usage examples for all commands and common workflows.

```bash
dazzlesum examples
```

### `shadow` - Shadow Directory Help

Shows detailed help for shadow directory functionality.

```bash
dazzlesum shadow
```

### `verbosity` - Verbosity Levels Help

Shows detailed help for all 11 verbosity levels (-6 to +4) with examples and explanations.

```bash
dazzlesum verbosity
```

## Global Options

These options are available for all commands:

| Option | Description |
|--------|-------------|
| `directory` | Directory to process (default: current directory) |
| `-r`, `--recursive` | Process directories recursively |
| `-v`, `--verbose` | Increase verbosity (can be used multiple times: -v, -vv, -vvv, -vvvv) |
| `-q`, `--quiet` | Decrease verbosity (can be used multiple times: -q, -qq, -qqq, -qqqq, -qqqqq) |
| `--verbosity LEVEL` | Set verbosity level directly (-6 to +4, overrides -q/-v) |
| `--algorithm {md5,sha1,sha256,sha512}` | Hash algorithm (default: sha256) |
| `--shadow-dir DIR` | Store checksums in parallel shadow directory |
| `--follow-symlinks` | Follow symbolic links and junctions |
| `--line-endings {auto,unix,windows,preserve}` | Line ending handling strategy |
| `--no-color` | Disable colored output |
| `--show-log-types` | Show log type prefixes (INFO, ERROR, WARNING) |
| `--force-python` | Force Python implementation (skip native tools) |
| `-y`, `--yes` | Answer yes to all prompts |
| `--help` | Show help message and exit |
| `--version` | Show program version and exit |

## Verbosity Control

Dazzlesum provides 11 verbosity levels (-6 to +4) for precise output control:

### Quick Reference

| Level | Flags | Description |
|-------|-------|-------------|
| -6 | `-qqqqqq` | Silent mode - exit codes only (CI/CD) |
| -5 | `-qqqqq` | Grand totals only |
| -4 | `-qqqq` | Status lines for FAIL/MISSING directories only |
| -3 | `-qqq` | Show FAIL + status lines |
| -2 | `-qq` | Show MISSING + FAIL + status lines |
| -1 | `-q` | Show EXTRA + MISSING + FAIL (compressed EXTRA output) |
| 0 | (default) | Smart problem reporting + "No .shasum" messages |
| +1 | `-v` | Show everything including SUCCESS directories |
| +2 | `-vv` | Show file-by-file processing details |
| +3 | `-vvv` | Show debug information |
| +4 | `-vvvv` | Show all internal operations |

### Examples

```bash
# Ultra quiet - only directories with problems
dazzlesum verify -r -qqqq

# Quiet - hide EXTRA files, show other problems  
dazzlesum verify -r -qq

# Verbose - show all results including SUCCESS
dazzlesum verify -r -v

# Direct level setting
dazzlesum verify -r --verbosity=-3

# Arithmetic: -q -v = 0 (default level)
dazzlesum verify -r -q -v

# Silent mode for CI/CD
dazzlesum verify -r -qqqqqq
```

### Environment Variables

- `DAZZLESUM_VERBOSITY=-1` - Set default verbosity level
- `DAZZLESUM_SHOW_LOG_TYPES=1` - Force log type prefixes to show

### Fine-Grained Control

Use `--squelch` to manually override specific categories:

```bash
# Hide SUCCESS and EXTRA categories
dazzlesum verify -r --squelch SUCCESS,EXTRA

# Hide status lines for EXTRA-only directories
dazzlesum verify -r --squelch EXTRA_SUMMARY
```

## File Filtering

Both `create` and `update` commands support file filtering:

```bash
# Include only specific patterns
dazzlesum create -r --include "*.txt" --include "*.doc"

# Exclude specific patterns  
dazzlesum create -r --exclude "*.tmp" --exclude "*.log"

# Combine include and exclude
dazzlesum create -r --include "*.py" --exclude "*__pycache__*"
```

## Shadow Directory Usage

Shadow directories keep source directories clean by storing all checksum files in a parallel structure:

```bash
# Generate in shadow directory
dazzlesum create -r --shadow-dir ./checksums

# Verify from shadow directory
dazzlesum verify -r --shadow-dir ./checksums

# Both modes in shadow directory
dazzlesum create -r --mode both --shadow-dir ./verification
```

## Monolithic File Usage

Monolithic files contain all checksums in a single file with relative paths:

```bash
# Generate monolithic file
dazzlesum create -r --mode monolithic

# Custom monolithic filename
dazzlesum create -r --mode monolithic --output my-checksums.sha256

# Verify against monolithic file
dazzlesum verify --checksum-file checksums.sha256 /target/directory
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 130 | Interrupted by user (Ctrl+C) |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DAZZLESUM_VERBOSITY` | Set default verbosity level (-6 to +4) |
| `DAZZLESUM_SHOW_LOG_TYPES` | Force log type prefixes to show (1, true, yes) |

Examples:
```bash
# Set default to quiet mode
export DAZZLESUM_VERBOSITY=-2

# Always show log type prefixes
export DAZZLESUM_SHOW_LOG_TYPES=1
```

## File Patterns

File patterns support standard glob syntax:

- `*` - Match any characters
- `?` - Match single character  
- `[abc]` - Match any character in brackets
- `**` - Match directories recursively

Examples:
- `*.txt` - All text files
- `**/*.py` - All Python files recursively  
- `test_*.py` - Test files starting with "test_"
- `*.{jpg,png}` - Image files (jpg or png)
