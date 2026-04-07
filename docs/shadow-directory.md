# Shadow Directory Guide

Shadow directories provide a powerful way to keep your source directories clean while maintaining accurate checksum verification. Instead of placing `.shasum` files directly in your source directories, shadow directories store them in a parallel directory structure.

## Overview

Shadow directories solve the common problem of checksum file clutter. When you generate checksums for a directory tree, traditional tools create `.shasum` files alongside your data files. This can be problematic for:

- **Version Control**: You might not want checksum files in your Git repository
- **Clean Organization**: Keeping data files separate from metadata
- **Backup Operations**: Excluding checksum files from data backups
- **Distribution**: Sharing data without verification metadata

With shadow directories, your source directories remain pristine while all checksum files are stored in a parallel structure elsewhere.

## Basic Usage

### Enable Shadow Directory Mode

Use the `--shadow-dir` parameter to specify where checksum files should be stored:

```bash
# Store checksums in parallel shadow structure
dazzlesum -r --shadow-dir ./checksums /path/to/data

# Generate monolithic checksum in shadow directory
dazzlesum -r --mode monolithic --shadow-dir ./checksums /path/to/data

# Both individual and monolithic in shadow directory
dazzlesum -r --mode both --shadow-dir ./checksums /path/to/data
```

### Directory Structure Example

**Before (Traditional Mode):**
```
/data/
├── file1.txt
├── file2.txt
├── .shasum                    # Checksum file mixed with data
├── folder1/
│   ├── file3.txt
│   └── .shasum                # More checksum files mixed in
└── folder2/
    ├── file4.txt
    └── .shasum
```

**After (Shadow Directory Mode):**
```
/data/                         # Clean source directory
├── file1.txt
├── file2.txt
├── folder1/
│   └── file3.txt
└── folder2/
    └── file4.txt

/checksums/                    # Shadow directory structure
├── .shasum                    # Mirrors source structure
├── folder1/
│   └── .shasum
├── folder2/
│   └── .shasum
└── checksums.sha256          # Monolithic file (if enabled)
```

## Generation Modes with Shadow Directories

### Individual Mode (Default)

Creates `.shasum` files for each directory in the shadow structure:

```bash
dazzlesum -r --shadow-dir ./shadow /path/to/source
```

**Result:**
- Source directories remain completely clean
- Shadow directory mirrors source structure with `.shasum` files
- Each `.shasum` file contains checksums for files in corresponding source directory

### Monolithic Mode

Creates a single checksum file in the shadow root:

```bash
dazzlesum -r --mode monolithic --shadow-dir ./shadow /path/to/source
```

**Result:**
- Single `checksums.sha256` file in shadow root
- Contains checksums for all files in source tree
- Source directories remain completely clean

### Both Modes

Combines individual and monolithic approaches:

```bash
dazzlesum -r --mode both --shadow-dir ./shadow /path/to/source
```

**Result:**
- Individual `.shasum` files in shadow structure
- Plus monolithic `checksums.sha256` in shadow root
- Maximum verification flexibility

## Verification with Shadow Directories

When verifying checksums, specify the same shadow directory:

```bash
# Verify using shadow directory
dazzlesum -r --verify --shadow-dir ./shadow /path/to/source

# Verbose verification
dazzlesum -r --verify --shadow-dir ./shadow -v /path/to/source

# Show all verification results
dazzlesum -r --verify --shadow-dir ./shadow --show-all-verifications /path/to/source
```

### Verification Process

1. **Path Resolution**: Dazzlesum maps each source directory to its corresponding shadow location
2. **Checksum Lookup**: Reads checksum files from shadow structure
3. **File Verification**: Compares actual file checksums against shadow-stored values
4. **Results Reporting**: Reports verification status normally

## Advanced Features

### Custom Output Filenames

Specify custom monolithic filenames in shadow directories:

```bash
# Custom monolithic filename
dazzlesum -r --mode monolithic --output backup-checksums.sha256 --shadow-dir ./shadow /path/to/source
```

**Result:**
- Creates `./shadow/backup-checksums.sha256` instead of default name
- Useful for organizing multiple checksum sets

### Multiple Hash Algorithms

Use different algorithms with shadow directories:

```bash
# SHA512 checksums in shadow directory
dazzlesum -r --algorithm sha512 --shadow-dir ./shadow /path/to/source

# Multiple algorithms (separate shadow directories recommended)
dazzlesum -r --algorithm sha256 --shadow-dir ./shadow-sha256 /path/to/source
dazzlesum -r --algorithm sha512 --shadow-dir ./shadow-sha512 /path/to/source
```

### Verbosity and Logging

Shadow directory operations support all logging levels:

```bash
# Detailed output
dazzlesum -r --shadow-dir ./shadow -vv /path/to/source

# Show shadow paths being used
dazzlesum -r --shadow-dir ./shadow -v /path/to/source
```

## Use Cases and Workflows

### 1. Version Control Integration

Keep checksum metadata separate from tracked code:

```bash
# Generate checksums without polluting Git repository
dazzlesum -r --shadow-dir .checksums ./src

# Add shadow directory to .gitignore
echo ".checksums/" >> .gitignore

# Verify data integrity during CI/CD
dazzlesum -r --verify --shadow-dir .checksums ./src
```

