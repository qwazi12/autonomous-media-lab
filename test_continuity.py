import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from continuity import ContinuityLedger, ContinuityError


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'continuity.sqlite'
        self.ledger = ContinuityLedger(self.db, 'series-a')

    def episode(self, number=1, value='alive', canonical='Mira'):
        quote = f'Mira is {value}. Red is called {canonical}.'
        refs = [{'id': 'E1', 'quote': quote}]
        return {'episode_id': f'S01E{number:02}', 'position': number, 'source_sha256': str(number) * 64,
                'evidence': [{'id': 'E1', 'text': quote, 'scene_id': 'S00001', 'start': 0, 'end': 4}],
                'facts': [{'subject': 'Mira', 'predicate': 'status', 'value': value,
                           'evidence_refs': refs, 'operator_reviewed': True}],
                'aliases': [{'alias': 'Red', 'canonical': canonical, 'evidence_refs': refs, 'operator_reviewed': True}]}

    def test_persistence_and_exact_citations(self):
        self.ledger.record_episode(self.episode())
        result = ContinuityLedger(self.db, 'series-a').context(1)
        self.assertEqual(result['facts'][0]['evidence'][0]['scene_id'], 'S00001')
        self.assertEqual(result['facts'][0]['source_sha256'], '1' * 64)
        self.assertEqual(result['facts'][0]['semantic_verification'], 'operator_reviewed_only')

    def test_spoiler_boundary_excludes_future_conflicts(self):
        self.ledger.record_episode(self.episode())
        self.ledger.record_episode(self.episode(2, 'dead', 'Other'))
        past = self.ledger.context(1)
        self.assertEqual(len(past['facts']), 1)
        self.assertEqual(past['contradictions'], [])
        self.assertEqual(past['alias_conflicts'], [])
        self.assertNotIn('S01E02', json.dumps(past))
        self.assertEqual(self.ledger.context(0)['episodes'], [])

    def test_conflicts_preserved_not_resolved(self):
        for entry in (self.episode(), self.episode(2, 'dead', 'Other')):
            self.ledger.record_episode(entry)
        result = self.ledger.context(2)
        self.assertEqual(result['contradictions'][0]['values'], ['alive', 'dead'])
        self.assertEqual(result['alias_conflicts'][0]['candidates'], ['Mira', 'Other'])
        self.assertEqual(len(result['facts']), 2)
        self.assertEqual(len(result['aliases']), 2)

    def test_duplicate_idempotent_and_changes_refused(self):
        first = self.ledger.record_episode(self.episode())
        replay = self.ledger.record_episode(self.episode())
        self.assertTrue(first['created'])
        self.assertFalse(replay['created'])
        self.assertEqual(first['digest'], replay['digest'])
        with self.assertRaises(ContinuityError):
            self.ledger.record_episode(self.episode(value='dead'))
        self.assertEqual(len(self.ledger.context(10)['episodes']), 1)

    def test_position_collision_refused(self):
        self.ledger.record_episode(self.episode())
        entry = self.episode()
        entry['episode_id'] = 'DifferentEpisode'
        with self.assertRaises(ContinuityError):
            self.ledger.record_episode(entry)

    def test_series_isolation(self):
        self.ledger.record_episode(self.episode())
        other = ContinuityLedger(self.db, 'series-b')
        self.assertEqual(other.context(10)['facts'], [])
        other.record_episode(self.episode(value='dead'))
        self.assertEqual(self.ledger.context(1)['facts'][0]['value'], 'alive')

    def test_requires_explicit_review(self):
        for value in (False, 1, 'true', None):
            entry = self.episode()
            entry['facts'][0]['operator_reviewed'] = value
            with self.subTest(value=value), self.assertRaises(ContinuityError):
                self.ledger.record_episode(entry)
        self.assertEqual(self.ledger.context(1)['facts'], [])

    def test_missing_or_invented_evidence_rejected(self):
        for refs in ([], [{'id': 'unknown', 'quote': 'Mira'}], [{'id': 'E1', 'quote': 'Never spoken'}]):
            entry = self.episode()
            entry['facts'][0]['evidence_refs'] = refs
            with self.subTest(refs=refs), self.assertRaises(ContinuityError):
                self.ledger.record_episode(entry)

    def test_future_episode_citation_cannot_cross_boundary(self):
        later = self.episode(2)
        later['evidence'][0]['id'] = 'future'
        for kind in ('facts', 'aliases'):
            later[kind][0]['evidence_refs'][0]['id'] = 'future'
        self.ledger.record_episode(later)
        current = self.episode()
        current['facts'][0]['evidence_refs'] = [{'id': 'future', 'quote': 'Mira'}]
        with self.assertRaises(ContinuityError):
            self.ledger.record_episode(current)

    def test_deterministic_out_of_order_updates(self):
        self.ledger.record_episode(self.episode(2, 'dead'))
        self.ledger.record_episode(self.episode())
        first = self.ledger.context(2)
        self.assertEqual([x['position'] for x in first['episodes']], [1, 2])
        self.assertEqual(first, self.ledger.context(2))

    def test_atomic_concurrent_dedup(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.ledger.record_episode(self.episode()), range(4)))
        self.assertEqual(sum(item['created'] for item in results), 1)

    def test_invalid_alias_rolls_back_entire_episode(self):
        entry = self.episode()
        entry['aliases'][0]['evidence_refs'] = []
        with self.assertRaises(ContinuityError):
            self.ledger.record_episode(entry)
        self.assertEqual(self.ledger.context(10)['episodes'], [])

    def test_no_assertions_generated_from_raw_evidence(self):
        entry = self.episode()
        entry['facts'], entry['aliases'] = [], []
        self.ledger.record_episode(entry)
        result = self.ledger.context(1)
        self.assertEqual(result['facts'], [])
        self.assertEqual(result['aliases'], [])

    def test_invalid_boundaries_and_times(self):
        for boundary in (True, -1, 1.5, None):
            with self.subTest(boundary=boundary), self.assertRaises(ContinuityError):
                self.ledger.context(boundary)
        for start, end in ((True, 2), (0, float('inf')), (2, 1), (-1, 2)):
            entry = self.episode()
            entry['evidence'][0].update(start=start, end=end)
            with self.subTest(start=start, end=end), self.assertRaises(ContinuityError):
                self.ledger.record_episode(entry)

    def test_content_integrity_on_read(self):
        self.ledger.record_episode(self.episode())
        with sqlite3.connect(self.db) as conn:
            data = conn.execute('SELECT payload FROM continuity_episodes').fetchone()[0]
            conn.execute('UPDATE continuity_episodes SET payload=?', (data.replace('alive', 'dead'),))
        with self.assertRaisesRegex(ContinuityError, 'integrity'):
            self.ledger.context(1)

    def test_tampered_order_cannot_expose_future_episode(self):
        self.ledger.record_episode(self.episode(2))
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE continuity_episodes SET position=1')
        with self.assertRaisesRegex(ContinuityError, 'integrity'):
            self.ledger.context(1)

    def test_database_symlink_refused(self):
        target = Path(self.tmp.name) / 'source'
        target.write_bytes(b'preserve source')
        link = Path(self.tmp.name) / 'linked.sqlite'
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(ContinuityError):
            ContinuityLedger(link, 'series')
        self.assertEqual(target.read_bytes(), b'preserve source')

    def test_database_symlink_parent_refused(self):
        parent = Path(self.tmp.name) / 'real'
        parent.mkdir()
        link = Path(self.tmp.name) / 'alias'
        try:
            link.symlink_to(parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(ContinuityError):
            ContinuityLedger(link / 'nested' / 'new.sqlite', 'series')
        self.assertFalse((parent / 'nested').exists())

    def test_database_hardlink_refused(self):
        link = Path(self.tmp.name) / 'hardlinked.sqlite'
        before = self.db.read_bytes()
        try:
            os.link(self.db, link)
        except (OSError, NotImplementedError):
            self.skipTest('Hardlinks unavailable')
        with self.assertRaises(ContinuityError):
            ContinuityLedger(link, 'other')
        self.assertEqual(self.db.read_bytes(), before)
        with self.assertRaises(ContinuityError):
            self.ledger.record_episode(self.episode())

    def test_sqlite_companion_links_refused(self):
        target = Path(self.tmp.name) / 'source'
        target.write_bytes(b'preserve source')
        for suffix in ('-journal', '-wal', '-shm'):
            link = Path(str(self.db) + suffix)
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('Symlinks unavailable')
            with self.subTest(suffix=suffix), self.assertRaises(ContinuityError):
                self.ledger.record_episode(self.episode())
            link.unlink()
        self.assertEqual(target.read_bytes(), b'preserve source')

    def test_reordered_assertions_and_evidence_dedup(self):
        entry = self.episode()
        second = copy.deepcopy(entry['facts'][0])
        second['predicate'] = 'observed_status'
        entry['facts'].append(second)
        self.ledger.record_episode(entry)
        entry['facts'].reverse()
        self.assertFalse(self.ledger.record_episode(entry)['created'])


if __name__ == '__main__':
    unittest.main()
