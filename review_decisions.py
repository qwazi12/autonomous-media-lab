#!/usr/bin/env python3
"""Local review decisions tied to artifact bytes, not an accuracy certificate.

All files below an output directory, except this module's .review/ metadata,
are SHA-256 fingerprinted. Changed, added or missing files invalidate decisions.
This is a local audit log, not authenticated identity or tamper-proof storage.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
from pathlib import Path
import sqlite3
import stat
import sys
from datetime import datetime, timezone

DECISIONS = ('approve', 'reject', 'request_changes')
REQUIRED = ('draft.mp4', 'index.json', 'plan.json', 'qa.json')


def snapshot(root: Path) -> dict:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Artifact root must be a directory')
    for name in REQUIRED:
        if not (root / name).is_file():
            raise ValueError('Required review artifact missing: ' + name)
    hashes = {}
    def visit(directory):
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root)
            if relative.parts[0] == '.review':
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError('Symlink artifacts are not supported: ' + str(relative))
            if stat.S_ISDIR(mode):
                visit(path)
            elif stat.S_ISREG(mode):
                before = path.stat()
                digest = hashlib.sha256()
                with path.open('rb') as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                        digest.update(chunk)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                    raise ValueError('Artifact changed while hashing: ' + str(relative))
                hashes[relative.as_posix()] = digest.hexdigest()
            else:
                raise ValueError('Unsupported artifact file type: ' + str(relative))
    visit(root)
    encoded = json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()
    return {'algorithm': 'sha256', 'files': hashes, 'digest': hashlib.sha256(encoded).hexdigest()}


def _metadata(root):
    directory = Path(root).resolve() / '.review'
    if directory.is_symlink():
        raise ValueError('Review metadata directory cannot be a symlink')
    directory.mkdir(exist_ok=True)
    return directory


def record_decision(root: Path, decision: str, reviewer: str, notes: str = '', *, attest_reviewed: bool = False, expected_snapshot: dict | None = None) -> dict:
    if decision not in DECISIONS:
        raise ValueError('Decision must be approve, reject, or request_changes')
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError('A nonempty reviewer name is required')
    if not isinstance(notes, str):
        raise ValueError('Notes must be text')
    if attest_reviewed is not True:
        raise ValueError('Explicit human review attestation is required; do not auto-approve')
    current = snapshot(root)
    if expected_snapshot is not None and current != expected_snapshot:
        raise ValueError('Artifacts differ from the reviewed snapshot. Review the current files again.')
    record = {'schema_version': 1, 'decision': decision, 'reviewer': reviewer.strip(), 'notes': notes,
              'attest_reviewed': True, 'recorded_at': datetime.now(timezone.utc).isoformat(), 'snapshot': current,
              'limitations': 'User-asserted local review only; not authenticated identity, semantic verification, rights clearance, or publication authorization.'}
    database = _metadata(root) / 'decisions.sqlite'
    if database.is_symlink():
        raise ValueError('Review database cannot be a symlink')
    if database.exists() and database.stat().st_nlink > 1:
        raise ValueError('Review database cannot have multiple hard links')
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL)')
        # Rehash before committing so common concurrent edits fail closed.
        if snapshot(root) != current:
            raise ValueError('Artifacts changed before saving the review decision')
        cursor = connection.execute('INSERT INTO decisions(record) VALUES (?)', (json.dumps(record, ensure_ascii=False),))
        record['id'] = cursor.lastrowid
    return record


def import_decision(root: Path, payload: dict, *, attest_reviewed: bool = False) -> dict:
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or not isinstance(payload.get('snapshot'), dict):
        raise ValueError('Invalid decision payload or missing artifact snapshot')
    # JSON alone does not authorize recording a human decision. CLI requires an
    # explicit attestation even when the browser export contains its checkbox.
    return record_decision(root, payload.get('decision'), payload.get('reviewer'), payload.get('notes', ''),
                           attest_reviewed=attest_reviewed, expected_snapshot=payload['snapshot'])


def review_status(root: Path) -> dict:
    database = Path(root).resolve() / '.review' / 'decisions.sqlite'
    if database.parent.is_symlink() or database.is_symlink():
        raise ValueError('Review metadata cannot use symlinks')
    if not database.exists():
        return {'status': 'unreviewed', 'valid': False, 'decision': None}
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        row = connection.execute('SELECT id, record FROM decisions ORDER BY id DESC LIMIT 1').fetchone()
    if not row:
        return {'status': 'unreviewed', 'valid': False, 'decision': None}
    record = json.loads(row[1])
    record['id'] = row[0]
    try:
        current = snapshot(root)
    except (ValueError, OSError) as exc:
        return {'status': 'invalidated', 'valid': False, 'decision': record, 'reason': str(exc)}
    old = record['snapshot']['files']
    new = current['files']
    changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    valid = current == record['snapshot']
    return {'status': record['decision'] if valid else 'invalidated', 'valid': valid,
            'decision': record, 'changed_artifacts': changed}


def export_decision_ui(root: Path) -> Path:
    """Export an offline companion page under .review/, never persist on click.

    Browser downloads a payload only. Import it with the CLI and explicit human
    attestation; import rejects outdated artifact hashes. Keep downloads outside
    the artifact root so they do not themselves invalidate the snapshot.
    """
    frozen = json.dumps(snapshot(root), ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    target = _metadata(root) / 'decision.html'
    if target.is_symlink():
        raise ValueError('Review UI cannot be a symlink')
    if target.exists() and target.stat().st_nlink > 1:
        raise ValueError('Review UI cannot have multiple hard links')
    target.write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Record draft review</title>
<style>body{font:17px/1.6 system-ui;background:#111b2b;color:#edf3fc;max-width:760px;margin:40px auto;padding:20px}a{color:#7dd9cc}label{display:block;margin:18px 0}input:not([type=checkbox]),textarea,select,button{box-sizing:border-box;width:100%;padding:12px;font:inherit}textarea{min-height:120px}.warning{color:#ffd395}button{cursor:pointer}</style>
<h1>Draft review decision</h1><p class="warning">Human review required. This page exports a decision payload; it does not save approval, verify factual accuracy, or authorize publication.</p>
<p><a href="../review.html">Open evidence review</a> · <a href="../draft.mp4">Open draft video</a></p>
<p>Review the draft and evidence before choosing a decision. If any artifact changes after this page was generated, generate a fresh page and review again.</p>
<form id="form"><label>Reviewer name<input id="reviewer" required maxlength="300"></label><label>Decision<select id="decision"><option value="request_changes">Request changes</option><option value="reject">Reject</option><option value="approve">Approve</option></select></label><label>Review notes<textarea id="notes"></textarea></label><label><input type="checkbox" id="attest" required> I reviewed these artifacts and intend to record this decision.</label><button>Download decision payload</button></form>
<p>Save the download outside the artifact directory. Then import it using review_decisions.py import ROOT PAYLOAD --attest-reviewed. Nothing is uploaded.</p><p id="status" role="status"></p>
<script type="application/json" id="snapshot">''' + frozen + '''</script><script>
document.getElementById('form').addEventListener('submit',event=>{event.preventDefault();const payload={schema_version:1,decision:document.getElementById('decision').value,reviewer:document.getElementById('reviewer').value,notes:document.getElementById('notes').value,attest_reviewed:document.getElementById('attest').checked,snapshot:JSON.parse(document.getElementById('snapshot').textContent)};const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='review-decision.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);document.getElementById('status').textContent='Payload download requested. Decision is not persisted until CLI import succeeds.';});
</script></html>''', encoding='utf-8')
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('record', 'import', 'status', 'export-ui'):
        sub = commands.add_parser(command)
        sub.add_argument('root', type=Path)
        if command in ('record', 'import'):
            sub.add_argument('--attest-reviewed', action='store_true', help='Explicitly assert that a human reviewed the artifacts and authorized this decision')
        if command == 'record':
            sub.add_argument('decision', choices=DECISIONS)
            sub.add_argument('--reviewer', required=True)
            sub.add_argument('--notes', default='')
        if command == 'import':
            sub.add_argument('payload', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'record':
            result = record_decision(args.root, args.decision, args.reviewer, args.notes, attest_reviewed=args.attest_reviewed)
        elif args.command == 'import':
            result = import_decision(args.root, json.loads(args.payload.read_text(encoding='utf-8')), attest_reviewed=args.attest_reviewed)
        elif args.command == 'status':
            result = review_status(args.root)
        else:
            result = {'path': str(export_decision_ui(args.root))}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as exc:
        print('Review decision error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
