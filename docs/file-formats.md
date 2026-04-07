# File Formats

This document describes the file formats used by dazzlesum for storing checksums.

## .shasum File Format

Dazzlesum generates `.shasum` files that are compatible with standard checksum tools while adding extra metadata.

### Individual .shasum Format

Each directory gets its own `.shasum` file containing checksums for files in that directory only.

```
# Dazzle checksum tool v1.3.6 - sha256 - 2025-06-29T09:00:00Z
abc123def456789012345678901234567890123456789012345678901234567890  file1.txt
789012fed345678901234567890123456789012345678901234567890123456789  file2.doc
fed456abc789012345678901234567890123456789012345678901234567890123  script.py
# End of checksums
```

### Monolithic Format

A single file containing checksums for an entire directory tree with relative paths.

```
# Dazzle monolithic checksum file v1.3.6 - sha256 - 2025-06-29T09:00:00Z
# Root directory: /path/to/project
abc123def456789012345678901234567890123456789012345678901234567890  folder1/file1.txt
789012fed345678901234567890123456789012345678901234567890123456789  folder1/file2.doc
fed456abc789012345678901234567890123456789012345678901234567890123  folder2/subfolder/file3.py
456789abc123def456789012345678901234567890123456789012345678901234  README.md
# End of checksums
```

## Header Information

All checksum files include a header with:
- Tool name and version
- Hash algorithm used
- Generation timestamp (ISO 8601 format)
- Root directory (monolithic files only)

## Format Compatibility

### Standard Tool Compatibility

Dazzlesum files are compatible with standard tools:

```bash
# Verify with sha256sum (Linux/macOS)
sha256sum -c .shasum

# Verify with certutil (Windows)
certutil -hashfile filename SHA256

# Verify with shasum (macOS)
shasum -a 256 -c .shasum
```

### Line Ending Handling

- **Unix/Linux/macOS**: LF (`\n`)
- **Windows**: CRLF (`\r\n`) when using `--line-endings windows`
- **Auto**: Detects and preserves existing line endings

## Metadata Files

### State File (.dazzle-state.json)

Dazzlesum maintains a state file for incremental operations:

```json
{
  "version": "1.1.0",
  "algorithm": "sha256",
  "last_update": "2025-06-27T09:00:00Z",
  "files": {
    "file1.txt": {
      "size": 1024,
      "mtime": 1703635200.123,
      "checksum": "abc123def456..."
    },
    "file2.doc": {
      "size": 2048,
      "mtime": 1703635300.456,
      "checksum": "789012fed345..."
    }
  },
  "directories": {
    "subfolder": {
      "processed": true,
      "file_count": 5,
      "last_update": "2025-06-27T09:00:00Z"
    }
  }
}
```

## Backup Directory Structure

When using `--manage backup`, dazzlesum creates a parallel directory structure:

```
Original Structure:
/project/
├── .shasum
├── folder1/
│   ├── .shasum
│   └── file1.txt
└── folder2/
    ├── .shasum
    └── file2.txt

Backup Structure:
/backup/
├── .shasum
├── folder1/
│   └── .shasum
└── folder2/
    └── .shasum
```

## Character Encoding

### File Names
- UTF-8 encoding for file paths in checksum files
- ASCII-safe escaping for problematic characters
- Cross-platform path normalization

### Content
- ASCII-only output for DOS compatibility
- No Unicode symbols in progress indicators
- Standard hexadecimal representation for checksums

## Checksum Algorithms

### Supported Algorithms

| Algorithm | Output Length | Example |
|-----------|---------------|---------|
| MD5 | 32 characters | `5d41402abc4b2a76b9719d911017c592` |
| SHA1 | 40 characters | `aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d` |
| SHA256 | 64 characters | `2cf24dba4f21d4288094e9b4c6c` |
| SHA512 | 128 characters | `9b71d224bd62f3785d96d46ad3ea` |

### Algorithm Selection

Default algorithm selection:
1. SHA256 (recommended default)
2. Can be overridden with `--algorithm` option
3. Detected from existing files during verification

## Error Handling

### Invalid Files
Files that cannot be read are noted in the output but don't stop processing:

```
# WARNING: Could not read file: permission-denied.txt
# ERROR: File not found: missing-file.txt
abc123def456...  valid-file.txt
```

### Encoding Issues
- Binary files are processed normally (content checksum)
- File names with special characters are UTF-8 encoded
- Invalid UTF-8 sequences are handled gracefully

## Migration and Portability

### Cross-Platform Considerations
- Path separators normalized (`/` vs `\`)
- Case sensitivity handling varies by filesystem
- Symbolic links and junctions handled appropriately

### Version Compatibility
- Forward compatible: newer versions can read older formats
- Backward compatible: basic formats work with older tools
- Version information in headers aids troubleshooting

## Custom Output Formats

### Custom Monolithic Names
```bash
# Custom filename
dazzlesum -r --mode monolithic --output project-v1.2.sha256

# Include timestamp
dazzlesum -r --mode monolithic --output "backup-$(date +%Y%m%d).sha256"
```

### Integration with Other Tools
Dazzlesum output can be processed by:
- Standard Unix checksum tools
- Build systems and CI/CD pipelines
- Backup verification scripts
- Custom validation tools