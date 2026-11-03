"""Large carousel transport, Chromium repair and stale-result boundaries."""
from collections import Counter
from io import BytesIO
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def photo(index):
    return (f'https://scontent.cdninstagram.com/{index}.jpg?signature=unchanged', 'image', '')


def png():
    buffer = BytesIO()
    Image.new('RGB', (32, 40), 'pink').save(buffer, format='PNG')
    return buffer.getvalue()


class InstagramPreviewRegression(unittest.TestCase):
    def test_twenty_images_reuse_two_connections_and_repair_only_missing(self):
        media = [photo(i) for i in range(20)]
        counts, sessions, active, peak = Counter(), [], [0], [0]
        lock = threading.Lock()
        class Session:
            closed = False
            def __init__(self): sessions.append(self)
            def get(self, url, **options):
                with lock:
                    counts[url] += 1; active[0] += 1; peak[0] = max(peak[0], active[0])
                try:
                    time.sleep(.005)
                    if url in {media[i][0] for i in (2, 11, 17)}:
                        raise main.requests.exceptions.SSLError('UNEXPECTED_EOF_WHILE_READING')
                    response = Mock(); response.content = png()
                    response.__enter__ = Mock(return_value=response); response.__exit__ = Mock()
                    return response
                finally:
                    with lock: active[0] -= 1
            def close(self): self.closed = True
        context = SimpleNamespace(_closing=False, _thumbnail_generation=1,
            ig_extractor=SimpleNamespace(cookies_path='unused'),
            _schedule_media_callback=Mock(), _apply_instagram_preview=Mock(),
            _instagram_background_preview_status=Mock(), _finish_instagram_previews=Mock())
        def repair(missing, cookies, proxy, cancelled, callback):
            self.assertEqual(set(missing), {2, 11, 17})
            self.assertEqual(proxy, 'http://127.0.0.1:9876')
            for index in missing:
                callback(index, (media[index][0], 32, 40, Image.new('RGB', (32, 40)), 'image'))
        with patch.object(main.requests, 'Session', Session), patch.object(main, '_read_instagram_browser_previews', side_effect=repair) as browser:
            main.InstagramDownloaderApp._load_instagram_previews(context, media, 1, 'http://127.0.0.1:9876')
        self.assertEqual(len(sessions), 2); self.assertLessEqual(peak[0], 2)
        self.assertTrue(all(session.closed for session in sessions))
        self.assertEqual([counts[item[0]] for item in media], [3 if i in (2, 11, 17) else 1 for i in range(20)])
        browser.assert_called_once()
        calls = context._schedule_media_callback.call_args_list
        repaired = [call.args[2] for call in calls if call.args[0] is context._apply_instagram_preview and call.args[2][3] is not None]
        self.assertEqual(len(repaired), 20)
        self.assertEqual(calls[-1].args, (context._finish_instagram_previews, 1))

    def test_browser_uses_original_urls_one_hidden_context_and_closes(self):
        extractor = main.InstagramExtractor('unused', 'http://127.0.0.1:9876')
        page = Mock()
        def goto(url, **options):
            self.assertEqual(options['referer'], 'https://www.instagram.com/')
            response = Mock(ok=True, url=url); response.body.return_value = png()
            return response
        page.goto.side_effect = goto
        extractor._init_browser = Mock(return_value=page)
        extractor.close = Mock()
        callback = Mock()
        with patch.object(main, 'InstagramExtractor', return_value=extractor) as factory:
            result = main._read_instagram_browser_previews({3: photo(3), 11: photo(11)},
                'unused', extractor.proxy, lambda: False, callback)
        factory.assert_called_once_with('unused', extractor.proxy)
        extractor._init_browser.assert_called_once_with()  # default headless
        self.assertEqual([call.args[0] for call in page.goto.call_args_list], [photo(i)[0] for i in (3, 11)])
        self.assertEqual(set(result), {3, 11}); self.assertEqual(callback.call_count, 2)
        page.close.assert_called_once(); extractor.close.assert_called_once()
        route = Mock(); route.request.url = 'https://not-instagram.example/image.jpg'
        page.route.call_args.args[1](route)
        route.abort.assert_called_once(); route.continue_.assert_not_called()

    def test_untrusted_media_never_starts_browser_and_redirects_are_rejected(self):
        for url in ('http://scontent.cdninstagram.com/image.jpg', 'https://127.0.0.1/image.jpg',
                    'https://cdninstagram.com.evil.example/image.jpg', 'https://scontent.cdninstagram.com:81/image.jpg',
                    'https://user:pass@scontent.cdninstagram.com/image.jpg'):
            with self.subTest(url=url), patch.object(main, 'InstagramExtractor') as factory:
                self.assertEqual(main._read_instagram_browser_previews({0: (url, 'image', '')}, 'unused', None, lambda: False), {})
                factory.assert_not_called()
        extractor = Mock(); page = extractor._context.new_page.return_value
        page.goto.return_value = Mock(ok=True, url='https://evil.example/image.jpg')
        self.assertEqual(main._read_instagram_browser_previews({0: photo(0)}, 'unused', None,
            lambda: False, extractor=extractor), {})
        page.goto.return_value.body.assert_not_called(); extractor.close.assert_not_called()
        page.close.assert_called_once()

    def test_failed_read_closes_page_and_cancelled_result_never_reaches_ui(self):
        extractor = Mock(); page = extractor._context.new_page.return_value
        page.goto.side_effect = RuntimeError('TLS handshake failed')
        self.assertEqual(main._read_instagram_browser_previews({0: photo(0)}, 'unused', None,
            lambda: False, extractor=extractor), {})
        page.close.assert_called_once()
        page.reset_mock(); page.goto.side_effect = None
        response = Mock(ok=True, url=photo(0)[0]); response.body.return_value = png()
        page.goto.return_value = response
        cancelled = Mock(side_effect=[False, False, True]); callback = Mock()
        self.assertEqual(main._read_instagram_browser_previews({0: photo(0)}, 'unused', None,
            cancelled, callback, extractor), {})
        callback.assert_not_called(); page.close.assert_called_once()


if __name__ == '__main__': unittest.main()
