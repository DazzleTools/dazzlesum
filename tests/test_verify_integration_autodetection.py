#!/usr/bin/env python3
"""
Integration test for verify command with monolithic auto-detection.

Tests the end-to-end functionality of running `dazzlesum` in a directory
with only monolithic checksum files to verify auto-detection works correctly.
"""

import os
import sys
import unittest
import tempfile
import shutil
import subprocess
from pathlib import Path

# Add the parent directory to sys.path so we can import dazzlesum
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestVerifyIntegrationAutoDetection(unittest.TestCase):
    """Integration tests for verify command with monolithic auto-detection."""

    def setUp(self):
        """Set up test environment with temporary directories."""
        self.test_dir = tempfile.mkdtemp()
        self.test_path = Path(self.test_dir)
        
        # Create test files
        (self.test_path / "file1.txt").write_text("Test content 1")
        (self.test_path / "file2.txt").write_text("Test content 2")
        
        # Path to dazzlesum script
        self.dazzlesum_path = Path(__file__).parent.parent / "dazzlesum.py"

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_verify_with_monolithic_auto_detection(self):
        """Test that verify command auto-detects and uses monolithic checksum files."""
        # First, create checksums using monolithic mode
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path),
            "create", "-r", "--mode", "monolithic", str(self.test_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        self.assertEqual(result.returncode, 0, f"Create failed: {result.stderr}")
        
        # Verify that checksums.sha256 was created
        checksums_file = self.test_path / "checksums.sha256"
        self.assertTrue(checksums_file.exists(), "checksums.sha256 file was not created")
        
        # Now test auto-detection by running verify without explicit --output
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path)  # No arguments - should auto-detect
        ], capture_output=True, text=True, cwd=self.test_path)
        
        # Note: .tmp files are now excluded from monolithic checksums, so should succeed
        self.assertEqual(result.returncode, 0, f"Auto-detection verify failed: {result.stderr}")
        
        # Check that verification was successful for actual files
        self.assertIn("Context-aware: executing 'verify .'", result.stderr)
        self.assertIn("file1.txt", result.stderr)
        self.assertIn("file2.txt", result.stderr)
        self.assertIn("OK", result.stderr)

    def test_verify_explicit_command_with_auto_detection(self):
        """Test that explicit verify command also uses auto-detection."""
        # Create monolithic checksums
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path),
            "create", "-r", "--mode", "monolithic", str(self.test_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        self.assertEqual(result.returncode, 0, f"Create failed: {result.stderr}")
        
        # Test explicit verify command without --output
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path),
            "verify", "--show-all", str(self.test_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        # Note: .tmp files are now excluded from monolithic checksums, so should succeed
        self.assertEqual(result.returncode, 0, f"Explicit verify failed: {result.stderr}")
        
        # Check that verification was successful for actual files (look for verified count)
        self.assertIn("OK", result.stderr)
        # Should show successful verification (OK messages for files)
        self.assertIn("file1.txt", result.stderr)
        self.assertIn("file2.txt", result.stderr)

    def test_priority_individual_over_monolithic_integration(self):
        """Test that individual .shasum files take priority in actual verification."""
        # Create both individual and monolithic checksums
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path),
            "create", "--mode", "both", "-r", str(self.test_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        self.assertEqual(result.returncode, 0, f"Create both modes failed: {result.stderr}")
        
        # Verify both files exist
        self.assertTrue((self.test_path / ".shasum").exists())
        self.assertTrue((self.test_path / "checksums.sha256").exists())
        
        # Run auto-detection verification
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        # Note: Individual verification takes priority and detects monolithic file as EXTRA
        # Exit code 2 means SOME EXTRA files found
        self.assertEqual(result.returncode, 2, f"Priority verification failed: {result.stderr}")
        
        # Should use individual verification (evident by the format of output)
        # Individual verification shows files without full paths and detects extra file
        self.assertIn("file1.txt", result.stderr)
        self.assertIn("file2.txt", result.stderr)
        self.assertIn("EXTRA checksums.sha256", result.stderr)

    def test_monolithic_detection_with_custom_filename(self):
        """Test auto-detection works with custom monolithic filenames."""
        # Create monolithic checksum with custom name
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path),
            "create", "-r", "--mode", "monolithic", 
            "--output", "my-checksums.sha256", str(self.test_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        self.assertEqual(result.returncode, 0, f"Create custom monolithic failed: {result.stderr}")
        
        # Verify custom file exists
        custom_file = self.test_path / "my-checksums.sha256"
        self.assertTrue(custom_file.exists())
        
        # Test auto-detection
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        # Note: .tmp files are now excluded from monolithic checksums, so should succeed
        self.assertEqual(result.returncode, 0, f"Custom filename auto-detection failed: {result.stderr}")
        
        # Verification should work for actual files
        self.assertIn("file1.txt", result.stderr)
        self.assertIn("file2.txt", result.stderr)

    def test_no_auto_detection_fallback(self):
        """Test that verification fails gracefully when no checksum files exist."""
        # Run in directory with no checksum files
        result = subprocess.run([
            sys.executable, str(self.dazzlesum_path)
        ], capture_output=True, text=True, cwd=self.test_path)
        
        # Should auto-detect 'create' and create checksums
        self.assertEqual(result.returncode, 0)
        self.assertIn("Context-aware: executing 'create .'", result.stderr)
        
        # Should have created .shasum file
        self.assertTrue((self.test_path / ".shasum").exists())


if __name__ == '__main__':
    unittest.main()