### 2. Data Backup Workflows

Maintain data integrity without checksum file overhead:

```bash
# Create checksums before backup
dazzlesum -r --mode both --shadow-dir ./integrity-check ./data

# Backup only data (checksums stored separately)
rsync -av ./data/ backup-server:/backups/

# Verify after restoration
dazzlesum -r --verify --shadow-dir ./integrity-check ./restored-data
```

### 3. Content Distribution

Share data without verification metadata:

```bash
# Generate checksums for distribution verification
dazzlesum -r --mode monolithic --shadow-dir ./verification ./content

# Share content directory (clean)
tar czf content.tar.gz ./content

# Share verification checksums separately
tar czf verification.tar.gz ./verification

# Recipients can verify after extraction
dazzlesum -r --verify --shadow-dir ./verification ./content
```

### 4. Multi-Environment Development

Maintain checksums across development environments:

```bash
# Development environment
dazzlesum -r --shadow-dir ./dev-checksums ./project

# Staging environment  
dazzlesum -r --verify --shadow-dir ./dev-checksums ./project

# Production verification
dazzlesum -r --verify --shadow-dir ./prod-checksums ./deployed-project
```

## Best Practices

### 1. Shadow Directory Organization

**Recommended Structure:**
```
project/
├── data/                      # Source data (clean)
├── checksums/                 # Shadow directory
│   ├── .shasum
│   ├── subdirs/.shasum
│   └── checksums.sha256
└── scripts/
    └── verify-integrity.sh    # Verification script
```

### 2. Naming Conventions

Use descriptive shadow directory names:

```bash
# Algorithm-specific shadows
--shadow-dir ./checksums-sha256
--shadow-dir ./checksums-sha512

# Purpose-specific shadows  
--shadow-dir ./backup-verification
--shadow-dir ./distribution-checksums
--shadow-dir ./integrity-monitoring
```

### 3. Automation Scripts

Create verification scripts for repeatable workflows:

```bash
#!/bin/bash
# verify-integrity.sh

SOURCE_DIR="./data"
SHADOW_DIR="./checksums"

echo "Verifying data integrity..."
dazzlesum -r --verify --shadow-dir "$SHADOW_DIR" "$SOURCE_DIR"

if [ $? -eq 0 ]; then
    echo "✓ All files verified successfully"
else
    echo "✗ Verification failed - check output above"
    exit 1
fi
```

### 4. Performance Considerations

- **Large Trees**: Shadow directories add minimal overhead for large directory trees
- **Network Storage**: Place shadow directories on fast local storage for better performance
- **Concurrent Access**: Multiple shadow directories enable parallel verification workflows

## Troubleshooting

### Common Issues

**1. Permission Denied Creating Shadow Directory**
```bash
# Error: Permission denied creating shadow directory
# Solution: Ensure write permissions for shadow location
chmod 755 /path/to/shadow-parent
dazzlesum -r --shadow-dir /path/to/shadow-parent/checksums ./data
```

**2. Shadow Directory Not Found During Verification**
```bash
# Error: Shadow directory not found
# Solution: Verify shadow directory path exists
ls -la ./checksums
dazzlesum -r --verify --shadow-dir ./checksums ./data
```

**3. Mixed Shadow and Traditional Files**
```bash
# Issue: Some .shasum files in source, some in shadow
# Solution: Choose one approach consistently
# Remove traditional .shasum files:
find ./data -name ".shasum" -delete
# Or move them to shadow:
find ./data -name ".shasum" -exec mv {} ./checksums/ \;
```

### Debugging Tips

**1. Use Verbose Mode**
```bash
# See exactly which shadow paths are being used
dazzlesum -r --shadow-dir ./checksums -vv ./data
```

**2. Check Shadow Structure**
```bash
# Verify shadow directory structure matches expectations
find ./checksums -type f -name "*.sha*" -o -name ".shasum"
```

**3. Compare Paths**
```bash
# Compare source and shadow structures
diff <(find ./data -type d | sort) <(find ./checksums -type d | sort)
```

## Limitations

### Current Limitations

1. **Path Mapping**: Shadow directories must be accessible from the same system as source directories
2. **Relative Paths**: Shadow directories work best with absolute paths for complex setups
3. **Network Paths**: UNC paths and network mounts may require additional configuration

### Future Enhancements

The shadow directory system is designed for extensibility. Future versions may include:

- **Remote Shadow Storage**: Cloud-based shadow directories
- **Encrypted Shadows**: Encrypted checksum storage
- **Shadow Synchronization**: Multi-location shadow directory sync
- **Compression**: Compressed shadow directory archives

## Summary

Shadow directories provide a clean, organized approach to checksum management without cluttering your source data. They enable:

- **Clean Source Directories**: No checksum files mixed with data
- **Flexible Verification**: Full verification capability maintained
- **Better Organization**: Separate data from metadata
- **Workflow Integration**: Easy integration with backup, distribution, and development workflows

Use shadow directories when you need recursive folder checksum verification without the overhead of checksum files scattered throughout your directory structure.
