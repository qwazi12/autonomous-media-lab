#!/usr/bin/env python3
"""Generate original synthetic fixtures and exercise all five workflows, no model/API needed.
The narration is explicitly a hand-authored fixture, not an AI-quality demonstration.
"""
import argparse,json,subprocess,sys
from pathlib import Path
from pipeline import ff,save

def create(root):
    root.mkdir(parents=True,exist_ok=False)
    colors=['blue','green','orange']
    for i,c in enumerate(colors):
        ff(['-f','lavfi','-i',f'color=c={c}:s=640x360:d=10','-c:v','libx264','-pix_fmt','yuv420p',str(root/f'{i}.mp4')])
        ff(['-f','lavfi','-i',f'color=c={c}:s=640x360','-frames:v','1',str(root/f'{i}.png')])
    (root/'list.txt').write_text(''.join(f"file '{i}.mp4'\n" for i in range(3)))
    ff(['-f','concat','-safe','1','-i',str(root/'list.txt'),'-c','copy',str(root/'source.mp4')])
    (root/'dialogue.srt').write_text('1\n00:00:00,000 --> 00:00:09,000\nThe signal begins blue.\n\n2\n00:00:10,000 --> 00:00:19,000\nThe signal turns green.\n\n3\n00:00:20,000 --> 00:00:29,000\nThe signal ends orange.\n')
    save(root/'plan.json',{'title':'Synthetic three-color story — integration fixture','segments':[{'id':f'B{i+1:03}','narration':t,'scene_ids':[f'S{i+1:05}'],'review_notes':['Hand-authored synthetic fixture, not generated story understanding.']} for i,t in enumerate(['The screen starts blue. This establishes the first signal in our simple demonstration.','The screen changes to green, marking the next stage of the sequence.','Finally the screen turns orange. This concludes the three color demonstration.'])]})
    cards=[{'image':f'{i}.png','description':f'A solid {c} frame.','evidence':[f'The displayed color is {c}.'],'source_url':'urn:original:synthetic-fixture','as_of':'2026-11-09'} for i,c in enumerate(colors)]
    save(root/'panels.json',{'panels':cards});save(root/'cards.json',{'cards':cards})

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='demo');p.add_argument('--all',action='store_true');a=p.parse_args()
    root=Path(a.output).resolve();create(root)
    workflows=['movie','tv','anime','manhwa','educational'] if a.all else ['movie']
    for workflow in workflows:
        source=root/('panels.json' if workflow=='manhwa' else 'cards.json' if workflow=='educational' else 'source.mp4')
        cmd=[sys.executable,str(Path(__file__).with_name('pipeline.py')),'--source',str(source),'--plan',str(root/'plan.json'),'--output',str(root/workflow),'--workflow',workflow,'--rights-confirmed']
        if workflow in ('movie','tv','anime'):cmd+=['--subtitles',str(root/'dialogue.srt')]
        subprocess.run(cmd,check=True)
if __name__=='__main__':main()
