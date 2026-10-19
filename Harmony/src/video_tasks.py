"""Bounded video jobs; workers publish events and never access Tk widgets."""
from collections import OrderedDict
from dataclasses import dataclass, field, replace
import os
import re
import threading
import subprocess
import time
from urllib.parse import parse_qs, urldefrag, urlsplit
import uuid


class TaskCancelled(Exception):
    pass


def run_media_process(command, cancel_event=None, timeout=300):
    """Keep clip processing interruptible without blocking the UI thread."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', errors='replace', creationflags=flags) as process:
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event and cancel_event.is_set():
                process.kill(); process.communicate()
                raise TaskCancelled()
            if time.monotonic() > deadline:
                process.kill(); process.communicate()
                raise TimeoutError('处理片段超时')
            try:
                stdout, stderr = process.communicate(timeout=.2)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue


def parse_video_links(text):
    urls = []
    for index, url in enumerate(re.split(r'\s+', text.strip()), 1):
        if not url: continue
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            raise ValueError(f'第 {index} 个链接无效，请每行粘贴一个完整视频链接')
        url = urldefrag(url)[0]
        if url not in urls: urls.append(url)
    if not urls: raise ValueError('请先粘贴视频链接')
    return urls


def video_identity(url):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower().removeprefix('www.')
    if host == 'youtu.be': return ('youtube', parts.path.strip('/'))
    if host in ('youtube.com', 'm.youtube.com', 'music.youtube.com'):
        video_id = (parse_qs(parts.query).get('v') or [''])[0]
        if not video_id and parts.path.startswith(('/shorts/', '/live/', '/embed/')):
            video_id = parts.path.split('/')[2]
        if video_id: return ('youtube', video_id)
    return (host, parts.path.rstrip('/'), parts.query)


def validate_clip(start, end):
    def seconds(value):
        parts = value.strip().split(':')
        if not 1 <= len(parts) <= 3 or any(not re.fullmatch(r'\d+(?:\.\d+)?', p) for p in parts):
            raise ValueError('片段时间请填写为 分:秒 或 时:分:秒')
        if any('.' in p for p in parts[:-1]) or any(float(p) >= 60 for p in parts[1:]):
            raise ValueError('片段时间中的分、秒应小于 60')
        return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))
    if seconds(end) <= seconds(start): raise ValueError('片段结束时间应大于起始时间')


@dataclass(frozen=True)
class VideoOptions:
    save_dir: str
    fmt_key: str = 'best'
    codec: str = '不限制'
    container: str = 'mkv'
    clip: bool = False
    start: str = ''
    end: str = ''
    subtitles: bool = False
    cookie_data: bytes | None = field(default=None, repr=False, compare=False)


@dataclass
class VideoTask:
    id: str
    url: str
    options: VideoOptions
    state: str = 'waiting'
    progress: float = 0.0
    title: str = ''
    message: str = '等待下载'
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)


class VideoTaskQueue:
    FINISHED = {'done', 'failed', 'cancelled'}

    def __init__(self, runner, concurrency=3):
        self.runner = runner
        self.concurrency = concurrency
        self.tasks = OrderedDict()
        self._lock = threading.RLock()
        self._changed = set()
        self.closed = False

    def add(self, urls, options):
        added, duplicates = [], 0
        with self._lock:
            if self.closed: raise RuntimeError('下载队列已关闭')
            active = {(video_identity(t.url), os.path.normcase(os.path.abspath(t.options.save_dir)))
                      for t in self.tasks.values() if t.state not in self.FINISHED}
            for url in urls:
                key = (video_identity(url), os.path.normcase(os.path.abspath(options.save_dir)))
                if key in active:
                    duplicates += 1; continue
                task = VideoTask(uuid.uuid4().hex, url, options)
                self.tasks[task.id] = task
                self._changed.add(task.id)
                active.add(key); added.append(task.id)
            self._start_available()
        return added, duplicates

    def set_concurrency(self, count):
        if not 1 <= int(count) <= 5: raise ValueError('同时下载数量应为 1–5')
        with self._lock:
            self.concurrency = int(count)
            self._start_available()

    def snapshots(self):
        with self._lock: return [replace(t) for t in self.tasks.values()]

    def drain_changes(self):
        with self._lock:
            changed = bool(self._changed)
            self._changed.clear()
            return self.snapshots() if changed else None

    def clear_finished(self):
        with self._lock:
            for task_id in list(self.tasks):
                if self.tasks[task_id].state in self.FINISHED:
                    del self.tasks[task_id]
                    self._changed.add(task_id)

    def cancel_task(self, task_id):
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.state in self.FINISHED: return
            task.cancel.set()
            if task.state == 'waiting': task.state = 'cancelled'
            task.message = '已取消' if task.state == 'cancelled' else '正在取消…'
            self._changed.add(task_id)

    def retry(self, task_id):
        with self._lock:
            task = self.tasks.get(task_id)
            if self.closed or not task or task.state not in ('failed', 'cancelled'): return False
            key = (video_identity(task.url), os.path.normcase(os.path.abspath(task.options.save_dir)))
            if any(other.id != task.id and other.state not in self.FINISHED and
                   (video_identity(other.url), os.path.normcase(os.path.abspath(other.options.save_dir))) == key
                   for other in self.tasks.values()): return False
            task.state, task.progress, task.message = 'waiting', 0.0, '等待重试'
            task.cancel = threading.Event()
            self._changed.add(task.id); self._start_available()
            return True

    def close(self):
        with self._lock:
            self.closed = True
            for task in self.tasks.values():
                if task.state not in self.FINISHED:
                    task.cancel.set()
                    if task.state == 'waiting': task.state = 'cancelled'

    def _start_available(self):
        if self.closed: return
        running = sum(t.state == 'running' for t in self.tasks.values())
        for task in self.tasks.values():
            if running >= self.concurrency: break
            if task.state != 'waiting': continue
            task.state, task.message = 'running', '正在解析…'
            self._changed.add(task.id); running += 1
            threading.Thread(target=self._run, args=(task,), daemon=True,
                             name=f'harmony-video-{task.id[:8]}').start()

    def _run(self, task):
        def progress(value):
            if task.cancel.is_set(): raise TaskCancelled()
            with self._lock:
                if isinstance(value, (int, float)):
                    task.progress = max(task.progress, min(.99, float(value)))
                else: task.message = str(value)
                self._changed.add(task.id)

        def info(value):
            with self._lock:
                task.title = str(value).splitlines()[0].removeprefix('标题: ')
                self._changed.add(task.id)

        try:
            if task.cancel.is_set(): raise TaskCancelled()
            success = self.runner(task, progress, info)
            if task.cancel.is_set(): raise TaskCancelled()
            if not success: raise RuntimeError(task.message or '下载未完成')
            with self._lock:
                task.state, task.progress, task.message = 'done', 1.0, '下载完成'
        except Exception as error:
            with self._lock:
                task.state = 'cancelled' if task.cancel.is_set() else 'failed'
                task.message = '已取消' if task.cancel.is_set() else str(error) or '下载失败'
        finally:
            with self._lock:
                self._changed.add(task.id)
                self._start_available()
