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
