#!/usr/bin/env python3
"""Export a validated completed run to a local Remotion public-assets bundle. No render/install."""
import argparse,json,math,shutil,hashlib
from checkpoints import Checkpoints
from pathlib import Path
import render

def export(run,source,destination,fps=30):
 run=Path(run).resolve();source=render.local_path(source,'Source');dest=Path(destination).resolve()
 if dest.exists():raise ValueError('Destination exists; choose a new local bundle directory')
 if any(p.is_symlink() for p in run.rglob('*')):raise ValueError('Run contains symlinks')
 state=json.loads((run/'checkpoint.json').read_text());ledger=json.loads((run/'run.json').read_text())
 if ledger.get('status')!='draft_complete':raise ValueError('Only completed draft runs can be exported')
 cp=Checkpoints(run,state['signature'],resume=True)
 if not all(cp.valid(s) for s in ('index','plan','audio','render')):raise ValueError('Run artifacts failed checkpoint validation')
 if 'project.json' not in state['stages']['render']:raise ValueError('Project is not included in verified render checkpoint')
 if ledger.get('workflow') in ('manhwa','educational'):
  if source!=(run/'source.mp4').resolve():raise ValueError('Supply the verified generated panel/card source.mp4')
 else:
  h=hashlib.sha256()
  with source.open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  if h.hexdigest()!=ledger.get('source_hash'):raise ValueError('Source does not match completed run')
 project=json.loads((run/'project.json').read_text());scenes=render.validate_project(project,render.probe(source,'video'))
 dest.mkdir(parents=True);assets=dest/'public';assets.mkdir();shutil.copyfile(source,assets/'source.mp4')
 clips=[];audio=[];cursor=0
 for scene_index,s in enumerate(scenes):
  length=math.ceil(s['duration']*fps);remaining=length;position=cursor
  for shot in s['shots']:
   n=min(remaining,max(1,round((shot['out']-shot['in'])*fps)))
   if remaining<=0:break
   clips.append({'startFrame':position,'durationFrames':n,'sourceStartFrame':round(shot['in']*fps),'src':'source.mp4','kind':'video','caption':s['narration']})
   remaining-=n;position+=n
  if remaining:
   thumb=f"freeze-{scene_index:05}.jpg";at=max(s['shots'][-1]['in'],s['shots'][-1]['out']-0.05)
   render.run(['ffmpeg','-v','error','-nostdin','-ss',str(at),'-i',str(source),'-frames:v','1',str(assets/thumb)])
   clips.append({'startFrame':position,'durationFrames':remaining,'sourceStartFrame':0,'src':thumb,'kind':'image','caption':s['narration']})
  wav=render.audio_path(run/'audio',s['audioFile']);audio_name=f'audio-{scene_index:05}.wav';shutil.copyfile(wav,assets/audio_name);audio.append({'startFrame':cursor,'src':audio_name});cursor+=length
 manifest={'title':project['title'],'fps':fps,'width':1280,'height':720,'clips':clips,'audio':audio}
 (dest/'manifest.json').write_text(json.dumps(manifest,indent=2));return dest/'manifest.json'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(export(a.run,a.source,a.output))
if __name__=='__main__':main()
