"""Evidence coverage and measurable draft acceptance, never automatic legal approval."""
import re

def evaluate(index,plan,qa,target_seconds,workflow):
    checks=[]
    def add(name,passed,detail):checks.append({'name':name,'status':'pass' if passed else 'review_required','detail':detail})
    scenes={s['id']:s for s in index['scenes']}
    missing=[]
    for b in plan['segments']:
        refs=[scenes[r] for r in b['scene_ids']]
        if not any(s.get('evidence') or s.get('visual_description') for s in refs):missing.append(b['id'])
    add('source_evidence_present',not missing,{'segments_without_text_or_visual_observations':missing})
    issues=plan.get('critic',{}).get('issues',[])
    add('critic_findings',plan.get('generator')!='imported_plan' and not issues,
        {'issues':issues,'critic_is_proof':False,'imported_script':plan.get('generator')=='imported_plan'})
    duration=qa.get('duration_seconds',0)
    add('requested_duration',target_seconds*.8<=duration<=target_seconds*1.2,{'actual_seconds':duration,'target_seconds':target_seconds,'tolerance_fraction':.2})
    add('visual_pacing',not any('freeze padding' in s for s in qa.get('warnings',[]) if isinstance(s,str)),{'check':'freeze padding warning'})
    findings=plan.get('workflow_findings',[])
    add('specialized_worker_findings',not findings,{'findings':findings})
    if workflow in ('movie','tv','anime'):
        absent=[s['id'] for s in scenes.values() if not s.get('temporal_observations')]
        add('multimodal_coverage',not absent,{'scenes_without_temporal_observations':absent,'sampling_does_not_prove_completeness':True})
    add('human_editorial_review',False,{'requirement':'A reviewer must verify story, visual matches, pronunciation, rights and quality against the actual output.'})
    return {'schema_version':1,'status':'human_review_required','checks':checks,'ready_to_publish':False,
      'limitations':['Structural references do not prove semantic support.','No copyright or publication authorization is inferred.']}
