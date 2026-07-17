#!/usr/bin/env python3
"""
Tests for Windows junction detection in FIFODirectoryWalker.

Regression (2026-07-16, found by profiling update mode): _is_junction()
shelled out to `dir /AL` for every NON-junction directory (~60ms per folder,
hours at library scale) and misclassified any directory reached through a
junction ancestor (resolve() != path for all of them). Detection must be pure
lstat: no subprocess, no resolve().
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Add the parent directory to sys.path so we can import dazzlesum
sys.path.insert(0, str(Path(__file__).parent.parent))

import dazzlesum


class TestJunctionDetection(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.walker = dazzlesum.SymlinkHandler()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_regular_directory_is_not_a_junction(self):
        d = self.temp_dir / "plain"
        d.mkdir()
        self.assertFalse(self.walker._is_junction(d))
        is_link, _ = self.walker.is_symlink_or_junction(d)
        self.assertFalse(is_link)

    def test_detection_never_spawns_a_subprocess(self):
        """The old implementation forked `dir /AL` per directory; walking a
        166K-folder library would spend hours in CreateProcess. Any future
        reintroduction of subprocess-based detection must fail here."""
        d = self.temp_dir / "plain"
        d.mkdir()
        with mock.patch.object(subprocess, 'run',
                               side_effect=AssertionError(
                                   "junction detection must not spawn processes")), \
             mock.patch.object(subprocess, 'Popen',
                               side_effect=AssertionError(
                                   "junction detection must not spawn processes")):
            self.walker._is_junction(d)
            self.walker.is_symlink_or_junction(d)
            self.walker.should_follow_link(d)

    @unittest.skipUnless(os.name == 'nt', "junctions are Windows-only")
    def test_real_junction_is_detected_and_not_followed(self):
        target = self.temp_dir / "target"
        target.mkdir()
        (target / "inside.txt").write_text("x", encoding='utf-8')
        junction = self.temp_dir / "junction"

        # Junctions must be created via PowerShell (mklink via cmd.exe is
        # unreliable from non-interactive shells)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"New-Item -ItemType Junction -Path '{junction}' -Target '{target}' | Out-Null"],
            capture_output=True, text=True)
        if result.returncode != 0 or not junction.exists():
            self.skipTest(f"could not create junction: {result.stderr.strip()}")

        try:
            self.assertTrue(self.walker._is_junction(junction))
            is_link, link_type = self.walker.is_symlink_or_junction(junction)
            self.assertTrue(is_link)
            self.assertEqual(link_type, 'junction')
            # Default (follow_symlinks=False): do not traverse
            self.assertFalse(self.walker.should_follow_link(junction, False))
        finally:
            # Remove the junction itself (never its target's contents)
            os.rmdir(junction)

    @unittest.skipUnless(os.name == 'nt', "Windows-only scenario")
    def test_directory_reached_through_junction_ancestor_is_not_misclassified(self):
        """Old Method 2 flagged EVERY directory under a junction as a junction
        (resolve() != path), which silently skipped whole trees."""
        target = self.temp_dir / "real-tree"
        (target / "sub").mkdir(parents=True)
        junction = self.temp_dir / "via-junction"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"New-Item -ItemType Junction -Path '{junction}' -Target '{target}' | Out-Null"],
            capture_output=True, text=True)
        if result.returncode != 0 or not junction.exists():
            self.skipTest(f"could not create junction: {result.stderr.strip()}")

        try:
            through = junction / "sub"  # a plain dir, reached via junction
            self.assertFalse(self.walker._is_junction(through))
            is_link, _ = self.walker.is_symlink_or_junction(through)
            self.assertFalse(is_link)
        finally:
            os.rmdir(junction)


if __name__ == '__main__':
    unittest.main()
