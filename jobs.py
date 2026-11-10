#!/usr/bin/env python3
"""Durable local draft queue. No downloading or publication.

Example: python jobs.py enqueue spec.json; python jobs.py work --once
Spec paths are resolved relative to the JSON file. Rights must be explicitly true.
A crashed worker's expired lease becomes failed, never silently rerun. Inspect its
logs/process before `retry ID`; retries always use a fresh output directory.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

WORKFLOWS = ('movie', 'tv', 'anime', 'manhwa', 'educational')
FIELDS = {'source', 'workflow', 'subtitles', 'plan', 'model', 'vision_model',
          'audio_dir', 'context', 'asr_model', 'asr_engine', 'provider', 'key_env', 'remote_authorized', 'max_provider_calls', 'ocr', 'target_seconds', 'rights_confirmed'}


def validate_spec(spec, base=None):
    if not isinstance(spec, dict):
        raise ValueError('Spec must be a JSON object')
    if set(spec) - FIELDS:
        raise ValueError('Unknown spec fields: ' + ', '.join(sorted(set(spec) - FIELDS)))
    if spec.get('rights_confirmed') is not True:
        raise ValueError('rights_confirmed must be explicitly true for authorized inputs')
    result = dict(spec)
    result.setdefault('workflow', 'movie')
    result.setdefault('target_seconds', 360)
    if result['workflow'] not in WORKFLOWS:
        raise ValueError('Unsupported workflow')
    seconds = result['target_seconds']
    if type(seconds) is not int or not 30 <= seconds <= 3600:
        raise ValueError('target_seconds must be an integer from 30 to 3600')
    base = Path(base or Path.cwd()).resolve()
    for key in ('source', 'subtitles', 'plan', 'audio_dir', 'context', 'asr_model'):
        if key not in result:
            if key == 'source':
                raise ValueError('source is required')
            continue
        value = result[key]
        if not isinstance(value, str) or not value.strip() or '\x00' in value or '://' in value:
            raise ValueError(key + ' must be a local path')
        path = (base / value).resolve()
        if (key == 'audio_dir' and not path.is_dir()) or (key != 'audio_dir' and not path.is_file()):
            raise ValueError(key + ' does not exist or has the wrong file type: ' + str(path))
        result[key] = str(path)
    for key in ('model', 'vision_model'):
        if key in result and (not isinstance(result[key], str) or not result[key].strip()
                              or len(result[key]) > 200 or '\x00' in result[key]):
            raise ValueError(key + ' must be a nonempty model name')
    if result.get('asr_engine','whisper-cpp') not in ('whisper-cpp','openai-whisper'): raise ValueError('Invalid asr_engine')
    if result.get('provider','ollama') not in ('ollama','gemini'):raise ValueError('Invalid provider')
    if 'remote_authorized' in result and type(result['remote_authorized']) is not bool:raise ValueError('remote_authorized must be boolean')
    if result.get('provider')=='gemini' and (result.get('remote_authorized') is not True or type(result.get('max_provider_calls')) is not int or not 1<=result['max_provider_calls']<=1000):raise ValueError('Explicit Gemini authorization and bounded request count required')
    if 'key_env' in result:
        import re
        if not isinstance(result['key_env'],str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,99}',result['key_env']):raise ValueError('key_env must be an environment variable name')
    if 'ocr' in result and type(result['ocr']) is not bool: raise ValueError('ocr must be boolean')
    return result


class Queue:
    def __init__(self, db='.recap-jobs/jobs.sqlite', output_root=None):
        self.db = Path(db).resolve()
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.output_root = Path(output_root or self.db.parent / 'runs').resolve()
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, spec_hash TEXT UNIQUE NOT NULL,
                    spec TEXT NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0, token TEXT,
                    lease_until REAL, output TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at REAL NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.db), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def event(conn, job_id, event, details=None):
        conn.execute('INSERT INTO audit(job_id,at,event,details) VALUES (?,?,?,?)',
                     (job_id, time.time(), event, json.dumps(details or {}, sort_keys=True)))

    def enqueue(self, spec, base=None):
        spec = validate_spec(spec, base)
        # Hash the canonical spec, not mutable source bytes. Changed media at the
        # same path requires a different spec/path or an explicit retry.
        encoded = json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT id FROM jobs WHERE spec_hash=?', (digest,)).fetchone()
            if existing:
                return existing['id'], False
            job_id = uuid.uuid4().hex
            now = time.time()
            conn.execute('INSERT INTO jobs(id,spec_hash,spec,status,created,updated) VALUES (?,?,?,?,?,?)',
                         (job_id, digest, encoded, 'queued', now, now))
            self.event(conn, job_id, 'enqueued')
            return job_id, True

    def claim(self, lease_seconds=60):
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError('Lease must be positive and finite')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = time.time()
            expired = conn.execute("SELECT id FROM jobs WHERE status='running' AND lease_until < ?", (now,)).fetchall()
            for row in expired:
                conn.execute("UPDATE jobs SET status='failed',token=NULL,lease_until=NULL,updated=?,error=? WHERE id=?",
                             (now, 'Worker lease expired; inspect previous process before retry', row['id']))
                self.event(conn, row['id'], 'lease_expired')
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1").fetchone()
            if not row:
                return None
            attempt = row['attempt'] + 1
            token = uuid.uuid4().hex
            output = str(self.output_root / row['id'] / ('attempt-%04d' % attempt) / 'output')
            conn.execute("UPDATE jobs SET status='running',attempt=?,token=?,lease_until=?,output=?,updated=?,error=NULL WHERE id=?",
                         (attempt, token, now + lease_seconds, output, now, row['id']))
            self.event(conn, row['id'], 'claimed', {'attempt': attempt, 'output': output})
            return dict(conn.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())

    def heartbeat(self, job, lease_seconds=60):
        with self.connect() as conn:
            now = time.time()
            return conn.execute("UPDATE jobs SET lease_until=?,updated=? WHERE id=? AND status='running' AND token=? AND lease_until>=?",
                                (now + lease_seconds, now, job['id'], job['token'], now)).rowcount == 1

    def finish(self, job, returncode, error=None):
        with self.connect() as conn:
            status = 'succeeded' if returncode == 0 else 'failed'
            changed = conn.execute("UPDATE jobs SET status=?,updated=?,error=?,lease_until=NULL,token=NULL WHERE id=? AND status='running' AND token=?",
                                   (status, time.time(), error, job['id'], job['token'])).rowcount
            if changed:
                self.event(conn, job['id'], status, {'attempt': job['attempt'], 'returncode': returncode, 'error': error})
            return bool(changed)

    def retry(self, job_id):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('Unknown job ID')
            if row['status'] != 'failed':
                raise ValueError('Only failed jobs can be retried; run work to expire a stale lease first')
            conn.execute("UPDATE jobs SET status='queued',updated=?,error=NULL WHERE id=?", (time.time(), job_id))
            self.event(conn, job_id, 'retry_requested')

    def status(self, job_id=None):
        with self.connect() as conn:
            if job_id is None:
                return [dict(row) for row in conn.execute('SELECT * FROM jobs ORDER BY created,id')]
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('Unknown job ID')
            result = dict(row)
            result['audit'] = [dict(item) for item in conn.execute('SELECT * FROM audit WHERE job_id=? ORDER BY id', (job_id,))]
            return result


def pipeline_command(job):
    spec = validate_spec(json.loads(job['spec']))
    command = [sys.executable, str(Path(__file__).resolve().with_name('pipeline.py')),
               '--source', spec['source'], '--output', job['output'],
               '--workflow', spec['workflow'], '--target-seconds', str(spec['target_seconds']),
               '--rights-confirmed']
    for key in ('subtitles', 'plan', 'model', 'vision_model', 'audio_dir', 'context', 'asr_model', 'asr_engine', 'provider', 'key_env', 'max_provider_calls'):
        if key in spec:
            # Equals syntax keeps even values beginning with '-' a single value.
            command.append('--' + key.replace('_', '-') + '=' + str(spec[key]))
    if spec.get('remote_authorized'):command.append('--remote-authorized')
    if spec.get('ocr'): command.append('--ocr')
    return command


def run_once(queue, lease_seconds=60):
    job = queue.claim(lease_seconds)
    if job is None:
        return None
    process = None
    try:
        command = pipeline_command(job)
        attempt = Path(job['output']).parent
        attempt.mkdir(parents=True, exist_ok=False)
        (attempt / 'spec.json').write_text(job['spec'], encoding='utf-8')
        with (attempt / 'stdout.log').open('wb') as stdout, (attempt / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       shell=False, cwd=str(Path(__file__).resolve().parent))
            while True:
                try:
                    code = process.wait(timeout=min(10, lease_seconds / 3))
                    break
                except subprocess.TimeoutExpired:
                    if not queue.heartbeat(job, lease_seconds):
                        raise RuntimeError('Lost worker lease; stopping subprocess')
        queue.finish(job, code, None if code == 0 else 'Pipeline exited %s; inspect stderr.log' % code)
    except (Exception, KeyboardInterrupt) as exc:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        queue.finish(job, -1, str(exc) or type(exc).__name__)
        if isinstance(exc, KeyboardInterrupt):
            raise
    return queue.status(job['id'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='.recap-jobs/jobs.sqlite')
    parser.add_argument('--output-root', help='Default: runs beside queue database')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('enqueue').add_argument('spec')
    worker = commands.add_parser('work')
    worker.add_argument('--once', action='store_true')
    worker.add_argument('--poll-seconds', type=float, default=5)
    commands.add_parser('status').add_argument('id', nargs='?')
    commands.add_parser('retry').add_argument('id')
    args = parser.parse_args(argv)
    try:
        queue = Queue(args.db, args.output_root)
        if args.command == 'enqueue':
            path = Path(args.spec).resolve()
            job_id, created = queue.enqueue(json.loads(path.read_text(encoding='utf-8')), path.parent)
            print(json.dumps({'id': job_id, 'created': created}))
        elif args.command == 'status':
            print(json.dumps(queue.status(args.id), indent=2))
        elif args.command == 'retry':
            queue.retry(args.id)
            print(json.dumps({'id': args.id, 'status': 'queued'}))
        else:
            if not math.isfinite(args.poll_seconds) or args.poll_seconds <= 0:
                raise ValueError('poll-seconds must be positive and finite')
            while True:
                result = run_once(queue)
                if result:
                    print(json.dumps({'id': result['id'], 'status': result['status'], 'output': result['output']}), flush=True)
                if args.once:
                    return 1 if result and result['status'] == 'failed' else 0
                if not result:
                    time.sleep(args.poll_seconds)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print('Blocked: ' + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
