import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from checkpoints import Checkpoints, CheckpointError, signature


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source.txt'
        self.source.write_text('input', encoding='utf-8')
        self.root = self.base / 'output'
        self.sig = signature({'workflow': 'movie', 'private': 'not-to-persist'}, [self.source])
        self.cp = Checkpoints(self.root, self.sig)
        self.artifact = self.root / 'index.json'
        self.artifact.write_text('{"scenes": []}', encoding='utf-8')

    def test_signature_stable_and_content_sensitive(self):
        self.assertEqual(self.sig, signature({'private': 'not-to-persist', 'workflow': 'movie'}, [self.source]))
        self.source.write_text('changed', encoding='utf-8')
        self.assertNotEqual(self.sig, signature({'workflow': 'movie', 'private': 'not-to-persist'}, [self.source]))
        self.assertNotIn('not-to-persist', self.cp.path.read_text())

    def test_missing_input_fails(self):
        with self.assertRaises(CheckpointError):
            signature({}, [self.base / 'missing'])

    def test_record_resume_and_missing_stage(self):
        self.assertFalse(self.cp.valid('indexed'))
        self.cp.record('indexed', [self.artifact])
        self.assertTrue(self.cp.valid('indexed'))
        reopened = Checkpoints(self.root, self.sig, resume=True)
        self.assertTrue(reopened.valid('indexed'))
        self.assertFalse(reopened.valid('planned'))

    def test_signature_mismatch_and_overwrite_refused(self):
        before = self.cp.path.read_bytes()
        with self.assertRaises(CheckpointError):
            Checkpoints(self.root, 'different', resume=True)
        with self.assertRaises(CheckpointError):
            Checkpoints(self.root, self.sig)
        self.assertEqual(before, self.cp.path.read_bytes())

    def test_missing_manifest_resume_refused(self):
        with self.assertRaises(CheckpointError):
            Checkpoints(self.base / 'new-root', self.sig, resume=True)

    def test_tamper(self):
        self.cp.record('indexed', [self.artifact])
        self.artifact.write_text('changed', encoding='utf-8')
        self.assertFalse(self.cp.valid('indexed'))

    def test_missing_artifact(self):
        self.cp.record('indexed', [self.artifact])
        self.artifact.unlink()
        self.assertFalse(self.cp.valid('indexed'))

    def test_invalidate_keeps_artifacts(self):
        self.cp.record('indexed', [self.artifact])
        self.cp.invalidate('indexed')
        self.assertFalse(self.cp.valid('indexed'))
        self.assertTrue(self.artifact.exists())
        self.cp.invalidate('indexed')

    def test_refuse_outside_and_traversal(self):
        for value in (self.source, '../source.txt', self.cp.path, self.cp.lock_path):
            with self.subTest(value=value), self.assertRaises(CheckpointError):
                self.cp.record('indexed', [value])
        self.assertFalse(self.cp.valid('indexed'))

    def test_external_symlink_refused(self):
        link = self.root / 'link.txt'
        try:
            link.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(CheckpointError):
            self.cp.record('indexed', [link])

    def test_forged_external_record_invalid(self):
        data = json.loads(self.cp.path.read_text())
        data['stages']['forged'] = {'../source.txt': 'not-a-real-hash'}
        self.cp.path.write_text(json.dumps(data), encoding='utf-8')
        self.assertFalse(self.cp.valid('forged'))

    def test_atomic_record_failure_preserves_previous(self):
        self.cp.record('indexed', [self.artifact])
        before = self.cp.path.read_bytes()
        with patch('checkpoints.os.replace', side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):
                self.cp.record('planned', [self.artifact])
        self.assertEqual(before, self.cp.path.read_bytes())
        self.assertTrue(self.cp.valid('indexed'))
        self.assertFalse(self.cp.valid('planned'))
        self.assertEqual(list(self.root.glob('.checkpoint-*.tmp')), [])

    def test_unreadable_artifact_does_not_partially_record(self):
        before = self.cp.path.read_bytes()
        with self.assertRaises(CheckpointError):
            self.cp.record('indexed', [self.artifact, 'missing.json'])
        self.assertEqual(before, self.cp.path.read_bytes())

    def test_lock_exclusive_no_stealing_and_nested(self):
        other = Checkpoints(self.root, self.sig, resume=True)
        with self.cp.lock():
            with self.cp:
                self.cp.record('indexed', ['index.json'])
                self.assertTrue(self.cp.valid('indexed'))
            with self.assertRaises(CheckpointError):
                other.record('other', ['index.json'])
        self.assertFalse(self.cp.lock_path.exists())
        self.cp.lock_path.write_text('stale lock', encoding='utf-8')
        with self.assertRaises(CheckpointError):
            self.cp.valid('indexed')
        self.assertEqual(self.cp.lock_path.read_text(), 'stale lock')

    def test_lock_released_on_error(self):
        with self.assertRaises(RuntimeError):
            with self.cp.lock():
                raise RuntimeError('test')
        self.assertFalse(self.cp.lock_path.exists())

    def test_updates_refresh_other_stage_records(self):
        other = Checkpoints(self.root, self.sig, resume=True)
        self.cp.record('indexed', [self.artifact])
        other.record('planned', [self.artifact])
        self.assertTrue(self.cp.valid('indexed'))
        self.assertTrue(self.cp.valid('planned'))


if __name__ == '__main__':
    unittest.main()
