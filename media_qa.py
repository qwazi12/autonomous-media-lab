"""Measured audiovisual checks; no subjective quality or rights certification."""
import json,re,subprocess
from pathlib import Path
import render

def inspect_media(path,expected_seconds=None):
 path=render.local_path(path,'Rendered video')
 data=json.loads(render.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
 streams=data['streams'];video=next((s for s in streams if s['codec_type']=='video'),None);audio=next((s for s in streams if s['codec_type']=='audio'),None)
 checks=[{'name':'video_stream','status':'pass' if video else 'fail'},{'name':'audio_stream','status':'pass' if audio else 'fail'}]
 duration=float(data['format']['duration'])
 if expected_seconds is not None:checks.append({'name':'duration','status':'pass' if abs(duration-expected_seconds)<0.15 else 'fail','measured':duration,'expected':expected_seconds})
 cmd=['ffmpeg','-hide_banner','-nostdin','-protocol_whitelist','file,pipe','-i',str(path),'-vf','blackdetect=d=1:pix_th=0.10','-af','silencedetect=noise=-45dB:d=1,volumedetect','-f','null','-']
 proc=subprocess.run(cmd,capture_output=True,text=True,timeout=7200)
 if proc.returncode:checks.append({'name':'signal_scan','status':'error','detail':proc.stderr[-1500:]})
 else:
  black=re.findall(r'black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)',proc.stderr)
  silence=re.findall(r'silence_end: ([\d.]+) \| silence_duration: ([\d.]+)',proc.stderr)
  peak=re.search(r'max_volume: ([-\d.]+) dB',proc.stderr)
  checks.extend([{'name':'black_intervals','status':'review' if black else 'pass','intervals':black},{'name':'silence_intervals','status':'review' if silence else 'pass','intervals':silence},{'name':'peak_volume','status':'review' if peak and float(peak[1])>=-0.1 else 'pass','dbfs':float(peak[1]) if peak else None}])
 return {'checks':checks,'duration_seconds':duration,'width':video.get('width') if video else None,'height':video.get('height') if video else None,'limitations':['Black/silence may be intentional.','Peak scan is not loudness normalization or perceptual audio review.','Semantic accuracy and rights are not verified.']}
