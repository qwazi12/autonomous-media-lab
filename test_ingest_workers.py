import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont
from ingest_workers import ocr_image, segment_page, transcribe_video


class IngestWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'original.png'
        Image.new('RGB', (600, 400), 'white').save(self.image)

    @unittest.skipUnless(shutil.which('tesseract'), 'requires installed Tesseract')
    def test_real_ocr_on_original_image(self):
        image = Image.new('RGB', (1000, 240), 'white')
        font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if not Path(font_path).exists():
            self.skipTest('Test font unavailable')
        ImageDraw.Draw(image).text((35, 70), 'ORIGINAL HELLO WORLD', fill='black', font=ImageFont.truetype(font_path, 54))
        image.save(self.image)
        result = ocr_image(self.image)
        self.assertIn('HELLO', result['text'])
        self.assertIn('WORLD', result['text'])
        self.assertTrue(result['words'])
        for word in result['words']:
            self.assertEqual(len(word['bbox']), 4)
            self.assertGreaterEqual(word['confidence'], 0)
            self.assertLessEqual(word['confidence'], 100)
        self.assertTrue(result['warnings'])

    def test_four_panels_and_direction(self):
        image = Image.new('RGB', (600, 400), 'white')
        draw = ImageDraw.Draw(image)
        for box in [(10, 10, 280, 180), (320, 10, 590, 180), (10, 220, 280, 390), (320, 220, 590, 390)]:
            draw.rectangle(box, fill='#334466')
        image.save(self.image)
        left = segment_page(self.image, self.root/'ltr', 'ltr')
        right = segment_page(self.image, self.root/'rtl', 'rtl')
        self.assertEqual(len(left['panels']), 4)
        self.assertLess(left['panels'][0]['bbox'][0], left['panels'][1]['bbox'][0])
        self.assertGreater(right['panels'][0]['bbox'][0], right['panels'][1]['bbox'][0])
        self.assertFalse(left['reading_order_verified'])
        for panel in left['panels']:
            self.assertTrue(panel['uncertain'])
            self.assertTrue(Path(panel['image']).is_file())

    def test_blank_page_preserved_and_invalid_direction(self):
        result = segment_page(self.image, self.root/'panels')
        self.assertEqual(len(result['panels']), 1)
        self.assertEqual(result['panels'][0]['bbox'], [0, 0, 600, 400])
        with self.assertRaises(ValueError):
            segment_page(self.image, self.root/'invalid', 'guess')

    def test_no_ocr_installation(self):
        with patch('ingest_workers.shutil.which', return_value=None), patch('ingest_workers.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Tesseract is not installed'):
                ocr_image(self.image)
            run.assert_not_called()

    def test_asr_requires_model_then_cli(self):
        with self.assertRaisesRegex(FileNotFoundError, 'local whisper.cpp model'):
            transcribe_video(self.image, self.root/'out.srt', self.root/'absent.bin')
        model = self.root/'model.bin'
        model.write_bytes(b'fake model for absence test')
        with patch('ingest_workers.shutil.which', return_value=None), patch('ingest_workers.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'No remote fallback'):
                transcribe_video(self.image, self.root/'out.srt', model)
            run.assert_not_called()

    def test_asr_local_cli_contract_and_output(self):
        model = self.root/'model.bin'
        model.write_bytes(b'mocked local model')
        calls = []
        def execute(command, **kwargs):
            calls.append(command)
            if command[0].endswith('whisper-cli'):
                prefix = Path(command[command.index('-of')+1])
                prefix.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nOriginal test audio\n', encoding='utf-8')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch('ingest_workers.shutil.which', side_effect=lambda name: '/usr/bin/'+name), patch('ingest_workers.subprocess.run', side_effect=execute):
            output = transcribe_video(self.image, self.root/'result', model)
        self.assertEqual(output.name, 'result.srt')
        self.assertIn('Original test audio', output.read_text())
        self.assertEqual(len(calls), 2)
        self.assertIn(str(model.resolve()), calls[1])
        self.assertIn('-osrt', calls[1])

    def test_ocr_failure_clear_and_no_shell(self):
        with patch('ingest_workers.shutil.which', return_value='/usr/bin/tesseract'), patch('ingest_workers.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'missing traineddata')) as run:
            with self.assertRaisesRegex(RuntimeError, 'missing traineddata'):
                ocr_image(self.image)
            self.assertNotIn('shell', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
