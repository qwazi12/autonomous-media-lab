"""Persistent, evidence-cited TV/anime continuity. No inference or network calls.

Episode order is an explicit positive integer, never guessed from labels. Entries
are immutable: exact replays are idempotent, changed replays fail. Assertions
require operator review and exact quotations, but this is provenance validation,
not independent semantic verification. Conflicting values may represent temporal
change; they are surfaced for review, never automatically resolved.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import stat
from pathlib import Path
import re
import sqlite3
import sys


class ContinuityError(ValueError):
    pass


def _text(value, name, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContinuityError(f'{name} requires nonempty text up to {limit} characters')
    return value


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _id(value):
    return hashlib.sha256(_encode(value).encode('utf-8')).hexdigest()


def _fields(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ContinuityError(f'{label} must be an object with supported fields only')


def validate_episode(payload):
    _fields(payload, ('episode_id', 'position', 'source_sha256', 'evidence', 'facts', 'aliases'), 'Episode')
    episode = _text(payload.get('episode_id'), 'episode_id', 200)
    position = payload.get('position')
    if type(position) is not int or position < 1:
        raise ContinuityError('position must be an explicit positive integer')
    source = payload.get('source_sha256')
    if not isinstance(source, str) or not re.fullmatch('[a-fA-F0-9]{64}', source):
        raise ContinuityError('source_sha256 must identify the source content')
    evidence = payload.get('evidence')
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 10000:
        raise ContinuityError('Episode requires 1–10000 evidence records')
    by_id = {}
    for row in evidence:
        _fields(row, ('id', 'text', 'scene_id', 'start', 'end'), 'Evidence')
        evidence_id = _text(row.get('id'), 'evidence id', 200)
        if evidence_id in by_id:
            raise ContinuityError('Evidence IDs must be unique within an episode')
        normalized = {'id': evidence_id, 'text': _text(row.get('text'), 'evidence text', 20000)}
        if 'scene_id' in row:
            normalized['scene_id'] = _text(row['scene_id'], 'scene_id', 200)
        if ('start' in row) != ('end' in row):
            raise ContinuityError('Evidence timing requires both start and end')
        if 'start' in row:
            a, b = row['start'], row['end']
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (a, b)) or not 0 <= a < b:
                raise ContinuityError('Evidence timing must be finite and 0 <= start < end')
            normalized.update(start=float(a), end=float(b))
        if 'scene_id' not in normalized and 'start' not in normalized:
            raise ContinuityError('Evidence needs a scene_id or time range locating its source')
        by_id[evidence_id] = normalized

    def assertions(kind, keys):
        rows = payload.get(kind, [])
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ContinuityError(f'{kind} must be a bounded list')
        results = {}
        for row in rows:
            _fields(row, (*keys, 'evidence_refs', 'operator_reviewed'), kind)
            if row.get('operator_reviewed') is not True:
                raise ContinuityError('Assertions require explicit operator_reviewed true')
            item = {key: _text(row.get(key), key) for key in keys}
            refs = row.get('evidence_refs')
            if not isinstance(refs, list) or not refs:
                raise ContinuityError('Every assertion requires quoted source evidence')
            citations = {}
            for ref in refs:
                _fields(ref, ('id', 'quote'), 'Evidence reference')
                evidence_id = _text(ref.get('id'), 'reference id', 200)
                quote = _text(ref.get('quote'), 'quote', 20000)
                if evidence_id not in by_id or quote not in by_id[evidence_id]['text']:
                    raise ContinuityError('References must quote existing evidence from this exact episode')
                citations[(evidence_id, quote)] = {'id': evidence_id, 'quote': quote}
            item['evidence_refs'] = [citations[key] for key in sorted(citations)]
            item['operator_reviewed'] = True
            results[_encode(item)] = item
        return [results[key] for key in sorted(results)]

    return {'episode_id': episode, 'position': position, 'source_sha256': source.lower(),
            'evidence': [by_id[key] for key in sorted(by_id)],
            'facts': assertions('facts', ('subject', 'predicate', 'value')),
            'aliases': assertions('aliases', ('alias', 'canonical'))}


def _safe_database_path(value):
    # Inspect lexical parents before resolve() can hide a linked directory.
    raw = Path(os.path.abspath(os.path.expanduser(os.fspath(value))))
    for entry in (*reversed(raw.parents), raw):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ContinuityError('Continuity database path and parents must not be symlinks')
        if entry == raw:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise ContinuityError('Continuity database must be an unlinked regular file')
        elif not stat.S_ISDIR(info.st_mode):
            raise ContinuityError('Continuity database parents must be directories')
    # SQLite may write these companions itself. Protect pre-existing links too.
    for suffix in ('-journal', '-wal', '-shm'):
        companion = Path(str(raw) + suffix)
        try:
            info = companion.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise ContinuityError('Continuity database companions must not be links or special files')
    return raw


class ContinuityLedger:
    def __init__(self, path, series_id):
        self.series_id = _text(series_id, 'series_id', 200)
        self.path = _safe_database_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _safe_database_path(self.path)
        with self._connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS continuity_episodes (
                series_id TEXT NOT NULL, episode_id TEXT NOT NULL,
                position INTEGER NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(series_id,episode_id), UNIQUE(series_id,position))''')

    @contextmanager
    def _connection(self):
        _safe_database_path(self.path)
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def record_episode(self, payload):
        """Append reviewed evidence atomically; return {created, episode_id, digest}."""
        entry = validate_episode(payload)
        digest = _id(entry)
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT digest FROM continuity_episodes WHERE series_id=? AND episode_id=?',
                                    (self.series_id, entry['episode_id'])).fetchone()
            if existing:
                if existing['digest'] != digest:
                    raise ContinuityError('Episode already recorded with different evidence or assertions; immutable entries cannot be replaced')
                return {'created': False, 'episode_id': entry['episode_id'], 'digest': digest}
            collision = conn.execute('SELECT episode_id FROM continuity_episodes WHERE series_id=? AND position=?',
                                     (self.series_id, entry['position'])).fetchone()
            if collision:
                raise ContinuityError('Episode position already assigned in this series')
            conn.execute('INSERT INTO continuity_episodes VALUES (?,?,?,?,?)',
                         (self.series_id, entry['episode_id'], entry['position'], digest, _encode(entry)))
        return {'created': True, 'episode_id': entry['episode_id'], 'digest': digest}

    def context(self, through_position):
        """Retrieve only evidence at/before the explicit inclusive spoiler boundary.

        For prior continuity of episode N, request N-1. No future episode labels,
        counts, conflicts, or alias candidates are exposed in the returned data.
        """
        if type(through_position) is not int or through_position < 0:
            raise ContinuityError('through_position must be an explicit nonnegative integer')
        with self._connection() as conn:
            rows = conn.execute('SELECT payload,digest,episode_id,position FROM continuity_episodes WHERE series_id=? AND position<=? ORDER BY position,episode_id',
                                (self.series_id, through_position)).fetchall()
        entries = []
        for row in rows:
            try:
                entry = validate_episode(json.loads(row['payload']))
            except (ValueError, TypeError) as exc:
                raise ContinuityError('Stored continuity payload is invalid') from exc
            if (entry['episode_id'] != row['episode_id'] or entry['position'] != row['position']
                    or entry['position'] > through_position or _id(entry) != row['digest']):
                raise ContinuityError('Stored continuity payload failed integrity verification')
            entries.append(entry)
        facts, aliases = [], []
        groups, names = {}, {}
        for entry in entries:
            evidence = {row['id']: row for row in entry['evidence']}
            for kind, destination in (('facts', facts), ('aliases', aliases)):
                for assertion in entry[kind]:
                    item = {**assertion, 'episode_id': entry['episode_id'], 'position': entry['position'],
                            'source_sha256': entry['source_sha256'], 'semantic_verification': 'operator_reviewed_only'}
                    item['id'] = _id({'series_id': self.series_id, 'episode_id': entry['episode_id'], 'kind': kind, 'assertion': assertion})
                    item['evidence'] = [dict(evidence[ref['id']]) for ref in assertion['evidence_refs']]
                    destination.append(item)
                    if kind == 'facts':
                        groups.setdefault((item['subject'], item['predicate']), []).append(item)
                    else:
                        names.setdefault(item['alias'], []).append(item)
        contradictions = []
        for (subject, predicate), items in sorted(groups.items()):
            values = sorted({item['value'] for item in items})
            if len(values) > 1:
                contradictions.append({'subject': subject, 'predicate': predicate, 'values': values,
                    'assertion_ids': sorted(item['id'] for item in items),
                    'status': 'review_required', 'reason': 'Different cited values; may be temporal change, not a proven contradiction'})
        conflicts = []
        for alias, items in sorted(names.items()):
            candidates = sorted({item['canonical'] for item in items})
            if len(candidates) > 1:
                conflicts.append({'alias': alias, 'candidates': candidates,
                                  'assertion_ids': sorted(item['id'] for item in items), 'status': 'unresolved'})
        return {'schema_version': 1, 'series_id': self.series_id, 'through_position': through_position,
                'episodes': [{'episode_id': entry['episode_id'], 'position': entry['position'],
                              'source_sha256': entry['source_sha256'], 'evidence': entry['evidence']} for entry in entries],
                'facts': facts, 'aliases': aliases, 'contradictions': contradictions, 'alias_conflicts': conflicts,
                'limitations': ['Assertions are operator reviewed, not independently verified against media.',
                               'Conflicts are exact subject/predicate comparisons; semantic contradictions are not inferred.',
                               'Aliases are cited assertions only; identities are never automatically merged.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--series', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('record').add_argument('episode_json')
    commands.add_parser('context').add_argument('--through-position', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        ledger = ContinuityLedger(args.db, args.series)
        if args.command == 'record':
            result = ledger.record_episode(json.loads(Path(args.episode_json).read_text(encoding='utf-8')))
        else:
            result = ledger.context(args.through_position)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print('Blocked: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
