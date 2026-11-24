"""Regression coverage for note links, exact-post media and request context."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_sources import parse_post_link
from xiaohongshu_media import is_original_image_url, note_media_from_page, XiaohongshuMediaExtractor


NOTE_ID = '6a9d0eb2000000002a024480'
OTHER_ID = '6a9d0eb2000000002a024481'
NOTE_URL = f'https://www.xiaohongshu.com/discovery/item/{NOTE_ID}?xsec_token=sample%3D&xsec_source=app_share&share_id=tracking'
SHORT_URL = 'https://xhslink.cn/o/AbcDef123'
IMAGE_A = 'https://sns-webpic-qc.xhscdn.com/img/a!nd_dft_wgth_webp_3'
IMAGE_B = 'https://sns-webpic-qc.xhscdn.com/img/b'
VIDEO = 'https://sns-video-hw.xhscdn.com/stream/test.mp4?sign=sample'
OBJECT_KEY = 'note_pre_post_uhdr/1040exampleaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
ORIGINAL = f'https://ci.xiaohongshu.com/{OBJECT_KEY}'


def page_for(note, note_id=NOTE_ID):
    other = {'imageList': [{'urlDefault': IMAGE_B}]}
    state = {'note': {'noteDetailMap': {OTHER_ID: {'note': other}, note_id: {'note': note}}}}
    return '<script>window.__INITIAL_STATE__=' + json.dumps(state) + ';</script>'


def response(status, html='', location=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.headers = {'Location': location} if location else {}
    result.iter_content.return_value = iter([html.encode('utf-8')])
    return result


class XiaohongshuRegression(unittest.TestCase):
    def test_share_text_and_supported_note_paths_keep_access_parameters(self):
        for text in (f'看看这篇笔记 {SHORT_URL} 复制后打开小红书', f'{SHORT_URL} 复制链接',
                     'http://xhslink.com/AbcDef123'):
            with self.subTest(text=text):
                link = parse_post_link(text)
                self.assertTrue(link.is_short)
                self.assertEqual(link.cache_key, 'xhs_short_AbcDef123')
        for path in ('/explore/', '/discovery/item/', f'/user/profile/{OTHER_ID}/'):
            link = parse_post_link(NOTE_URL.replace('/discovery/item/', path))
            self.assertEqual(link.cache_key, 'xhs_' + NOTE_ID)
            self.assertEqual(parse_qs(urlsplit(link.url).query), {'xsec_token': ['sample='], 'xsec_source': ['app_share']})
        for url in ('https://xhslink.cn.evil.test/o/AbcDef123',
                    f'https://www.xiaohongshu.com:8080/explore/{NOTE_ID}',
                    f'https://www.xiaohongshu.com/user/profile/{NOTE_ID}',
                    f'请查看 {SHORT_URL} 和 {NOTE_URL}'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_post_link(url)

    def test_ordered_gallery_prefers_display_images_and_preserves_strings(self):
        html = page_for({'type': 'normal', 'desc': 'undefined', 'imageList': [
            {'urlDefault': IMAGE_A, 'urlPre': IMAGE_B},
            {'infoList': [{'imageScene': 'WB_PRV', 'url': IMAGE_A}, {'imageScene': 'WB_DFT', 'url': IMAGE_B}]},
        ], 'extra': '__js_undefined__'}).replace('"__js_undefined__"', 'undefined')
        self.assertEqual(note_media_from_page(html, NOTE_ID), [(IMAGE_A, 'image', IMAGE_A), (IMAGE_B, 'image', IMAGE_B)])

    def test_original_uses_file_id_or_signed_display_path_and_keeps_preview(self):
        signed = (f'https://sns-webpic-qc.xhscdn.com/202611230830/{"a" * 32}/{OBJECT_KEY}'
                  '!nd_dft_wgth_webp_3?imageView2/2/w/1080/format/jpg')
        html = page_for({'imageList': [
            {'fileId': OBJECT_KEY, 'urlDefault': IMAGE_A},
            {'urlDefault': signed},
            {'fileId': '../bad', 'urlDefault': IMAGE_B},
            {'fileId': OBJECT_KEY},
        ]})
        self.assertEqual(note_media_from_page(html, NOTE_ID), [
            (ORIGINAL, 'image', IMAGE_A), (ORIGINAL, 'image', signed),
            (IMAGE_B, 'image', IMAGE_B), (ORIGINAL, 'image', ''),
        ])

    def test_regional_image_key_preserves_region_and_namespace(self):
        key = 'oss-sg/' + OBJECT_KEY
        original = 'https://ci.xiaohongshu.com/' + key
        display = f'https://sns-webpic-qc.xhscdn.com/202611231805/{"e" * 32}/{key}!nd_dft_wgth_webp_3'
        for image in ({'fileId': key, 'urlDefault': display}, {'urlDefault': display}):
            with self.subTest(has_file_id='fileId' in image):
                self.assertEqual(note_media_from_page(page_for({'imageList': [image]}), NOTE_ID),
                                 [(original, 'image', display)])
                self.assertTrue(is_original_image_url(original))
        for bad_key in ('oss-sg/../' + OBJECT_KEY.split('/')[-1],
                        'oss-sg/%2e%2e/' + OBJECT_KEY.split('/')[-1], key + '?resize=1080'):
            self.assertFalse(is_original_image_url('https://ci.xiaohongshu.com/' + bad_key))

    def test_video_selects_playable_mp4_and_keeps_cover_as_preview(self):
        html = page_for({'type': 'video', 'imageList': [{'urlDefault': IMAGE_A}], 'video': {'media': {'stream': {
            'h264': [{'masterUrl': VIDEO, 'width': 1080, 'height': 1920},
                     {'masterUrl': VIDEO.replace('.mp4', '.m3u8'), 'width': 2160, 'height': 3840},
                     {'masterUrl': 'https://evil.test/stream.mp4', 'width': 2160, 'height': 3840}],
            'h265': [{'masterUrl': VIDEO.replace('test.mp4', 'hevc.mp4'), 'width': 2160, 'height': 3840}],
        }}}})
        self.assertEqual(note_media_from_page(html, NOTE_ID), [(VIDEO, 'video', IMAGE_A)])
        with self.assertRaisesRegex(ValueError, 'MP4'):
            note_media_from_page(page_for({'type': 'video', 'imageList': [{'urlDefault': IMAGE_A}]}), NOTE_ID)

    def test_wrong_note_or_incomplete_gallery_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '无法读取'):
            note_media_from_page(page_for({'imageList': [{'urlDefault': IMAGE_A}]}, OTHER_ID), NOTE_ID)
        with self.assertRaisesRegex(ValueError, '不完整'):
            note_media_from_page(page_for({'imageList': [{'urlDefault': IMAGE_A}, {'urlDefault': 'https://evil.test/a.jpg'}]}), NOTE_ID)

    def test_short_link_sets_download_context_without_forwarding_share_token(self):
        extractor = XiaohongshuMediaExtractor()
        proxy = 'http://127.0.0.1:9876'
        with patch('xiaohongshu_media.requests.Session') as session:
            client = session.return_value.__enter__.return_value
            note_html = page_for({'imageList': [
                {'fileId': OBJECT_KEY, 'urlDefault': IMAGE_A, 'width': 4284, 'height': 5712},
                {'urlDefault': IMAGE_B, 'width': 4284, 'height': 5712},
            ]})
            client.get.side_effect = [response(302, location=NOTE_URL), response(200, note_html)]
            self.assertEqual(extractor.extract(SHORT_URL, proxy=proxy), [(ORIGINAL, 'image', IMAGE_A), (IMAGE_B, 'image', IMAGE_B)])
            self.assertEqual(extractor.original_size(ORIGINAL), (4284, 5712))
            self.assertEqual(extractor.original_size(IMAGE_B), (0, 0))
            self.assertEqual(client.get.call_args.args[0], NOTE_URL)
            self.assertFalse(client.get.call_args.kwargs['allow_redirects'])
            client.proxies.update.assert_called_once_with({'http': proxy, 'https': proxy})
            self.assertEqual(extractor.proxy, proxy)
            self.assertEqual(extractor.resolved_link.post_id, NOTE_ID)
            self.assertEqual(extractor.request_headers(IMAGE_A)['Referer'], 'https://www.xiaohongshu.com/')
            self.assertEqual(extractor.request_headers(ORIGINAL), extractor.request_headers(IMAGE_A))
            self.assertFalse(extractor.request_headers('https://evil.test/a.jpg'))

    def test_refuses_offsite_redirect_and_clears_old_request_context(self):
        extractor = XiaohongshuMediaExtractor()
        for target in ('https://example.test/explore/' + NOTE_ID, 'https://www.xiaohongshu.com/404'):
            with self.subTest(target=target), patch('xiaohongshu_media.requests.Session') as session:
                extractor._request_headers[IMAGE_A] = {'Referer': 'old'}
                extractor._original_sizes[ORIGINAL] = (4284, 5712)
                client = session.return_value.__enter__.return_value
                client.get.return_value = response(302, location=target)
                with self.assertRaisesRegex(ValueError, '小红书'):
                    extractor.extract(SHORT_URL)
                client.get.assert_called_once()
                self.assertIsNone(extractor.resolved_link)
                self.assertEqual(extractor.request_headers(IMAGE_A), {})
                self.assertEqual(extractor.original_size(ORIGINAL), (0, 0))
