import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from prepare_lesson import prepare_lesson
from research import ingest_sources


class PrepareLessonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'one.txt').write_text('First fact. Second fact.')
        (self.root / 'two.txt').write_text('Different source.')
        Image.new('RGB', (100, 80), 'blue').save(self.root / 'diagram.png')
        self.corpus = ingest_sources([
            {'path': self.root / 'one.txt', 'url': 'https://example.org/one', 'accessed_on': '2026-11-10', 'published_on': '2025-01-01'},
            {'path': self.root / 'two.txt', 'url': 'https://example.org/two', 'accessed_on': '2026-11-10'}])
        self.card = {'image': 'diagram.png', 'description': 'Operator authored diagram description.',
                     'evidence_ids': [self.corpus['sources'][0]['evidence'][0]['id']]}

    def prepare(self, cards=None):
        return prepare_lesson(self.corpus, cards if cards is not None else [self.card], image_base=self.root)

    def test_quotes_provenance_paths_and_image_hash(self):
        card = self.prepare()['cards'][0]
        self.assertEqual(card['evidence'], ['First fact.'])
        self.assertEqual(card['image'], str((self.root / 'diagram.png').resolve()))
        self.assertEqual(card['source_url'], 'https://example.org/one')
        self.assertEqual(card['as_of'], '2025-01-01')
        self.assertEqual(card['provenance']['as_of_basis'], 'published_on')
        self.assertEqual(card['image_sha256'], hashlib.sha256((self.root / 'diagram.png').read_bytes()).hexdigest())

    def test_access_date_fallback(self):
        self.card['evidence_ids'] = [self.corpus['sources'][1]['evidence'][0]['id']]
        card = self.prepare()['cards'][0]
        self.assertEqual(card['as_of'], '2026-11-10')
        self.assertEqual(card['provenance']['as_of_basis'], 'accessed_on')

    def test_cross_source_card_rejected_then_explicit_split_passes(self):
        other = copy.deepcopy(self.card)
        other['evidence_ids'] = [self.corpus['sources'][1]['evidence'][0]['id']]
        mixed = copy.deepcopy(self.card)
        mixed['evidence_ids'] += other['evidence_ids']
        with self.assertRaisesRegex(ValueError, 'split'):
            self.prepare([mixed])
        self.assertEqual(len(self.prepare([self.card, other])['cards']), 2)

    def test_missing_duplicate_unknown_references_fail(self):
        for ids in [[], ['not-found'], self.card['evidence_ids'] * 2, [5]]:
            card = {**self.card, 'evidence_ids': ids}
            with self.assertRaises(ValueError):
                self.prepare([card])

    def test_changed_original_and_tampered_corpus_fail(self):
        altered = copy.deepcopy(self.corpus)
        altered['sources'][0]['evidence'][0]['text'] = 'Fabricated.'
        with self.assertRaises(ValueError):
            prepare_lesson(altered, [self.card], image_base=self.root)
        (self.root / 'one.txt').write_text('Changed.')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.prepare()

    def test_bad_image_and_empty_description_fail(self):
        for change in [{'image': 'https://example.org/image.png'}, {'description': ''}]:
            with self.assertRaises(ValueError):
                self.prepare([{**self.card, **change}])
        (self.root / 'fake.png').write_text('Not image data.')
        with self.assertRaises(OSError):
            self.prepare([{**self.card, 'image': 'fake.png'}])

    def test_cli_and_pipeline_manifest_contract(self):
        corpus_path = self.root / 'corpus.json'
        cards_path = self.root / 'cards.json'
        manifest_path = self.root / 'lesson.json'
        corpus_path.write_text(json.dumps(self.corpus))
        cards_path.write_text(json.dumps({'cards': [self.card]}))
        command = [sys.executable, str(Path(__file__).with_name('prepare_lesson.py')), str(corpus_path), str(cards_path), '--output', str(manifest_path)]
        run = subprocess.run(command, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        again = subprocess.run(command, capture_output=True)
        self.assertNotEqual(again.returncode, 0)
        # Exercise actual pipeline ingestion, with only FFmpeg work mocked.
        import pipeline
        output = self.root / 'run'
        output.mkdir()
        with patch.object(pipeline, 'ff'):
            index = pipeline.panel_source(manifest_path, output, educational=True)
        self.assertEqual(index['scenes'][0]['evidence'][0]['text'], 'First fact.')
        self.assertEqual(index['scenes'][0]['evidence'][0]['source_url'], 'https://example.org/one')
        self.assertEqual(index['scenes'][0]['evidence'][0]['as_of'], '2025-01-01')


if __name__ == '__main__':
    unittest.main()
