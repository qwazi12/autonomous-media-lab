"""Generate a portable, offline review page for an unreviewed recap draft."""
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _time(value: object) -> str:
    try:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            return "unknown"
    except (TypeError, ValueError, OverflowError):
        return "unknown"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02}:{minutes:02}:{seconds:06.3f}"


def _range(item: dict) -> str:
    return f"{_time(item.get('start'))} – {_time(item.get('end'))}"


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _thumbnail(scene: dict) -> str | None:
    # Never load a remote URL or a file outside the exported frame directory.
    candidate = scene.get("thumbnail")
    if isinstance(candidate, str) and re.fullmatch(r"frames/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp)", candidate):
        return candidate
    scene_id = str(scene.get("id", ""))
    if re.fullmatch(r"[A-Za-z0-9_-]+", scene_id):
        return f"frames/{scene_id}.jpg"
    return None


def _notes(value: object) -> str:
    values = value if isinstance(value, list) else [value]
    return "".join(f"<li>{_escape(v)}</li>" for v in values if v is not None and str(v).strip())


def write_review(path: Path, index: dict, plan: dict, qa: dict) -> None:
    """Write self-contained HTML beside draft.mp4 and the frames directory.

    Every source-derived string is HTML escaped. Frame locations are confined to
    safe relative names. No external fonts, scripts, or network assets are used.
    QA is surfaced as supplied evidence, never as a claim of human approval.
    """
    scenes = [s for s in _list(index.get("scenes")) if isinstance(s, dict)]
    lookup = {str(s.get("id")): s for s in scenes}
    anchors = {str(s.get("id")): f"scene-{i}" for i, s in enumerate(scenes)}
    scene_html = []
    for i, scene in enumerate(scenes):
        source = _thumbnail(scene)
        media = (f'<img loading="lazy" src="{_escape(source)}" alt="Frame for scene {_escape(scene.get("id"))}">'
                 if source else '<div class="missing">No safe thumbnail path available</div>')
        evidence = []
        for item in _list(scene.get("evidence")):
            if isinstance(item, dict):
                evidence.append(f'<li><div class="eyebrow">Evidence {_escape(item.get("id"))} · {_escape(_range(item))}</div><p>{_escape(item.get("text"))}</p></li>')
        evidence_html = "".join(evidence) or '<li class="warning">No textual evidence supplied for this scene.</li>'
        description = scene.get("visual_description") or "No visual description supplied."
        scene_html.append(f'''<article class="scene" id="scene-{i}">
          <div class="frame">{media}<p class="media-error" hidden>Thumbnail unavailable. Check the exported frames directory.</p></div>
          <div class="scene-body"><h3>Scene {_escape(scene.get('id'))}</h3>
          <div class="eyebrow">Source time {_escape(_range(scene))}</div>
          <p>{_escape(description)}</p><h4>Supporting evidence</h4><ul class="evidence">{evidence_html}</ul></div></article>''')
    segments = [s for s in _list(plan.get("segments")) if isinstance(s, dict)]
    segment_html = []
    for i, segment in enumerate(segments):
        citations = []
        for scene_id in _list(segment.get("scene_ids")):
            key = str(scene_id)
            if key in lookup:
                citations.append(f'<a class="citation" href="#{anchors[key]}">Scene {_escape(scene_id)} · {_escape(_range(lookup[key]))}</a>')
            else:
                citations.append(f'<span class="citation warning">Missing scene: {_escape(scene_id)}</span>')
        citations_html = "".join(citations) or '<span class="warning">No scene citations supplied.</span>'
        notes = _notes(segment.get("review_notes"))
        notes_html = f'<div class="review-notes"><h4>Review notes / uncertainty</h4><ul>{notes}</ul></div>' if notes else '<p class="muted">No segment review notes supplied. Verify narration against the evidence.</p>'
        segment_html.append(f'''<article class="segment"><div class="eyebrow">Segment {i + 1} · {_escape(segment.get('id'))}</div>
          <h3>Narration</h3><p class="narration">{_escape(segment.get('narration')) or 'No narration supplied.'}</p>
          <div class="citations">{citations_html}</div>{notes_html}</article>''')
    qa_html = _escape(json.dumps(qa, ensure_ascii=False, indent=2, default=str)) if qa else "No automated QA results supplied."
    title = _escape(plan.get("title") or "Recap review")
    document = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>''' + title + ''' · Draft review</title><style>
