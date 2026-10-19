"""TikTok post routing, native web-data parsing and scoped download context."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_sources import (TikTokMediaExtractor, parse_post_link, tiktok_photos_from_status,
                           tiktok_video_from_formats, _configure_tiktok_certificates)


class TikTokRegression(unittest.TestCase):
    def test_full_short_shared_links_and_platform_cache_names(self):
        urls = ('https://www.tiktok.com/@creator/video/12345?lang=en',
                'https://m.tiktok.com/@creator/photo/12345',
                'https://tiktok.com/share/video/12345', 'https://www.tiktok.com/embed/v2/12345')
        for url in urls:
            with self.subTest(url=url):
                link = parse_post_link(url)
                self.assertEqual((link.platform, link.cache_key, link.is_short), ('TikTok', 'tiktok_12345', False))
                self.assertEqual(parse_post_link(link.url).cache_key, link.cache_key)
        for url in ('https://vm.tiktok.com/ZABC123/', 'https://vt.tiktok.com/ZABC123/', 'https://www.tiktok.com/t/ZABC123/'):
            self.assertTrue(parse_post_link(url).is_short)
        self.assertEqual(parse_post_link('看看这个视频 https://vt.tiktok.com/ZABC123/ 复制链接打开 TikTok').post_id, 'short_ZABC123')
        self.assertNotEqual(parse_post_link(urls[0]).cache_key, parse_post_link('https://x.com/user/status/12345').cache_key)

    def test_profiles_live_external_redirects_and_lookalikes_are_rejected(self):
        for url in ('https://www.tiktok.com/@creator', 'https://www.tiktok.com/@creator/live',
                    'https://tiktok.com.evil.example/@creator/video/12345', 'https://vm.tiktok.com.evil.example/ZABC/',
                    'https://www.tiktok.com@evil.example/@creator/video/12345', 'https://v.douyin.com/ZABC/',
                    'https://vt.tiktok.com/', 'file:///tiktok.com/@creator/video/12345'):
            with self.subTest(url=url), self.assertRaises(ValueError): parse_post_link(url)

    def test_photo_order_original_urls_and_music_exclusion(self):
        first = 'https://cdn.example/first.image?signature=keep'
        second = 'https://cdn.example/second.webp'
        payload = {'imagePost': {'images': [
            {'imageURL': {'urlList': ['javascript:bad', first]}, 'displayImage': {'urlList': ['https://cdn.example/small.jpg']}},
            {'displayImage': {'urlList': [second]}}, {'imageURL': {'urlList': [first]}}]},
            'music': {'playUrl': 'https://cdn.example/music.m4a'}, 'video': {'cover': 'https://cdn.example/cover.jpg'}}
        result = tiktok_photos_from_status(payload)
        self.assertEqual(result, [(first, 'image', first), (second, 'image', second)])
        self.assertEqual(tiktok_photos_from_status({'image_post_info': {'images': [{'display_image': {'url_list': [first]}}]}}), [(first, 'image', first)])

    def test_video_chooses_best_playable_combined_stream(self):
        formats = [
            {'url': 'https://cdn.example/music.mp4', 'ext': 'mp4', 'vcodec': 'none'},
            {'url': 'https://cdn.example/small.mp4', 'height': 540, 'vcodec': 'h264', 'preference': -1},
            {'url': 'https://cdn.example/big.mp4', 'height': 1080, 'vcodec': 'h264', 'preference': -1},
            {'url': 'https://cdn.example/mute.mp4', 'height': 2160, 'vcodec': 'h265', 'acodec': 'none'},
            {'url': 'https://cdn.example/unsupported.mp4', 'height': 2160, 'vcodec': 'bytevc2'},
            {'url': 'https://cdn.example/watermark.mp4', 'height': 2160, 'preference': -2},
            {'url': 'https://cdn.example/master.m3u8', 'height': 2160}]
        self.assertEqual(tiktok_video_from_formats(formats)[0], ('https://cdn.example/big.mp4', 'video', ''))
        with self.assertRaises(ValueError): tiktok_video_from_formats(formats[:1])

    def test_short_link_resolves_to_stable_post_and_keeps_scoped_headers(self):
        from yt_dlp.extractor.tiktok import TikTokIE, TikTokVMIE
        status = {'id': '12345', 'video': {'playAddr': 'https://cdn.example/video.mp4',
                                         'cover': 'https://cdn.example/cover.jpg', 'width': 720, 'height': 1280}}
        extractor = TikTokMediaExtractor()
        with patch.object(TikTokVMIE, '_real_extract', return_value={'url': 'https://www.tiktok.com/@creator/video/12345?x=1'}), \
             patch.object(TikTokIE, '_extract_web_data_and_status', return_value=(status, 0)) as web, \
             patch.object(TikTokIE, 'extract_subtitles', return_value={}):
            result = extractor.extract('https://vt.tiktok.com/ZABC123/')
        self.assertEqual(result, [('https://cdn.example/video.mp4', 'video', 'https://cdn.example/cover.jpg')])
        self.assertEqual(extractor.resolved_link.cache_key, 'tiktok_12345')
        web.assert_called_once_with('https://www.tiktok.com/@creator/video/12345', '12345')
        headers = extractor.request_headers(result[0][0])
        self.assertEqual(headers['Referer'], extractor.resolved_link.url)
        self.assertTrue(headers['User-Agent']); self.assertNotIn('Cookie', headers)
        headers['Cookie'] = 'modified by caller'
        self.assertNotIn('Cookie', extractor.request_headers(result[0][0]))
        self.assertEqual(extractor.request_headers('https://unrelated.example/'), {})

    def test_image_post_does_not_download_audio_and_bad_cookies_are_ignored(self):
        from yt_dlp.extractor.tiktok import TikTokIE
        status = {'imagePost': {'images': [{'imageURL': {'urlList': ['https://cdn.example/photo.jpg']}}]},
                  'music': {'playUrl': 'https://cdn.example/music.mp3'}}
        with tempfile.TemporaryDirectory() as folder:
            cookie = Path(folder) / 'cookies.json'; cookie.write_text('invalid', encoding='utf-8')
            extractor = TikTokMediaExtractor(cookie)
            with patch.object(TikTokIE, '_extract_web_data_and_status', return_value=(status, 0)) as web, \
                 patch.object(TikTokIE, '_parse_aweme_video_web') as video:
                result = extractor.extract('https://www.tiktok.com/@creator/photo/12345', proxy='http://127.0.0.1:9876')
            self.assertEqual(len(result), 1); self.assertEqual(result[0][1], 'image'); video.assert_not_called()
            web.assert_called_once_with('https://www.tiktok.com/@creator/video/12345', '12345')
            self.assertEqual(extractor.proxy, 'http://127.0.0.1:9876')

    def test_unavailable_or_invalid_short_destination_clears_old_context(self):
        from yt_dlp.extractor.tiktok import TikTokIE, TikTokVMIE
        extractor = TikTokMediaExtractor(); extractor._request_headers['old'] = {'Cookie': 'old'}
        with patch.object(TikTokIE, '_extract_web_data_and_status', return_value=({}, 10204)):
            with self.assertRaisesRegex(ValueError, 'TikTok.*网络'):
                extractor.extract('https://www.tiktok.com/@creator/video/12345')
        self.assertIsNone(extractor.resolved_link); self.assertEqual(extractor.request_headers('old'), {})
        with patch.object(TikTokVMIE, '_real_extract', return_value={'url': 'https://example.com/video.mp4'}), \
             patch.object(TikTokIE, '_extract_web_data_and_status') as web:
            with self.assertRaises(ValueError): extractor.extract('https://vt.tiktok.com/ZABC123/')
            web.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows libcurl certificate paths')
    def test_unicode_ca_fix_is_private_and_keeps_verification_enabled(self):
        import certifi
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / '中文' / 'ca.pem'; source.parent.mkdir(); source.write_bytes(b'public CA bundle')
            session = SimpleNamespace(verify=True)
            factory = Mock(return_value=session)
            handler = SimpleNamespace(_create_instance=factory)
            ydl = SimpleNamespace(_request_director=SimpleNamespace(handlers={'CurlCFFI': handler}))
            original = certifi.where
            with patch.object(certifi, 'where', return_value=str(source)):
                _configure_tiktok_certificates(ydl, folder)
                actual = handler._create_instance(cookiejar='this downloader only')
            self.assertEqual(Path(actual.verify).read_bytes(), b'public CA bundle')
            self.assertTrue(str(actual.verify).isascii()); factory.assert_called_once_with(cookiejar='this downloader only')
            self.assertIs(certifi.where, original)
