#!/usr/bin/env python3
"""
Tests for incremental update mode (StateCache + update_checksums_for_directory
+ run_update).

The load-bearing test here is
test_update_detects_content_change_with_older_mtime: synced trees (e.g.
Resilio Sync) deliver content changes carrying ORIGIN mtimes that can be older
than the local cache's recorded state. Update must compare stat EQUALITY
against recorded state, never "is mtime newer". A newer-than heuristic fails
this test; the shipped design must not.
"""

import os
import sys
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Add the parent directory to sys.path so we can import dazzlesum
sys.path.insert(0, str(Path(__file__).parent.parent))

import dazzlesum


def write_file(path: Path, content: str):
    path.write_text(content, encoding='utf-8')


class HashCallCounter:
    """Wrap a generator's hash calculator to count real hash computations."""

    def __init__(self, generator):
        self.count = 0
        self._original = generator.calculator.calculate_file_hash
        generator.calculator.calculate_file_hash = self._counting
        self._generator = generator

    def _counting(self, file_path):
        self.count += 1
        return self._original(file_path)


class UpdateModeTestBase(unittest.TestCase):
    """Shared fixture: small tree with a nested subdirectory."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.root = self.temp_dir / "data"
        self.root.mkdir()
        (self.root / "sub").mkdir()
        write_file(self.root / "a.txt", "alpha\n")
        write_file(self.root / "b.txt", "bravo\n")
        write_file(self.root / "sub" / "c.txt", "charlie\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_generator(self, **kwargs):
        return dazzlesum.ChecksumGenerator(
            algorithm='sha256', summary_mode=False,
            generate_individual=True, generate_monolithic=False, **kwargs)

    def first_update(self, generator=None, **kwargs):
        """Initial update run: builds manifests AND the state cache."""
        generator = generator or self.make_generator()
        return generator.run_update(self.root, recursive=True, **kwargs)

    def read_manifest(self, directory: Path):
        return dazzlesum.parse_shasum_file(directory / dazzlesum.SHASUM_FILENAME)


class TestUpdateBasics(UpdateModeTestBase):

    def test_initial_update_creates_manifests_and_cache(self):
        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 3)
        self.assertEqual(totals['added'], 3)
        self.assertTrue((self.root / dazzlesum.SHASUM_FILENAME).exists())
        self.assertTrue((self.root / "sub" / dazzlesum.SHASUM_FILENAME).exists())
        self.assertTrue((self.root / dazzlesum.CACHE_FILENAME).exists())
        self.assertEqual(set(self.read_manifest(self.root)), {"a.txt", "b.txt"})

    def test_unchanged_tree_zero_rehash(self):
        self.first_update()
        manifest_mtime = (self.root / dazzlesum.SHASUM_FILENAME).stat().st_mtime_ns

        generator = self.make_generator()
        counter = HashCallCounter(generator)
        totals = generator.run_update(self.root, recursive=True)

        self.assertEqual(counter.count, 0)
        self.assertEqual(totals['rehashed'], 0)
        self.assertEqual(totals['unchanged'], 3)
        self.assertEqual(totals['rewritten'], 0)
        # Manifest untouched on disk, not merely equal in content
        self.assertEqual(
            (self.root / dazzlesum.SHASUM_FILENAME).stat().st_mtime_ns,
            manifest_mtime)

    def test_changed_file_rehashed_and_manifest_updated(self):
        self.first_update()
        old_hash = self.read_manifest(self.root)["a.txt"]
        write_file(self.root / "a.txt", "ALPHA CHANGED\n")

        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 1)
        self.assertEqual(totals['rewritten'], 1)
        self.assertNotEqual(self.read_manifest(self.root)["a.txt"], old_hash)

    def test_update_detects_content_change_with_older_mtime(self):
        """THE Resilio case: same-size content change delivered with an mtime
        OLDER than the recorded state. A 'newer-than' shortcut misses this
        forever; stat-equality must catch it."""
        self.first_update()
        target = self.root / "a.txt"
        old_hash = self.read_manifest(self.root)["a.txt"]
        old_stat = target.stat()

        # Same byte length, different content ('alpha\n' -> 'omega\n')
        write_file(target, "omega\n")
        self.assertEqual(target.stat().st_size, old_stat.st_size)
        # Backdate mtime one hour BEFORE the recorded state
        older_ns = old_stat.st_mtime_ns - 3_600_000_000_000
        os.utime(target, ns=(older_ns, older_ns))

        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 1)
        self.assertNotEqual(self.read_manifest(self.root)["a.txt"], old_hash)

    def test_added_file(self):
        self.first_update()
        write_file(self.root / "new.txt", "new file\n")
        totals = self.first_update()
        self.assertEqual(totals['added'], 1)
        self.assertEqual(totals['rehashed'], 1)
        self.assertIn("new.txt", self.read_manifest(self.root))

    def test_deleted_file_removed_from_manifest(self):
        self.first_update()
        (self.root / "b.txt").unlink()
        totals = self.first_update()
        self.assertEqual(totals['removed'], 1)
        self.assertNotIn("b.txt", self.read_manifest(self.root))

    def test_keep_missing_retains_deleted_entries(self):
        self.first_update()
        stored_hash = self.read_manifest(self.root)["b.txt"]
        (self.root / "b.txt").unlink()
        totals = self.first_update(keep_missing=True)
        self.assertEqual(totals['removed'], 0)
        self.assertEqual(self.read_manifest(self.root)["b.txt"], stored_hash)

    def test_touched_file_rehashes_but_manifest_untouched(self):
        """mtime bumped, content identical: one rehash to confirm, but the
        manifest must stay byte-identical (no rewrite, no git churn)."""
        self.first_update()
        manifest_mtime = (self.root / dazzlesum.SHASUM_FILENAME).stat().st_mtime_ns
        now_ns = (self.root / "a.txt").stat().st_mtime_ns + 5_000_000_000
        os.utime(self.root / "a.txt", ns=(now_ns, now_ns))

        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 1)
        self.assertEqual(totals['rewritten'], 0)
        self.assertEqual(
            (self.root / dazzlesum.SHASUM_FILENAME).stat().st_mtime_ns,
            manifest_mtime)

        # And the cache learned the new mtime: next run is zero-rehash
        generator = self.make_generator()
        counter = HashCallCounter(generator)
        generator.run_update(self.root, recursive=True)
        self.assertEqual(counter.count, 0)

    def test_external_manifest_edit_triggers_rehash(self):
        """A manifest hash that disagrees with the cache means someone edited
        the manifest externally -- update must re-establish truth."""
        self.first_update()
        manifest_path = self.root / dazzlesum.SHASUM_FILENAME
        good_hash = self.read_manifest(self.root)["a.txt"]
        tampered = manifest_path.read_text(encoding='utf-8').replace(
            good_hash, "0" * len(good_hash))
        manifest_path.write_text(tampered, encoding='utf-8')

        totals = self.first_update()
        self.assertGreaterEqual(totals['rehashed'], 1)
        self.assertEqual(self.read_manifest(self.root)["a.txt"], good_hash)

    def test_cache_file_never_checksummed(self):
        self.first_update()
        self.first_update()
        manifest = self.read_manifest(self.root)
        for name in manifest:
            self.assertFalse(name.startswith(dazzlesum.CACHE_FILENAME))
            self.assertNotEqual(name, dazzlesum.SHASUM_FILENAME)


class TestBootstrap(UpdateModeTestBase):

    def _create_manifests_without_cache(self):
        """Simulate a pre-existing manifest tree with no cache (the D:\\M
        baseline situation): full create, then delete the cache."""
        self.first_update()
        (self.root / dazzlesum.CACHE_FILENAME).unlink()

    def test_bootstrap_hash_reverifies(self):
        self._create_manifests_without_cache()
        generator = self.make_generator()
        counter = HashCallCounter(generator)
        totals = generator.run_update(self.root, recursive=True, bootstrap='hash')
        self.assertEqual(counter.count, 3)
        self.assertEqual(totals['rehashed'], 3)
        self.assertEqual(totals['rewritten'], 0)  # content identical

    def test_bootstrap_trust_seeds_cache_without_rehash(self):
        self._create_manifests_without_cache()
        generator = self.make_generator()
        counter = HashCallCounter(generator)
        totals = generator.run_update(self.root, recursive=True, bootstrap='trust')
        self.assertEqual(counter.count, 0)
        self.assertEqual(totals['unchanged'], 3)

        # Cache is now seeded: a subsequent changed file is still caught
        write_file(self.root / "a.txt", "changed after trust\n")
        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 1)


class TestScopingAndModes(UpdateModeTestBase):

    def test_dirs_from_limits_scope(self):
        self.first_update()
        write_file(self.root / "a.txt", "changed root\n")
        write_file(self.root / "sub" / "c.txt", "changed sub\n")

        # Only nominate 'sub' -- root's change must NOT be picked up
        totals = self.first_update(dirs=["sub"])
        self.assertEqual(totals['dirs'], 1)
        self.assertEqual(totals['rehashed'], 1)

        # Root remains stale until swept
        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 1)

    def test_dirs_outside_root_are_skipped(self):
        self.first_update()
        outside = self.temp_dir / "outside"
        outside.mkdir()
        totals = self.first_update(dirs=[str(outside)])
        self.assertEqual(totals['dirs'], 0)

    def test_paranoid_rehashes_everything(self):
        self.first_update()
        generator = self.make_generator()
        counter = HashCallCounter(generator)
        totals = generator.run_update(self.root, recursive=True, paranoid=True)
        self.assertEqual(counter.count, 3)
        self.assertEqual(totals['rehashed'], 3)
        self.assertEqual(totals['rewritten'], 0)


class TestShadowDirUpdate(UpdateModeTestBase):

    def setUp(self):
        super().setUp()
        self.shadow = self.temp_dir / "shadow"

    def make_shadow_generator(self):
        return self.make_generator(shadow_dir=str(self.shadow))

    def test_shadow_update_places_cache_and_manifests_in_shadow(self):
        generator = self.make_shadow_generator()
        totals = generator.run_update(self.root, recursive=True)
        self.assertEqual(totals['rehashed'], 3)
        self.assertTrue((self.shadow / dazzlesum.SHASUM_FILENAME).exists())
        self.assertTrue((self.shadow / "sub" / dazzlesum.SHASUM_FILENAME).exists())
        self.assertTrue((self.shadow / dazzlesum.CACHE_FILENAME).exists())
        # Source tree stays clean
        self.assertFalse((self.root / dazzlesum.SHASUM_FILENAME).exists())
        self.assertFalse((self.root / dazzlesum.CACHE_FILENAME).exists())

    def test_shadow_update_incremental(self):
        generator = self.make_shadow_generator()
        generator.run_update(self.root, recursive=True)

        generator2 = self.make_shadow_generator()
        counter = HashCallCounter(generator2)
        totals = generator2.run_update(self.root, recursive=True)
        self.assertEqual(counter.count, 0)
        self.assertEqual(totals['unchanged'], 3)

        write_file(self.root / "sub" / "c.txt", "changed\n")
        generator3 = self.make_shadow_generator()
        totals = generator3.run_update(self.root, recursive=True)
        self.assertEqual(totals['rehashed'], 1)


class TestDirsFromParsing(UpdateModeTestBase):
    """CLI-layer parsing of --dirs-from. Regression: PowerShell pipes prepend
    a BOM (U+FEFF) to stdin, and Windows editors add one to files -- either
    silently corrupted the first folder name into '\\ufeffsub' (skipped as
    'not a directory'). Caught by human checklist HV.4, 2026-07-16."""

    def make_args(self, **overrides):
        import argparse
        defaults = dict(
            algorithm='sha256', line_endings='auto', include=None, exclude=None,
            follow_symlinks=False, log=None, shadow_dir=None, yes=True,
            force_python=False, recursive=True, dirs_from=None,
            bootstrap='hash', paranoid=False, keep_missing=False)
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_dirs_from_file_with_bom(self):
        self.first_update()
        write_file(self.root / "sub" / "c.txt", "changed\n")
        dirs_file = self.temp_dir / "dirs.txt"
        with open(dirs_file, 'w', encoding='utf-8-sig') as f:
            f.write("sub\n")

        rc = dazzlesum.execute_update_action(
            self.make_args(dirs_from=str(dirs_file)), self.root)
        self.assertEqual(rc, 0)
        # The change in sub/ must actually have been picked up
        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 0)

    def test_dirs_from_stdin_with_bom(self):
        import io
        self.first_update()
        write_file(self.root / "sub" / "c.txt", "changed via stdin\n")

        real_stdin = sys.stdin
        bom = chr(0xFEFF)
        sys.stdin = io.StringIO(bom + "sub\n")
        try:
            rc = dazzlesum.execute_update_action(
                self.make_args(dirs_from='-'), self.root)
        finally:
            sys.stdin = real_stdin
        self.assertEqual(rc, 0)
        totals = self.first_update()
        self.assertEqual(totals['rehashed'], 0)


class TestExcludeTraversalPruning(UpdateModeTestBase):
    """Regression (2026-07-17, caught live on the D:\\M library): --exclude
    patterns only filtered FILES by basename; FIFODirectoryWalker descended
    into excluded directories anyway, checksumming .git/.private/.sync
    contents (files inside an excluded dir don't match the dir's pattern).
    This is also the true cause of the original library scan's .private and
    shadow-tree self-scan leakage."""

    def setUp(self):
        super().setUp()
        (self.root / ".git" / "objects").mkdir(parents=True)
        write_file(self.root / ".git" / "config", "gitcfg\n")
        write_file(self.root / ".git" / "objects" / "ab12", "blob\n")
        (self.root / ".private" / "notes").mkdir(parents=True)
        write_file(self.root / ".private" / "notes" / "secret.md", "shh\n")

    def test_walker_prunes_excluded_dirs(self):
        walker = dazzlesum.FIFODirectoryWalker(exclude_patterns=['.git', '.private'])
        seen = []
        walker.walk_and_process(self.root, seen.append, recursive=True)
        seen_names = {p.name for p in seen}
        self.assertIn('sub', seen_names)
        self.assertNotIn('.git', seen_names)
        self.assertNotIn('objects', seen_names)
        self.assertNotIn('.private', seen_names)

    def test_update_does_not_manifest_excluded_dirs(self):
        generator = self.make_generator(exclude_patterns=['.git', '.private'])
        totals = generator.run_update(self.root, recursive=True)
        self.assertEqual(totals['dirs'], 2)  # root + sub only
        self.assertFalse((self.root / ".git" / dazzlesum.SHASUM_FILENAME).exists())
        self.assertFalse(
            (self.root / ".private" / "notes" / dazzlesum.SHASUM_FILENAME).exists())
        self.assertTrue((self.root / dazzlesum.SHASUM_FILENAME).exists())

    def test_create_path_does_not_manifest_excluded_dirs(self):
        generator = self.make_generator(exclude_patterns=['.git', '.private'])
        generator.process_directory_tree(self.root, recursive=True)
        self.assertFalse((self.root / ".git" / dazzlesum.SHASUM_FILENAME).exists())
        self.assertFalse(
            (self.root / ".private" / "notes" / dazzlesum.SHASUM_FILENAME).exists())
        self.assertTrue((self.root / "sub" / dazzlesum.SHASUM_FILENAME).exists())


class TestStateCacheUnit(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_roundtrip_and_replace(self):
        with dazzlesum.StateCache(self.temp_dir / "cache.sqlite") as cache:
            entries = {"f.txt": {'size': 10, 'mtime_ns': 123456789,
                                 'algo': 'sha256', 'hash': 'ab' * 32}}
            cache.replace_folder("sub/dir", entries)
            got = cache.get_folder("sub/dir")
            self.assertEqual(got["f.txt"]['size'], 10)
            self.assertEqual(got["f.txt"]['mtime_ns'], 123456789)

            cache.replace_folder("sub/dir", {})
            self.assertEqual(cache.get_folder("sub/dir"), {})

    def test_folder_key_stable_and_posix(self):
        root = self.temp_dir
        sub = root / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(dazzlesum.StateCache.folder_key(sub, root), "a/b")
        self.assertEqual(dazzlesum.StateCache.folder_key(root, root), ".")

    def test_cache_is_regenerable_after_delete(self):
        cache_path = self.temp_dir / "cache.sqlite"
        with dazzlesum.StateCache(cache_path) as cache:
            cache.replace_folder(".", {"x": {'size': 1, 'mtime_ns': 2,
                                             'algo': 'sha256', 'hash': 'ff' * 32}})
        cache_path.unlink()
        with dazzlesum.StateCache(cache_path) as cache:
            self.assertEqual(cache.get_folder("."), {})

    def test_schema_matches_documented_columns(self):
        with dazzlesum.StateCache(self.temp_dir / "cache.sqlite") as cache:
            cols = [row[1] for row in
                    cache.conn.execute("PRAGMA table_info(file_state)")]
        self.assertEqual(cols, ['folder', 'name', 'size', 'mtime_ns',
                                'algo', 'hash', 'scanned_at'])


if __name__ == '__main__':
    unittest.main()
