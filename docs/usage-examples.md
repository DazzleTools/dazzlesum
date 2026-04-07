# Usage Examples

This document provides practical examples for common dazzlesum use cases (v1.3.6+).

## Basic Workflow

### 1. Generate Checksums
```bash
# Start with current directory
dazzlesum create

# Process entire project recursively
dazzlesum create -r

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

On source system:
```bash
# Create backup of checksums
dazzlesum manage -r /data backup --backup-dir /checksums
```

On target system:
```bash
# Restore checksums and verify
dazzlesum manage -r /migrated-data restore --backup-dir /checksums
dazzlesum verify -r /migrated-data -v
```

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
```bash
# Generate checksums for media collection
dazzlesum -r /media/library --include "*.mp4,*.mkv,*.mp3,*.flac"

# Verify after moving files
dazzlesum -r /media/library --verify --include "*.mp4,*.mkv,*.mp3,*.flac"
```

### Project Synchronization
```bash
# Generate checksums excluding temporary files
dazzlesum -r /project --exclude "*.tmp,*.log,node_modules/**,__pycache__/**"

# Verify project integrity after sync
dazzlesum -r /project --verify --exclude "*.tmp,*.log,node_modules/**,__pycache__/**"
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

# Backup checksums before network operations
dazzlesum -r "//server/share" --manage backup --backup-dir ./network-checksums

# Use shadow directories for network shares to avoid network I/O for checksums
dazzlesum -r "//server/share" --shadow-dir ./local-checksums
```

## Troubleshooting

### Debug Mode
```bash
# Maximum verbosity for debugging
dazzlesum -r --verify -vvv

# Force Python implementation if native tools fail
dazzlesum -r --force-python
```

### Permission Issues
```bash
# Skip files with permission issues
dazzlesum -r --continue-on-error

# Dry run to see what would be processed
dazzlesum -r --manage remove --dry-run
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

# Backup to different drive
python dazzlesum.py -r C:\Data --manage backup --backup-dir D:\Checksums

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
dazzlesum -r . --shadow-dir "$SHADOW_DIR" --exclude ".git/**,.checksums/**"

# Verify integrity
if dazzlesum -r . --verify --shadow-dir "$SHADOW_DIR" --exclude ".git/**,.checksums/**" --quiet; then
    echo "✓ File integrity verified"
    exit 0
else
    echo "✗ File integrity check failed"
    exit 1
fi
```