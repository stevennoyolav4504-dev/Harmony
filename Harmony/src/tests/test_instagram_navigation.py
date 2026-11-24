"""Instagram connection drops, bounded retries and canonical share links."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


class InstagramNavigationRegression(unittest.TestCase):
    def setUp(self):
        self.extractor = main.InstagramExtractor('unused', 'http://127.0.0.1:9876')
        self.page = Mock(); self.page.url = 'https://www.instagram.com/p/target/'

    def test_connection_drop_retries_same_canonical_post_without_restarting_browser(self):
        self.page.goto.side_effect = [RuntimeError('Page.goto: net::ERR_CONNECTION_CLOSED'),
                                     RuntimeError('Page.goto: net::ERR_CONNECTION_RESET'), None]
        self.extractor._init_browser = Mock(return_value=self.page)
        media = [('https://scontent.cdninstagram.com/image.jpg', 'image', '')]
        progress = Mock()
        with patch.object(main, '_wait_instagram_ready', return_value=(media, True)) as ready:
            result = self.extractor.extract('https://www.instagram.com/reels/target/?utm_source=share&srtk=tracking', progress)
        self.assertEqual(result, media)
        self.extractor._init_browser.assert_called_once_with()
        self.assertEqual(len(self.page.goto.call_args_list), 3)
        for call in self.page.goto.call_args_list:
            self.assertEqual(call.args, ('https://www.instagram.com/p/target/',))
            self.assertEqual(call.kwargs, {'wait_until': 'domcontentloaded', 'timeout': 20000})
        self.assertEqual([c.args[0] for c in self.page.wait_for_timeout.call_args_list], [600, 1200])
        ready.assert_called_once()
        self.assertEqual(self.extractor.proxy, 'http://127.0.0.1:9876')
        self.assertEqual(sum('正在重连' in call.args[0] for call in progress.call_args_list), 2)

    def test_persistent_connection_failure_is_bounded_and_actionable(self):
        for error in (RuntimeError('net::ERR_CONNECTION_CLOSED'), main.BrowserTimeoutError('Timeout')):
            with self.subTest(error=error):
                self.page.reset_mock(); self.page.goto.side_effect = error
                with self.assertRaisesRegex(RuntimeError, '网络代理和系统代理') as caught:
                    self.extractor._navigate_post(self.page, self.page.url)
                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(self.page.goto.call_count, 3)
                self.assertEqual(self.page.wait_for_timeout.call_count, 2)

    def test_security_proxy_dns_and_unknown_failures_are_not_blindly_retried(self):
        for message, hint in [('net::ERR_CERT_AUTHORITY_INVALID', '安全连接'),
                              ('net::ERR_SSL_PROTOCOL_ERROR', '安全连接'),
                              ('net::ERR_PROXY_CONNECTION_FAILED', '代理连接失败'),
                              ('net::ERR_TUNNEL_CONNECTION_FAILED', '代理连接失败'),
                              ('net::ERR_NAME_NOT_RESOLVED', 'DNS'),
                              ('net::ERR_INTERNET_DISCONNECTED', '网络'),
                              ('Target page, context or browser has been closed', 'has been closed')]:
            with self.subTest(message=message):
                self.page.reset_mock(); self.page.goto.side_effect = RuntimeError(message)
                with self.assertRaisesRegex(RuntimeError, hint):
                    self.extractor._navigate_post(self.page, self.page.url)
                self.page.goto.assert_called_once(); self.page.wait_for_timeout.assert_not_called()

    def test_login_and_checkpoint_are_not_retried_even_after_timeout(self):
        for path in ('/accounts/login/', '/challenge/123/'):
            for error in (None, main.BrowserTimeoutError('Timeout')):
                with self.subTest(path=path, error=error):
                    self.page.reset_mock(); self.page.url = 'https://www.instagram.com'+path
                    self.page.goto.side_effect = error
                    with self.assertRaisesRegex(RuntimeError, '设置'):
                        self.extractor._navigate_post(self.page, 'https://www.instagram.com/p/target/')
                    self.page.goto.assert_called_once(); self.page.wait_for_timeout.assert_not_called()

    def test_cancelled_navigation_does_not_retry_or_parse_post(self):
        self.extractor._init_browser = Mock(return_value=self.page)
        self.page.goto.side_effect = RuntimeError('net::ERR_CONNECTION_CLOSED')
        with patch.object(main, '_wait_instagram_ready') as ready, self.assertRaisesRegex(RuntimeError, '取消'):
            self.extractor.extract(self.page.url, cancelled=Mock(side_effect=[False, True]))
        self.page.goto.assert_called_once(); self.page.wait_for_timeout.assert_not_called()
        ready.assert_not_called()

    def test_successful_reel_keeps_video_fallback_after_url_normalization(self):
        self.extractor._init_browser = Mock(return_value=self.page)
        self.page.locator.return_value.count.return_value = 0
        image = [('https://scontent.cdninstagram.com/cover.jpg', 'image', '')]
        video = [('https://scontent.cdninstagram.com/video.mp4', 'video', '')]
        for path in ('reel', 'reels'):
            with self.subTest(path=path), patch.object(main, '_wait_instagram_ready', return_value=(image, False)), \
                 patch.object(main, 'extract_post_media_from_json', return_value=video) as fallback:
                result = self.extractor.extract(f'https://www.instagram.com/{path}/target/?tracking=discard')
                self.assertIn(video[0], result); fallback.assert_called_once()

    def test_invalid_or_other_platform_link_never_opens_browser(self):
        self.extractor._init_browser = Mock()
        for url in ('https://instagram.com.evil.example/p/target/', 'https://x.com/creator/status/12345'):
            with self.subTest(url=url), self.assertRaises(ValueError): self.extractor.extract(url)
        self.extractor._init_browser.assert_not_called()


if __name__ == '__main__': unittest.main()
