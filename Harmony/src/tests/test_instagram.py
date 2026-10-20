"""Exact-post fast path, complete sidecars and adaptive readiness boundaries."""
import copy
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from instagram_media import complete_instagram_media, read_complete_instagram_post


def photo(name):
    return {'__typename': 'GraphImage', 'display_url': f'https://scontent.cdninstagram.com/{name}.jpg'}


def sidecar():
    return {'shortcode': 'target', '__typename': 'GraphSidecar',
            'display_url': 'https://scontent.cdninstagram.com/parent-cover.jpg',
            'edge_sidecar_to_children': {'count': 3, 'edges': [
                {'node': photo('first')},
                {'node': {'__typename': 'GraphVideo', 'video_url': 'https://scontent.cdninstagram.com/video.mp4',
                          'display_url': 'https://scontent.cdninstagram.com/video-cover.jpg'}},
                {'node': photo('last')}]}}


class InstagramFastPathRegression(unittest.TestCase):
    def test_worker_records_extraction_failure_and_reports_it_to_ui(self):
        for url in ('https://www.instagram.com/p/target/','https://x.com/creator/status/12345',
                    'https://www.tiktok.com/@creator/video/1234567890123456789'):
            platform=main.parse_post_link(url).platform
            extractor=Mock();extractor.extract.side_effect=RuntimeError('backend failure')
            context=SimpleNamespace(ig_extractor=extractor,x_extractor=extractor,tiktok_extractor=extractor,
                                    after=Mock(),_fetch_complete=Mock())
            with self.subTest(platform=platform),self.assertLogs(main.logger,level='ERROR') as logged:
                main.InstagramDownloaderApp._fetch_worker(context,url,None)
                self.assertIn(platform+' 提取失败',logged.output[0])
                self.assertIn('RuntimeError: backend failure',logged.output[0])
                context.after.assert_called_once_with(0,context._fetch_complete,[],'backend failure')
                self.assertEqual(extractor.close.call_count,int(platform=='Instagram'))

    def test_extraction_is_headless_with_bundled_chromium_and_keeps_proxy(self):
        engine=Mock();browser=engine.chromium.launch.return_value
        context=browser.new_context.return_value
        with tempfile.TemporaryDirectory() as folder:
            cookies=Path(folder)/'cookies.json';cookies.write_text('[]',encoding='utf-8')
            extractor=main.InstagramExtractor(str(cookies),'http://127.0.0.1:9876')
            with patch.object(main,'_browsers_ready',True),patch.object(main,'sync_playwright') as start,patch.object(main,'Stealth'):
                start.return_value.start.return_value=engine
                page=extractor._init_browser()
                self.assertIs(page,context.new_page.return_value)
                options=engine.chromium.launch.call_args.kwargs
                self.assertTrue(options['headless']);self.assertEqual(options['channel'],'chromium')
                self.assertEqual(options['proxy'],{'server':'http://127.0.0.1:9876'})
                extractor.close();browser.close.assert_called_once();engine.stop.assert_called_once()

    def test_auth_paths_request_explicit_login_without_flagging_post_names(self):
        for path in ('/accounts/login/','/challenge/123/','/checkpoint/','/accounts/suspended/'):
            with self.subTest(path=path),self.assertRaisesRegex(RuntimeError,'设置'):
                main._check_instagram_access('https://www.instagram.com'+path)
        main._check_instagram_access('https://www.instagram.com/p/challenge_example/')

    def test_hidden_verification_fails_immediately_in_navigation_and_readiness(self):
        page=Mock();page.url='https://www.instagram.com/challenge/123/'
        extractor=main.InstagramExtractor('unused');extractor._init_browser=Mock(return_value=page)
        with patch.object(main.time,'sleep') as sleep,patch.object(main,'_wait_instagram_ready') as ready:
            with self.assertRaisesRegex(RuntimeError,'账号验证'):
                extractor.extract('https://www.instagram.com/p/target/')
            sleep.assert_not_called();ready.assert_not_called()
        with self.assertRaisesRegex(RuntimeError,'账号验证'):
            main._wait_instagram_ready(page,'target')

    def test_exact_post_ignores_recommendations_and_parent_cover(self):
        recommended = dict(photo('recommended'), shortcode='other')
        result = complete_instagram_media({'feed': [recommended, sidecar(), recommended]}, 'target')
        self.assertEqual([m[1] for m in result], ['image', 'video', 'image'])
        self.assertEqual([m[0].rsplit('/', 1)[1] for m in result], ['first.jpg', 'video.mp4', 'last.jpg'])
        self.assertIsNone(complete_instagram_media({'feed': [recommended]}, 'target'))

    def test_incomplete_sidecar_missing_video_or_ambiguous_count_falls_back(self):
        variants = []
        count = sidecar(); count['edge_sidecar_to_children']['count'] = 4; variants.append(count)
        more = sidecar(); more['edge_sidecar_to_children']['page_info'] = {'has_next_page': True}; variants.append(more)
        unknown = sidecar(); del unknown['edge_sidecar_to_children']['count']; variants.append(unknown)
        missing = sidecar(); del missing['edge_sidecar_to_children']['edges'][1]['node']['video_url']; variants.append(missing)
        for payload in variants:
            with self.subTest(payload=payload): self.assertIsNone(complete_instagram_media(payload, 'target'))

    def test_api_carousel_keeps_order_and_highest_resolution(self):
        node = {'code': 'target', 'media_type': 8, 'carousel_media_count': 2, 'carousel_media': [
            {'media_type': 1, 'image_versions2': {'candidates': [
                {'url': 'https://scontent.cdninstagram.com/small.jpg', 'width': 320, 'height': 320},
                {'url': 'https://scontent.cdninstagram.com/original.jpg', 'width': 1440, 'height': 1440}]}},
            {'media_type': 2, 'video_versions': [{'url': 'https://scontent.cdninstagram.com/original.mp4', 'type': 102}]}]}
        result = complete_instagram_media({'data': {'items': [node]}}, 'target')
        self.assertTrue(result[0][0].endswith('/original.jpg')); self.assertEqual(result[1][1], 'video')
        node['carousel_media_count'] = 3
        self.assertIsNone(complete_instagram_media(node, 'target'))

    def test_untrusted_cdn_and_untyped_cover_are_not_full_media(self):
        for node in (dict(photo('ok'), shortcode='target', display_url='https://cdninstagram.com.evil.example/image.jpg'),
                     {'code': 'target', 'thumbnail_src': 'https://scontent.cdninstagram.com/cover.jpg'}):
            self.assertIsNone(complete_instagram_media(node, 'target'))

    def test_bad_script_does_not_mask_later_matching_post(self):
        page = Mock(); page.evaluate.return_value = ['not json', json.dumps({'media': dict(photo('other'), shortcode='other')}), json.dumps(sidecar())]
        self.assertEqual(len(read_complete_instagram_post(page, 'target')), 3)

    def test_delayed_complete_data_beats_incomplete_dom_before_settling(self):
        clock = Mock(value=0.0)
        page = Mock(); page.url = 'https://www.instagram.com/p/target/'
        page.locator.return_value.count.return_value = 0
        page.wait_for_timeout.side_effect = lambda ms: setattr(clock, 'value', clock.value + ms / 1000)
        first = [('https://scontent.cdninstagram.com/first.jpg', 'image', '')]
        full = complete_instagram_media(sidecar(), 'target')
        with patch.object(main.time, 'monotonic', side_effect=lambda: clock.value), \
             patch.object(main, 'read_complete_instagram_post', side_effect=lambda *_: full if clock.value >= .3 else None), \
             patch.object(main, 'extract_current_visible_media', return_value=first):
            result, complete = main._wait_instagram_ready(page, 'target')
        self.assertTrue(complete); self.assertEqual(result, full); self.assertLess(clock.value, .6)

    def test_dom_wait_resets_when_late_carousel_control_appears(self):
        clock = Mock(value=0.0)
        page = Mock(); page.url = 'https://www.instagram.com/p/target/'
        page.locator.return_value.count.side_effect = lambda: int(clock.value >= .4)
        page.wait_for_timeout.side_effect = lambda ms: setattr(clock, 'value', clock.value + ms / 1000)
        media = [('https://scontent.cdninstagram.com/first.jpg', 'image', '')]
        with patch.object(main.time, 'monotonic', side_effect=lambda: clock.value), \
             patch.object(main, 'read_complete_instagram_post', return_value=None), \
             patch.object(main, 'extract_current_visible_media', side_effect=lambda *_, **kw: media if clock.value >= .2 else []):
            result, complete = main._wait_instagram_ready(page, 'target')
        self.assertFalse(complete); self.assertEqual(result, media)
        self.assertGreaterEqual(clock.value, .9); self.assertLess(clock.value, 1.5)

    def test_carousel_wait_recognizes_video_and_waits_for_stable_new_item(self):
        clock = Mock(value=0.0); page = Mock()
        page.wait_for_timeout.side_effect = lambda ms: setattr(clock, 'value', clock.value + ms / 1000)
        video = [('https://scontent.cdninstagram.com/next.mp4', 'video', '')]
        with patch.object(main.time, 'monotonic', side_effect=lambda: clock.value), \
             patch.object(main, 'extract_current_visible_media', side_effect=[[], video, video, video]):
            result = main._wait_carousel_ready(page, {'https://scontent.cdninstagram.com/first.jpg'})
        self.assertEqual(result, {video[0][0]}); self.assertLess(clock.value, 1)
