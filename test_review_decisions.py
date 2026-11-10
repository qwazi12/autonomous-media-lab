import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from review_decisions import (REQUIRED, export_decision_ui, import_decision, main,
                              record_decision, review_status, snapshot)


class ReviewDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'artifacts'
        self.root.mkdir()
        for name in REQUIRED:
            (self.root / name).write_bytes(b'original test artifact ' + name.encode())
        (self.root / 'review.html').write_text('<html>Test review</html>')

    def record(self, decision='approve'):
        return record_decision(self.root, decision, 'Test reviewer', 'Test decision only', attest_reviewed=True)

    def test_decisions_persist_with_history(self):
        self.assertEqual(review_status(self.root)['status'], 'unreviewed')
        for decision in ('approve', 'reject', 'request_changes'):
            saved = self.record(decision)
            state = review_status(self.root)
            self.assertTrue(state['valid'])
            self.assertEqual(state['status'], decision)
            self.assertEqual(state['decision']['id'], saved['id'])
            self.assertEqual(len(saved['snapshot']['files']['draft.mp4']), 64)
        with sqlite3.connect(self.root / '.review/decisions.sqlite') as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 3)

    def test_changed_added_and_removed_files_invalidate(self):
        self.record()
        (self.root / 'draft.mp4').write_bytes(b'changed')
        state = review_status(self.root)
        self.assertEqual(state['status'], 'invalidated')
        self.assertIn('draft.mp4', state['changed_artifacts'])
        self.record()
        (self.root / 'new-evidence.txt').write_text('new evidence')
        self.assertEqual(review_status(self.root)['status'], 'invalidated')
        self.record()
        (self.root / 'new-evidence.txt').unlink()
        self.assertEqual(review_status(self.root)['status'], 'invalidated')
        self.record()
        (self.root / 'qa.json').unlink()
        state = review_status(self.root)
        self.assertEqual(state['status'], 'invalidated')
        self.assertIn('Required review artifact missing', state['reason'])

    def test_explicit_attestation_and_valid_fields_required(self):
        with self.assertRaisesRegex(ValueError, 'attestation'):
            record_decision(self.root, 'approve', 'Tester')
        with self.assertRaises(ValueError):
            record_decision(self.root, 'automatic', 'Tester', attest_reviewed=True)
        with self.assertRaises(ValueError):
            record_decision(self.root, 'approve', '', attest_reviewed=True)
        self.assertFalse((self.root / '.review/decisions.sqlite').exists())

    def test_stale_payload_fails_closed_and_import_requires_attestation(self):
        payload = {'schema_version': 1, 'snapshot': snapshot(self.root), 'reviewer': 'Tester',
                   'decision': 'request_changes', 'notes': 'Needs work', 'attest_reviewed': True}
        with self.assertRaisesRegex(ValueError, 'attestation'):
            import_decision(self.root, payload)
        saved = import_decision(self.root, payload, attest_reviewed=True)
        self.assertEqual(saved['decision'], 'request_changes')
        (self.root / 'plan.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'differ'):
            import_decision(self.root, payload, attest_reviewed=True)
        with self.assertRaisesRegex(ValueError, 'missing artifact snapshot'):
            import_decision(self.root, {'schema_version': 1}, attest_reviewed=True)

    def test_ui_export_is_offline_escaped_and_does_not_invalidate(self):
        # Unix filenames can contain markup; do not embed them as executable HTML.
        (self.root / '<script>danger.txt').write_text('untrusted')
        before = snapshot(self.root)
        self.record()
        ui = export_decision_ui(self.root)
        page = ui.read_text()
        self.assertNotIn('<script>danger.txt', page)
        self.assertIn('\\u003cscript\\u003e', page)
        self.assertIn('Download decision payload', page)
        self.assertIn('Nothing is uploaded', page)
        self.assertNotIn('fetch(', page)
        self.assertNotIn('https://', page)
        self.assertEqual(snapshot(self.root), before)
        self.assertTrue(review_status(self.root)['valid'])

    def test_symlink_artifacts_and_metadata_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_text('outside')
        link = self.root / 'link'
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            snapshot(self.root)
        link.unlink()
        (self.root / '.review').symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.record()

    def test_hardlinked_metadata_rejected_without_modifying_sources(self):
        metadata = self.root / '.review'
        metadata.mkdir()
        original_database = Path(self.temp.name) / 'original.sqlite'
        with sqlite3.connect(original_database) as connection:
            connection.execute('CREATE TABLE original(value TEXT)')
        before = original_database.read_bytes()
        os.link(original_database, metadata / 'decisions.sqlite')
        with self.assertRaisesRegex(ValueError, 'multiple hard links'):
            self.record()
        self.assertEqual(original_database.read_bytes(), before)
        original_html = Path(self.temp.name) / 'original.html'
        original_html.write_text('Original source document')
        os.link(original_html, metadata / 'decision.html')
        with self.assertRaisesRegex(ValueError, 'multiple hard links'):
            export_decision_ui(self.root)
        self.assertEqual(original_html.read_text(), 'Original source document')

    def test_cli_record_status_and_import(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['record', str(self.root), 'reject', '--reviewer', 'CLI Tester', '--attest-reviewed'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['decision'], 'reject')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['status', str(self.root)]), 0)
            self.assertEqual(main(['export-ui', str(self.root)]), 0)
        payload = Path(self.temp.name) / 'decision.json'
        payload.write_text(json.dumps({'schema_version': 1, 'snapshot': snapshot(self.root),
                                      'decision': 'approve', 'reviewer': 'CLI Tester'}))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['import', str(self.root), str(payload), '--attest-reviewed']), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['record', str(self.root), 'approve', '--reviewer', 'Tester']), 2)


if __name__ == '__main__':
    unittest.main()
