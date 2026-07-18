#!/usr/bin/env python3
"""
Test the new automated versioning system.
"""

import os
import sys
import unittest
from pathlib import Path

# Add parent directory to path so we can import dazzlesum
sys.path.insert(0, str(Path(__file__).parent.parent))

import dazzlesum


class TestVersioningSystem(unittest.TestCase):
    """Test the automated versioning system."""

    def test_version_format_static(self):
        """Test that static version follows expected format."""
        version = dazzlesum.__version__
        
        # Should be string
        self.assertIsInstance(version, str)
        
        if '_' in version:
            # Repokit-stamped build: 1.4.2_main_85-20260717-9310051e or
            # 1.5.0-alpha_main_92-... (BASE[-PHASE]_BRANCH_BUILD-DATE-HASH;
            # parse from the right so branch names with separators stay safe)
            prefix, build_info = version.rsplit('_', 1)
            base = prefix.split('_', 1)[0]
            base = base.split('-', 1)[0]  # strip optional -PHASE (alpha/beta/rcN)

            # Base version should be semantic
            parts = base.split('.')
            self.assertEqual(len(parts), 3)
            for part in parts:
                self.assertTrue(part.isdigit())

            # Build info should match pattern: Build#-YYYYMMDD-CommitHash
            self.assertRegex(build_info, r'^\d+-\d{8}-[a-f0-9]{8}[a-f0-9]*$')

            # Should NOT end with -dev for static builds
            self.assertFalse(build_info.endswith('-dev'))
        else:
            # Fallback version: 1.3.0
            parts = version.split('.')
            self.assertGreaterEqual(len(parts), 3)

    def test_static_version_immutable(self):
        """Test that static version is not affected by environment variables."""
        # Save original version
        original_version = dazzlesum.__version__
        
        # Test that CI injection doesn't affect static version
        test_version = "1.4.0_50-20250630-abcd1234"
        os.environ['DAZZLESUM_VERSION'] = test_version
        
        # Reload version
        from importlib import reload
        reload(dazzlesum)
        
        # Should still use static version (not injected)
        self.assertEqual(dazzlesum.__version__, original_version)
        
        # Cleanup
        if 'DAZZLESUM_VERSION' in os.environ:
            del os.environ['DAZZLESUM_VERSION']
        reload(dazzlesum)

    def test_version_components_accessible(self):
        """Test that version components can be extracted."""
        version = dazzlesum.__version__
        
        if '_' in version:
            # BASE_BRANCH_BUILD-YYYYMMDD-HASH -- build info is the last
            # '_'-separated token
            base_version, build_info = version.rsplit('_', 1)

            # Should be able to extract build number
            build_parts = build_info.split('-')
            build_number = build_parts[0]
            self.assertTrue(build_number.isdigit())
            
            # Should be able to extract date
            if len(build_parts) >= 2:
                date_part = build_parts[1]
                self.assertEqual(len(date_part), 8)  # YYYYMMDD
                self.assertTrue(date_part.isdigit())
            
            # Should be able to extract commit hash
            if len(build_parts) >= 3:
                commit_part = build_parts[2]
                # Remove -dev suffix if present
                if commit_part.endswith('-dev'):
                    commit_part = commit_part[:-4]
                self.assertEqual(len(commit_part), 8)  # 8-character hash
                self.assertRegex(commit_part, r'^[a-f0-9]{8}$')

    def test_version_comparison_compatibility(self):
        """Test that version can be compared for basic ordering."""
        version = dazzlesum.__version__
        
        # Extract base version for comparison (strip build info + -PHASE)
        if '_' in version:
            base_version = version.split('_')[0]
        else:
            base_version = version
        base_version = base_version.split('-', 1)[0]
        
        # Should be greater than previous version
        self.assertGreater(base_version, "1.2.0")
        
        # Should be semantic version compatible
        parts = base_version.split('.')
        major, minor, patch = map(int, parts[:3])
        self.assertGreaterEqual(major, 1)
        self.assertGreaterEqual(minor, 0)
        self.assertGreaterEqual(patch, 0)


if __name__ == '__main__':
    unittest.main()