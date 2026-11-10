import tempfile
import unittest
from pathlib import Path

from review import write_review


class ReviewTests(unittest.TestCase):
    def render(self, index=None, plan=None, qa=None):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "review.html"
            write_review(target, index or {}, plan or {}, qa or {})
            return target.read_text(encoding="utf-8")

    def test_evidence_and_source_links(self):
        page = self.render(
            {"scenes": [{"id": "s01", "start": 61.25, "end": 72, "evidence": [{"id": "e01", "start": 62, "end": 64, "text": "A door closes."}], "visual_description": "A dark hallway."}]},
            {"title": "A recap", "segments": [{"id": "seg1", "narration": "Someone leaves.", "scene_ids": ["s01"], "review_notes": ["Identity uncertain"]}]},
            {"warnings": ["Check speaker identity"]},
        )
        for expected in ['src="draft.mp4"', 'src="frames/s01.jpg"', 'href="#scene-0"', 'id="scene-0"', '00:01:01.250', '00:01:12.000', '00:01:02.000', 'A door closes.', 'Identity uncertain', 'Check speaker identity', 'DRAFT · HUMAN REVIEW REQUIRED']:
            self.assertIn(expected, page)

    def test_untrusted_text_is_escaped_everywhere(self):
        attack = '</script><script>alert("x")</script><img src=x onerror=alert(1)>'
        page = self.render(
            {"scenes": [{"id": attack, "visual_description": attack, "thumbnail": "https://evil.example/a.jpg", "evidence": [{"id": attack, "text": attack}]}]},
            {"title": attack, "segments": [{"id": attack, "narration": attack, "scene_ids": [attack, "missing"], "review_notes": attack}]},
            {"warnings": [attack]},
        )
        self.assertNotIn(attack, page)
        self.assertNotIn('src="https://', page)
        self.assertNotIn('onerror=', page.replace('onerror=alert(1)&gt;', ''))
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('href="#scene-0"', page)
        self.assertIn('Missing scene: missing', page)

    def test_empty_inputs_are_explicit(self):
        page = self.render()
        for expected in ['No planned segments supplied.', 'No indexed scenes supplied.', 'No automated QA results supplied.', 'Draft video unavailable or unsupported.', 'video.addEventListener', '@media(max-width:800px)']:
            self.assertIn(expected, page)

    def test_path_confinement_and_invalid_time(self):
        page = self.render({"scenes": [
            {"id": "safe", "thumbnail": "../../private.jpg", "start": float("nan"), "end": -1},
            {"id": "../../unsafe", "thumbnail": "file:///etc/passwd"},
            {"id": "custom", "thumbnail": "frames/custom_thumb.png"},
        ]})
        self.assertIn('src="frames/safe.jpg"', page)
        self.assertIn('src="frames/custom_thumb.png"', page)
        self.assertNotIn('src="../../', page)
        self.assertNotIn('file:///etc/passwd', page)
        self.assertIn('No safe thumbnail path available', page)
        self.assertIn('Source time unknown – unknown', page)

    def test_missing_citations_and_evidence(self):
        page = self.render({"scenes": [{"id": "a"}]}, {"segments": [{"id": "one"}]})
        self.assertIn('No scene citations supplied.', page)
        self.assertIn('No textual evidence supplied for this scene.', page)
        self.assertIn('No narration supplied.', page)


if __name__ == "__main__":
    unittest.main()
