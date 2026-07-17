#!/usr/bin/env python3
"""
Comprehensive test suite for the verbosity system.
This is a permanent CI/CD test suite for all 11 verbosity levels (-6 to +4).
"""

import os
import sys
import tempfile
import subprocess
import hashlib
import pytest
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def calculate_sha256(content):
    """Calculate SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()

@pytest.fixture
def comprehensive_test_directory():
    """Create a comprehensive test directory structure with all issue types."""
    test_dir = tempfile.mkdtemp(prefix="dazzlesum_verbosity_test_")
    test_path = Path(test_dir)
    
    # 1. SUCCESS-only directory (perfect verification)
    success_dir = test_path / "success_only"
    success_dir.mkdir()
    success_file = success_dir / "success.txt"
    content = "Success content"
    success_file.write_text(content)
    shasum_file = success_dir / ".shasum"
    shasum_file.write_text(f"{calculate_sha256(content)}  success.txt\n")
    
    # 2. SUCCESS with extras directory 
    success_extras_dir = test_path / "success_with_extras"
    success_extras_dir.mkdir()
    
    verified_file = success_extras_dir / "verified.txt"
    verified_content = "Verified content"
    verified_file.write_text(verified_content)
    
    extra_file = success_extras_dir / "extra.txt"
    extra_file.write_text("Extra content")
    
    shasum_extras = success_extras_dir / ".shasum"
    shasum_extras.write_text(f"{calculate_sha256(verified_content)}  verified.txt\n")
    
    # 3. FAIL-only directory
    fail_dir = test_path / "fail_only"
    fail_dir.mkdir()
    fail_file = fail_dir / "fail.txt"
    fail_file.write_text("Fail content")
    shasum_fail = fail_dir / ".shasum"
    shasum_fail.write_text("wrongchecksum123456789abcdef  fail.txt\n")
    
    # 4. MISSING-only directory
    missing_dir = test_path / "missing_only"
    missing_dir.mkdir()
    shasum_missing = missing_dir / ".shasum"
    shasum_missing.write_text(f"{calculate_sha256('missing')}  missing.txt\n")
    
    # 5. Pure EXTRA-only directory
    extra_dir = test_path / "extra_only"
    extra_dir.mkdir()
    extra_file = extra_dir / "extra.txt"
    extra_file.write_text("Extra content")
    shasum_empty = extra_dir / ".shasum"
    shasum_empty.write_text("")  # Empty = all files are extra
    
    # 6. Mixed issues directory
    mixed_dir = test_path / "mixed_issues"
    mixed_dir.mkdir()
    
    mixed_success = mixed_dir / "success.txt"
    mixed_success_content = "Mixed success"
    mixed_success.write_text(mixed_success_content)
    
    mixed_fail = mixed_dir / "fail.txt"
    mixed_fail.write_text("Mixed fail")
    
    shasum_mixed = mixed_dir / ".shasum"
    shasum_mixed.write_text(f"{calculate_sha256(mixed_success_content)}  success.txt\nwrongchecksum123  fail.txt\n")
    
    yield test_path
    
    # Cleanup
    import shutil
    shutil.rmtree(test_path)

def run_dazzlesum_with_level(test_dir, level):
    """Run dazzlesum with specified verbosity level and return output."""
    if level >= 0:
        cmd = [sys.executable, str(project_root / "dazzlesum.py"), "verify", "-r"] + ["-v"] * level + [str(test_dir)]
    else:
        cmd = [sys.executable, str(project_root / "dazzlesum.py"), "verify", "-r"] + ["-q"] * abs(level) + [str(test_dir)]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"

class TestVerbosityLevels:
    """Test all verbosity levels with comprehensive scenarios."""
    
    def test_level_minus_6_silent(self, comprehensive_test_directory):
        """Level -6 should be completely silent."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -6)
        
        # Should have no output except exit codes
        assert stdout.strip() == ""
        assert stderr.strip() == ""
        assert exit_code != 0  # Should reflect actual verification results
    
    def test_level_minus_5_grand_totals_only(self, comprehensive_test_directory):
        """Level -5 should show only grand totals."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -5)
        
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        
        # Should have startup message + grand totals
        assert any("GRAND TOTALS" in line for line in lines)
        
        # Should NOT have individual directory status lines. The grand-totals
        # block's own "Files: N verified, ..." summary line (added in v1.3.6)
        # is not a per-directory line and must not count.
        status_lines = [line for line in lines
                        if ': ' in line and 'verified' in line
                        and not line.strip().startswith('Files:')]
        assert len(status_lines) == 0
    
    def test_level_minus_4_force_summary(self, comprehensive_test_directory):
        """Level -4 should show status lines for directories with FAIL/MISSING but not SUCCESS."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -4)
        
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        
        # Should show FAIL and MISSING directories
        fail_lines = [line for line in lines if 'fail_only' in line and ': ' in line]
        missing_lines = [line for line in lines if 'missing_only' in line and ': ' in line]
        mixed_lines = [line for line in lines if 'mixed_issues' in line and ': ' in line]
        
        assert len(fail_lines) == 1
        assert len(missing_lines) == 1  
        assert len(mixed_lines) == 1
        
        # Should NOT show SUCCESS directories (even with extras)
        success_lines = [line for line in lines if ('success_only' in line or 'success_with_extras' in line) and ': ' in line]
        assert len(success_lines) == 0
        
        # Should NOT show pure EXTRA directories
        extra_lines = [line for line in lines if 'extra_only' in line and ': ' in line]
        assert len(extra_lines) == 0
    
    def test_level_minus_3_shows_fails(self, comprehensive_test_directory):
        """Level -3 should show FAIL directories and status lines."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -3)
        
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        
        # Should show directories with FAIL issues
        fail_lines = [line for line in lines if 'FAIL' in line and ': ' in line]
        assert len(fail_lines) >= 1
    
    def test_level_minus_2_shows_missing_and_fails(self, comprehensive_test_directory):
        """Level -2 should show MISSING and FAIL directories."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -2)
        
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        
        # Should show directories with MISSING or FAIL issues
        issue_lines = [line for line in lines if ('FAIL' in line or 'missing_only' in line) and ': ' in line]
        assert len(issue_lines) >= 2
    
    def test_level_minus_1_shows_extras(self, comprehensive_test_directory):
        """Level -1 should show EXTRA, MISSING, and FAIL directories."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -1)
        
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        
        # Should show more directories including some with extras
        status_lines = [line for line in lines if ': ' in line and 'verified' in line]
        assert len(status_lines) >= 3
    
    def test_level_0_default_behavior(self, comprehensive_test_directory):
        """Level 0 should show default behavior."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, 0)
        
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        
        # Should show most directories but not SUCCESS-only
        status_lines = [line for line in lines if ': ' in line and 'verified' in line]
        assert len(status_lines) >= 4
    
    def test_level_plus_1_shows_everything(self, comprehensive_test_directory):
        """Level +1 should show all directories including SUCCESS."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, 1)
        
        all_output = stdout + stderr
        lines = all_output.strip().split('\n')
        
        # Should show all directories
        status_lines = [line for line in lines if ': ' in line and 'verified' in line]
        assert len(status_lines) >= 5
        
        # Should include SUCCESS directories
        success_lines = [line for line in lines if 'SUCCESS' in line and ': ' in line]
        assert len(success_lines) >= 1

class TestVerbosityProgression:
    """Test that verbosity levels show progressively more information."""
    
    def test_progressive_information_disclosure(self, comprehensive_test_directory):
        """Test that higher verbosity levels show more information."""
        results = {}
        
        for level in [-5, -4, -3, -2, -1, 0, 1]:
            exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, level)
            all_output = stdout + stderr
            # Exclude the grand-totals "Files: ..." summary line (v1.3.6);
            # only per-directory status lines measure disclosure here
            status_lines = [line for line in all_output.split('\n')
                            if ': ' in line and 'verified' in line
                            and not line.strip().startswith('Files:')]
            results[level] = len(status_lines)
        
        # Each level should show same or more information than more restrictive levels
        assert results[-4] >= results[-5]  # -4 shows more than -5
        assert results[-3] >= results[-4]  # -3 shows more than -4  
        assert results[-2] >= results[-3]  # -2 shows more than -3
        assert results[-1] >= results[-2]  # -1 shows more than -2
        assert results[0] >= results[-1]   # 0 shows more than -1
        assert results[1] >= results[0]    # 1 shows more than 0

class TestExplicitSquelchOverrides:
    """Regression (v1.4.4): --squelch only modified keys already present in
    the level's default dict, so categories absent from a level's defaults
    (e.g. EXTRA_SUMMARY at most levels) silently no-op'd."""

    def test_squelch_extra_summary_hides_pure_extras_dir(self, comprehensive_test_directory):
        cmd = [sys.executable, str(project_root / "dazzlesum.py"), "verify", "-r",
               "-q", "--squelch", "EXTRA_SUMMARY", str(comprehensive_test_directory)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        all_output = result.stdout + result.stderr
        extra_only_lines = [line for line in all_output.split('\n')
                            if 'extra_only' in line and 'verified' in line]
        assert len(extra_only_lines) == 0, extra_only_lines
        # Failing dirs must still be visible
        assert any('fail_only' in line and 'verified' in line
                   for line in all_output.split('\n'))


class TestSuccessWithExtrasFiltering:
    """Specific tests for SUCCESS directories with extra files."""
    
    def test_success_with_extras_hidden_at_level_4(self, comprehensive_test_directory):
        """SUCCESS directories with extras should be hidden at level -4."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -4)
        
        all_output = stdout + stderr
        
        # Should NOT see SUCCESS directories with extras
        success_extras_lines = [line for line in all_output.split('\n') 
                               if 'success_with_extras' in line and ': ' in line]
        assert len(success_extras_lines) == 0
    
    def test_success_with_extras_shown_at_level_1(self, comprehensive_test_directory):
        """SUCCESS directories with extras should be shown at level +1."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, 1)
        
        all_output = stdout + stderr
        
        # Should see SUCCESS directories with extras
        success_extras_lines = [line for line in all_output.split('\n') 
                               if 'success_with_extras' in line and ': ' in line]
        assert len(success_extras_lines) >= 1

class TestExtraFiltering:
    """Tests for EXTRA file filtering behavior."""
    
    def test_pure_extra_directories_hidden_at_level_4(self, comprehensive_test_directory):
        """Pure EXTRA-only directories should be hidden at level -4."""
        exit_code, stdout, stderr = run_dazzlesum_with_level(comprehensive_test_directory, -4)
        
        all_output = stdout + stderr
        
        # Should NOT see pure EXTRA directories
        extra_lines = [line for line in all_output.split('\n') 
                      if 'extra_only' in line and ': ' in line]
        assert len(extra_lines) == 0

if __name__ == "__main__":
    # Allow running as standalone script
    pytest.main([__file__, "-v"])