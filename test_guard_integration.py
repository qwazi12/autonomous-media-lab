import copy,unittest
from workers import TVWorker,EducationalWorker
from acceptance import evaluate
class GuardIntegrationTests(unittest.TestCase):
 def test_unknown_provenance_retained_as_blocker(self):
  raw={'scenes':[{'id':'S1','start':0,'end':2,'evidence':[{'id':'E1','text':'Next episode reveals the culprit.'}]}]}
  worker=TVWorker();idx=worker.prepare(raw,{'episode':'one'})
  self.assertEqual(idx['scenes'][0]['evidence'],[])
  p={'segments':[{'id':'B1','narration':'The culprit appears.','scene_ids':['S1']}],'generator':'imported_plan'}
  p['workflow_findings']=worker.inspect(p,idx,{'episode':'one'})
  self.assertTrue(any(x.get('code')=='episode_provenance_unknown' for x in p['workflow_findings']))
  self.assertEqual(evaluate(idx,p,{'duration_seconds':30},30,'tv')['status'],'blocked')
 def test_draft_bound_operator_resolution(self):
  idx={'scenes':[{'id':'S1','start':0,'end':2,'evidence':[{'id':'E1','text':'Mira is alive.','episode':'one'}]}]}
  p={'segments':[{'id':'B1','narration':'Mira is alive.','scene_ids':['S1']}]};context={'episode':'one','prior_continuity':['Mira was missing.']}
  w=TVWorker();findings=w.inspect(p,idx,context)
  target=next(x for x in findings if x.get('code')=='continuity_comparison_unknown')
  context['evidence_guard_resolutions']=[{'finding_sha256':target['finding_sha256'],'reviewer':'Synthetic test reviewer','rationale':'Fixture comparison only','reviewed':True}]
  self.assertTrue(next(x for x in w.inspect(p,idx,context) if x.get('code')=='continuity_comparison_unknown')['human_resolved'])
  changed=copy.deepcopy(p);changed['segments'][0]['narration']='Mira is dead.'
  self.assertEqual(next(x for x in w.inspect(changed,idx,context) if x.get('code')=='continuity_comparison_unknown')['severity'],'blocking')
if __name__=='__main__':unittest.main()
