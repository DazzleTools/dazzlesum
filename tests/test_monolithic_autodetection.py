#!/usr/bin/env python3
"""
Test suite for monolithic checksum file auto-detection functionality.

This test verifies that the verify command can automatically detect and use
monolithic checksum files like checksums.sha256 without requiring explicit
--output parameter specification.
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

# Add the parent directory to sys.path so we can import dazzlesum
sys.path.insert(0, str(Path(__file__).parent.parent))

from dazzlesum import auto_detect_checksum_file, detect_context_command, is_monolithic_file


class TestMonolithicAutoDetection(unittest.TestCase):
    """Test cases for monolithic checksum file auto-detection."""

    def setUp(self):
        """Set up test environment with temporary directories."""
        self.test_dir = tempfile.mkdtemp()
        self.test_path = Path(self.test_dir)
        
        # Create test files
        (self.test_path / "file1.txt").write_text("Test content 1")
        (self.test_path / "file2.txt").write_text("Test content 2")

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_auto_detect_individual_shasum_file(self):
        """Test auto-detection prioritizes individual .shasum files."""
        # Create a .shasum file
        shasum_content = """# Dazzle checksum tool v1.3.0 - sha256 - 2025-06-28T13:30:00Z
hash1  file1.txt
hash2  file2.txt
"""
        (self.test_path / ".shasum").write_text(shasum_content)
        
        # Test auto-detection
        detected_file = auto_detect_checksum_file(self.test_path)
        self.assertIsNotNone(detected_file)
        self.assertEqual(detected_file.name, ".shasum")
        self.assertFalse(is_monolithic_file(detected_file))  # Individual file

    def test_auto_detect_standard_monolithic_file(self):
        """Test auto-detection finds standard monolithic checksum files."""
        # Create a checksums.sha256 file (monolithic format)
        monolithic_content = """# Dazzle monolithic checksum file v1.3.0 - sha256 - 2025-06-28T13:30:00Z
# Root directory: {root}
hash1  file1.txt
hash2  file2.txt
""".format(root=self.test_path)
        (self.test_path / "checksums.sha256").write_text(monolithic_content)
        
        # Test auto-detection
        detected_file = auto_detect_checksum_file(self.test_path)
        self.assertIsNotNone(detected_file)
        self.assertEqual(detected_file.name, "checksums.sha256")
        self.assertTrue(is_monolithic_file(detected_file))  # Monolithic file

    def test_auto_detect_priority_individual_over_monolithic(self):
        """Test that individual .shasum files take priority over monolithic files."""
        # Create both individual and monolithic files
        shasum_content = """# Dazzle checksum tool v1.3.0 - sha256 - 2025-06-28T13:30:00Z
hash1  file1.txt
hash2  file2.txt
"""
        (self.test_path / ".shasum").write_text(shasum_content)
        
        monolithic_content = """# Dazzle monolithic checksum file v1.3.0 - sha256 - 2025-06-28T13:30:00Z
# Root directory: {root}
hash1  file1.txt
hash2  file2.txt
""".format(root=self.test_path)
        (self.test_path / "checksums.sha256").write_text(monolithic_content)
        
        # Test auto-detection - should prefer .shasum
        detected_file = auto_detect_checksum_file(self.test_path)
        self.assertIsNotNone(detected_file)
        self.assertEqual(detected_file.name, ".shasum")

    def test_auto_detect_various_monolithic_patterns(self):
        """Test auto-detection works with various monolithic file patterns."""
        test_patterns = [
            "checksums.md5",
            "checksums.sha1", 
            "checksums.sha512",
            "CHECKSUMS",
            "SHA256SUMS"
        ]
        
        for pattern in test_patterns:
            with self.subTest(pattern=pattern):
                # Clean up previous files
                for file in self.test_path.glob("checksums*"):
                    file.unlink()
                for file in self.test_path.glob("*SUMS"):
                    file.unlink()
                for file in self.test_path.glob("CHECKSUMS"):
                    file.unlink()
                
                # Create monolithic file with pattern
                monolithic_content = """# Dazzle monolithic checksum file v1.3.0 - sha256 - 2025-06-28T13:30:00Z
# Root directory: {root}
hash1  file1.txt
hash2  file2.txt
""".format(root=self.test_path)
                (self.test_path / pattern).write_text(monolithic_content)
                
                # Test auto-detection
                detected_file = auto_detect_checksum_file(self.test_path)
                self.assertIsNotNone(detected_file, f"Failed to detect {pattern}")
                # Case-insensitive comparison for Windows filesystem compatibility
                self.assertEqual(detected_file.name.lower(), pattern.lower())
                self.assertTrue(is_monolithic_file(detected_file))

    def test_auto_detect_custom_extensions(self):
        """Test auto-detection works with custom checksum file extensions."""
        test_extensions = [
            "my-checksums.sha256",
            "project.md5",
            "verification.sha512"
        ]
        
        for extension in test_extensions:
            with self.subTest(extension=extension):
                # Clean up previous files
                for file in self.test_path.glob("*.*"):
                    if file.suffix in ['.sha256', '.md5', '.sha512']:
                        file.unlink()
                
                # Create monolithic file with custom extension
                monolithic_content = """# Dazzle monolithic checksum file v1.3.0 - sha256 - 2025-06-28T13:30:00Z
# Root directory: {root}
hash1  file1.txt
hash2  file2.txt
""".format(root=self.test_path)
                (self.test_path / extension).write_text(monolithic_content)
                
                # Test auto-detection
                detected_file = auto_detect_checksum_file(self.test_path)
                self.assertIsNotNone(detected_file, f"Failed to detect {extension}")
                self.assertEqual(detected_file.name, extension)
                self.assertTrue(is_monolithic_file(detected_file))

    def test_auto_detect_no_checksum_files(self):
        """Test auto-detection returns None when no checksum files exist."""
        # Test with directory containing only data files
        detected_file = auto_detect_checksum_file(self.test_path)
        self.assertIsNone(detected_file)

    def test_context_command_detection(self):
        """Test that context command detection integrates with auto-detection."""
        # Test with no checksum files - should return 'create'
        command = detect_context_command(self.test_path)
        self.assertEqual(command, 'create')
        
        # Add monolithic file - should return 'verify'
        monolithic_content = """# Dazzle monolithic checksum file v1.3.0 - sha256 - 2025-06-28T13:30:00Z
# Root directory: {root}
hash1  file1.txt
hash2  file2.txt
""".format(root=self.test_path)
        (self.test_path / "checksums.sha256").write_text(monolithic_content)
        
        command = detect_context_command(self.test_path)
        self.assertEqual(command, 'verify')

    def test_false_positives_rejected(self):
        """Test that files with checksum-like names but wrong content are rejected."""
        # Create a file with checksum-like name but non-checksum content
        (self.test_path / "checksums.sha256").write_text("This is not a checksum file")
        
        # Should not be detected as monolithic
        detected_file = auto_detect_checksum_file(self.test_path)
        self.assertIsNone(detected_file)
        
        # Context detection should return 'create'
        command = detect_context_command(self.test_path)
        self.assertEqual(command, 'create')


if __name__ == '__main__':
    unittest.main()