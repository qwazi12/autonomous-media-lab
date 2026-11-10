import io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from gemini_provider import GeminiModel,GeminiError,NoRedirect
class GeminiTests(unittest.TestCase):
 def model(self,**kw):return GeminiModel('gemini-test',authorized=True,max_calls=kw.get('max_calls',2))
 def response(self,data):
  opener=MagicMock();opener.open.return_value.__enter__.return_value=io.BytesIO(json.dumps(data).encode());return opener
 def good(self):return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}],'usageMetadata':{'totalTokenCount':5,'secret':'omit'}}
 def test_disabled_default(self):
  with self.assertRaises(GeminiError):GeminiModel('gemini-test')
 def test_invalid_names(self):
  for name in ('../secret','model?key=secret',''):
   with self.assertRaises(GeminiError):GeminiModel(name,authorized=True,max_calls=2)
 def test_missing_key(self):
  with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(GeminiError,'missing'):self.model().generate('hi')
 def test_json_and_header(self):
  op=self.response(self.good())
  with patch.dict(os.environ,{'GEMINI_API_KEY':'unit-test-not-real'}),patch('urllib.request.build_opener',return_value=op):
   m=self.model();self.assertEqual(m.generate('hi'),{'ok':True});req=op.open.call_args.args[0]
   self.assertNotIn('unit-test-not-real',req.full_url);self.assertEqual(req.get_header('X-goog-api-key'),'unit-test-not-real');self.assertEqual(m.usage,[{'totalTokenCount':5}])
 def test_quota_and_no_retry(self):
  op=MagicMock();op.open.side_effect=RuntimeError('secret unit-test-not-real')
  with patch.dict(os.environ,{'GEMINI_API_KEY':'unit-test-not-real'}),patch('urllib.request.build_opener',return_value=op):
   m=self.model(max_calls=1)
   with self.assertRaises(GeminiError) as err:m.generate('hi')
   self.assertNotIn('unit-test-not-real',str(err.exception))
   with self.assertRaisesRegex(GeminiError,'limit'):m.generate('hi')
   self.assertEqual(op.open.call_count,1)
 def test_blocked_or_truncated(self):
  for data in ({},{'candidates':[{'finishReason':'MAX_TOKENS'}]}):
   with patch.dict(os.environ,{'GEMINI_API_KEY':'fake'}),patch('urllib.request.build_opener',return_value=self.response(data)),self.assertRaises(GeminiError):self.model().generate('hi')
 def test_bad_json(self):
  data=self.good();data['candidates'][0]['content']['parts'][0]['text']='not json'
  with patch.dict(os.environ,{'GEMINI_API_KEY':'fake'}),patch('urllib.request.build_opener',return_value=self.response(data)),self.assertRaises(GeminiError):self.model().generate('hi')
 def test_image_validation(self):
  with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'GEMINI_API_KEY':'fake'}):
   p=Path(td)/'x.jpg';p.write_text('not image')
   with self.assertRaises(GeminiError):self.model().generate('hi',[p])
 def test_shared_quota(self):
  q={'used':0};a=GeminiModel('first',authorized=True,max_calls=1,quota=q);b=GeminiModel('second',authorized=True,max_calls=1,quota=q)
  with patch.dict(os.environ,{'GEMINI_API_KEY':'fake'}),patch('urllib.request.build_opener',return_value=self.response(self.good())):
   a.generate('hi')
   with self.assertRaisesRegex(GeminiError,'limit'):b.generate('hi')
 def test_queue_gates_and_arguments(self):
  from jobs import validate_spec,pipeline_command
  with tempfile.TemporaryDirectory() as td:
   f=Path(td)/'source.mp4';f.write_bytes(b'fixture')
   spec={'source':str(f),'rights_confirmed':True,'provider':'gemini'}
   with self.assertRaises(ValueError):validate_spec(spec)
   spec.update(remote_authorized=True,max_provider_calls=3)
   cmd=pipeline_command({'spec':json.dumps(spec),'output':str(Path(td)/'run')})
   self.assertIn('--max-provider-calls=3',cmd);self.assertIn('--remote-authorized',cmd)
 def test_redirect_rejected(self):
  with self.assertRaises(GeminiError):NoRedirect().redirect_request(None,None,None,None,None,None)
if __name__=='__main__':unittest.main()
