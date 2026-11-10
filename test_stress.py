"""Deterministic local concurrency/integrity stress. No media/provider calls."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from checkpoints import Checkpoints, CheckpointError
from jobs import Queue


class QueueStressTests(unittest.TestCase):
    JOBS = 100
    WORKERS = 12

    def setUp(self):
        self.started = time.perf_counter()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input.mp4'
        self.source.write_bytes(b'local placeholder; never dispatched')
        self.queue = Queue(self.root / 'jobs.sqlite')

    def tearDown(self):
        print(f'\nSTRESS {self._testMethodName}: {time.perf_counter() - self.started:.3f}s')

    def enqueue(self, index):
        return self.queue.enqueue({'source': str(self.source), 'rights_confirmed': True,
                                   'target_seconds': 30 + index})

    def test_100_jobs_concurrent_enqueue_dedup_and_exactly_once_claims(self):
        # Interleave four replays of every canonical spec, in fixed input order.
        submitted = [(index * 37 + replay * 13) % self.JOBS
                     for replay in range(4) for index in range(self.JOBS)]
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            enqueued = list(pool.map(self.enqueue, submitted))
        self.assertEqual(sum(created for _, created in enqueued), self.JOBS)
        self.assertEqual(len(set(job_id for job_id, _ in enqueued)), self.JOBS)
        self.assertEqual(len(self.queue.status()), self.JOBS)
        mapping = {}
        for spec_index, (job_id, _) in zip(submitted, enqueued):
            self.assertEqual(mapping.setdefault(spec_index, job_id), job_id)

        barrier = threading.Barrier(self.WORKERS)
        def consume(_):
            barrier.wait(timeout=30)
            claimed = []
            while True:
                job = self.queue.claim(lease_seconds=3600)
                if job is None:
                    return claimed
                forged = dict(job, token='not-the-owner')
                self.assertFalse(self.queue.heartbeat(forged))
                self.assertFalse(self.queue.finish(forged, 0))
                self.assertTrue(self.queue.heartbeat(job, lease_seconds=3600))
                self.assertTrue(self.queue.finish(job, 0))
                self.assertFalse(self.queue.finish(job, 0))
                claimed.append(job)
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            claims = [job for batch in pool.map(consume, range(self.WORKERS)) for job in batch]
        self.assertEqual(len(claims), self.JOBS)
        self.assertEqual(set(job['id'] for job in claims), set(mapping.values()))
        self.assertEqual(set(Counter(job['id'] for job in claims).values()), {1})
        self.assertEqual(len({job['token'] for job in claims}), self.JOBS)
        self.assertEqual(len({job['output'] for job in claims}), self.JOBS)
        for row in self.queue.status():
            self.assertEqual(row['status'], 'succeeded')
            self.assertEqual(row['attempt'], 1)
            self.assertIsNone(row['token'])
            self.assertIsNone(row['lease_until'])
            events = [event['event'] for event in self.queue.status(row['id'])['audit']]
            self.assertEqual(events, ['enqueued', 'claimed', 'succeeded'])
        self.assertIsNone(self.queue.claim())

    def test_100_expired_jobs_retry_token_fencing_and_fresh_outputs(self):
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            list(pool.map(self.enqueue, range(self.JOBS)))
            first = list(pool.map(lambda _: self.queue.claim(3600), range(self.JOBS)))
        self.assertEqual(len({job['id'] for job in first}), self.JOBS)
        # Force expiry via database timestamps rather than nondeterministic sleeps.
        with self.queue.connect() as connection:
            connection.execute("UPDATE jobs SET lease_until=0 WHERE status='running'")
        self.assertIsNone(self.queue.claim())  # Expired work is failed, never auto-retried.
        self.assertTrue(all(row['status'] == 'failed' for row in self.queue.status()))
        originals = {job['id']: job for job in first}
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            list(pool.map(self.queue.retry, sorted(originals)))
            second = list(pool.map(lambda _: self.queue.claim(3600), range(self.JOBS)))
        self.assertEqual(len({job['id'] for job in second}), self.JOBS)
        def finish_retry(current):
            old = originals[current['id']]
            self.assertEqual(current['attempt'], 2)
            self.assertNotEqual(current['output'], old['output'])
            self.assertNotEqual(current['token'], old['token'])
            self.assertFalse(self.queue.heartbeat(old))
            self.assertFalse(self.queue.finish(old, 0))
            self.assertTrue(self.queue.finish(current, 0))
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            list(pool.map(finish_retry, second))
        for row in self.queue.status():
            self.assertEqual(row['status'], 'succeeded')
            events = [event['event'] for event in self.queue.status(row['id'])['audit']]
            self.assertEqual(events, ['enqueued', 'claimed', 'lease_expired', 'retry_requested', 'claimed', 'succeeded'])


class CheckpointStressTests(unittest.TestCase):
    def test_100_artifacts_tamper_delete_and_review_invalidation(self):
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = Checkpoints(root, 'fixed-test-signature')
            for index in range(100):
                path = root / f'artifact-{index:03}.txt'
                path.write_text(f'evidence-{index}', encoding='utf-8')
                checkpoint.record(f'stage-{index:03}', [path])
            for index in range(100):
                path = root / f'artifact-{index:03}.txt'
                if index % 3 == 0:
                    path.write_text('tampered', encoding='utf-8')
                elif index % 3 == 1:
                    path.unlink()
            reopened = Checkpoints(root, 'fixed-test-signature', resume=True)
            for index in range(100):
                with self.subTest(index=index):
                    self.assertEqual(reopened.valid(f'stage-{index:03}'), index % 3 == 2)
            review = root / 'review.html'
            review.write_text('unreviewed draft', encoding='utf-8')
            reopened.record('review', [review])
            self.assertTrue(reopened.valid('review'))
            reopened.invalidate('review')
            self.assertFalse(reopened.valid('review'))
            self.assertEqual(review.read_text(), 'unreviewed draft')
            # Forged traversal cannot turn an external file into a valid artifact.
            state = json.loads(reopened.path.read_text())
            state['stages']['forged'] = {'../outside': '0' * 64}
            reopened.path.write_text(json.dumps(state), encoding='utf-8')
            self.assertFalse(reopened.valid('forged'))
            reopened.path.write_text('{truncated', encoding='utf-8')
            with self.assertRaises(CheckpointError):
                reopened.valid('stage-002')
        print(f'\nSTRESS checkpoint_100_artifacts: {time.perf_counter() - started:.3f}s')


if __name__ == '__main__':
    unittest.main()
