#!/usr/bin/env python3
"""
Test squelch system and grand totals functionality.

These tests define the expected behavior for output filtering and summary statistics
in recursive verification operations.
"""

import os
import sys
import unittest
import tempfile
import shutil
import subprocess
from pathlib import Path

# Add parent directory to path so we can import dazzlesum
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSquelchAndGrandTotals(unittest.TestCase):
    """Test squelch system and grand totals for recursive verification."""

    def setUp(self):
        """Set up test environment with complex directory structure."""
        self.test_dir = tempfile.mkdtemp()
        self.test_path = Path(self.test_dir)
        
        # Create complex test structure:
        # - success_dir: successful verification
        # - failure_dir: hash mismatch
        # - missing_dir: missing file
        # - extra_dir: extra file
        # - empty_dir: no .shasum file
        # - mixed_dir: mix of success and failure
        
        # Success directory
        success_dir = self.test_path / "success_dir"
        success_dir.mkdir()
        (success_dir / "file1.txt").write_text("content1")
        (success_dir / "file2.txt").write_text("content2")
        
        # Failure directory - we'll create checksums then modify files
        failure_dir = self.test_path / "failure_dir"
        failure_dir.mkdir()
        (failure_dir / "file3.txt").write_text("original content")
        
        # Missing directory - we'll create checksums then delete files
        missing_dir = self.test_path / "missing_dir"
        missing_dir.mkdir()
        (missing_dir / "file4.txt").write_text("will be deleted")
        
        # Extra directory - we'll create checksums then add extra files
        extra_dir = self.test_path / "extra_dir"
        extra_dir.mkdir()
        (extra_dir / "file5.txt").write_text("normal file")
        
        # Mixed directory - some success, some failure
        mixed_dir = self.test_path / "mixed_dir"
        mixed_dir.mkdir()
        (mixed_dir / "good.txt").write_text("good content")
        (mixed_dir / "bad.txt").write_text("will be modified")
        
        # Empty directory - no files to checksum
        empty_dir = self.test_path / "empty_dir"
        empty_dir.mkdir()
        
        # Path to dazzlesum script
        self.dazzlesum_path = Path(__file__).parent.parent / "dazzlesum.py"

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def run_dazzlesum(self, args, expect_success=True):
        """Helper to run dazzlesum with given arguments."""
        cmd = [sys.executable, str(self.dazzlesum_path)] + args
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if expect_success and result.returncode not in [0, 1, 2, 3, 4, 5]:  # Allow verification exit codes
            self.fail(f"Command failed: {' '.join(cmd)}\nStdout: {result.stdout}\nStderr: {result.stderr}")
        
        return result

    def create_test_checksums(self):
        """Create checksums for test directories, then introduce problems."""
        # Create checksums for all directories
        result = self.run_dazzlesum(["create", "-r", str(self.test_path)])
        self.assertEqual(result.returncode, 0)
        
        # Now introduce problems to test verification
        
        # Modify file in failure_dir to create hash mismatch
        failure_file = self.test_path / "failure_dir" / "file3.txt"
        failure_file.write_text("modified content")
        
        # Delete file in missing_dir
        missing_file = self.test_path / "missing_dir" / "file4.txt"
        missing_file.unlink()
        
        # Add extra file in extra_dir
        extra_file = self.test_path / "extra_dir" / "extra.txt"
        extra_file.write_text("unexpected file")
        
        # Modify one file in mixed_dir
        mixed_file = self.test_path / "mixed_dir" / "bad.txt"
        mixed_file.write_text("modified bad content")

    def test_grand_totals_display(self):
        """Test that recursive verify shows grand totals at the end."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", str(self.test_path)], expect_success=False)
        
        # Should contain grand totals section
        self.assertIn("=== GRAND TOTALS ===", result.stderr)
        
        # Should show directory counts
        self.assertIn("Directories:", result.stderr)
        self.assertIn("processed", result.stderr)
        
        # Should show file statistics
        self.assertIn("Files:", result.stderr)
        self.assertIn("verified", result.stderr)
        self.assertIn("failed", result.stderr)
        self.assertIn("missing", result.stderr)
        
        # Should show overall percentage
        self.assertRegex(result.stderr, r'\d+%/\d+%')
        
        # Should show processing time
        self.assertIn("Processing:", result.stderr)
        self.assertIn("seconds", result.stderr)

    def test_grand_totals_statistics_accuracy(self):
        """Test that grand totals accurately reflect aggregate results."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", str(self.test_path)], expect_success=False)
        
        # Parse the grand totals to verify accuracy
        output = result.stderr
        
        # Should have verified files from success_dir (2), extra_dir (1), mixed_dir (1 good) = 4 total
        self.assertIn("4 verified", output)
        
        # Should have failed files from failure_dir (1), mixed_dir (1 bad) = 2 total
        self.assertIn("2 failed", output)
        
        # Should have missing files from missing_dir (1) = 1 total
        self.assertIn("1 missing", output)
        
        # Should have extra files from extra_dir (1) = 1 total  
        self.assertIn("1 extra", output)

    def test_default_behavior_hides_success_messages(self):
        """Test that new default behavior hides SUCCESS messages but shows problems."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", str(self.test_path)], expect_success=False)
        
        # Should NOT show SUCCESS messages for successful directories
        self.assertNotIn("100%/0% SUCCESS", result.stderr)
        
        # Should show failure messages
        self.assertIn("FAIL", result.stderr)
        self.assertIn("MISS", result.stderr)
        
        # Should show grand totals
        self.assertIn("=== GRAND TOTALS ===", result.stderr)

    def test_show_all_flag_displays_everything(self):
        """Test that --show-all flag shows all results including SUCCESS."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", "--show-all", str(self.test_path)], expect_success=False)
        
        # Should show SUCCESS messages
        self.assertIn("100%/0% SUCCESS", result.stderr)
        
        # Should also show failure messages
        self.assertIn("FAIL", result.stderr)
        self.assertIn("MISS", result.stderr)
        
        # Should show grand totals
        self.assertIn("=== GRAND TOTALS ===", result.stderr)

    def test_squelch_success_parameter(self):
        """Test --squelch=SUCCESS parameter explicitly hides success messages."""
        self.create_test_checksums()
        
        # First verify that --show-all would show SUCCESS
        result_all = self.run_dazzlesum(["verify", "-r", "--show-all", str(self.test_path)], expect_success=False)
        self.assertIn("100%/0% SUCCESS", result_all.stderr)
        
        # Now test that squelch hides them
        result = self.run_dazzlesum(["verify", "-r", "--show-all", "--squelch=SUCCESS", str(self.test_path)], expect_success=False)
        
        # Should NOT show SUCCESS messages
        self.assertNotIn("100%/0% SUCCESS", result.stderr)
        
        # Should still show problems
        self.assertIn("FAIL", result.stderr)
        self.assertIn("MISS", result.stderr)

    def test_squelch_no_shasum_parameter(self):
        """Test --squelch=NO_SHASUM parameter hides 'No .shasum file found' messages."""
        self.create_test_checksums()
        
        # Default should show "No .shasum file found" for empty_dir
        result_default = self.run_dazzlesum(["verify", "-r", "--show-all", str(self.test_path)], expect_success=False)
        self.assertIn("No .shasum file found", result_default.stderr)
        
        # With squelch should hide them
        result = self.run_dazzlesum(["verify", "-r", "--show-all", "--squelch=NO_SHASUM", str(self.test_path)], expect_success=False)
        
        # Should NOT show "No .shasum file found" messages
        self.assertNotIn("No .shasum file found", result.stderr)
        
        # Should still show other problems
        self.assertIn("FAIL", result.stderr)
        self.assertIn("MISS", result.stderr)

    def test_multiple_squelch_categories(self):
        """Test multiple squelch categories with comma separation."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", "--show-all", "--squelch=SUCCESS,NO_SHASUM", str(self.test_path)], expect_success=False)
        
        # Should hide both SUCCESS and NO_SHASUM messages
        self.assertNotIn("100%/0% SUCCESS", result.stderr)
        self.assertNotIn("No .shasum file found", result.stderr)
        
        # Should still show actual problems
        self.assertIn("FAIL", result.stderr)
        self.assertIn("MISS", result.stderr)
        
        # Should show grand totals
        self.assertIn("=== GRAND TOTALS ===", result.stderr)

    def test_quiet_mode(self):
        """Test -q mode shows only failures and basic summary."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", "-q", str(self.test_path)], expect_success=False)
        
        # Should show problems
        self.assertIn("FAIL", result.stderr)
        self.assertIn("MISS", result.stderr)
        
        # Should NOT show processing messages
        self.assertNotIn("Starting recursive processing", result.stderr)
        self.assertNotIn("Completed processing", result.stderr)
        
        # Should show basic grand totals
        self.assertIn("=== GRAND TOTALS ===", result.stderr)

    def test_exit_code_based_on_aggregate_results(self):
        """Test that exit code reflects overall repository health, not individual directories."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", str(self.test_path)], expect_success=False)
        
        # With our test data:
        # - 4 verified, 2 failed, 1 missing, 1 extra = 8 total expected files
        # - 4 verified out of 7 actual files (4+2+1) = 57% success 
        # This should result in exit code 5 (MANY FAILS) based on 57% success rate
        
        self.assertEqual(result.returncode, 5)

    def test_individual_directory_verify_no_grand_totals(self):
        """Test that single directory verification doesn't show grand totals."""
        self.create_test_checksums()
        
        # Verify just one directory with --show-all to see the SUCCESS message
        result = self.run_dazzlesum(["verify", "--show-all", str(self.test_path / "success_dir")])
        
        # Should NOT show grand totals for single directory
        self.assertNotIn("=== GRAND TOTALS ===", result.stderr)
        
        # Should show normal directory result when using --show-all
        self.assertIn("100%/0% SUCCESS", result.stderr)

    def test_grand_totals_directory_categorization(self):
        """Test that grand totals categorize directories by result type."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", str(self.test_path)], expect_success=False)
        
        # Should categorize directories in grand totals
        # Format: "Directories: X processed (Y success, Z no-shasum, A partial, B failed)"
        totals_line = [line for line in result.stderr.split('\n') if 'Directories:' in line and 'processed' in line][0]
        
        # Should have directory counts
        self.assertIn("success", totals_line)
        self.assertIn("no-shasum", totals_line)  # for empty_dir
        self.assertIn("partial", totals_line)    # for mixed_dir
        self.assertIn("failed", totals_line)     # for failure_dir, missing_dir

    def test_squelch_doesnt_affect_exit_codes(self):
        """Test that squelching output doesn't change exit codes."""
        self.create_test_checksums()
        
        # Get exit code with full output
        result_full = self.run_dazzlesum(["verify", "-r", "--show-all", str(self.test_path)], expect_success=False)
        
        # Get exit code with squelched output
        result_squelched = self.run_dazzlesum(["verify", "-r", "--squelch=SUCCESS,NO_SHASUM", str(self.test_path)], expect_success=False)
        
        # Exit codes should be identical regardless of squelch settings
        self.assertEqual(result_full.returncode, result_squelched.returncode)

    def test_grand_totals_performance_metrics(self):
        """Test that grand totals include processing time and throughput."""
        self.create_test_checksums()
        
        result = self.run_dazzlesum(["verify", "-r", str(self.test_path)], expect_success=False)
        
        # Should include processing time
        self.assertRegex(result.stderr, r'Processing: [\d.]+ seconds')
        
        # Should include throughput (files/sec)
        self.assertRegex(result.stderr, r'\d+ files/sec')

    def test_verbosity_interaction_with_squelch(self):
        """Test how verbosity levels interact with squelch system."""
        self.create_test_checksums()
        
        # Verbose should show more detail even with default squelch
        result = self.run_dazzlesum(["verify", "-r", "-v", str(self.test_path)], expect_success=False)
        
        # With verbosity, should show processing messages
        self.assertIn("Starting recursive processing", result.stderr)
        
        # But should still respect default squelch (no SUCCESS spam)
        # Count SUCCESS messages - should be minimal or zero
        success_count = result.stderr.count("100%/0% SUCCESS")
        self.assertLessEqual(success_count, 1)  # Maybe one for demonstration, but not all

    def test_help_includes_squelch_documentation(self):
        """Test that --help includes documentation for squelch system."""
        result = self.run_dazzlesum(["verify", "--help"])
        
        # Should document squelch options
        self.assertIn("--squelch", result.stdout)
        self.assertIn("--show-all", result.stdout)
        self.assertIn("-q, --quiet", result.stdout)
        
        # Should explain categories
        self.assertIn("SUCCESS", result.stdout)
        self.assertIn("NO_SHASUM", result.stdout)


if __name__ == '__main__':
    unittest.main()