#!/usr/bin/env python3
"""
Debug script for verify output verbosity analysis.

Created: 2025-06-29
Purpose: Test different verbosity levels for verify command output
Result: Confirmed default behavior is quiet, --show-all shows individual files
Status: Useful for understanding verify command output behavior

Usage:
    python3 debug_verbosity_test.py
    
Expected Output:
    - Default: Only header, no file details
    - --show-all: Shows "OK filename" for each verified file
    - -v/-vv: Shows info-level logging
    - Demonstrates how verbosity affects verify output
"""
import tempfile
import subprocess
import sys
from pathlib import Path

# Create test setup
test_dir = Path(tempfile.mkdtemp())
test_file = test_dir / "test.txt"
test_file.write_text("Test content for CLI testing")

script_path = Path(__file__).parent / "dazzlesum.py"

print(f"Test directory: {test_dir}")

# Create monolithic checksums
cmd = [sys.executable, str(script_path), "create", "-r", "--mode", "monolithic", str(test_dir)]
result = subprocess.run(cmd, capture_output=True, text=True)

mono_file = test_dir / "checksums.sha256"
print(f"Monolithic file created: {mono_file.exists()}")

# Test different verbosity levels
for flag in ["", "--show-all", "-v", "-vv"]:
    print(f"\n=== Testing with {flag or 'default'} ===")
    cmd = [sys.executable, str(script_path), "verify", "--checksum-file", str(mono_file), str(test_dir)]
    if flag:
        cmd.append(flag)
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Command: {' '.join(cmd)}")
    print(f"Exit code: {result.returncode}")
    print(f"Stderr: {result.stderr}")
    if result.stdout:
        print(f"Stdout: {result.stdout}")

# Clean up
import shutil
shutil.rmtree(test_dir)