#!/usr/bin/env python3
"""
Basic tests for dazzlesum functionality.
"""

import unittest
import tempfile
import os
import sys
from pathlib import Path

# Add the parent directory to sys.path so we can import dazzlesum
sys.path.insert(0, str(Path(__file__).parent.parent))

import dazzlesum


class TestBasicFunctionality(unittest.TestCase):
    """Test basic dazzlesum functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.test_dir, "test.txt")
        with open(self.test_file, 'w') as f:
            f.write("Hello, world!")

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_import_works(self):
        """Test that we can import dazzlesum."""
        self.assertTrue(hasattr(dazzlesum, 'main'))
        self.assertTrue(hasattr(dazzlesum, '__version__'))

    def test_native_tool_detection_reads_both_streams(self):
        """U4 regression (v1.5.0-alpha.7): detection must not trust exit
        codes or single streams -- real certutil prints usage to STDOUT with
        rc=1, and fsum 2.51 prints its banner to STDERR. The old checks
        rejected every native tool, silently forcing Python hashing."""
        import sys as _sys
        from unittest import mock

        calc = dazzlesum.DazzleHashCalculator('sha256')
        hashing_mod = _sys.modules[type(calc).__module__]

        def fake_run(cmd, **kwargs):
            r = mock.Mock()
            tool = cmd[0]
            if tool == 'certutil':
                r.returncode, r.stdout, r.stderr = 1, 'Usage:\n  CertUtil [Options]', ''
            elif tool == 'fsum':
                r.returncode, r.stdout, r.stderr = 0, '', 'SlavaSoft Optimizing Checksum Utility - fsum 2.51'
            else:
                raise FileNotFoundError(tool)
            return r

        with mock.patch.object(hashing_mod.subprocess, 'run', side_effect=fake_run):
            self.assertTrue(calc._tool_available('certutil'))
            self.assertTrue(calc._tool_available('fsum'))
            self.assertFalse(calc._tool_available('no-such-tool'))

    def test_python_first_hash_ordering(self):
        """Engine-order regression (v1.5.0-alpha.7): hashlib-supported
        algorithms must hash in-process. Native tools cost a per-file
        subprocess spawn (~75ms for certutil, >100x slower on small files)
        and hash raw bytes, bypassing line-ending normalization -- so a
        native digest would not even match existing manifests for CRLF
        text files. Native is reserved for algorithms hashlib lacks."""
        import hashlib as _hashlib
        from unittest import mock

        content = b'\x00binary\r\ncontent'  # null byte: never normalized
        blob = os.path.join(self.test_dir, 'ordering.bin')
        with open(blob, 'wb') as f:
            f.write(content)

        calc = dazzlesum.DazzleHashCalculator('sha256')
        # hashlib covers sha256, so no native tool is probed at all
        self.assertIsNone(calc.native_tool)

        # Even with a native tool forced onto the calculator, the hot path
        # must not consult it for a hashlib-supported algorithm
        calc.native_tool = 'certutil'
        with mock.patch.object(type(calc), '_calculate_with_native_tool') as native:
            digest = calc.calculate_file_hash(Path(blob))
        native.assert_not_called()
        self.assertEqual(digest, _hashlib.sha256(content).hexdigest())

    def test_force_python_removed_and_python_is_the_engine(self):
        """--force-python was removed in v1.5.1.

        Python hashlib became the engine for every algorithm this CLI offers
        in 1.5.0, leaving the flag nothing to force. Honouring it could only
        REMOVE capability: on a restricted-crypto build where hashlib cannot
        construct md5/sha1, the native tool is the only working path, so
        suppressing it would turn a working run into a crash.

        Pins both halves -- the flag is gone from the parser, and the
        behavior it claimed to provide is now unconditional.
        """
        parser = dazzlesum.create_argument_parser()
        with self.assertRaises(SystemExit) as caught:
            parser.parse_args(['create', '--force-python', self.test_dir])
        self.assertEqual(caught.exception.code, 2, 'argparse usage error')

        # The behavior the flag described is now the default, unconditionally
        for algorithm in dazzlesum.SUPPORTED_ALGORITHMS:
            calc = dazzlesum.DazzleHashCalculator(algorithm)
            self.assertIsNone(calc.native_tool,
                              f'{algorithm} should hash in-process')

    def test_unc_layer_via_filekit(self):
        """Guard (v1.5.0-alpha.7): the UNC layer must be genuinely wired.
        The old direct unctools soft-import silently failed for months
        (HAVE_UNCTOOLS False on every modern install) with no test noticing;
        UNC support now flows through dazzle-filekit and must be present."""
        self.assertTrue(dazzlesum.HAVE_UNCTOOLS)
        self.assertTrue(callable(dazzlesum.is_unc_path))
        self.assertFalse(dazzlesum.is_unc_path('C:/plain/local/path'))
        self.assertFalse(hasattr(dazzlesum, 'normalize_path'),
                         "normalize_path was removed from the public surface in 1.5.0")

    def test_version_string(self):
        """Test that version string exists and is reasonable."""
        version = dazzlesum.__version__
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)
        # Should be "1.4.2" or the repokit-stamped form
        # "1.4.2_main_85-20260717-9310051e" (BASE_BRANCH_BUILD-YYYYMMDD-HASH)
        if '_' in version:
            # Stamped build format; parse from the right so branch names
            # containing '-' or '_' stay safe
            prefix, build_info = version.rsplit('_', 1)
            base_version = prefix.split('_', 1)[0]
            parts = base_version.split('.')
            self.assertGreaterEqual(len(parts), 3)
            # Check build info format: Build#-YYYYMMDD-CommitHash[-dev]
            self.assertRegex(build_info, r'^\d+-\d{8}-[a-f0-9]{8}')
        else:
            # Basic version format
            parts = version.split('.')
            self.assertGreaterEqual(len(parts), 2)

    def test_supported_algorithms(self):
        """Test that supported algorithms are defined."""
        self.assertTrue(hasattr(dazzlesum, 'SUPPORTED_ALGORITHMS'))
        algorithms = dazzlesum.SUPPORTED_ALGORITHMS
        self.assertIn('sha256', algorithms)
        self.assertIn('md5', algorithms)
        self.assertIn('sha1', algorithms)
        self.assertIn('sha512', algorithms)

    def test_default_algorithm(self):
        """Test that default algorithm is defined."""
        self.assertTrue(hasattr(dazzlesum, 'DEFAULT_ALGORITHM'))
        default = dazzlesum.DEFAULT_ALGORITHM
        self.assertEqual(default, 'sha256')

    def test_shasum_filename_constant(self):
        """Test that SHASUM_FILENAME constant is defined."""
        self.assertTrue(hasattr(dazzlesum, 'SHASUM_FILENAME'))
        filename = dazzlesum.SHASUM_FILENAME
        self.assertEqual(filename, '.shasum')

    def test_calculate_hashes_dazzlelib_shape(self):
        """calculate_hashes emits the dazzle-lib HashResultDict shape.

        The DazzleLib cross-layer boundary: hex digests keyed by algorithm
        name, matching filekit verification.calculate_file_hash output.
        """
        calc = dazzlesum.DazzleHashCalculator(algorithm='sha256')
        result = calc.calculate_hashes(Path(self.test_file))
        self.assertEqual(list(result.keys()), ['sha256'])
        digest = result['sha256']
        self.assertIsInstance(digest, str)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, calc.calculate_file_hash(Path(self.test_file)))


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions if accessible."""

    def test_is_windows_function(self):
        """Test that is_windows function exists and returns boolean."""
        # The function might be imported or defined
        if hasattr(dazzlesum, 'is_windows'):
            result = dazzlesum.is_windows()
            self.assertIsInstance(result, bool)


