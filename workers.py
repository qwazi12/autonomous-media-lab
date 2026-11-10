"""Specialized deterministic preparation and review workers.
Models remain creative assistants; these workers enforce format-specific contracts.
"""
import copy,re

class WorkerError(ValueError):pass

def require_text(value,label):
    if not isinstance(value,str) or not value.strip():raise WorkerError(f'{label} must be nonempty text')
    return value

class MovieWorker:
    name='movie'
    def prepare(self,index,context):
        result=copy.deepcopy(index)
        result['workflow_context']={'format':self.name,'narrative_order':'screen order; flashbacks need explicit review','characters':context.get('characters',[])}
        return result
    def inspect(self,plan,index,context):
        findings=[];scene_map={s['id']:s for s in index['scenes']};last=-1
        for b in plan['segments']:
            refs=[scene_map[r] for r in b['scene_ids']]
            if min(r['start'] for r in refs)<last:findings.append({'segment_id':b['id'],'severity':'review','reason':'Source order moves backward; verify flashback or deliberate editorial jump.'})
            last=max(r['end'] for r in refs)
            if not any(r.get('evidence') or r.get('visual_description') for r in refs):findings.append({'segment_id':b['id'],'severity':'review','reason':'No textual or vision observations support the cited scene; inspect footage.'})
        return findings

class TVWorker(MovieWorker):
    name='tv'
    def prepare(self,index,context):
        r=super().prepare(index,context)
        episode=context.get('episode')
        if episode is not None:
            require_text(episode,'episode')
            # Evidence explicitly tagged to another episode cannot enter this recap.
            for scene in r['scenes']:
                scene['evidence']=[e for e in scene.get('evidence',[]) if e.get('episode',episode)==episode]
        r['workflow_context'].update({'episode':episode,'prior_continuity':context.get('prior_continuity',[]),'spoiler_boundary':context.get('spoiler_boundary',episode),'continuity_verified':False})
        return r
    def inspect(self,plan,index,context):
        issues=super().inspect(plan,index,context)
        if not context.get('episode'):issues.append({'severity':'review','reason':'Episode identity missing; no season continuity can be certified.'})
        return issues

class AnimeWorker(MovieWorker):
    name='anime'
    def prepare(self,index,context):
        r=super().prepare(index,context);aliases=context.get('aliases',{})
        if not isinstance(aliases,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in aliases.items()):raise WorkerError('aliases must map names to canonical names')
        r['workflow_context'].update({'aliases':aliases,'pronunciations':context.get('pronunciations',{}),'identity_verified':False})
        # Preserve exact original evidence and add annotations instead of rewriting it.
        for s in r['scenes']:
            for e in s.get('evidence',[]):
                e['alias_mentions']=[{'observed':a,'canonical':c} for a,c in aliases.items() if re.search(r'\b'+re.escape(a)+r'\b',e.get('text',''),re.I)]
        return r

class ManhwaWorker(MovieWorker):
    name='manhwa'
    def prepare(self,index,context):
        r=super().prepare(index,context);direction=context.get('reading_direction','ltr')
        if direction not in ('ltr','rtl','vertical'):raise WorkerError('reading_direction must be ltr, rtl or vertical')
        r['workflow_context'].update({'reading_direction':direction,'order_confirmed':context.get('order_confirmed') is True,'chapter':context.get('chapter')})
        for i,s in enumerate(r['scenes']):s['panel_order']=i+1
        return r
    def inspect(self,plan,index,context):
        issues=super().inspect(plan,index,context)
        if context.get('order_confirmed') is not True:issues.append({'severity':'review','reason':'Panel reading order has not been confirmed by the operator.'})
        return issues

class EducationalWorker(MovieWorker):
    name='educational'
    def prepare(self,index,context):
        r=super().prepare(index,context);claims=[]
        for s in r['scenes']:
            for e in s.get('evidence',[]):
                if not e.get('source_url') or not e.get('as_of'):raise WorkerError('Every educational evidence item requires a source and as-of date')
                claims.append({'id':e['id'],'scene_id':s['id'],'claim':e['text'],'source':e['source_url'],'as_of':e['as_of'],'verified':False})
        if not claims:raise WorkerError('Educational workflow needs sourced evidence claims')
        r['claim_ledger']=claims
        r['workflow_context'].update({'learning_objectives':context.get('learning_objectives',[]),'audience':context.get('audience','general'),'sources_independently_verified':False})
        return r
    def inspect(self,plan,index,context):
        issues=super().inspect(plan,index,context)
        for b in plan['segments']:
            # Detect novel numeric strings for review; this is not equation verification.
            allowed=' '.join(e['text'] for s in index['scenes'] if s['id'] in b['scene_ids'] for e in s.get('evidence',[]))
            for number in re.findall(r'\b\d+(?:[.,]\d+)*%?',b['narration']):
                if number not in allowed:issues.append({'segment_id':b['id'],'severity':'review','reason':f'Numeric assertion {number} not found in cited evidence.'})
        issues.append({'severity':'review','reason':'Source URLs and claims need independent factual verification.'})
        return issues

WORKERS={w.name:w for w in (MovieWorker,TVWorker,AnimeWorker,ManhwaWorker,EducationalWorker)}
def get_worker(kind):
    try:return WORKERS[kind]()
    except KeyError:raise WorkerError('Unknown workflow')
