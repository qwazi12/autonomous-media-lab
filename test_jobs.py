import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import jobs


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'source.mp4').write_bytes(b'test media placeholder')
        self.queue = jobs.Queue(self.root / 'queue.sqlite')
        self.spec = {'source': 'source.mp4', 'rights_confirmed': True}

    def enqueue(self):
        return self.queue.enqueue(self.spec, self.root)[0]

    def test_dedup_defaults_and_relative_paths(self):
        first = self.enqueue()
        spec = dict(self.spec, source=str(self.root / 'source.mp4'), workflow='movie', target_seconds=360)
        second, created = self.queue.enqueue(spec)
        self.assertEqual(first, second)
        self.assertFalse(created)
        self.assertEqual(len(self.queue.status()), 1)

    def test_rights_explicit_boolean(self):
        for value in (None, False, 1, 'true'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.queue.enqueue(dict(self.spec, rights_confirmed=value), self.root)

    def test_validation(self):
        for changes in ({'source': 'https://example.org/movie'}, {'source': 'missing'},
                        {'workflow': 'arbitrary'}, {'target_seconds': True}, {'target_seconds': 0},
                        {'command': 'echo unsafe'}, {'output': 'replace-existing'}, {'model': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.queue.enqueue(dict(self.spec, **changes), self.root)

    def test_atomic_claim(self):
        self.enqueue()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.queue.claim(), range(4)))
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        claim = next(x for x in claims if x)
        self.assertEqual(claim['attempt'], 1)
        self.assertEqual(claim['status'], 'running')
        self.assertGreater(claim['lease_until'], time.time())

    def test_retry_new_output_and_audit(self):
        job_id = self.enqueue()
        first = self.queue.claim()
        self.queue.finish(first, 1, 'test failure')
        self.queue.retry(job_id)
        second = self.queue.claim()
        self.assertNotEqual(first['output'], second['output'])
        self.assertEqual(second['attempt'], 2)
        self.assertFalse(self.queue.finish(first, 0))
        self.assertTrue(self.queue.finish(second, 0))
        status = self.queue.status(job_id)
        self.assertEqual(status['status'], 'succeeded')
        self.assertEqual([x['event'] for x in status['audit']],
                         ['enqueued', 'claimed', 'failed', 'retry_requested', 'claimed', 'succeeded'])

    def test_retry_rejects_nonfailed(self):
        job_id = self.enqueue()
        with self.assertRaises(ValueError):
            self.queue.retry(job_id)
        with self.assertRaises(ValueError):
            self.queue.retry('unknown')

    def test_expired_lease_requires_manual_retry(self):
        job_id = self.enqueue()
        claim = self.queue.claim()
        with self.queue.connect() as conn:
            conn.execute('UPDATE jobs SET lease_until=0')
        self.assertFalse(self.queue.heartbeat(claim))
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.status(job_id)['status'], 'failed')
        self.assertFalse(self.queue.finish(claim, 0))

    def test_heartbeat(self):
        self.enqueue()
        claim = self.queue.claim(1)
        self.assertTrue(self.queue.heartbeat(claim, 60))
        self.assertGreater(self.queue.status(claim['id'])['lease_until'], claim['lease_until'])

    def test_dispatch_no_shell(self):
        self.spec['model'] = '-model; echo not-executed'
        job_id = self.enqueue()
        with patch('jobs.subprocess.Popen') as popen:
            popen.return_value.wait.return_value = 0
            result = jobs.run_once(self.queue)
        self.assertEqual(result['status'], 'succeeded')
        command = popen.call_args.args[0]
        self.assertIn('--model=-model; echo not-executed', command)
        self.assertIn('--rights-confirmed', command)
        self.assertFalse(popen.call_args.kwargs['shell'])
        self.assertTrue((Path(result['output']).parent / 'stdout.log').exists())
        self.assertFalse(Path(result['output']).exists())  # Pipeline owns creation.
        self.assertEqual(result['id'], job_id)

    def test_worker_failure_is_durable(self):
        self.enqueue()
        with patch('jobs.subprocess.Popen', side_effect=OSError('cannot launch')):
            result = jobs.run_once(self.queue)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('cannot launch', result['error'])
        self.assertIsNone(jobs.run_once(self.queue))

    def test_deleted_source_revalidated(self):
        self.enqueue()
        (self.root / 'source.mp4').unlink()
        with patch('jobs.subprocess.Popen') as popen:
            result = jobs.run_once(self.queue)
        popen.assert_not_called()
        self.assertEqual(result['status'], 'failed')

    def test_database_reopen(self):
        job_id = self.enqueue()
        reopened = jobs.Queue(self.root / 'queue.sqlite')
        self.assertEqual(reopened.status(job_id)['status'], 'queued')


if __name__ == '__main__':
    unittest.main()
