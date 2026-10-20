"""Visible legacy fallback, identity-safe merging and resource cleanup."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main
from instagram_media import map_instagram_recovery


def media(name, kind='image', host='old.cdninstagram.com'):
    return (f'https://{host}/{name}',kind,'')


def row(item):return (item[0],0,0,None,item[1])


class InstagramRecoveryRegression(unittest.TestCase):
    def test_legacy_browser_is_visible_and_preserves_proxy(self):
        engine=Mock()
        with tempfile.TemporaryDirectory() as folder:
            cookie=Path(folder)/'cookies.json';cookie.write_text('[]',encoding='utf-8')
            extractor=main.InstagramExtractor(str(cookie),'http://127.0.0.1:9876')
            with patch.object(main,'_browsers_ready',True),patch.object(main,'sync_playwright') as start,patch.object(main,'Stealth'):
                start.return_value.start.return_value=engine
                extractor._init_browser(headless=False)
                self.assertFalse(engine.chromium.launch.call_args.kwargs['headless'])
                self.assertEqual(engine.chromium.launch.call_args.kwargs['proxy'],{'server':'http://127.0.0.1:9876'})
                extractor.close()
                engine.chromium.launch.return_value.close.assert_called_once();engine.stop.assert_called_once()

    def test_legacy_extractor_clicks_carousel_instead_of_complete_json(self):
        page=Mock();page.url='https://www.instagram.com/p/target/'
        page.locator.return_value.count.return_value=1
        page.locator.return_value.first.is_visible.side_effect=[True,False]
        first,last=media('first.jpg'),media('last.jpg')
        extractor=main.InstagramExtractor('unused');extractor._init_browser=Mock(return_value=page)
        with patch.object(main,'_wait_instagram_ready',return_value=([first],False)) as ready, \
             patch.object(main,'extract_current_visible_media',side_effect=[[first],[last]]), \
             patch.object(main,'_wait_carousel_ready'):
            self.assertEqual(extractor.extract(page.url,legacy=True),[first,last])
            extractor._init_browser.assert_called_once_with(headless=False)
            self.assertFalse(ready.call_args.kwargs['allow_complete'])
            page.locator.return_value.first.click.assert_called_once()

    def test_legacy_readiness_never_returns_bad_complete_json(self):
        clock=Mock(value=0.0);page=Mock();page.url='https://www.instagram.com/p/target/'
        page.locator.return_value.count.return_value=0
        page.wait_for_timeout.side_effect=lambda ms:setattr(clock,'value',clock.value+ms/1000)
        good=[media('loaded.jpg')]
        with patch.object(main.time,'monotonic',side_effect=lambda:clock.value), \
             patch.object(main,'read_complete_instagram_post',return_value=[media('bad.jpg')]) as complete, \
             patch.object(main,'extract_current_visible_media',return_value=good):
            result,is_complete=main._wait_instagram_ready(page,'target',allow_complete=False)
            self.assertEqual(result,good);self.assertFalse(is_complete);complete.assert_not_called()

    def test_partial_legacy_post_cannot_drop_video_or_shift_later_images(self):
        original=[row(media('first.jpg')),row(media('movie.mp4','video')),row(media('last.heic'))]
        legacy=[media('first.jpg',host='new.cdninstagram.com'),media('last.jpg',host='new.cdninstagram.com')]
        mapped=map_instagram_recovery(original,legacy)
        self.assertEqual(set(mapped),{0,2});self.assertEqual(mapped[2],legacy[1])

    def test_full_traversal_can_refresh_names_but_conflicting_order_cannot(self):
        original=[row(media('first.jpg')),row(media('last.jpg'))]
        changed=[media('new-first.jpg'),media('new-last.jpg')]
        self.assertEqual(map_instagram_recovery(original,changed),dict(enumerate(changed)))
        reordered=[media('last.jpg'),media('new-first.jpg')]
        self.assertEqual(map_instagram_recovery(original,reordered),{1:reordered[0]})
        duplicate=[media('first.jpg'),media('first.jpg')]
        self.assertEqual(map_instagram_recovery(original,duplicate),{})

    def test_recovery_worker_closes_browser_after_failure_and_ignores_cancellation(self):
        context=SimpleNamespace(_closing=False,_thumbnail_generation=1,
            ig_extractor=SimpleNamespace(cookies_path='unused'),_schedule_media_callback=Mock(),
            _instagram_recovery_status=Mock(),_finish_instagram_recovery=Mock())
        with patch.object(main,'InstagramExtractor') as factory,self.assertLogs(main.logger,level='ERROR'):
            factory.return_value.extract.side_effect=RuntimeError('closed browser')
            main.InstagramDownloaderApp._recover_instagram_worker(context,'https://www.instagram.com/p/target/',1,[],None)
            factory.return_value.close.assert_called_once()
            self.assertTrue(factory.return_value.extract.call_args.kwargs['legacy'])
            context._schedule_media_callback.assert_called_once_with(context._finish_instagram_recovery,1,{},'closed browser')
        context._schedule_media_callback.reset_mock();context._closing=True
        with patch.object(main,'InstagramExtractor') as factory:
            main.InstagramDownloaderApp._recover_instagram_worker(context,'unused',1,[],None)
            factory.assert_not_called();context._schedule_media_callback.assert_not_called()

    def test_legacy_readiness_and_carousel_stop_when_cancelled(self):
        page=Mock();page.url='https://www.instagram.com/p/target/'
        with self.assertRaisesRegex(RuntimeError,'取消'):
            main._wait_instagram_ready(page,'target',allow_complete=False,cancelled=lambda:True)
        with self.assertRaisesRegex(RuntimeError,'取消'):
            main._wait_carousel_ready(page,set(),cancelled=lambda:True)
        page.evaluate.assert_not_called()

    def test_worker_refreshes_only_identified_missing_items_and_keeps_video(self):
        context=SimpleNamespace(_closing=False,_thumbnail_generation=1,
            ig_extractor=SimpleNamespace(cookies_path='unused'),_schedule_media_callback=Mock(),
            _instagram_recovery_status=Mock(),_finish_instagram_recovery=Mock())
        original=[row(media('first.jpg')),row(media('movie.mp4','video')),row(media('last.heic'))]
        original[0]=(original[0][0],20,20,Mock(), 'image')
        legacy=[media('first.jpg',host='new.cdninstagram.com'),media('last.jpg',host='new.cdninstagram.com')]
        recovered=(legacy[1][0],30,30,Mock(),'image')
        with patch.object(main,'InstagramExtractor') as factory,patch.object(main,'_read_instagram_preview',return_value=recovered) as read:
            factory.return_value.extract.return_value=legacy
            main.InstagramDownloaderApp._recover_instagram_worker(context,'https://www.instagram.com/p/target/',1,original,None)
            read.assert_called_once();self.assertEqual(read.call_args.args[0],legacy[1])
            factory.return_value.close.assert_called_once()
            context._schedule_media_callback.assert_called_once_with(context._finish_instagram_recovery,1,{2:recovered},None)
