#!/usr/bin/env python3
"""
Test script to verify that level -4 (FORCE_SUMMARY) shows status lines for all directories
even when all issues in that directory are squelched.

This tests the fix for the critical level -4 issue identified in the postmortem.
"""

import os
import sys
import tempfile
import subprocess
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def setup_test_directory():
    """Create a test directory structure with various issue types."""
    test_dir = tempfile.mkdtemp(prefix="dazzlesum_level4_test_")
    test_path = Path(test_dir)
    
    # Create a directory with ONLY FAIL issues (should show status line at level -4)
    fail_dir = test_path / "fail_only"
    fail_dir.mkdir()
    
    # Create a file and corresponding .shasum with wrong checksum
    test_file = fail_dir / "test.txt"
    test_file.write_text("Hello World")
    
    shasum_file = fail_dir / ".shasum"
    # Intentionally wrong checksum to create FAIL
    shasum_file.write_text("wrongchecksum123456789abcdef  test.txt\n")
    
    # Create a directory with ONLY MISSING issues (should show status line at level -4)
    missing_dir = test_path / "missing_only"
    missing_dir.mkdir()
    
    # Create .shasum referencing a non-existent file
    shasum_missing = missing_dir / ".shasum"
    shasum_missing.write_text("a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3  nonexistent.txt\n")
    
    return test_path

def run_dazzlesum_with_level(test_dir, level):
    """Run dazzlesum with specified verbosity level and return output."""
    cmd = [sys.executable, str(project_root / "dazzlesum.py"), "verify", "-r", f"-{'q' * abs(level)}", str(test_dir)]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"

def test_level_4_force_summary():
    """Test that level -4 shows status lines even for directories with only squelched issues."""
    print("Testing level -4 FORCE_SUMMARY fix...")
    
    test_dir = setup_test_directory()
    print(f"Created test directory: {test_dir}")
    
    try:
        # Test level -4 (should show status lines despite squelched individual FAIL lines)
        exit_code, stdout, stderr = run_dazzlesum_with_level(test_dir, -4)
        
        print(f"\nLevel -4 output:")
        print(f"Exit code: {exit_code}")
        print(f"STDOUT:\n{stdout}")
        if stderr:
            print(f"STDERR:\n{stderr}")
        
        # Check that status lines are shown (they appear in stderr)
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        status_lines = [line for line in lines if ': ' in line and ('verified' in line or 'failed' in line)]
        
        print(f"\nFound {len(status_lines)} status lines:")
        for line in status_lines:
            print(f"  {line}")
        
        # Should have status lines for both directories despite squelched individual issues
        if len(status_lines) >= 2:
            print("✅ SUCCESS: Level -4 shows status lines for directories with squelched issues")
            return True
        else:
            print("❌ FAILED: Level -4 not showing expected status lines")
            return False
            
    finally:
        # Cleanup
        import shutil
        shutil.rmtree(test_dir)
        print(f"\nCleaned up test directory: {test_dir}")

def test_comparison_with_level_5():
    """Compare level -4 vs level -5 to ensure different behavior."""
    print("\nComparing level -4 vs level -5...")
    
    test_dir = setup_test_directory()
    
    try:
        # Test level -5 (should NOT show status lines)
        exit_code_5, stdout_5, stderr_5 = run_dazzlesum_with_level(test_dir, -5)
        
        # Test level -4 (should show status lines)
        exit_code_4, stdout_4, stderr_4 = run_dazzlesum_with_level(test_dir, -4)
        
        all_output_5 = stdout_5 + stderr_5
        all_output_4 = stdout_4 + stderr_4
        level_5_status_count = len([line for line in all_output_5.split('\n') if ': ' in line and 'verified' in line])
        level_4_status_count = len([line for line in all_output_4.split('\n') if ': ' in line and 'verified' in line])
        
        print(f"Level -5 status lines: {level_5_status_count}")
        print(f"Level -4 status lines: {level_4_status_count}")
        
        if level_4_status_count > level_5_status_count:
            print("✅ SUCCESS: Level -4 shows more status lines than level -5")
            return True
        else:
            print("❌ FAILED: Level -4 doesn't show more status lines than level -5")
            return False
            
    finally:
        import shutil
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    print("=" * 60)
    print("TESTING LEVEL -4 FORCE_SUMMARY FIX")
    print("=" * 60)
    
    success = True
    
    success &= test_level_4_force_summary()
    success &= test_comparison_with_level_5()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 ALL TESTS PASSED - Level -4 fix is working correctly!")
    else:
        print("💥 SOME TESTS FAILED - Level -4 fix needs more work")
    print("=" * 60)
    
    sys.exit(0 if success else 1)