import unittest
from workers import *
class WorkerTests(unittest.TestCase):
 def setUp(self):
  self.index={'scenes':[{'id':'S1','start':0,'end':10,'evidence':[{'id':'E1','text':'Rin sees 2 lights.','episode':'one','source_url':'urn:test','as_of':'2026-11-09'}]}]}
  self.plan={'segments':[{'id':'B1','narration':'There are 3 lights.','scene_ids':['S1']}]}
 def test_movie_does_not_mutate(self):
  r=MovieWorker().prepare(self.index,{});r['scenes'][0]['id']='changed';self.assertEqual(self.index['scenes'][0]['id'],'S1')
 def test_tv_episode_filter(self):self.assertEqual(TVWorker().prepare(self.index,{'episode':'two'})['scenes'][0]['evidence'],[])
 def test_anime_alias_annotations(self):
  e=AnimeWorker().prepare(self.index,{'aliases':{'Rin':'Ren'}})['scenes'][0]['evidence'][0]
  self.assertEqual(e['alias_mentions'][0]['canonical'],'Ren');self.assertEqual(e['text'],'Rin sees 2 lights.')
 def test_manhwa_direction(self):
  with self.assertRaises(WorkerError):ManhwaWorker().prepare(self.index,{'reading_direction':'random'})
 def test_education_provenance_required(self):
  self.index['scenes'][0]['evidence'][0].pop('source_url')
  with self.assertRaises(WorkerError):EducationalWorker().prepare(self.index,{})
 def test_education_new_numbers_flagged(self):self.assertIn('3',EducationalWorker().inspect(self.plan,self.index,{})[0]['reason'])
 def test_education_claim_ledger(self):self.assertFalse(EducationalWorker().prepare(self.index,{})['claim_ledger'][0]['verified'])
if __name__=='__main__':unittest.main()
