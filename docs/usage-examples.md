# Usage Examples

This document provides practical examples for common dazzlesum use cases.

## Choosing what to process

Every command accepts an optional directory argument, so you rarely need to `cd` anywhere first. Omit it to work on the current directory:

```bash
dazzlesum create -r                          # current directory
dazzlesum create -r /srv/archive             # absolute path
dazzlesum create -r ../sibling-project       # relative path
dazzlesum create -r "D:\Media\Photos 2026"   # quote paths containing spaces
dazzlesum create -r \\server\share\backups   # UNC network share
```

The same argument works for `verify`, `update`, and `manage`. Two related options are worth knowing:

- `--shadow-dir DIR` writes manifests somewhere other than the folder being scanned, leaving the source tree untouched.
- `--dirs-from FILE` (on `update`) processes only the directories listed in a file, which is how you drive a scoped update from a change detector such as a git hook or filesystem watcher.

## Basic Workflow

### 1. Generate Checksums
```bash
# Start with current directory
dazzlesum create

# Process entire project recursively
dazzlesum create -r

# Process a folder you are not currently in
dazzlesum create -r /srv/archive

# Use SHA512 for extra security
dazzlesum create -r --algorithm sha512
```

### 2. Verify Integrity
```bash
# Verify all checksums
dazzlesum verify -r

# Verbose verification to see what's happening
dazzlesum verify -r -v

# Silent mode for automation (11 verbosity levels: -6 to +4)
dazzlesum verify -r -qqqqqq

# Filter specific output types
dazzlesum verify -r --squelch SUCCESS,NO_SHASUM

# Show all files, not just problems
dazzlesum verify -r --show-all-verifications
```

### 3. Update Changed Files
```bash
# Update only changed files
dazzlesum update -r

# Update with verbose output
dazzlesum update -r -vv
```

## Integration Examples

### Backup Verification

Before creating a backup:
```bash
# Generate checksums for source data
dazzlesum create -r /important/data --mode monolithic --output backup-checksums.sha256
```

After restoring from backup:
```bash
# Verify restored data matches original
dazzlesum verify -r /restored/data --output backup-checksums.sha256
```

### CI/CD Pipeline

Generate checksums for build artifacts:
```bash
# Generate checksums for release artifacts
dazzlesum create -r ./dist --mode monolithic --output release-checksums.sha256
```

Verify deployment:
```bash
# Verify deployed files match build
dazzlesum verify -r ./deployed --output release-checksums.sha256
```

### Data Migration

`manage backup` copies **only the `.shasum` manifest files** out of a data tree, never the data itself. Each manifest is copied to the same relative position under `--backup-dir`, producing a parallel tree of just the verification metadata:

```
/data/.shasum              ->  /checksums/.shasum
/data/photos/.shasum       ->  /checksums/photos/.shasum
/data/photos/2024/.shasum  ->  /checksums/photos/2024/.shasum
```

The source tree is untouched (add `--dry-run` to preview). Because manifests are tiny compared to the data, this gives you a portable snapshot of the integrity layer that travels separately from the data.

On source system:
```bash
# Snapshot the checksum manifests (data files are not copied)
dazzlesum manage -r /data backup --backup-dir /checksums
```

On target system, `restore` is the mirror image: it re-plants each backed-up manifest at the same relative position under the target root, so the checksums re-attach to the migrated data wherever it now lives:
```bash
# Restore manifests onto the migrated tree, then verify the data against them
dazzlesum manage -r /migrated-data restore --backup-dir /checksums
dazzlesum verify -r /migrated-data -v
```

Note: `manage backup` finds manifests stored **in-tree** (the default layout). If you use `--shadow-dir`, your manifests already live in a separate parallel tree -- that shadow tree *is* your checksum layer, and you can back it up directly with ordinary tools (or version it in git).

### Shadow Directory Workflows

Keep source directories clean during verification:

```bash
# Generate checksums without cluttering source directory
dazzlesum create -r /important/data --shadow-dir ./verification-data

# Verify using shadow directory
dazzlesum verify -r /important/data --shadow-dir ./verification-data

# Both individual and monolithic in shadow directory
dazzlesum create -r /project --mode both --shadow-dir ./checksums
```

## File Organization

### Media Library Management

`--include` and `--exclude` take ONE pattern each; repeat the flag for multiple patterns (comma-joined lists inside a single argument are not split and will not match anything):

```bash
# Generate checksums for media collection
dazzlesum create -r /media/library --include "*.mp4" --include "*.mkv" --include "*.mp3" --include "*.flac"

# Verify after moving files
dazzlesum verify -r /media/library --include "*.mp4" --include "*.mkv" --include "*.mp3" --include "*.flac"
```

### Project Synchronization
```bash
# Generate checksums excluding temporary files and dependency dirs
# (a bare directory name like "node_modules" excludes the whole subtree)
dazzlesum create -r /project --exclude "*.tmp" --exclude "*.log" --exclude "node_modules" --exclude "__pycache__"

# Verify project integrity after sync (same patterns)
dazzlesum verify -r /project --exclude "*.tmp" --exclude "*.log" --exclude "node_modules" --exclude "__pycache__"
```

