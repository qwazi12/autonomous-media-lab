import copy
import unittest
from evidence_guards import filter_episode, inspect_guards, quantities


def source(text='The distance was 12 km.', **metadata):
    return {'scenes': [{'id': 'S1', 'start': 0, 'end': 10, 'evidence': [
        {'id': 'E1', 'text': text, 'episode': 'one', **metadata}]}]}


def draft(text='The distance was 12 km.'):
    return {'segments': [{'id': 'B1', 'narration': text, 'scene_ids': ['S1']}]}


class EvidenceGuardTests(unittest.TestCase):
    def codes(self, text, evidence, context=None, workflow='educational'):
        findings = inspect_guards(draft(text), evidence, context or {}, workflow)
        for item in findings:
            self.assertEqual(item['severity'], 'blocking')
            self.assertTrue(item['requires_review'])
            self.assertIn('evidence', item)
        return {item['code'] for item in findings}

    def test_numeric_exact_tokens_not_substrings(self):
        self.assertIn('unsupported_numeric_token', self.codes('There are 2 birds.', source('There are 20 birds.')))
        self.assertNotIn('unsupported_numeric_token', self.codes('There are 20 birds.', source('There are 20 birds.')))
        self.assertEqual([q['number'] for q in quantities('Count: 20. Value: -1.5. Cost: $12.')], ['20', '-1.5', '12'])

    def test_number_unit_pair_not_independent_membership(self):
        self.assertIn('quantity_unit_mismatch', self.codes('Travel 12 miles.', source('Travel 12 km then 20 miles.')))
        self.assertNotIn('quantity_unit_mismatch', self.codes('Travel 12 kilometers.', source('Travel 12 km.')))
        self.assertIn('quantity_unit_mismatch', self.codes('Travel 12.', source('Travel 12 km.')))

    def test_percentage_temperature_currency_units(self):
        cases = [('Value is 12%.', 'Value is 12 kg.'), ('Temperature: 12 °F.', 'Temperature: 12 °C.'), ('Cost: €12.', 'Cost: $12.')]
        for text, evidence in cases:
            with self.subTest(text=text):
                self.assertIn('quantity_unit_mismatch', self.codes(text, source(evidence)))

    def test_quantity_support_is_citation_scoped(self):
        index = source('There are 20 birds.')
        other = source('There are 99 birds.')['scenes'][0]
        other['id'] = 'S2'
        index['scenes'].append(other)
        self.assertIn('unsupported_numeric_token', self.codes('There are 99 birds.', index))

    def test_filter_withholds_untagged_and_other_episode(self):
        index = source()
        index['scenes'][0]['evidence'] += [{'id': 'E2', 'text': 'No episode.'}, {'id': 'E3', 'text': 'Future reveal.', 'episode': 'two'}]
        original = copy.deepcopy(index)
        filtered, findings = filter_episode(index, {'episode': 'one'})
        self.assertEqual(index, original)
        self.assertEqual([e['id'] for e in filtered['scenes'][0]['evidence']], ['E1'])
        self.assertEqual({f['code'] for f in findings}, {'episode_provenance_unknown', 'episode_mismatch'})
        self.assertEqual(findings[0]['evidence'][0]['evidence_id'], 'E2')

    def test_filter_withholds_unscoped_visual_description(self):
        index = source()
        index['scenes'][0]['visual_description'] = 'A reveal from an unknown episode.'
        filtered, findings = filter_episode(index, {'episode': 'one'})
        self.assertIsNone(filtered['scenes'][0]['visual_description'])
        self.assertIn('visual_episode_provenance_unknown', [f['code'] for f in findings])

    def test_unscoped_temporal_rows_and_uncertainties_never_reach_model(self):
        index = source()
        scene = index['scenes'][0]
        scene['temporal_observations'] = [{'text': 'Future episode reveal.'}]
        scene['vision_uncertainties'] = ['Identity visible next episode.']
        filtered, findings = filter_episode(index, {'episode': 'one'})
        self.assertNotIn('temporal_observations', filtered['scenes'][0])
        self.assertNotIn('vision_uncertainties', filtered['scenes'][0])
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]['evidence'][0]['value'], scene['temporal_observations'])
        self.assertIn('temporal_observations', scene)
        scene['episode'] = 'one'
        filtered, _ = filter_episode(index, {'episode': 'one'})
        self.assertEqual(filtered['scenes'][0]['temporal_observations'], scene['temporal_observations'])

    def test_missing_episode_identity_is_blocking_not_inferred(self):
        _, findings = filter_episode(source(), {})
        self.assertEqual(findings[0]['code'], 'episode_identity_unknown')
        for episode in ['', 2, True]:
            with self.assertRaises(ValueError):
                filter_episode(source(), {'episode': episode})

    def test_inspection_reports_untagged_evidence_for_tv_and_anime(self):
        index = source()
        index['scenes'][0]['evidence'][0].pop('episode')
        for workflow in ['tv', 'anime']:
            self.assertIn('episode_provenance_unknown', self.codes('Something happened.', index, {'episode': 'one'}, workflow))

    def test_continuity_is_unknown_not_claimed_contradiction_detection(self):
        for narration in ['Mira is alive.', 'Mira died.']:
            findings = inspect_guards(draft(narration), source('Mira is alive.'), {'episode': 'one', 'prior_continuity': ['Mira is alive.']}, 'tv')
            gate = next(f for f in findings if f['code'] == 'continuity_comparison_unknown')
            self.assertIn('UNKNOWN', gate['reason'])
            self.assertIn('no contradiction', gate['reason'])
            self.assertEqual(gate['draft_segments'][0]['narration'], narration)

    def test_speaker_metadata_and_text_ambiguity(self):
        for evidence in [source('Run!', speaker_ambiguous=True), source('Run!', speaker_candidates=['Mira', 'Ren']), source('Run!', speaker='unknown'), source('A bubble says Run!; speaker could be Mira or Ren.')]:
            self.assertIn('speaker_attribution_ambiguous', self.codes('Mira shouts Run!', evidence))

    def test_unknown_scene_and_empty_evidence_block(self):
        empty = {'scenes': [{'id': 'S1', 'evidence': []}]}
        self.assertIn('no_cited_text_evidence', self.codes('Something happened.', empty))
        self.assertIn('unknown_scene_reference', self.codes('Something happened.', {'scenes': []}))

    def test_no_false_semantic_approval(self):
        # No rule matches an unsupported nonnumeric assertion. Empty results are
        # explicitly not an accuracy certificate; the semantic review stays open.
        self.assertEqual(inspect_guards(draft('The Moon is made of cheese.'), source('The Moon is rocky.'), {}, 'movie'), [])


