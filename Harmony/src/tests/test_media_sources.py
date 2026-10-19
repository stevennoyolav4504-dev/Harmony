"""Post routing, mixed X media and photo-only/quoted-post boundaries."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_sources import parse_post_link, x_media_from_status, XMediaExtractor


class PostMediaRegression(unittest.TestCase):
    def test_routing_and_cache_names_do_not_collide(self):
        ig = parse_post_link('https://www.instagram.com/reel/12345/?igsh=x')
        x = parse_post_link('https://mobile.twitter.com/user/status/12345/video/1?s=20')
        self.assertEqual((ig.platform, ig.cache_key), ('Instagram', '12345'))
        self.assertEqual((x.platform, x.cache_key), ('X', 'x_12345'))
        self.assertEqual(parse_post_link('https://x.com/i/web/status/12345').cache_key, x.cache_key)

    def test_unrelated_and_lookalike_domains_are_rejected(self):
        for url in ('https://x.com.evil.example/u/status/123', 'https://example.com/?x=instagram.com',
                    'file:///x.com/u/status/123', 'https://x.com/user', 'https://x.com@evil.example/u/status/123'):
            with self.subTest(url=url), self.assertRaises(ValueError): parse_post_link(url)

    def test_original_photos_best_mp4_gif_and_order(self):
        photo = {'type': 'photo', 'media_url_https': 'https://pbs.twimg.com/media/picture.png'}
        video = {'type': 'video', 'media_url_https': 'https://pbs.twimg.com/media/thumb.jpg',
                 'video_info': {'variants': [
                     {'content_type': 'application/x-mpegURL', 'url': 'https://video.twimg.com/v.m3u8', 'bitrate': 9999},
                     {'content_type': 'video/mp4', 'url': 'https://video.twimg.com/small.mp4', 'bitrate': 100},
                     {'content_type': 'video/mp4', 'url': 'https://video.twimg.com/large.mp4', 'bitrate': 1000}]}}
        gif = {'type': 'animated_gif', 'video_info': {'variants': [{'url': 'https://video.twimg.com/gif.mp4'}]}}
        result = x_media_from_status({'extended_entities': {'media': [photo, video, photo, gif]}})
        self.assertEqual([item[1] for item in result], ['image', 'video', 'video'])
        self.assertIn('format=png', result[0][0]); self.assertIn('name=orig', result[0][0])
        self.assertEqual(result[1][0], 'https://video.twimg.com/large.mp4')
        self.assertEqual(result[1][2], video['media_url_https'])

    def test_syndication_keeps_only_media_from_requested_post(self):
        own = {'type': 'photo', 'media_url_https': 'https://pbs.twimg.com/media/own.jpg'}
        quoted = {'type': 'photo', 'media_url_https': 'https://pbs.twimg.com/media/quote.jpg'}
        result = x_media_from_status({'mediaDetails': [own], 'extended_entities': {'media': [own, quoted]}})
        self.assertEqual(len(result), 1); self.assertIn('/own?', result[0][0])
        self.assertEqual(x_media_from_status({'quoted_tweet': {}, 'extended_entities': {'media': [quoted]}}), [])

    def test_extractor_falls_back_without_using_instagram(self):
        from yt_dlp.extractor.twitter import TwitterIE
        payload = {'mediaDetails': [{'type': 'photo', 'media_url_https': 'https://pbs.twimg.com/media/pic.jpg'}]}
        with patch.object(TwitterIE, '_extract_status', side_effect=[RuntimeError('guest limited'), payload]) as fetch:
            result = XMediaExtractor().extract('https://x.com/example/status/12345')
        self.assertEqual(fetch.call_count, 2); self.assertEqual(result[0][1], 'image')
