import unittest
from acceptance import evaluate
class AcceptanceTests(unittest.TestCase):
 def test_missing_evidence_and_duration(self):
  r=evaluate({'scenes':[{'id':'S1'}]},{'segments':[{'id':'B1','scene_ids':['S1']}],'generator':'imported_plan'}, {'duration_seconds':20},300,'movie')
  self.assertFalse(r['ready_to_publish'])
  self.assertEqual(next(x for x in r['checks'] if x['name']=='source_evidence_present')['status'],'review_required')
  self.assertEqual(next(x for x in r['checks'] if x['name']=='requested_duration')['status'],'review_required')
 def test_never_auto_approval(self):
  r=evaluate({'scenes':[{'id':'S1','evidence':['visible']} ]},{'segments':[{'id':'B1','scene_ids':['S1']}],'generator':'local_ollama','critic':{'issues':[]}}, {'duration_seconds':300},300,'manhwa')
  self.assertEqual(r['status'],'human_review_required')
if __name__=='__main__':unittest.main()
