#!/usr/bin/env python3
"""
Debug script for verify output behavior analysis.

Created: 2025-06-29
Purpose: Test --show-all flag behavior and verify output patterns
Result: Confirmed --show-all shows individual file results but not directory status
Status: Useful for debugging verify command output formatting

Usage:
    python3 test_verify_output.py
    
Expected Output:
    - Shows behavior of verify with --show-all flag
    - Demonstrates single directory vs recursive verification
    - Useful for understanding what success messages are displayed
"""

import os
import sys
import tempfile
import subprocess
from pathlib import Path

# Create test directory
with tempfile.TemporaryDirectory() as tmpdir:
    test_path = Path(tmpdir)
    
    # Create a success directory
    success_dir = test_path / "success_dir"
    success_dir.mkdir()
    (success_dir / "file1.txt").write_text("content1")
    (success_dir / "file2.txt").write_text("content2")
    
    # First create checksums
    print("Creating checksums...")
    result = subprocess.run([sys.executable, "dazzlesum.py", "create", "-r", str(test_path)], 
                          capture_output=True, text=True)
    print(f"Create exit code: {result.returncode}")
    
    # Now verify with --show-all
    print("\nVerifying with --show-all...")
    result = subprocess.run([sys.executable, "dazzlesum.py", "verify", "-r", "--show-all", str(test_path)], 
                          capture_output=True, text=True)
    print(f"Verify exit code: {result.returncode}")
    print("\nStderr output:")
    print(result.stderr)
    print("\nStdout output:")
    print(result.stdout)
    
    # Also test single directory verify
    print("\n\nVerifying single directory...")
    result = subprocess.run([sys.executable, "dazzlesum.py", "verify", str(success_dir)], 
                          capture_output=True, text=True)
    print(f"Single dir exit code: {result.returncode}")
    print("\nStderr output:")
    print(result.stderr)
    print("\nStdout output:")
    print(result.stdout)