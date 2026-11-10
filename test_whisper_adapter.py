import tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
from whisper_adapter import transcribe_openai_whisper

class WhisperAdapterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.source=self.root/'source.wav';self.source.write_bytes(b'original');self.model=self.root/'base.en.pt';self.model.write_bytes(b'local model');self.out=self.root/'out.srt'
 def test_explicit_file_not_download_name(self):
  with self.assertRaises(FileNotFoundError):transcribe_openai_whisper(self.source,self.out,self.root/'base')
 def test_no_cli_no_fallback(self):
  with patch('whisper_adapter.shutil.which',return_value=None),patch('whisper_adapter.subprocess.run') as run:
   with self.assertRaisesRegex(RuntimeError,'no installation'):transcribe_openai_whisper(self.source,self.out,self.model)
   run.assert_not_called()
 def test_output_never_overwritten(self):
  self.out.write_text('keep')
  with patch('whisper_adapter.shutil.which',side_effect=lambda n:'/bin/'+n):
   with self.assertRaises(FileExistsError):transcribe_openai_whisper(self.source,self.out,self.model)
  self.assertEqual(self.out.read_text(),'keep')
 def test_command_contract(self):
  calls=[]
  def run(cmd,**kwargs):
   calls.append(cmd)
   if cmd[0].endswith('whisper'):
    Path(cmd[cmd.index('--output_dir')+1],'audio.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nOriginal fixture.\n')
   return subprocess.CompletedProcess(cmd,0,'','')
  with patch('whisper_adapter.shutil.which',side_effect=lambda n:'/bin/'+n),patch('whisper_adapter.subprocess.run',side_effect=run):
   result=transcribe_openai_whisper(self.source,self.out,self.model)
  self.assertIn('Original fixture',result.read_text());self.assertEqual(self.source.read_bytes(),b'original')
  command=calls[1];self.assertEqual(command[command.index('--model')+1],str(self.model.resolve()));self.assertEqual(command[command.index('--device')+1],'cpu');self.assertEqual(command[command.index('--fp16')+1],'False');self.assertIn('file,pipe',calls[0])
 def test_empty_result_rejected(self):
  with patch('whisper_adapter.shutil.which',side_effect=lambda n:'/bin/'+n),patch('whisper_adapter.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')):
   with self.assertRaisesRegex(RuntimeError,'nonempty'):transcribe_openai_whisper(self.source,self.out,self.model)
 def test_language_threads_validation(self):
  for language,threads in [('English',4),('en',0),('en',True)]:
   with self.assertRaises(ValueError):transcribe_openai_whisper(self.source,self.out,self.model,language,threads)
if __name__=='__main__':unittest.main()
