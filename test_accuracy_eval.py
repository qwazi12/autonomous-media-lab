"""Deterministic adversarial accuracy probes; no provider/network calls.

Run: python -m unittest test_accuracy_eval -v
Passing tests demonstrate narrow checks, not semantic accuracy. Previously
uncontained gaps now produce conservative review blockers or withheld evidence;
these results do not establish automatic semantic understanding.
Fixtures are authored/synthetic, not a measured real-world benchmark.
"""
import copy
import tempfile
import unittest
from pathlib import Path

from pipeline import PipelineError, validate_plan
from research import ingest_sources, validate_claims
from workers import AnimeWorker, EducationalWorker, MovieWorker, TVWorker, WorkerError


def index(text='The survey counted 20 birds.', episode='one'):
    return {'scenes': [{'id': 'S1', 'start': 0, 'end': 10,
                        'evidence': [{'id': 'E1', 'text': text, 'episode': episode,
                                      'source_url': 'https://example.org/synthetic', 'as_of': '2026-11-10'}]}]}


def plan(text='The survey counted 20 birds.', refs=None):
    return {'title': 'Synthetic evaluation', 'segments': [
        {'id': 'B1', 'narration': text, 'scene_ids': ['S1'] if refs is None else refs, 'review_notes': []}]}


def numeric_flags(draft, source):
    return [finding for finding in EducationalWorker().inspect(draft, source, {})
            if 'Numeric assertion' in finding['reason'] or finding.get('code') in ('quantity_unit_mismatch','unsupported_numeric_token')]


class ExtractiveGroundingAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'survey.txt'
        self.source.write_text('The survey counted 20 birds. The treatment did not improve survival. The distance was 12 km.\nA different survey counted 99 birds.')
        self.corpus = ingest_sources([{'path': self.source, 'url': 'https://example.org/synthetic-survey', 'accessed_on': '2026-11-10'}])
        self.evidence = self.corpus['sources'][0]['evidence']

    def check(self, text, positions):
        return validate_claims(self.corpus, [{'id': 'claim', 'text': text,
                                            'evidence_ids': [self.evidence[i]['id'] for i in positions]}])

    def test_exact_sentence_supported_with_traceable_citation(self):
        report = self.check('The survey counted 20 birds.', [0])
        self.assertTrue(report['ok'])
        self.assertEqual(report['claims'][0]['citations'][0]['url'], 'https://example.org/synthetic-survey')

    def test_adversarial_mutations_require_review(self):
        cases = [('The survey counted 99 birds.', [0]),
                 ('The survey counted 2 birds.', [0]),
                 ('The treatment improved survival.', [1]),
                 ('The distance was 12 miles.', [2]),
                 ('The survey proved there were exactly 20 birds everywhere.', [0])]
        for text, refs in cases:
            with self.subTest(text=text):
                report = self.check(text, refs)
                self.assertFalse(report['ok'])
                self.assertEqual(report['claims'][0]['status'], 'needs_review')

    def test_correct_paraphrase_is_also_conservatively_reviewed(self):
        self.assertFalse(self.check('Twenty birds were counted in the survey.', [0])['ok'])

    def test_wrong_citation_cannot_borrow_number_from_other_sentence(self):
        self.assertFalse(self.check(self.evidence[3]['text'], [0])['ok'])

    def test_truncated_quote_cannot_remove_negation(self):
        self.assertFalse(self.check('improve survival.', [1])['ok'])

    def test_integrity_check_rejects_edited_quote(self):
        corpus = copy.deepcopy(self.corpus)
        corpus['sources'][0]['evidence'][0]['text'] = 'The survey counted 2000 birds.'
        with self.assertRaises(ValueError):
            validate_claims(corpus, [{'id': 'claim', 'text': 'The survey counted 2000 birds.', 'evidence_ids': [self.evidence[0]['id']]}])

    def test_exact_quote_is_not_truth_verification(self):
        # Source authenticity/truth is explicitly out of scope; a false source
        # statement still passes text matching. This is a limitation probe.
        self.source.write_text('The Moon is made entirely of cheese.')
        corpus = ingest_sources([{'path': self.source, 'url': 'https://example.org/false-fixture', 'accessed_on': '2026-11-10'}])
        item = corpus['sources'][0]['evidence'][0]
        result = validate_claims(corpus, [{'id': 'claim', 'text': item['text'], 'evidence_ids': [item['id']]}])
        self.assertTrue(result['ok'])
        self.assertIn('not independent factual verification', result['scope'])


