"""Threads links, exact-post media, safe redirects and scoped request context."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from media_sources import parse_post_link
from threads_media import ThreadsMediaExtractor,ThreadsPage,threads_media_from_payload
import requests


URL='https://www.threads.com/@creator/post/ABC_123'
def image(name):
    return {'media_type':1,'image_versions2':{'candidates':[
        {'url':f'https://scontent.cdninstagram.com/{name}-small.jpg','width':320,'height':320},
        {'url':f'https://scontent.cdninstagram.com/{name}.jpg','width':1440,'height':1440}]}}


def video():
    return {'media_type':2,'image_versions2':image('cover')['image_versions2'],'video_versions':[
        {'url':'https://video.fbcdn.net/small.mp4','width':320,'height':180},
        {'url':'https://video.fbcdn.net/main.mp4','width':1920,'height':1080}]}


def page(post,canonical=URL):
    return '<meta content="'+canonical+'" property="og:url"><script data-sjs type="application/json">'+json.dumps({'data':{'post':post}})+'</script>'


def response(body='',status=200,location=None):
    r=requests.Response();r.status_code=status;r._content=body.encode();r._content_consumed=True
    if location:r.headers['Location']=location
    return r


class ThreadsRegression(unittest.TestCase):
    def test_links_domains_tracking_and_cache_are_normalized(self):
        for url in ('https://www.threads.net/@creator/post/ABC_123/?xmt=tracking',URL,
                    'https://threads.com/t/ABC_123#reply'):
            link=parse_post_link(url)
            self.assertEqual((link.platform,link.cache_key,link.is_short),('Threads','threads_ABC_123',False))
        for host in ('threads.net','www.threads.com'):
            link=parse_post_link(f'https://{host}/share/A_token/?x=1')
            self.assertTrue(link.is_short);self.assertEqual(link.cache_key,'threads_short_A_token')
        self.assertNotEqual(parse_post_link(URL).cache_key,parse_post_link('https://instagram.com/p/ABC_123/').cache_key)
        self.assertEqual(parse_post_link('看看这个帖子 '+URL+' 复制链接').cache_key,'threads_ABC_123')

    def test_bad_threads_links_cannot_become_other_platforms(self):
        for url in ('https://threads.com.evil.example/@creator/post/ABC_123','https://threads.com@evil.example/t/ABC',
                    'https://threads.com/@creator','https://threads.com:9020/t/ABC','file:///threads.com/t/ABC'):
            with self.subTest(url=url),self.assertRaises(ValueError):parse_post_link(url)

    def test_mixed_media_preserve_order_and_exclude_replies_quotes_and_cover(self):
        post={'code':'ABC_123','media_type':8,'carousel_media_count':3,'image_versions2':image('parent')['image_versions2'],
              'carousel_media':[image('first'),video(),image('last')],
              'text_post_app_info':{'quoted_post':dict(image('quote'),code='quote')}}
        payload={'replies':[dict(image('reply'),code='reply')],'post':post,'recommended':[dict(video(),code='other')]}
        media=threads_media_from_payload(payload,'ABC_123')
        self.assertEqual([m[1] for m in media],['image','video','image'])
        self.assertTrue(media[0][0].endswith('/first.jpg'));self.assertTrue(media[1][0].endswith('/main.mp4'))
        self.assertTrue(media[2][0].endswith('/last.jpg'));self.assertTrue(media[1][2].endswith('/cover.jpg'))
        self.assertIsNone(threads_media_from_payload(payload,'absent'))

    def test_single_photo_and_text_only_are_not_confused(self):
        self.assertTrue(threads_media_from_payload(dict(image('own'),code='target'),'target')[0][0].endswith('/own.jpg'))
        text={'code':'target','media_type':19,'image_versions2':{'candidates':[]},'video_versions':[],
              'text_post_app_info':{'quoted_post':dict(video(),code='quoted')}}
        self.assertEqual(threads_media_from_payload(text,'target'),[])

    def test_incomplete_duplicate_and_untrusted_media_are_rejected(self):
        variants=[{'code':'target','media_type':8,'carousel_media_count':3,'carousel_media':[image('one')]},
                  {'code':'target','media_type':8,'carousel_media':[image('one'),image('one')]},
                  {'code':'target','media_type':2,'video_versions':[{'url':'https://video.fbcdn.net/stream.mpd'}]}]
        malicious=image('bad');malicious['code']='target'
        for candidate in malicious['image_versions2']['candidates']:candidate['url']='https://fbcdn.net.evil.example/photo.jpg'
        variants.append(malicious)
        for payload in variants:
            with self.subTest(payload=payload),self.assertRaises(ValueError):threads_media_from_payload(payload,'target')

    def test_script_attribute_order_bad_script_and_share_canonical(self):
        html='<script type="application/json">bad json</script>'+page(dict(image('own'),code='ABC_123'))
        parser=ThreadsPage();parser.feed(html)
        self.assertEqual(parser.canonical,URL);self.assertEqual(len(parser.scripts),2)
        extractor=ThreadsMediaExtractor()
        with patch.object(requests.Session,'get',return_value=response(html)):
            media=extractor.extract('https://www.threads.net/share/A_token/')
        self.assertEqual(extractor.resolved_link.cache_key,'threads_ABC_123')
        self.assertEqual(extractor.request_headers(media[0][0])['Referer'],URL)
        self.assertEqual(extractor.request_headers('https://unrelated.example/'),{})
        with patch.object(requests.Session,'get',return_value=response(page(dict(image('own'),code='ABC_123'),'/@creator/post/ABC_123'))):
            extractor.extract('https://www.threads.net/share/A_token/')
            self.assertEqual(extractor.resolved_link.url,URL)

    def test_share_without_exact_post_never_selects_a_recommendation(self):
        html=page(dict(video(),code='other'),canonical='https://www.threads.com/share/unknown/')
        with patch.object(requests.Session,'get',return_value=response(html)):
            with self.assertRaises(ValueError):ThreadsMediaExtractor().extract('https://www.threads.com/share/unknown/')

    def test_redirects_are_followed_only_within_threads(self):
        extractor=ThreadsMediaExtractor()
        with patch.object(requests.Session,'get',side_effect=[response(status=302,location=URL),response(page(dict(image('own'),code='ABC_123')))]) as get:
            extractor.extract('https://www.threads.com/share/token/')
            self.assertEqual(get.call_count,2)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
        with patch.object(requests.Session,'get',return_value=response(status=302,location='http://127.0.0.1/private')) as get:
            with self.assertRaisesRegex(ValueError,'跳转'):extractor.extract(URL)
            self.assertEqual(get.call_count,1)

    def test_cookie_scope_proxy_and_context_reset(self):
        payload=[{'domain':'.threads.com','name':'threads_session','value':'private'},
                 {'domain':'.instagram.com','name':'ig_session','value':'do-not-send'},
                 {'domain':'.evil.example','name':'foreign','value':'do-not-send'}]
        seen=[]
        def get(session,url,**kwargs):
            seen.append((list(session.cookies),dict(session.proxies)))
            self.assertEqual(kwargs['proxies'],{'http':'http://127.0.0.1:9876','https':'http://127.0.0.1:9876'})
            return response(page(dict(image('own'),code='ABC_123')))
        with tempfile.TemporaryDirectory() as folder:
            cookie=Path(folder)/'cookies.json';original=json.dumps(payload).encode();cookie.write_bytes(original)
            extractor=ThreadsMediaExtractor(cookie)
            with patch.object(requests.Session,'get',autospec=True,side_effect=get):
                media=extractor.extract(URL,proxy='http://127.0.0.1:9876')
            self.assertEqual([c.name for c in seen[0][0]],['threads_session'])
            self.assertEqual(seen[0][1],{'http':'http://127.0.0.1:9876','https':'http://127.0.0.1:9876'})
            self.assertNotIn('Cookie',extractor.request_headers(media[0][0]));self.assertEqual(cookie.read_bytes(),original)
            with patch.object(requests.Session,'get',return_value=response('blocked',403)):
                with self.assertRaisesRegex(ValueError,'Threads'):extractor.extract(URL)
            self.assertIsNone(extractor.resolved_link);self.assertEqual(extractor.request_headers(media[0][0]),{})
