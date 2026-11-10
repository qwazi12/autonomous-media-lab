import unittest,tempfile
from pathlib import Path
from temporal import sample_times,enrich_temporal
class Model:
 def __init__(self,result):self.result=result
 def generate(self,prompt,images):self.images=images;return self.result
class TemporalTests(unittest.TestCase):
 def test_sampling(self):self.assertEqual(sample_times(0,6),[1,3,5])
 def test_invalid_bounds(self):
  with self.assertRaises(ValueError):sample_times(1,0)
 def test_evidence(self):
  with tempfile.TemporaryDirectory() as td:
   index={'scenes':[{'id':'S00001','start':0,'end':6}]}
   model=Model({'observations':[{'frame_index':1,'description':'Door open'}],'description':'Door visible','uncertainties':[]})
   def extract(args):Path(args[-1]).parent.mkdir(exist_ok=True);Path(args[-1]).write_bytes(b'image')
   enrich_temporal(index,Path(td),model,Path('source.mp4'),extract)
   self.assertEqual(index['scenes'][0]['temporal_observations'][0]['time'],3)
   self.assertEqual(len(model.images),3)
 def test_invalid_reference(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(ValueError):enrich_temporal({'scenes':[{'id':'S1','start':0,'end':1}]},Path(td),Model({'description':'x','observations':[{'frame_index':4,'description':'x'}]}),Path('v'),lambda a:None)
if __name__=='__main__':unittest.main()
