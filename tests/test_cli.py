#!/usr/bin/env python3
"""
Test CLI interface and subparser functionality for dazzlesum.
"""

import os
import sys
import unittest
import tempfile
import shutil
import subprocess
from pathlib import Path

# Add parent directory to path so we can import dazzlesum
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dazzlesum


class TestCLIInterface(unittest.TestCase):
    """Test command-line interface and subparser functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.test_file = self.test_dir / "test.txt"
        self.test_file.write_text("Test content for CLI testing")
        
        # Get path to dazzlesum.py script
        self.script_path = Path(__file__).parent.parent / "dazzlesum.py"
    
    def tearDown(self):
        """Clean up test environment."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def run_dazzlesum(self, args, expect_success=True):
        """Helper to run dazzlesum with given arguments."""
        cmd = [sys.executable, str(self.script_path)] + args
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if expect_success and result.returncode != 0:
            self.fail(f"Command failed: {' '.join(cmd)}\nStdout: {result.stdout}\nStderr: {result.stderr}")
        
        return result
    
    def test_help_command(self):
        """Test main help command."""
        result = self.run_dazzlesum(["--help"])
        self.assertIn("Available commands", result.stdout)
        self.assertIn("create", result.stdout)
        self.assertIn("verify", result.stdout)
        self.assertIn("update", result.stdout)
        self.assertIn("manage", result.stdout)
    
    def test_version_command(self):
        """Test version command."""
        result = self.run_dazzlesum(["--version"])
        # Match semantic version pattern dynamically
        self.assertRegex(result.stdout, r'dazzlesum \d+\.\d+\.\d+(_\d+-\d{8}-[a-f0-9]{8})?')
    
    def test_create_subcommand_help(self):
        """Test create subcommand help."""
        result = self.run_dazzlesum(["create", "--help"])
        self.assertIn("Generate checksum files", result.stdout)
        self.assertIn("--mode", result.stdout)
        self.assertIn("--output", result.stdout)
    
    def test_verify_subcommand_help(self):
        """Test verify subcommand help."""
        result = self.run_dazzlesum(["verify", "--help"])
        self.assertIn("Verify file integrity", result.stdout)
        self.assertIn("--show-all-verifications", result.stdout)
    
    def test_update_subcommand_help(self):
        """Test update subcommand help."""
        result = self.run_dazzlesum(["update", "--help"])
        self.assertIn("Update checksums", result.stdout)
        self.assertIn("--include", result.stdout)
    
    def test_manage_subcommand_help(self):
        """Test manage subcommand help."""
        result = self.run_dazzlesum(["manage", "--help"])
        self.assertIn("Backup, remove, restore", result.stdout)
        self.assertIn("operation", result.stdout)
    
    def test_help_topics(self):
        """Test help-only subcommands."""
        # Test mode help
        result = self.run_dazzlesum(["mode"])
        self.assertIn("--mode OPTION", result.stdout)
        self.assertIn("individual", result.stdout)
        self.assertIn("monolithic", result.stdout)
        
        # Test examples help
        result = self.run_dazzlesum(["examples"])
        self.assertIn("COMPREHENSIVE EXAMPLES", result.stdout)
        self.assertIn("dazzlesum create", result.stdout)
        
        # Test shadow help
        result = self.run_dazzlesum(["shadow"])
        self.assertIn("SHADOW DIRECTORIES", result.stdout)
        self.assertIn("parallel directory", result.stdout)
    
    def test_create_command_basic(self):
        """Test basic create command functionality."""
        result = self.run_dazzlesum(["create", str(self.test_dir)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Dazzle Checksum Tool", result.stderr)
        
        # Check that .shasum file was created
        shasum_file = self.test_dir / ".shasum"
        self.assertTrue(shasum_file.exists())
    
    def test_create_command_monolithic(self):
        """Test create command with monolithic mode."""
        result = self.run_dazzlesum(["create", "-r", "--mode", "monolithic", str(self.test_dir)])
        self.assertEqual(result.returncode, 0)
        
        # Check that monolithic file was created
        mono_file = self.test_dir / "checksums.sha256"
        self.assertTrue(mono_file.exists())
        
        # Verify content format
        content = mono_file.read_text()
        self.assertIn("# Dazzle monolithic checksum file", content)
        self.assertIn("test.txt", content)
    
    def test_verify_command_basic(self):
        """Test basic verify command functionality."""
        # First create checksums
        self.run_dazzlesum(["create", str(self.test_dir)])
        
        # Then verify them
        result = self.run_dazzlesum(["verify", str(self.test_dir)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Dazzle Checksum Tool", result.stderr)
    
    def test_verify_command_monolithic(self):
        """Test verify command with monolithic file."""
        # First create monolithic checksums
        self.run_dazzlesum(["create", "-r", "--mode", "monolithic", str(self.test_dir)])
        
        # Then verify them
        mono_file = self.test_dir / "checksums.sha256"
        result = self.run_dazzlesum(["verify", "--checksum-file", str(mono_file), "--show-all", str(self.test_dir)])
        # Note: .tmp files are now excluded from monolithic checksums, so verification should succeed
        self.assertEqual(result.returncode, 0)  # Success - no missing .tmp file
        self.assertIn("OK", result.stderr)  # Files are verified successfully
    
    def test_deprecated_syntax_rejected(self):
        """Test that old syntax is no longer supported."""
        result = self.run_dazzlesum(["--verify", str(self.test_dir)], expect_success=False)
        # The command should fail with error message
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", result.stderr)
    
    def test_default_behavior(self):
        """Test that no subcommand defaults to create."""
        result = self.run_dazzlesum([str(self.test_dir)])
        self.assertEqual(result.returncode, 0)
        
        # Should create .shasum file (default create behavior)
        shasum_file = self.test_dir / ".shasum"
        self.assertTrue(shasum_file.exists())
    
    def test_manage_list_command(self):
        """Test manage list command."""
        # First create some checksums
        self.run_dazzlesum(["create", str(self.test_dir)])
        
        # Then list them
        result = self.run_dazzlesum(["manage", str(self.test_dir), "list"])
        self.assertEqual(result.returncode, 0)
    
    def test_shadow_directory_integration(self):
        """Test shadow directory functionality with new CLI."""
        shadow_dir = self.test_dir / "shadow"
        shadow_dir.mkdir()
        
        # Create with shadow directory
        result = self.run_dazzlesum([
            "create", "-r", "--shadow-dir", str(shadow_dir), str(self.test_dir)
        ])
        self.assertEqual(result.returncode, 0)
        
        # Check that shadow directory has .shasum file
        shadow_shasum = shadow_dir / ".shasum"
        self.assertTrue(shadow_shasum.exists())
        
        # Original directory should remain clean
        orig_shasum = self.test_dir / ".shasum"
        self.assertFalse(orig_shasum.exists())
    
    def test_error_handling(self):
        """Test error handling for invalid commands and arguments."""
        # Test invalid subcommand
        result = self.run_dazzlesum(["invalid_command"], expect_success=False)
        self.assertNotEqual(result.returncode, 0)
        
        # Test missing required arguments for manage
        result = self.run_dazzlesum(["manage", "backup"], expect_success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--backup-dir is required", result.stderr)
    
    def test_argument_validation(self):
        """Test argument validation for different subcommands."""
        # Test monolithic mode without recursive flag shows interactive prompt
        result = subprocess.run([
            sys.executable, str(self.script_path),
            "create", "--mode", "monolithic", str(self.test_dir)
        ], input="n\n", capture_output=True, text=True)
        
        self.assertEqual(result.returncode, 0)  # User chose to cancel, not an error
        self.assertIn("Monolithic mode works by creating a single checksum file", result.stdout)
        self.assertIn("Operation cancelled", result.stdout)


if __name__ == '__main__':
    unittest.main()