class StructuralAndNumericAccuracyTests(unittest.TestCase):
    def test_unknown_and_missing_scene_references_rejected(self):
        for refs in [[], ['S999'], ['S1', 'S999']]:
            with self.subTest(refs=refs), self.assertRaises(PipelineError):
                validate_plan(plan(refs=refs), index())

    def test_structural_validity_does_not_imply_semantic_accuracy(self):
        # A real scene ID alone cannot prove the associated narration.
        validate_plan(plan('The survey counted a million dragons.'), index())

    def test_fabricated_numeric_token_flagged(self):
        self.assertTrue(numeric_flags(plan('The survey counted 99 birds.'), index()))

    def test_numeric_evidence_must_belong_to_cited_scene(self):
        source = index()
        second = copy.deepcopy(source['scenes'][0])
        second.update(id='S2', start=10, end=20)
        second['evidence'][0]['text'] = 'The survey counted 99 birds.'
        source['scenes'].append(second)
        self.assertTrue(numeric_flags(plan('The survey counted 99 birds.', ['S1']), source))

    def test_numeric_substring_does_not_support_fabricated_number(self):
        # Desired behavior: "2" must not be supported merely by "20".
        self.assertTrue(numeric_flags(plan('The survey counted 2 birds.'), index()))

    def test_unit_change_is_blocked_for_review(self):
        self.assertTrue(numeric_flags(plan('The distance was 12 miles.'), index('The distance was 12 km.')))

    def test_backward_scene_order_requests_review(self):
        source = index()
        second = copy.deepcopy(source['scenes'][0])
        second.update(id='S2', start=10, end=20)
        source['scenes'].append(second)
        draft = plan(refs=['S2'])
        draft['segments'].append({'id': 'B2', 'narration': 'Earlier scene.', 'scene_ids': ['S1']})
        self.assertTrue(any('backward' in x['reason'] for x in MovieWorker().inspect(draft, source, {})))


class ContinuityAndSpeakerAccuracyTests(unittest.TestCase):
    def test_tv_removes_explicit_future_episode_evidence(self):
        source = index()
        future = copy.deepcopy(source['scenes'][0]['evidence'][0])
        future.update(id='E2', episode='two', text='The culprit is revealed next episode.')
        source['scenes'][0]['evidence'].append(future)
        prepared = TVWorker().prepare(source, {'episode': 'one'})
        self.assertEqual([e['id'] for e in prepared['scenes'][0]['evidence']], ['E1'])
        self.assertEqual(len(source['scenes'][0]['evidence']), 2)

    def test_future_snapshot_and_future_snapshot_entry_rejected(self):
        for worker in [TVWorker(), AnimeWorker()]:
            for snapshot in [{'through_position': 2, 'episodes': []},
                             {'through_position': 1, 'episodes': [{'position': 3}]}]:
                with self.subTest(worker=worker.name, snapshot=snapshot), self.assertRaises(WorkerError):
                    worker.prepare(index(), {'episode': 'two', 'episode_position': 2, 'continuity_snapshot': snapshot})

    def test_prior_snapshot_preserved_but_not_certified(self):
        context = {'episode': 'two', 'episode_position': 2,
                   'continuity_snapshot': {'through_position': 1, 'episodes': [{'position': 1, 'summary': 'Mira is missing.'}]}}
        prepared = TVWorker().prepare(index(), context)
        self.assertFalse(prepared['workflow_context']['continuity_verified'])

    def test_anime_future_tagged_evidence_is_filtered(self):
        prepared = AnimeWorker().prepare(index(episode='two'), {'episode': 'one'})
        self.assertEqual(prepared['scenes'][0]['evidence'], [])

    def test_untagged_evidence_is_withheld_without_semantic_inference(self):
        source = index('In the next episode, Mira is revealed as the culprit.')
        source['scenes'][0]['evidence'][0].pop('episode')
        prepared = TVWorker().prepare(source, {'episode': 'one'})
        self.assertEqual(prepared['scenes'][0]['evidence'], [])

    def test_continuity_comparison_unknown_is_blocked(self):
        source = index('Mira is alive in the current scene.')
        context = {'episode': 'one', 'prior_continuity': ['Mira is alive.']}
        findings = TVWorker().inspect(plan('Mira died before this scene.'), source, context)
        self.assertTrue(any('contradict' in x['reason'].lower() for x in findings))

    def test_explicit_speaker_ambiguity_is_blocked(self):
        source = index('A speech bubble says "Run!"; speaker could be Mira or Ren.')
        findings = AnimeWorker().inspect(plan('Mira shouts "Run!".'), source, {})
        self.assertTrue(any('speaker' in x['reason'].lower() or 'ambig' in x['reason'].lower() for x in findings))


if __name__ == '__main__':
    unittest.main()