### Version Control Integration with Shadow Directories
```bash
# Keep Git repository clean by using shadow directories
dazzlesum -r ./src --shadow-dir ./.checksums

# Add shadow directory to .gitignore
echo ".checksums/" >> .gitignore

# Verify code integrity during CI/CD
dazzlesum -r ./src --verify --shadow-dir ./.checksums -v

# Generate release checksums in shadow directory
dazzlesum -r ./dist --mode monolithic --shadow-dir ./release-verification
```

## Performance Optimization

### Large Directory Trees
```bash
# Use quiet mode for large operations
dazzlesum -r /huge/directory --quiet

# Summary mode for progress tracking
dazzlesum -r /huge/directory --summary
```

### Network Storage
```bash
# Process network shares efficiently
dazzlesum -r "//server/share" --algorithm sha256

# Backup checksum manifests before network operations (copies only .shasum files)
dazzlesum manage -r "//server/share" backup --backup-dir ./network-checksums

# Use shadow directories for network shares to avoid network I/O for checksums
dazzlesum -r "//server/share" --shadow-dir ./local-checksums
```

## Troubleshooting

### Debug Mode
```bash
# Maximum verbosity for debugging
dazzlesum verify -r -vvv

# Show which hashing engine was selected (tool-selection line needs -vvvv)
dazzlesum create -r -vvvv
```

Hashing runs in-process through Python `hashlib`, so there is no native-tool
process to fall back from. The `--force-python` flag was removed in 1.5.1 --
delete it from any script that passes it; what it described is now the default.
See [platforms.md](platforms.md#hashing-engine).

### Permission Issues
```bash
# Skip files with permission issues
dazzlesum -r --continue-on-error

# Dry run to see what would be processed
dazzlesum manage -r . remove --dry-run
```

## Cross-Platform Usage

### Windows Command Prompt
```cmd
REM Basic usage in Windows
dazzlesum.py -r C:\MyData

REM Verify with UNC paths
dazzlesum.py -r \\server\share --verify

REM Use shadow directories on Windows
dazzlesum.py -r C:\ImportantData --shadow-dir C:\Checksums
```

### PowerShell
```powershell
# Use with PowerShell
python dazzlesum.py -r C:\Projects --mode both

# Backup checksum manifests to a different drive (copies only .shasum files)
python dazzlesum.py manage -r C:\Data backup --backup-dir D:\Checksums

# Shadow directories with PowerShell
python dazzlesum.py -r C:\ProjectData --shadow-dir D:\ProjectChecksums --mode both
```

### Unix/Linux
```bash
# Standard Unix usage
./dazzlesum.py -r ~/documents

# System-wide verification
sudo dazzlesum -r /etc --verify --exclude "*.tmp"
```

## Automation Scripts

### Batch Verification Script
```bash
#!/bin/bash
# verify-backups.sh

BACKUP_DIRS=("/backup/daily" "/backup/weekly" "/backup/monthly")

for dir in "${BACKUP_DIRS[@]}"; do
    echo "Verifying $dir..."
    if dazzlesum -r "$dir" --verify --quiet; then
        echo "✓ $dir verification passed"
    else
        echo "✗ $dir verification failed"
        exit 1
    fi
done
```

### Windows Batch File
```bat
@echo off
REM backup-with-checksums.bat

echo Generating checksums...
python dazzlesum.py -r C:\ImportantData --mode monolithic --output checksums.sha256

echo Copying files...
robocopy C:\ImportantData D:\Backup\Data /E /COPY:DAT

echo Verifying backup...
python dazzlesum.py -r D:\Backup\Data --verify --output checksums.sha256

echo Backup and verification complete.
```

### Shadow Directory Automation

```bash
#!/bin/bash
# clean-verification.sh - Keep source directories clean while verifying integrity

SOURCE_DIR="${1:-./data}"
SHADOW_DIR="${2:-./.checksums}"

echo "Generating checksums for $SOURCE_DIR using shadow directory $SHADOW_DIR..."
dazzlesum -r "$SOURCE_DIR" --mode both --shadow-dir "$SHADOW_DIR"

echo "Verifying integrity using shadow directory..."
if dazzlesum -r "$SOURCE_DIR" --verify --shadow-dir "$SHADOW_DIR" --quiet; then
    echo "✓ All files verified successfully (source directory remains clean)"
else
    echo "✗ Verification failed - check shadow directory: $SHADOW_DIR"
    exit 1
fi
```

### Git Pre-commit Hook with Shadow Directories

```bash
#!/bin/bash
# .git/hooks/pre-commit - Verify integrity before commits

SHADOW_DIR="./.checksums"

# Generate checksums for staged files using shadow directory
echo "Verifying staged files integrity..."
dazzlesum create -r . --shadow-dir "$SHADOW_DIR" --exclude ".git" --exclude ".checksums"

# Verify integrity
if dazzlesum verify -r . --shadow-dir "$SHADOW_DIR" --exclude ".git" --exclude ".checksums" -q; then
    echo "✓ File integrity verified"
    exit 0
else
    echo "✗ File integrity check failed"
    exit 1
fi
```