class TestShadowDirectoryIntegration(unittest.TestCase):
    """Test shadow directory integration with main functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.source_dir = Path(self.temp_dir) / "source"
        self.shadow_dir = Path(self.temp_dir) / "shadow"
        
        # Create source directory with test files
        self.source_dir.mkdir()
        (self.source_dir / "file1.txt").write_text("Test content 1")
        (self.source_dir / "file2.txt").write_text("Test content 2")
        
        # Create subdirectory
        subdir = self.source_dir / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("Test content 3")

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_shadow_directory_with_checksum_generator(self):
        """Test ChecksumGenerator works correctly with shadow directories."""
        # Create generator with shadow directory
        generator = dazzlesum.ChecksumGenerator(
            algorithm='sha256',
            shadow_dir=str(self.shadow_dir),
            generate_individual=True
        )
        
        # Process directory tree
        generator.process_directory_tree(self.source_dir, recursive=True)
        
        # Verify source directory is clean
        source_files = list(self.source_dir.rglob('*'))
        checksum_files = [f for f in source_files if f.name == '.shasum']
        self.assertEqual(len(checksum_files), 0, "Source directory should not contain .shasum files")
        
        # Verify shadow directory has checksums
        shadow_root_shasum = self.shadow_dir / ".shasum"
        shadow_subdir_shasum = self.shadow_dir / "subdir" / ".shasum"
        
        self.assertTrue(shadow_root_shasum.exists(), "Shadow root should contain .shasum file")
        self.assertTrue(shadow_subdir_shasum.exists(), "Shadow subdir should contain .shasum file")

    def test_shadow_directory_verification_workflow(self):
        """Test complete workflow: generate, modify, verify with shadow directory."""
        # Generate checksums
        generator = dazzlesum.ChecksumGenerator(
            algorithm='sha256',
            shadow_dir=str(self.shadow_dir),
            generate_individual=True
        )
        generator.process_directory_tree(self.source_dir, recursive=True)
        
        # Verify checksums (should pass)
        results = generator.verify_checksums_in_directory(self.source_dir)
        self.assertNotIn('error', results)
        self.assertEqual(len(results['failed']), 0)
        
        # Modify a file
        (self.source_dir / "file1.txt").write_text("Modified content")
        
        # Verify again (should fail)
        results = generator.verify_checksums_in_directory(self.source_dir)
        self.assertEqual(len(results['failed']), 1)
        self.assertIn('file1.txt', [f['filename'] for f in results['failed']])

    def test_shadow_directory_monolithic_integration(self):
        """Test monolithic mode integration with shadow directories."""
        # Create generator with monolithic mode and shadow directory
        generator = dazzlesum.ChecksumGenerator(
            algorithm='sha256',
            shadow_dir=str(self.shadow_dir),
            generate_monolithic=True,
            generate_individual=False
        )
        
        # Process directory tree
        generator.process_directory_tree(self.source_dir, recursive=True)
        
        # Verify source directory is clean
        source_files = list(self.source_dir.rglob('*'))
        checksum_files = [f for f in source_files if f.name.startswith('checksums.')]
        self.assertEqual(len(checksum_files), 0, "Source directory should not contain monolithic files")
        
        # Verify shadow directory has monolithic file
        shadow_monolithic = self.shadow_dir / "checksums.sha256"
        self.assertTrue(shadow_monolithic.exists(), "Shadow directory should contain monolithic file")
        
        # Verify content includes all files
        content = shadow_monolithic.read_text()
        self.assertIn("file1.txt", content)
        self.assertIn("file2.txt", content)
        self.assertIn("subdir/file3.txt", content)

    def test_shadow_directory_constants_and_classes(self):
        """Test that shadow directory classes and constants are accessible."""
        # Test ShadowPathResolver class exists
        self.assertTrue(hasattr(dazzlesum, 'ShadowPathResolver'))
        
        # Test we can create an instance
        resolver = dazzlesum.ShadowPathResolver(self.source_dir, self.shadow_dir)
        self.assertIsNotNone(resolver)
        
        # Test basic functionality
        shadow_path = resolver.get_shadow_shasum_path(self.source_dir)
        expected = self.shadow_dir / ".shasum"
        self.assertEqual(shadow_path, expected)


if __name__ == '__main__':
    unittest.main()
