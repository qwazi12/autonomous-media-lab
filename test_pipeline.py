import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pipeline as p

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.index={'scenes':[{'id':'S00001','start':0,'end':10,'evidence':[]}]}
        self.plan={'title':'Demo','segments':[{'id':'B001','narration':'A grounded line.','scene_ids':['S00001'],'review_notes':[]}]}
    def test_valid_plan(self):p.validate_plan(self.plan,self.index)
    def test_unknown_reference(self):
        self.plan['segments'][0]['scene_ids']=['S99999']
        with self.assertRaises(p.PipelineError):p.validate_plan(self.plan,self.index)
    def test_path_id_rejected(self):
        self.plan['segments'][0]['id']='../../a'
        with self.assertRaises(p.PipelineError):p.validate_plan(self.plan,self.index)
    def test_duplicate_id_rejected(self):
        self.plan['segments']*=2
        with self.assertRaises(p.PipelineError):p.validate_plan(self.plan,self.index)
    def test_empty_narration_rejected(self):
        self.plan['segments'][0]['narration']=' '
        with self.assertRaises(p.PipelineError):p.validate_plan(self.plan,self.index)
    def test_srt_and_html(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'a.srt';f.write_text('1\n00:00:01,000 --> 00:00:03,500\n<i>Hello</i>\n')
            self.assertEqual(p.parse_srt(f)[0]['text'],'Hello');self.assertEqual(p.parse_srt(f)[0]['end'],3.5)
    def test_srt_bad_timing(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'a.srt';f.write_text('1\n00:00:05,000 --> 00:00:03,000\nHello\n')
            with self.assertRaises(p.PipelineError):p.parse_srt(f)
    def test_model_failure_has_no_fallback(self):
        with patch('urllib.request.build_opener',side_effect=ConnectionRefusedError):
            with self.assertRaisesRegex(p.PipelineError,'No remote fallback'):p.LocalModel('local').generate('hello')
    def test_rights_gate(self):
        import argparse
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'input';f.write_text('x')
            with self.assertRaisesRegex(p.PipelineError,'authority'):p.execute(argparse.Namespace(output=str(Path(d)/'run'),source=str(f),rights_confirmed=False))
            self.assertFalse((Path(d)/'run').exists())
    def test_existing_output_protected(self):
        import argparse
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(p.PipelineError,'already exists'):p.execute(argparse.Namespace(output=d))
    def test_workflow_contracts(self):
        self.assertEqual(set(p.WORKFLOWS),{'movie','tv','anime','manhwa','educational'})
    def test_bad_analyst_references(self):
        class Fake:
            def generate(self,*a):return {'notes':[{'scene_id':'bad'}]}
        with self.assertRaisesRegex(p.PipelineError,'analysis references'):p.make_plan(self.index,Fake(),'movie',360)
    def test_local_generation_contract(self):
        responses=[{'notes':[{'scene_id':'S00001','facts':['A signal is visible.'],'uncertainties':[]}]},copy.deepcopy(self.plan),{'issues':[],'limitations':['Human review required.']}]
        class Fake:
            model='fixture'
            def generate(self,*a):return responses.pop(0)
        plan=p.make_plan(self.index,Fake(),'movie',360)
        self.assertEqual(plan['generator'],'local_ollama');self.assertEqual(plan['critic']['issues'],[])
    def test_model_prompt_bound(self):
        with self.assertRaisesRegex(p.PipelineError,'context'):
            p.LocalModel('fixture').generate('x'*60001)
    def test_cloud_model_rejected(self):
        with self.assertRaisesRegex(p.PipelineError,'Cloud-backed'):
            p.LocalModel('model:cloud')
if __name__=='__main__':unittest.main()
