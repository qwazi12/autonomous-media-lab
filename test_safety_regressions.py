"""Local/mocked regression coverage for pipeline boundaries; no model requests."""
import argparse
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from checkpoints import Checkpoints
import export_remotion
import pipeline


class SafetyRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'ORIGINAL SOURCE')
        self.output = self.root / 'run'
        self.plan = {'title': 'Draft', 'segments': [
            {'id': 'B001', 'narration': 'Visible action.', 'scene_ids': ['S00001'], 'review_notes': []}]}
        self.plan_file = self.root / 'plan.json'
        self.plan_file.write_text(json.dumps(self.plan), encoding='utf-8')
        self.index = {'schema_version': 1, 'duration': 10, 'source_hash': pipeline.digest(self.source),
                      'scenes': [{'id': 'S00001', 'start': 0, 'end': 10, 'evidence': []}], 'warnings': []}

    def args(self, **changes):
        args = dict(output=str(self.output), source=str(self.source), rights_confirmed=True,
                    resume=False, workflow='movie', subtitles=None, plan=str(self.plan_file),
                    context=None, asr_model=None, audio_dir=None, model=None,
                    vision_model=None, ocr=False, target_seconds=360)
        args.update(changes)
        return argparse.Namespace(**args)

    def stopped_after_index(self):
        args = self.args(plan=None)
        with patch('pipeline.index_video', return_value=copy.deepcopy(self.index)):
            with self.assertRaisesRegex(pipeline.PipelineError, 'Index ready'):
                pipeline.execute(args)
        return args

    def test_resume_refuses_file_symlink_before_source_write(self):
        args = self.stopped_after_index()
        ledger = self.output / 'run.json'
        ledger.unlink()
        try:
            ledger.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        args.resume = True
        with self.assertRaisesRegex(pipeline.PipelineError, 'symlink'):
            pipeline.execute(args)
        self.assertEqual(self.source.read_bytes(), b'ORIGINAL SOURCE')

    def test_resume_refuses_hardlink_before_source_write(self):
        args = self.stopped_after_index()
        ledger = self.output / 'run.json'
        ledger.unlink()
        try:
            os.link(self.source, ledger)
        except (OSError, NotImplementedError):
            self.skipTest('Hardlinks unavailable')
        args.resume = True
        with self.assertRaises(pipeline.PipelineError):
            pipeline.execute(args)
        self.assertEqual(self.source.read_bytes(), b'ORIGINAL SOURCE')

    def test_resume_refuses_directory_symlink(self):
        args = self.stopped_after_index()
        external = self.root / 'external'
        external.mkdir()
        marker = external / 'B001.wav'
        marker.write_bytes(b'KEEP')
        try:
            (self.output / 'audio').symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        args.resume = True
        with self.assertRaisesRegex(pipeline.PipelineError, 'symlink'):
            pipeline.execute(args)
        self.assertEqual(marker.read_bytes(), b'KEEP')

    def test_model_ignores_proxy_environment(self):
        response = io.StringIO(json.dumps({'response': '{"ok": true}'}))
        with patch.dict(os.environ, {'http_proxy': 'http://external.invalid:8080',
                                    'HTTP_PROXY': 'http://external.invalid:8080', 'NO_PROXY': ''}):
            with patch('pipeline.urllib.request.build_opener') as build:
                build.return_value.open.return_value = response
                self.assertEqual(pipeline.LocalModel('local').generate('private prompt'), {'ok': True})
        handlers = build.call_args.args
        proxy = next(item for item in handlers if isinstance(item, urllib.request.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        self.assertTrue(any(isinstance(item, pipeline.NoRedirect) for item in handlers))
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/generate')

    def test_model_redirects_blocked(self):
        request = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=b'private')
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status), self.assertRaises(pipeline.PipelineError):
                pipeline.NoRedirect().redirect_request(request, None, status, 'redirect', {}, 'https://external.invalid/')

    def test_verified_transcript_reused_after_index_failure(self):
        model = self.root / 'asr.bin'
        model.write_bytes(b'local model placeholder')
        args = self.args(plan=None, asr_model=str(model))
        def transcribe(_source, output, _model):
            output.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n', encoding='utf-8')
            return output
        with patch('ingest_workers.transcribe_video', side_effect=transcribe) as transcriber:
            with patch('pipeline.index_video', side_effect=RuntimeError('index interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'index interrupted'):
                    pipeline.execute(args)
            args.resume = True
            with patch('pipeline.index_video', return_value=copy.deepcopy(self.index)) as indexer:
                with self.assertRaisesRegex(pipeline.PipelineError, 'Index ready'):
                    pipeline.execute(args)
            transcriber.assert_called_once()
            self.assertEqual(indexer.call_args.args[2], self.output / 'transcript.srt')

    def test_tampered_transcript_blocks_index_reuse(self):
        model = self.root / 'asr.bin'
        model.write_bytes(b'local model placeholder')
        args = self.args(plan=None, asr_model=str(model))
        def transcribe(_source, output, _model):
            output.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n', encoding='utf-8')
            return output
        with patch('ingest_workers.transcribe_video', side_effect=transcribe), \
             patch('pipeline.index_video', return_value=copy.deepcopy(self.index)):
            with self.assertRaisesRegex(pipeline.PipelineError, 'Index ready'):
                pipeline.execute(args)
        (self.output / 'transcript.srt').write_text('tampered evidence', encoding='utf-8')
        args.resume = True
        with patch('pipeline.index_video') as indexer:
            with self.assertRaisesRegex(pipeline.PipelineError, 'Unverified transcript'):
                pipeline.execute(args)
            indexer.assert_not_called()

    def test_signal_scan_error_blocks_completion(self):
        def narrate(_plan, output):
            (output / 'audio').mkdir()
            (output / 'audio' / 'B001.wav').write_bytes(b'local audio placeholder')
        def render(_args):
            for name in ('draft.mp4', 'draft.srt', 'draft_edit_decisions.csv'):
                (self.output / name).write_bytes(b'render placeholder')
            return 0
        with patch('pipeline.index_video', return_value=copy.deepcopy(self.index)), \
             patch('pipeline.narrate', side_effect=narrate), \
             patch('pipeline.render.probe', return_value=2), \
             patch('pipeline.render.main', side_effect=render), \
             patch('media_qa.inspect_media', return_value={'checks': [{'name': 'signal_scan', 'status': 'error'}]}), \
             patch('review.write_review') as review:
            with self.assertRaisesRegex(pipeline.PipelineError, 'structural QA'):
                pipeline.execute(self.args())
        self.assertEqual(json.loads((self.output / 'run.json').read_text())['status'], 'blocked')
        review.assert_not_called()

    def export_fixture(self):
        self.output.mkdir()
        audio = self.output / 'audio'
        (audio / 'first').mkdir(parents=True)
        (audio / 'second').mkdir()
        (audio / 'first' / 'voice.wav').write_bytes(b'first narration')
        (audio / 'second' / 'voice.wav').write_bytes(b'second narration')
        scenes = []
        for scene_id, filename in (('../../escape', 'first/voice.wav'), ('normal', 'second/voice.wav')):
            scenes.append({'id': scene_id, 'title': 'x', 'beat': 'x', 'notes': '', 'narration': 'Visible.',
                           'duration': 2, 'shots': [{'in': 0, 'out': 1}], 'audioFile': filename})
        project = {'schemaVersion': 1, 'title': 'Draft', 'wpm': 145, 'scenes': scenes}
        for name, data in (('project.json', project), ('index.json', self.index), ('plan.json', self.plan),
                           ('run.json', {'status': 'draft_complete', 'workflow': 'movie',
                                         'source_hash': pipeline.digest(self.source)})):
            (self.output / name).write_text(json.dumps(data), encoding='utf-8')
        for name in ('draft.mp4', 'draft.srt', 'draft_edit_decisions.csv'):
            (self.output / name).write_bytes(b'completed draft placeholder')
        checkpoint = Checkpoints(self.output, 'fixture-signature')
        checkpoint.record('index', [self.output / 'index.json'])
        checkpoint.record('plan', [self.output / 'plan.json'])
        checkpoint.record('audio', list(audio.rglob('*.wav')))
        checkpoint.record('render', [self.output / name for name in ('draft.mp4', 'draft.srt', 'draft_edit_decisions.csv', 'project.json')])

    def test_export_refuses_unfinished_run(self):
        self.export_fixture()
        ledger_path = self.output / 'run.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['status'] = 'blocked'
        ledger_path.write_text(json.dumps(ledger), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'completed'):
            export_remotion.export(self.output, self.source, self.root / 'bundle')
        self.assertFalse((self.root / 'bundle').exists())

    def test_export_refuses_changed_source(self):
        self.export_fixture()
        self.source.write_bytes(b'UNRELATED MOVIE')
        with self.assertRaisesRegex(ValueError, 'Source does not match'):
            export_remotion.export(self.output, self.source, self.root / 'bundle')
        self.assertFalse((self.root / 'bundle').exists())

    def test_export_refuses_changed_project(self):
        self.export_fixture()
        project_file = self.output / 'project.json'
        project = json.loads(project_file.read_text())
        project['title'] = 'Unverified edit'
        project_file.write_text(json.dumps(project), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checkpoint validation'):
            export_remotion.export(self.output, self.source, self.root / 'bundle')
        self.assertFalse((self.root / 'bundle').exists())

    def test_export_uses_contained_freeze_paths_and_distinct_audio_names(self):
        self.export_fixture()
        destination = self.root / 'bundle'
        with patch('export_remotion.render.probe', return_value=10), patch('export_remotion.render.run') as ffmpeg:
            manifest_path = export_remotion.export(self.output, self.source, destination)
        self.assertEqual(ffmpeg.call_count, 2)
        for call in ffmpeg.call_args_list:
            target = Path(call.args[0][-1]).resolve()
            self.assertTrue(target.is_relative_to(destination / 'public'))
            self.assertNotIn('..', target.name)
        manifest = json.loads(manifest_path.read_text())
        first, second = [row['src'] for row in manifest['audio']]
        self.assertNotEqual(first, second)
        self.assertEqual((destination / 'public' / first).read_bytes(), b'first narration')
        self.assertEqual((destination / 'public' / second).read_bytes(), b'second narration')
        self.assertEqual((destination / 'public' / 'source.mp4').read_bytes(), b'ORIGINAL SOURCE')


if __name__ == '__main__':
    unittest.main()
