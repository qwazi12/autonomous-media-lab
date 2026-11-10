"""Conservative, deterministic evidence gates. No semantic truth certification.

Integrate filter_episode(index, context) before TV/anime generation; merge its
findings with inspect_guards(plan, filtered_index, context, workflow) after plan
validation. Findings are blocking review requests, not proof of falsehood. Keep
filter findings even when evidence is removed. Never turn an empty finding list
into an accuracy approval. IDs and source quotes are retained for human review.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

NUMBER = re.compile(r'(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?(?!\w|\.\d)')
# Deliberately explicit allowlist, not a claim of comprehensive unit parsing.
UNITS = {
    'km': 'km', 'kilometer': 'km', 'kilometers': 'km', 'kilometre': 'km', 'kilometres': 'km',
    'm': 'm', 'meter': 'm', 'meters': 'm', 'metre': 'm', 'metres': 'm',
    'cm': 'cm', 'mm': 'mm', 'mile': 'mile', 'miles': 'mile', 'mi': 'mile',
    'ft': 'ft', 'feet': 'ft', 'foot': 'ft', 'inch': 'inch', 'inches': 'inch',
    'kg': 'kg', 'kilogram': 'kg', 'kilograms': 'kg', 'g': 'g', 'gram': 'g', 'grams': 'g',
    'mg': 'mg', 'lb': 'lb', 'lbs': 'lb', 'pounds': 'lb',
    's': 's', 'sec': 's', 'seconds': 's', 'second': 's', 'minutes': 'min', 'minute': 'min', 'min': 'min',
    'hours': 'h', 'hour': 'h', 'h': 'h', 'days': 'day', 'day': 'day',
    '%': '%', 'percent': '%', 'percentage': '%', '°c': 'C', 'celsius': 'C', '°f': 'F', 'fahrenheit': 'F',
    'usd': 'USD', 'eur': 'EUR', 'gbp': 'GBP', '$': 'USD', '€': 'EUR', '£': 'GBP',
    'ml': 'ml', 'l': 'l', 'liters': 'l', 'litres': 'l', 'hz': 'Hz', 'khz': 'kHz', 'mhz': 'MHz',
    'w': 'W', 'kw': 'kW', 'mw': 'MW', 'j': 'J', 'kj': 'kJ',
}
_UNIT_TOKEN = re.compile(r'^\s*(°[cCfF]|%|[A-Za-z]+)(?![A-Za-z])')
AMBIGUITY = re.compile(r'\b(?:speaker\s+(?:is\s+)?(?:unknown|unclear|ambiguous)|unknown\s+speaker|unclear\s+speaker|ambiguous\s+speaker|speaker\s+(?:could|may|might)\s+be|unattributed\s+(?:speech|dialogue|bubble)|unidentified\s+voice)\b', re.I)


def _finding(code, reason, *, segment_id=None, evidence=None, **details):
    finding = {'code': code, 'severity': 'blocking', 'requires_review': True,
               'segment_id': segment_id, 'reason': reason, 'evidence': evidence or [], **details}
    finding['finding_sha256'] = _fingerprint(finding)
    return finding


def _fingerprint(finding: dict) -> str:
    payload = {key: value for key, value in finding.items()
               if key not in {'finding_sha256', 'human_resolved', 'resolution'}}
    # Resolution state must never change the identity of the original gate.
    payload['severity'] = 'blocking'
    payload['requires_review'] = True
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def apply_resolutions(findings: list[dict], context: dict) -> list[dict]:
    """Apply explicit operator attestations only to identical current findings.

    context.evidence_guard_resolutions is an operator-supplied list of objects:
    {finding_sha256, reviewer, rationale, reviewed: true}. No wildcard/blanket
    approvals, truth claims, or automatic attestations. Stale, malformed, duplicate,
    and unattested entries leave gates blocking. Caller must establish that the
    context came from the authorized operator, not a model or extracted source.
    Original evidence stays intact. This records human review, not factual proof.
    """
    entries = context.get('evidence_guard_resolutions', [])
    if not isinstance(entries, list):
        entries = []
    resolutions = {}
    duplicates = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fingerprint = entry.get('finding_sha256')
        if (not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint)
                or entry.get('reviewed') is not True
                or not isinstance(entry.get('reviewer'), str) or not entry['reviewer'].strip()
                or not isinstance(entry.get('rationale'), str) or not entry['rationale'].strip()):
            continue
        if fingerprint in resolutions:
            duplicates.add(fingerprint)
        resolutions[fingerprint] = entry
    result = []
    for original in findings:
        finding = copy.deepcopy(original)
        finding.pop('human_resolved', None)
        finding.pop('resolution', None)
        finding['severity'] = 'blocking'
        finding['requires_review'] = True
        fingerprint = _fingerprint(finding)
        finding['finding_sha256'] = fingerprint
        if fingerprint in resolutions and fingerprint not in duplicates:
            finding['severity'] = 'review'
            finding['human_resolved'] = True
            entry = resolutions[fingerprint]
            finding['resolution'] = {key: entry[key] for key in
                                     ('finding_sha256', 'reviewer', 'rationale', 'reviewed')}
        result.append(finding)
    return result


def _quote(scene, item):
    return {'scene_id': scene.get('id'), 'evidence_id': item.get('id'),
            'text': item.get('text', ''), 'episode': item.get('episode')}


def filter_episode(index: dict, context: dict) -> tuple[dict, list[dict]]:
    """Return a deep-copied index and blocking findings for withheld evidence.

    When context.episode is set, every evidence item needs its own exact episode
    tag. Missing tags are never inferred from scene/context. Visual descriptions
    also require a matching scene episode tag. Retain original assets but remove
    unscoped textual observations from the generation input.
    """
    result = copy.deepcopy(index)
    episode = context.get('episode')
    if episode is None:
        return result, [_finding('episode_identity_unknown', 'No episode identity supplied; episode provenance cannot be checked.')]
    if not isinstance(episode, str) or not episode.strip():
        raise ValueError('episode must be nonempty text when supplied')
    findings = []
    for scene in result.get('scenes', []):
        kept = []
        for item in scene.get('evidence', []):
            tag = item.get('episode')
            if tag == episode:
                kept.append(item)
            else:
                findings.append(_finding('episode_provenance_unknown' if tag is None or tag == '' else 'episode_mismatch',
                                         'Evidence withheld: its episode provenance is missing or differs from the requested episode.',
                                         evidence=[_quote(scene, item)], expected_episode=episode))
        scene['evidence'] = kept
        if scene.get('visual_description') and scene.get('episode') != episode:
            findings.append(_finding('visual_episode_provenance_unknown', 'Visual description withheld because its scene lacks a matching episode tag.',
                                     evidence=[{'scene_id': scene.get('id'), 'text': scene['visual_description'], 'episode': scene.get('episode')}], expected_episode=episode))
            scene['visual_description'] = None
        if scene.get('episode') != episode:
            for field in ('temporal_observations', 'vision_uncertainties'):
                if scene.get(field):
                    findings.append(_finding('visual_episode_provenance_unknown',
                                             f'{field} withheld because its scene lacks a matching episode tag.',
                                             evidence=[{'scene_id': scene.get('id'), 'field': field,
                                                        'value': copy.deepcopy(scene[field]), 'episode': scene.get('episode')}],
                                             expected_episode=episode))
                # Remove even empty/malformed fields from the model input.
                scene.pop(field, None)
    return result, findings


def quantities(text: str) -> list[dict]:
    """Extract numeric tokens with a small explicit unit vocabulary.

    No conversions, spelled-out quantities, range interpretation, or equation
    checking. Exact raw numbers are intentionally required: 12.0 and 12 differ.
    """
    output = []
    for match in NUMBER.finditer(text):
        following = _UNIT_TOKEN.match(text[match.end():])
        unit = UNITS.get(following.group(1).lower()) if following else None
        prefix = text[max(0, match.start() - 1):match.start()]
        if prefix in {'$', '€', '£'}:
            unit = UNITS[prefix]
        output.append({'number': match.group(), 'unit': unit, 'offset': match.start()})
    return output


def inspect_guards(plan: dict, index: dict, context: dict, workflow: str) -> list[dict]:
    """Report conservative blocking gates; never certify semantic correctness.

    Call structural plan validation first. Unsupported unit changes are flagged
    even if a mathematical conversion could justify them. Prior continuity always
    requires comparison by a reviewer; contradictions are not inferred by rules.
    Ambiguity metadata: speaker_ambiguous=true, speaker_candidates with >1 item,
    speaker in {unknown, unclear, ambiguous}, or supported explicit text phrases.
    """
    findings = []
    scene_map = {scene['id']: scene for scene in index.get('scenes', [])}
    if workflow in {'tv', 'anime'}:
        _, provenance = filter_episode(index, context)
        findings.extend(provenance)
    prior = context.get('prior_continuity') or context.get('continuity_snapshot')
    if workflow in {'tv', 'anime'} and prior:
        findings.append(_finding('continuity_comparison_unknown',
                                 'Prior continuity exists, but semantic consistency with this draft is UNKNOWN. Human comparison is required; no contradiction has been automatically established.',
                                 evidence=[{'prior_continuity': copy.deepcopy(prior)}],
                                 draft_segments=[{'id': s.get('id'), 'narration': s.get('narration')} for s in plan.get('segments', [])]))
    for segment in plan.get('segments', []):
        sid = segment.get('id')
        refs = segment.get('scene_ids', [])
        if not refs or any(ref not in scene_map for ref in refs):
            findings.append(_finding('unknown_scene_reference', 'Missing or unknown scene reference.', segment_id=sid, scene_ids=refs))
            continue
        cited = [scene_map[ref] for ref in refs]
        evidence = [_quote(scene, item) for scene in cited for item in scene.get('evidence', [])]
        if not evidence:
            findings.append(_finding('no_cited_text_evidence', 'No textual evidence remains for this segment.', segment_id=sid))
        allowed = [q for item in evidence for q in quantities(item['text'])]
        for quantity in quantities(segment.get('narration', '')):
            same_number = [q for q in allowed if q['number'] == quantity['number']]
            if not same_number:
                findings.append(_finding('unsupported_numeric_token', 'Narrated numeric token is absent from cited text.', segment_id=sid, evidence=evidence, quantity=quantity))
            elif not any(q['unit'] == quantity['unit'] for q in same_number):
                findings.append(_finding('quantity_unit_mismatch', 'Numeric token is present, but its associated unit differs or is missing. Review the quantity in context; conversions are not automatically validated.', segment_id=sid, evidence=evidence, quantity=quantity, cited_quantities=same_number))
        for scene in cited:
            items = [scene] + scene.get('evidence', [])
            for item in items:
                candidates = item.get('speaker_candidates')
                flagged = (item.get('speaker_ambiguous') is True or
                           (isinstance(candidates, list) and len(candidates) > 1) or
                           str(item.get('speaker', '')).lower() in {'unknown', 'unclear', 'ambiguous'} or
                           bool(AMBIGUITY.search(str(item.get('text', item.get('visual_description', ''))))))
                if flagged:
                    findings.append(_finding('speaker_attribution_ambiguous', 'Cited source explicitly indicates speaker ambiguity. Review all speaker attribution in this segment.', segment_id=sid,
                                             evidence=[{**_quote(scene, item), 'speaker': item.get('speaker'), 'speaker_candidates': candidates,
                                                        'speaker_ambiguous': item.get('speaker_ambiguous')}]))
    # Bind every gate to the exact reviewed draft, including provenance gates.
    # Changing narration or scene references invalidates earlier attestations.
    reviewed_draft = [{'id': s.get('id'), 'narration': s.get('narration'),
                       'scene_ids': s.get('scene_ids')} for s in plan.get('segments', [])]
    for finding in findings:
        finding['reviewed_draft'] = copy.deepcopy(reviewed_draft)
        finding['finding_sha256'] = _fingerprint(finding)
    return findings
