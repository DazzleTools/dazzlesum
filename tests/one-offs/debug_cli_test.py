#!/usr/bin/env python3
"""
Debug script for CLI test failures.

Created: 2025-06-29
Purpose: Debug monolithic verification test failures in CLI interface
Result: Identified that --show-all flag is needed to see verification output
Status: Useful for debugging CLI verification output issues

Usage:
    python3 debug_cli_test.py
    
Expected Output:
    - Shows monolithic checksum creation process
    - Shows verification output with different verbosity levels
    - Demonstrates default quiet behavior vs explicit output flags
"""
import tempfile
import subprocess
import sys
from pathlib import Path

# Create test setup like the failing test
test_dir = Path(tempfile.mkdtemp())
test_file = test_dir / "test.txt"
test_file.write_text("Test content for CLI testing")

script_path = Path(__file__).parent / "dazzlesum.py"

print(f"Test directory: {test_dir}")
print(f"Test file: {test_file}")
print(f"Script path: {script_path}")

# Step 1: Create monolithic checksums
print("\n=== Creating monolithic checksums ===")
cmd = [sys.executable, str(script_path), "create", "-r", "--mode", "monolithic", str(test_dir)]
result = subprocess.run(cmd, capture_output=True, text=True)
print(f"Create command: {' '.join(cmd)}")
print(f"Create exit code: {result.returncode}")
print(f"Create stderr: {result.stderr}")
print(f"Create stdout: {result.stdout}")

# Check if monolithic file was created
mono_file = test_dir / "checksums.sha256"
print(f"\nMonolithic file exists: {mono_file.exists()}")
if mono_file.exists():
    content = mono_file.read_text()
    print(f"Monolithic file content:\n{content}")

# Step 2: Verify with explicit monolithic file
print("\n=== Verifying with explicit monolithic file ===")
cmd = [sys.executable, str(script_path), "verify", "--checksum-file", str(mono_file), str(test_dir)]
result = subprocess.run(cmd, capture_output=True, text=True)
print(f"Verify command: {' '.join(cmd)}")
print(f"Verify exit code: {result.returncode}")
print(f"Verify stderr: {result.stderr}")
print(f"Verify stdout: {result.stdout}")

# Clean up
import shutil
shutil.rmtree(test_dir)