:root{color-scheme:dark;--bg:#0c1421;--panel:#142035;--border:#2d3d56;--ink:#edf3fc;--muted:#aebdd2;--accent:#78d8cb;--warn:#ffd395}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}main{max-width:1260px;margin:auto;padding:32px 24px 64px}h1{font-size:clamp(28px,4vw,46px);line-height:1.15;margin:14px 0}h2{font-size:24px;margin:28px 0 14px}h3,h4,p{margin:0 0 12px}h4{font-size:14px;color:var(--muted)}a{color:var(--accent)}a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:4px}.badge{display:inline-block;color:var(--warn);border:1px solid #756044;background:#332c22;border-radius:99px;padding:4px 12px;font-size:12px;font-weight:700;letter-spacing:.08em}.muted,.eyebrow{color:var(--muted)}.eyebrow{font-size:12px;letter-spacing:.04em;margin-bottom:9px}.intro{max-width:850px}.layout{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:28px}.panel,.segment,.scene{background:var(--panel);border:1px solid var(--border);border-radius:16px;overflow:hidden}.panel,.segment{padding:20px}.segment{margin-bottom:16px}.narration{font-size:18px;white-space:pre-wrap;overflow-wrap:anywhere}.citations{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.citation{font-size:12px;padding:6px 10px;border:1px solid var(--border);border-radius:8px;text-decoration:none}.citation:hover{border-color:var(--accent)}.warning{color:var(--warn)}.review-notes{border-left:3px solid var(--warn);padding-left:14px}.review-notes ul{margin:0;padding-left:20px}video{display:block;width:100%;max-height:420px;background:#05090f;border-radius:12px}.media-error,.missing{color:var(--warn);padding:18px;margin:0}.scene{scroll-margin-top:20px;margin-bottom:18px}.scene-body{padding:20px}.frame{background:#070d16}.frame img{display:block;width:100%;max-height:300px;object-fit:contain}.evidence{list-style:none;padding:0;margin:0}.evidence li{border-top:1px solid var(--border);padding:12px 0 0;margin-top:12px}.evidence p{white-space:pre-wrap;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 ui-monospace,monospace;color:var(--warn)}summary{cursor:pointer;font-weight:650}footer{color:var(--muted);font-size:13px;border-top:1px solid var(--border);margin-top:30px;padding-top:20px}[hidden]{display:none!important}@media(max-width:800px){main{padding:24px 16px}.layout{grid-template-columns:1fr;gap:0}.panel,.segment,.scene-body{padding:16px}}
</style></head><body><main><header><span class="badge">DRAFT · HUMAN REVIEW REQUIRED</span><h1>''' + title + '''</h1><p class="muted intro">Review narration alongside cited source scenes. Automated evidence and QA can be incomplete or wrong. This page does not establish factual accuracy, permission to use source material, or human approval.</p></header>
<div class="layout"><section aria-label="Draft and narration"><h2>Draft preview</h2><div class="panel"><video controls preload="metadata" src="draft.mp4" aria-label="Draft recap video">Your browser cannot play this video. Open draft.mp4 in a compatible player.</video><p class="media-error" id="video-error" hidden>Draft video unavailable or unsupported. Keep draft.mp4 beside this review page, or open it in a compatible player.</p><p class="muted">Unreviewed draft. Evidence times below refer to the source movie, not the draft timeline.</p></div><h2>Narration &amp; citations</h2>''' + ("".join(segment_html) or '<p class="warning">No planned segments supplied.</p>') + '''<h2>Automated QA / warnings</h2><details class="panel" open><summary>Inspect supplied QA results</summary><pre>''' + qa_html + '''</pre></details></section><section aria-label="Source evidence"><h2>Source evidence</h2>''' + ("".join(scene_html) or '<p class="warning">No indexed scenes supplied.</p>') + '''</section></div><footer>Offline review artifact · Check each claim, source alignment, audiovisual quality, and rights before publication.</footer></main><script>
const video=document.querySelector('video');
function showVideoError(){document.getElementById('video-error').hidden=false;}
video.addEventListener('error',showVideoError);if(video.error)showVideoError();
document.querySelectorAll('.frame img').forEach(img=>{function showError(){img.hidden=true;img.parentElement.querySelector('.media-error').hidden=false;}img.addEventListener('error',showError);if(img.complete&&img.naturalWidth===0)showError();});
</script></body></html>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
