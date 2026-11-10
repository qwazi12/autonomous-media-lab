import contextlib
import csv
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import render


def project():
    return {'schemaVersion': 1, 'title': 'Synthetic recap', 'wpm': 150, 'scenes': [
        {'id': 'one', 'title': 'Red then freeze', 'beat': '', 'notes': '', 'narration': 'A red beginning.', 'duration': 1, 'shots': [{'in': 0, 'out': .25}]},
        {'id': 'two', 'title': 'Reordered cuts', 'beat': '', 'notes': '', 'narration': 'The ending.', 'duration': 1, 'shots': [{'in': 1, 'out': 1.5}, {'in': .5, 'out': 1.5}]}]}


class ValidationTests(unittest.TestCase):
    def test_auto_duration(self):
        p = project()
        p['scenes'][0]['duration'] = None
        self.assertEqual(render.validate_project(p, 2)[0]['duration'], 2)
        p['scenes'][0]['narration'] = 'word ' * 10
        self.assertEqual(render.validate_project(p, 2)[0]['duration'], 4.5)

    def test_invalid_schema_and_numbers(self):
        for value in [None, {}, {'schemaVersion': True}]:
            with self.assertRaises(render.RenderError):
                render.validate_project(value, 2)
        for value in [0, -1, True, float('nan'), float('inf'), '10']:
            p = project()
            p['scenes'][0]['duration'] = value
            with self.subTest(value=value), self.assertRaises(render.RenderError):
                render.validate_project(p, 2)

    def test_project_limits(self):
        for wpm in [59.99, 300.01]:
            p = project()
            p['wpm'] = wpm
            with self.assertRaises(render.RenderError):
                render.validate_project(p, 2)
        for wpm in [60, 300]:
            p = project()
            p['wpm'] = wpm
            render.validate_project(p, 2)
        for key, value in [('title', 'a' * 251), ('scenes', project()['scenes'] * 251)]:
            p = project()
            p[key] = value
            with self.assertRaises(render.RenderError):
                render.validate_project(p, 2)
        for key in ['id', 'title', 'beat', 'notes', 'narration']:
            p = project()
            p['scenes'][0][key] = 'a' * 100001
            with self.subTest(key=key), self.assertRaises(render.RenderError):
                render.validate_project(p, 2)
        p = project()
        p['scenes'][0]['duration'] = .009
        with self.assertRaises(render.RenderError):
            render.validate_project(p, 2)
        p['scenes'][0]['duration'] = .01
        render.validate_project(p, 2)

    def test_caption_chunks_and_csv_safety(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scene = project()['scenes'][0]
            scene.update(id='=HYPERLINK("bad")', title='@SUM(1,1)', narration='word ' * 30, duration=10)
            render.write_sidecars([scene], root/'a.srt', root/'a.csv')
            blocks = (root/'a.srt').read_text().strip().split('\n\n')
            self.assertEqual(len(blocks), 2)
            self.assertIn('00:00:00,000 --> 00:00:05,000', blocks[0])
            self.assertIn('00:00:05,000 --> 00:00:10,000', blocks[1])
            for block in blocks:
                lines = block.splitlines()[2:]
                self.assertLessEqual(len(' '.join(lines)), 76)
                self.assertEqual(len(lines), 2)
                self.assertLessEqual(len(lines[0]), 42)
            with (root/'a.csv').open(newline='') as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[1][0], "'" + scene['id'])
            self.assertEqual(rows[1][1], "'" + scene['title'])
        for prefix in ['=', '+', '-', '@', '\t', '\r']:
            self.assertEqual(render.safe_csv(prefix + 'test'), "'" + prefix + 'test')

    def test_invalid_shots(self):
        for shot in [{'in': 0, 'out': 3}, {'in': 1, 'out': 1}, {'in': -1, 'out': 1}, {'in': 0, 'out': float('nan')}]:
            p = project()
            p['scenes'][0]['shots'] = [shot]
            with self.assertRaises(render.RenderError):
                render.validate_project(p, 2)

    def test_local_only_and_traversal(self):
        for value in ['https://example.com/a.mp4', 'file:///tmp/a.mp4', '//server/a.mp4']:
            with self.assertRaises(render.RenderError):
                render.local_path(value, 'test', False)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'a.wav').touch()
            self.assertEqual(render.audio_path(root, 'a.wav'), root / 'a.wav')
            for value in ['../a.wav', '..\\a.wav', '/tmp/a.wav', 'C:\\a.wav']:
                with self.assertRaises(render.RenderError):
                    render.audio_path(root, value)

    def test_probe_boundaries(self):
        for response in [{'streams': []}, {'streams': [{'codec_type': 'video', 'duration': 'NaN'}]}, {'streams': [{'codec_type': 'video'}]}]:
            with patch('render.run', return_value=json.dumps(response)), self.assertRaises(render.RenderError):
                render.probe(Path('movie.mp4'), 'video')
        with patch('render.run', return_value=json.dumps({'streams': [{'codec_type': 'video', 'duration': '2'}]})):
            self.assertEqual(render.probe(Path('movie.mp4'), 'video'), 2)

    def test_sidecar_trim_and_freeze(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            render.write_sidecars(project()['scenes'], root/'a.srt', root/'a.csv')
            self.assertIn('00:00:01,000 --> 00:00:02,000', (root/'a.srt').read_text())
            self.assertIn('freeze', (root/'a.csv').read_text())
            self.assertIn('1.5,2.0,0.5,1.0,shot', (root/'a.csv').read_text())


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source.mp4'
        render.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=10:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.source)])
        self.project_path = self.root/'project.json'
        self.project_path.write_text(json.dumps(project()))
        self.output = self.root/'output.mp4'
        self.args = [str(self.project_path), '--source', str(self.source), '--output', str(self.output), '--width', '160', '--height', '90', '--fps', '10']

    def invoke(self, extra=()):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return render.main(self.args + list(extra))

    def make_audio(self, name, duration):
        path = self.root/name
        render.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'sine=frequency=440:duration={duration}', str(path)])
        return path

    def test_dry_run_reports_freeze_padding(self):
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            self.assertEqual(render.main(self.args + ['--dry-run']), 0)
        self.assertIn('0.750s of last-frame freeze padding', stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_silent_render_and_overwrite(self):
        self.assertEqual(self.invoke(), 0)
        self.assertAlmostEqual(render.probe(self.output, 'video'), 2, places=1)
        self.assertTrue((self.root/'output.srt').exists())
        self.assertTrue((self.root/'output_edit_decisions.csv').exists())
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.invoke(['--overwrite']), 0)

    def test_full_narration_and_long_audio_rejection(self):
        audio = self.make_audio('short.wav', 1.5)
        self.assertEqual(self.invoke(['--narration', str(audio)]), 0)
        self.assertAlmostEqual(render.probe(self.output, 'audio'), 2, places=1)
        audio = self.make_audio('long.wav', 2.2)
        self.assertEqual(self.invoke(['--narration', str(audio), '--overwrite']), 1)

    def test_scene_audio_and_dry_run(self):
        self.make_audio('scene.wav', .75)
        p = project()
        p['scenes'][0]['audioFile'] = 'scene.wav'
        self.project_path.write_text(json.dumps(p))
        self.assertEqual(self.invoke(['--audio-dir', str(self.root), '--dry-run']), 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.invoke(['--audio-dir', str(self.root)]), 0)
        self.assertEqual(self.invoke(['--narration', str(self.root/'scene.wav'), '--overwrite']), 1)


if __name__ == '__main__':
    unittest.main()