class EvidenceResolutionTests(unittest.TestCase):
    def setUp(self):
        from evidence_guards import apply_resolutions
        self.apply = apply_resolutions
        self.findings = inspect_guards(draft('Travel 12 miles.'), source('Travel 12 km.'), {}, 'educational')
        self.entry = {'finding_sha256': self.findings[0]['finding_sha256'],
                      'reviewer': 'Test operator', 'rationale': 'Compared exact quote and documented editorial treatment.', 'reviewed': True}

    def test_exact_attestation_resolves_only_current_finding(self):
        original = copy.deepcopy(self.findings)
        result = self.apply(self.findings, {'evidence_guard_resolutions': [self.entry]})
        self.assertEqual(result[0]['severity'], 'review')
        self.assertTrue(result[0]['human_resolved'])
        self.assertEqual(result[0]['evidence'], original[0]['evidence'])
        self.assertEqual(self.findings, original)
        self.assertEqual(self.entry['finding_sha256'], inspect_guards(draft('Travel 12 miles.'), source('Travel 12 km.'), {}, 'educational')[0]['finding_sha256'])

    def test_stale_quote_and_forged_fingerprint_stay_blocking(self):
        changed = copy.deepcopy(self.findings)
        changed[0]['evidence'][0]['text'] = 'Changed quote.'
        # The caller's stale finding_sha256 is recomputed, never trusted.
        result = self.apply(changed, {'evidence_guard_resolutions': [self.entry]})
        self.assertEqual(result[0]['severity'], 'blocking')
        self.assertNotEqual(result[0]['finding_sha256'], self.entry['finding_sha256'])

    def test_unattested_blanket_and_mismatched_resolutions_stay_blocking(self):
        cases = [{}, {'reviewed': False}, {'reviewed': 'true'}, {'reviewer': ''},
                 {'rationale': ''}, {'finding_sha256': '0' * 64}, {'finding_sha256': '*'}]
        for changes in cases:
            entry = {**self.entry, **changes} if changes else {'reviewed': True}
            with self.subTest(entry=entry):
                result = self.apply(self.findings, {'evidence_guard_resolutions': [entry]})
                self.assertEqual(result[0]['severity'], 'blocking')
                self.assertNotIn('human_resolved', result[0])

    def test_changed_narration_invalidates_resolution(self):
        changed = inspect_guards(draft('Travel 12 miles to a secret base.'), source('Travel 12 km.'), {}, 'educational')
        result = self.apply(changed, {'evidence_guard_resolutions': [self.entry]})
        self.assertEqual(result[0]['severity'], 'blocking')

    def test_default_and_duplicate_resolutions_do_not_resolve(self):
        self.assertEqual(self.apply(self.findings, {})[0]['severity'], 'blocking')
        self.assertEqual(self.apply(self.findings, {'evidence_guard_resolutions': [self.entry, self.entry]})[0]['severity'], 'blocking')

    def test_prior_resolution_not_carried_without_attestation(self):
        resolved = self.apply(self.findings, {'evidence_guard_resolutions': [self.entry]})
        again = self.apply(resolved, {})
        self.assertEqual(again[0]['severity'], 'blocking')
        self.assertNotIn('human_resolved', again[0])


if __name__ == '__main__':
    unittest.main()
