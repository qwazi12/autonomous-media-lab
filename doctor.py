#!/usr/bin/env python3
"""Read-only readiness report; never installs, downloads, creates credentials or starts services."""
import argparse,json,shutil,subprocess,urllib.request
from pathlib import Path
from pipeline import NoRedirect

def inspect(model=None,vision_model=None,asr_model=None):
    report={'tools':{},'models':{},'ready':False,'network':'loopback read-only; proxies and redirects disabled'}
    for name in ('ffmpeg','ffprobe','tesseract','whisper','whisper-cli'):
        report['tools'][name]={'available':bool(shutil.which(name))}
    if shutil.which('ffmpeg'):
        p=subprocess.run(['ffmpeg','-hide_banner','-filters'],capture_output=True,text=True,timeout=15)
        report['tools']['flite']={'available':p.returncode==0 and 'flite' in p.stdout}
    wanted=[x for x in (model,vision_model) if x]
    report['models']['requested']=wanted
    if wanted:
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            with opener.open('http://127.0.0.1:11434/api/tags',timeout=3) as r:data=json.load(r)
            names={m['name'] for m in data.get('models',[]) if isinstance(m,dict) and isinstance(m.get('name'),str)}
            report['models']['installed_matches']={w:w in names or w+':latest' in names for w in wanted}
            report['models']['cloud_names_rejected']=all('cloud' not in w.lower() for w in wanted)
            report['models']['warning']='Custom model aliases or modified servers require operator verification that inference is local.'
        except Exception as e:report['models']['error']=type(e).__name__
    if asr_model:report['asr_weights']={'exists':Path(asr_model).is_file(),'downloads_attempted':False}
    report['ready']=all(report['tools'][n]['available'] for n in ('ffmpeg','ffprobe')) and (not wanted or (all(report['models'].get('installed_matches',{}).values()) and bool(report['models'].get('installed_matches')) and report['models'].get('cloud_names_rejected',False)))
    report['limits']='Readiness is not proof of model quality, licenses, semantic correctness or successful rendering.'
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model');p.add_argument('--vision-model');p.add_argument('--asr-model');a=p.parse_args()
    print(json.dumps(inspect(a.model,a.vision_model,a.asr_model),indent=2))
