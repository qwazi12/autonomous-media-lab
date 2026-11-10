import unittest
from workers import TVWorker,AnimeWorker,WorkerError
class ContinuityIntegrationTests(unittest.TestCase):
 def test_prior_context(self):
  for worker in (TVWorker(),AnimeWorker()):
   r=worker.prepare({'scenes':[]},{'episode_position':2,'continuity_snapshot':{'through_position':1,'episodes':[{'position':1}]}})
   self.assertIn('continuity_snapshot',r['workflow_context'])
 def test_future_rejected(self):
  for worker in (TVWorker(),AnimeWorker()):
   with self.assertRaises(WorkerError):worker.prepare({'scenes':[]},{'episode_position':2,'continuity_snapshot':{'through_position':2}})
 def test_hidden_future_rejected(self):
  for worker in (TVWorker(),AnimeWorker()):
   with self.assertRaises(WorkerError):worker.prepare({'scenes':[]},{'episode_position':2,'continuity_snapshot':{'through_position':1,'episodes':[{'position':3}]}})
if __name__=='__main__':unittest.main()
