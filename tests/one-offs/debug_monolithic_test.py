#!/usr/bin/env python3
"""
Debug script for monolithic verification test failures.

Created: 2025-06-29
Purpose: Identify why monolithic tests were finding extra files
Result: Discovered .tmp files were being included in checksums
Status: Can be used to debug similar monolithic checksum issues

Usage:
    python3 debug_monolithic_test.py
    
Expected Output:
    - Shows content of generated monolithic file
    - Lists which files are considered "missing" during verification
    - Reveals if temporary files are being included unexpectedly
"""

import tempfile
import shutil
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
import dazzlesum

# Create test setup
temp_dir = tempfile.mkdtemp()
original_dir = Path(temp_dir) / "original"
clone_dir = Path(temp_dir) / "clone"

# Create original directory with test files
original_dir.mkdir()
(original_dir / "file1.txt").write_text("Content 1")
(original_dir / "file2.txt").write_text("Content 2")

# Create subdirectory structure
subdir = original_dir / "subdir"
subdir.mkdir()
(subdir / "file3.txt").write_text("Content 3")

nested_dir = subdir / "nested"
nested_dir.mkdir()
(nested_dir / "file4.txt").write_text("Content 4")

# Generate monolithic checksums
generator = dazzlesum.ChecksumGenerator(
    algorithm='sha256',
    generate_monolithic=True,
    generate_individual=False,
    output_file='checksums.sha256'
)

generator.process_directory_tree(original_dir, recursive=True)

# Read the monolithic file
mono_file = original_dir / 'checksums.sha256'
content = mono_file.read_text()
print("Monolithic file content:")
print(content)
print("\n" + "="*50 + "\n")

# Create clone and remove a file
shutil.copytree(original_dir, clone_dir)
print(f"Removing: {clone_dir / 'subdir' / 'file3.txt'}")
(clone_dir / "subdir" / "file3.txt").unlink()

# Test detection
lines = [line for line in content.split('\n') 
        if line and not line.startswith('#') and '  ' in line]

print(f"Found {len(lines)} checksum lines")

missing_files = []
for line in lines:
    parts = line.split('  ', 1)
    if len(parts) == 2:
        expected_hash, filename = parts
        file_path = clone_dir / filename
        
        if not file_path.exists():
            missing_files.append(filename)
            print(f"Missing: {filename}")

print(f"\nTotal missing files: {len(missing_files)}")
print(f"Missing files: {missing_files}")

# Clean up
shutil.rmtree(temp_dir)