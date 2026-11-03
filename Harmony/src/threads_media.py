"""Public Threads page data, selected by exact post code without recommendations."""
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit

import requests
from media_sources import parse_post_link

_PAGE_AGENT = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
_MEDIA_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
_POST_KEYS = {'media_type', 'image_versions2', 'video_versions', 'carousel_media', 'video_dash_manifest'}


class ThreadsPage(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts=[]; self.canonical=''; self._script=None

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='script' and attrs.get('type')=='application/json': self._script=[]
        if tag=='link' and attrs.get('rel')=='canonical': self.canonical=attrs.get('href','')
        if tag=='meta' and attrs.get('property')=='og:url' and not self.canonical:
            self.canonical=attrs.get('content','')

    def handle_data(self, data):
        if self._script is not None: self._script.append(data)

    def handle_endtag(self, tag):
        if tag=='script' and self._script is not None:
            text=''.join(self._script)
            if len(text)<=5_000_000: self.scripts.append(text)
            self._script=None


def _url(value):
    if not isinstance(value,str): return None
    try:
        p=urlsplit(value);host=(p.hostname or '').lower()
        if p.scheme=='https' and not p.username and not p.password and p.port in (None,443) and (
                host=='cdninstagram.com' or host.endswith('.cdninstagram.com') or
                host=='fbcdn.net' or host.endswith('.fbcdn.net')):
            return value
    except ValueError: pass
    return None


def _area(item):
    try:return int(item.get('width') or 0)*int(item.get('height') or 0)
    except (ValueError,TypeError):return 0


def _single(post):
    images=(post.get('image_versions2') or {}).get('candidates') or []
    images=[item for item in images if isinstance(item,dict) and _url(item.get('url'))]
    image=max(images,key=_area)['url'] if images else ''
    if post.get('media_type')==2 or post.get('video_versions') or post.get('video_dash_manifest'):
        videos=[v for v in post.get('video_versions') or [] if isinstance(v,dict) and _url(v.get('url'))
                and not urlsplit(v['url']).path.lower().endswith(('.m3u8','.mpd'))]
        if not videos:raise ValueError('Threads 视频暂无可直接下载的 MP4 地址')
        best=max(videos,key=lambda v:(_area(v),v.get('type')==102))
        return best['url'],'video',image
    if image:return image,'image',image
    raise ValueError('Threads 媒体数据不完整，请重新提取')


def threads_media_from_payload(payload, code):
    """None means absent; [] means the matching post contains no media."""
    stack=[payload];inspected=0;failure=None
    while stack and inspected<100_000:
        node=stack.pop();inspected+=1
        if isinstance(node,list):stack.extend(reversed(node));continue
        if not isinstance(node,dict):continue
        if (node.get('code')==code or node.get('shortcode')==code) and _POST_KEYS.intersection(node):
            try:
                children=node.get('carousel_media')
                if isinstance(children,list):
                    count=node.get('carousel_media_count')
                    if not children or count is not None and count!=len(children):
                        raise ValueError('Threads 图片轮播数据不完整，请重新提取')
                    result=[_single(child) for child in children]
                elif node.get('media_type')==8:
                    raise ValueError('Threads 图片轮播数据不完整，请重新提取')
                elif node.get('media_type') in (0,19) and not (
                        (node.get('image_versions2') or {}).get('candidates') or
                        node.get('video_versions') or node.get('video_dash_manifest')):
                    return []
                else:result=[_single(node)]
                if len({item[0] for item in result})!=len(result):
                    raise ValueError('Threads 轮播包含重复媒体，未返回不完整结果')
                return result
            except (ValueError,TypeError,AttributeError) as error:
                failure=error
            continue  # Never collect a quoted post as this post's own media.
        stack.extend(reversed([v for v in node.values() if isinstance(v,(list,dict))]))
    if failure:raise ValueError('Threads 媒体数据不完整或格式暂不支持，请重新提取') from failure
    return None


class ThreadsMediaExtractor:
    def __init__(self,cookies_path=None):
        self.cookies_path=cookies_path;self.proxy=None;self.resolved_link=None;self._request_headers={}

    def request_headers(self,url):return dict(self._request_headers.get(url,{}))

    @staticmethod
    def _allowed_page(url):
        p=urlsplit(url)
        if p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,80,443) or (p.hostname or '').lower() not in ('threads.com','www.threads.com','threads.net','www.threads.net'):
            raise ValueError('Threads 分享链接跳转到了不支持的地址')

    def _page(self,session,url):
        for _ in range(6):
            self._allowed_page(url)
            for attempt in range(3):
                try:
                    options={'timeout':(10,25),'allow_redirects':False}
                    if self.proxy:options['proxies']={'http':self.proxy,'https':self.proxy}
                    response=session.get(url,**options)
                    break
                except (requests.ConnectionError,requests.Timeout):
                    if attempt==2:raise
                    time.sleep(.5*2**attempt)
            with response:
                if response.status_code in (301,302,303,307,308):
                    location=response.headers.get('Location')
                    if not location:raise ValueError('Threads 分享链接无法展开')
                    url=urljoin(url,location);continue
                response.raise_for_status()
                if len(response.content)>12_000_000:raise ValueError('Threads 页面过大，暂时无法解析')
                return response.content.decode('utf-8',errors='replace'),url
        raise ValueError('Threads 分享链接跳转过多')

    def extract(self,url,progress_callback=None,proxy=None):
        link=parse_post_link(url)
        if link.platform!='Threads':raise ValueError('需要 Threads 帖子链接')
        self.proxy=proxy;self.resolved_link=None;self._request_headers={}
        if progress_callback:progress_callback('正在读取 Threads 帖子…')
        try:
            with requests.Session() as session:
                session.headers.update({'User-Agent':_PAGE_AGENT,'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})
                if proxy:session.proxies.update({'http':proxy,'https':proxy})
                if self.cookies_path and Path(self.cookies_path).is_file():
                    try:payload=json.loads(Path(self.cookies_path).read_text(encoding='utf-8'))
                    except (OSError,ValueError):payload=[]
                    cookies=payload if isinstance(payload,list) else payload.get('cookies',[]) if isinstance(payload,dict) else []
                    for cookie in cookies:
                        if not isinstance(cookie,dict):continue
                        domain=str(cookie.get('domain','')).lstrip('.').lower()
                        if domain in ('threads.com','threads.net','www.threads.com','www.threads.net') and cookie.get('name'):
                            session.cookies.set(cookie['name'],str(cookie.get('value','')),domain=cookie['domain'],
                                                path=cookie.get('path','/'),secure=cookie.get('secure',True))
                html,final_url=self._page(session,link.url)
                page=ThreadsPage();page.feed(html)
                if link.is_short:
                    resolved=parse_post_link(urljoin(final_url,page.canonical) if page.canonical else final_url)
                    if resolved.platform!='Threads' or resolved.is_short:
                        raise ValueError('未能确定 Threads 分享链接对应的帖子，请使用完整帖子链接')
                    link=resolved
                elif page.canonical:
                    try:canonical=parse_post_link(urljoin(final_url,page.canonical))
                    except ValueError:canonical=None
                    if canonical and canonical.platform=='Threads' and canonical.post_id==link.post_id:
                        link=canonical
                media=None;failure=None
                for script in page.scripts:
                    if link.post_id not in script:continue
                    try:
                        result=threads_media_from_payload(json.loads(script),link.post_id)
                        if result is not None:media=result;break
                    except (ValueError,TypeError) as error:failure=error
                if media is None:
                    raise ValueError('未找到这个 Threads 帖子的完整媒体，可能已删除、需要登录或暂时受限') from failure
                for media_url,_,thumb in media:
                    for resource in (media_url,thumb):
                        if resource:self._request_headers[resource]={'User-Agent':_MEDIA_AGENT,'Referer':link.url}
                self.resolved_link=link
                return media
        except requests.RequestException as error:
            raise ValueError('Threads 读取失败，请检查网络或代理；帖子也可能需要登录或暂时受限') from error
