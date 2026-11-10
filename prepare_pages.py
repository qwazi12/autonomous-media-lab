#!/usr/bin/env python3
"""Prepare original/authorized pages for manhwa ingestion; proposed order needs review."""
import argparse,json
from pathlib import Path
from ingest_workers import segment_page,ocr_image

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('pages',nargs='+');p.add_argument('--output',required=True);p.add_argument('--direction',choices=['ltr','rtl'],required=True);p.add_argument('--rights-confirmed',action='store_true');a=p.parse_args()
 if not a.rights_confirmed:p.error('Confirm authority to use the pages with --rights-confirmed')
 out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False);panels=[];reports=[]
 for i,value in enumerate(a.pages):
  result=segment_page(Path(value),out/f'page-{i+1:04}',a.direction);reports.append(result)
  for item in result['panels']:
   ocr=ocr_image(Path(item['image']));panels.append({'image':str(Path(item['image']).relative_to(out)),'description':None,'evidence':[ocr['text']] if ocr['text'] else [],'ocr':ocr,'original_page':str(Path(value).resolve()),'bbox':item['bbox'],'order_verified':False})
 (out/'panels.json').write_text(json.dumps({'panels':panels,'reading_order_verified':False},indent=2));(out/'segmentation.json').write_text(json.dumps(reports,indent=2));print(out/'panels.json')
if __name__=='__main__':main()
