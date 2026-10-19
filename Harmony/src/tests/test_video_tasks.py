"""Real worker overlap, bounded concurrency, isolation and queue recovery."""
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_tasks import VideoOptions, VideoTaskQueue, parse_video_links, validate_clip, run_media_process, TaskCancelled


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline: raise AssertionError('Timed out waiting for worker state')
        time.sleep(.005)


class VideoQueueRegression(unittest.TestCase):
    def test_clip_process_can_be_cancelled_without_waiting_for_exit(self):
        cancel=threading.Event();timer=threading.Timer(.1,cancel.set);timer.start()
        try:
            started=time.monotonic()
            with self.assertRaises(TaskCancelled):
                run_media_process([sys.executable,'-c','import time;time.sleep(10)'],cancel)
            self.assertLess(time.monotonic()-started,3)
        finally:timer.cancel()
    def test_batch_validation_is_atomic_and_preserves_link_order(self):
        a, b = 'https://youtu.be/one', 'https://www.youtube.com/watch?v=two'
        self.assertEqual(parse_video_links(a+'\n'+b+'\n'+a), [a, b])
        with self.assertRaises(ValueError): parse_video_links(a+'\ninvalid')
        with self.assertRaises(ValueError): parse_video_links('file:///private/video.mp4')
        with self.assertRaises(ValueError): validate_clip('2:00', '1:00')
        with self.assertRaises(ValueError): validate_clip('0:99', '1:00')
        validate_clip('0:05', '1:05')

    def test_workers_overlap_and_respect_concurrency_limit(self):
        gate = threading.Event(); lock = threading.Lock(); running = 0; peak = 0
        def runner(task, progress, info):
            nonlocal running, peak
            with lock: running += 1; peak = max(peak, running)
            try:
                progress(.2); info(task.url); gate.wait(3)
                return True
            finally:
                with lock: running -= 1
        queue = VideoTaskQueue(runner, 2)
        try:
            queue.add([f'https://example.com/{i}' for i in range(4)], VideoOptions('output'))
            wait_until(lambda: running == 2)
            self.assertEqual([t.state for t in queue.snapshots()].count('waiting'), 2)
            self.assertEqual(peak, 2)
            queue.set_concurrency(3); wait_until(lambda: running == 3)
            self.assertEqual(peak, 3)
            gate.set(); wait_until(lambda: all(t.state == 'done' for t in queue.snapshots()))
            self.assertLessEqual(peak, 3)
        finally: gate.set(); queue.close()

    def test_active_youtube_aliases_are_not_written_to_same_file(self):
        gate = threading.Event()
        queue = VideoTaskQueue(lambda *args: gate.wait(3), 1)
        try:
            ids, duplicates = queue.add(['https://youtu.be/abc', 'https://www.youtube.com/watch?v=abc&t=5'], VideoOptions('output'))
            self.assertEqual((len(ids), duplicates), (1, 1))
        finally: gate.set(); queue.close()

    def test_failure_does_not_block_next_task_and_retry_reuses_row(self):
        attempts = {}
        def runner(task, progress, info):
            attempts[task.id] = attempts.get(task.id, 0) + 1
            if task.url.endswith('bad') and attempts[task.id] == 1: raise ValueError('test failure')
            progress(.4); return True
        queue = VideoTaskQueue(runner, 1)
        try:
            ids, _ = queue.add(['https://example.com/bad', 'https://example.com/good'], VideoOptions('output'))
            wait_until(lambda: all(t.state in queue.FINISHED for t in queue.snapshots()))
            self.assertEqual([t.state for t in queue.snapshots()], ['failed', 'done'])
            self.assertTrue(queue.retry(ids[0]))
            wait_until(lambda: all(t.state == 'done' for t in queue.snapshots()))
            self.assertEqual(len(queue.snapshots()), 2)
        finally: queue.close()

    def test_pending_cancel_and_close_do_not_start_more_work(self):
        gate = threading.Event(); started = []
        def runner(task, progress, info): started.append(task.id); gate.wait(3); return True
        queue = VideoTaskQueue(runner, 1)
        ids, _ = queue.add(['https://example.com/1', 'https://example.com/2'], VideoOptions('output'))
        wait_until(lambda: len(started) == 1)
        queue.cancel_task(ids[1]); queue.close(); gate.set()
        wait_until(lambda: queue.snapshots()[0].state == 'cancelled')
        self.assertEqual(started, [ids[0]])
        self.assertEqual(queue.snapshots()[1].state, 'cancelled')

    def test_each_job_retains_its_own_settings_and_progress(self):
        gate = threading.Event()
        def runner(task, progress, info):
            progress(.25 if task.options.fmt_key == '720p' else .75); gate.wait(3); return True
        queue = VideoTaskQueue(runner, 2)
        try:
            queue.add(['https://example.com/1'], VideoOptions('first', '720p'))
            queue.add(['https://example.com/2'], VideoOptions('second', '1080p'))
            wait_until(lambda: all(t.progress > 0 for t in queue.snapshots()))
            tasks = queue.snapshots()
            self.assertEqual([t.progress for t in tasks], [.25, .75])
            self.assertEqual([t.options.save_dir for t in tasks], ['first', 'second'])
        finally: gate.set(); queue.close()
