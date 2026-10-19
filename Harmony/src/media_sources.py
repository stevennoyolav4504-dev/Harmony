"""Validated post links and X / TikTok extraction through bundled yt-dlp."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class PostLink:
    platform: str
    post_id: str
    url: str
    is_short: bool = False

    @property
    def cache_key(self):
        prefix = {'X': 'x_', 'TikTok': 'tiktok_'}.get(self.platform, '')
        return prefix + self.post_id


def parse_post_link(url):
    # Mobile TikTok shares may include a caption around the actual URL.
    raw = url.strip()
    if not raw.startswith(('http://', 'https://')):
        urls = re.findall(r'https?://[^\s<>"\u4e00-\u9fff]+', raw)
        if len(urls) == 1:
            candidate = urls[0].rstrip('.,;!?，。；！？”）)]}')
            if (urlsplit(candidate).hostname or '').lower() in ('tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'):
                url = candidate
    parts = urlsplit(url.strip())
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https') or parts.username or parts.password:
        raise ValueError('请粘贴有效的 Instagram、X 或 TikTok 帖子链接')
    if host in ('instagram.com', 'www.instagram.com', 'm.instagram.com'):
        match = re.fullmatch(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)/?', parts.path)
        if match:
            return PostLink('Instagram', match[1], f'https://www.instagram.com/p/{match[1]}/')
    if host in ('x.com', 'www.x.com', 'mobile.x.com', 'm.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com', 'm.twitter.com'):
        match = re.fullmatch(r'/(?:[A-Za-z0-9_]+/status|i/(?:web/)?status)/(\d+)(?:/(?:photo|video)/\d+)?/?', parts.path)
        if match:
            return PostLink('X', match[1], f'https://x.com/i/status/{match[1]}')
    if host in ('tiktok.com', 'www.tiktok.com', 'm.tiktok.com'):
        match = re.fullmatch(r'/@([A-Za-z0-9_.-]*)/(video|photo)/(\d+)/?', parts.path)
        if match:
            return PostLink('TikTok', match[3], f'https://www.tiktok.com/@{match[1]}/{match[2]}/{match[3]}')
        match = re.fullmatch(r'/(?:share/video|embed(?:/v2)?)/(\d+)/?', parts.path)
        if match:
            return PostLink('TikTok', match[1], f'https://www.tiktok.com/@/video/{match[1]}')
        match = re.fullmatch(r'/t/([A-Za-z0-9]+)/?', parts.path)
    elif host in ('vm.tiktok.com', 'vt.tiktok.com'):
        match = re.fullmatch(r'/([A-Za-z0-9]+)/?', parts.path)
    else:
        match = None
    if match:
        return PostLink('TikTok', f'short_{match[1]}', urlunsplit(('https', host, parts.path, parts.query, '')), True)
    raise ValueError('请粘贴 Instagram、X 或 TikTok 帖子链接（支持 TikTok 分享短链接）')


def _http_url(url):
    if not isinstance(url, str): return None
    if url.startswith('//'): url = 'https:' + url
    parts = urlsplit(url)
    return url if parts.scheme in ('http', 'https') and parts.hostname and not parts.username and not parts.password else None


def tiktok_photos_from_status(status):
    """Return slides themselves, never the cover or background music."""
    post = status.get('imagePost') or status.get('image_post_info') or {}
    images = post.get('images') or []
    result, seen = [], set()
    for image in images:
        if not isinstance(image, dict): continue
        for field in ('imageURL', 'displayImage', 'display_image'):
            address = image.get(field) or {}
            urls = address.get('urlList') or address.get('url_list') or []
            url = next((valid for value in urls if (valid := _http_url(value))), None)
            if url:
                if url not in seen:
                    result.append((url, 'image', url)); seen.add(url)
                break
    return result


def tiktok_video_from_formats(formats, thumbnail=''):
    # The media grid downloads a single playable file, so skip audio, manifests,
    # video-only HEVC streams and bytevc2 instead of presenting them as videos.
    candidates = [f for f in formats if _http_url(f.get('url'))
                  and f.get('ext', 'mp4') == 'mp4'
                  and f.get('vcodec') not in ('none', 'bytevc2') and f.get('acodec') != 'none'
                  and f.get('protocol', 'https') in ('http', 'https')
                  and not urlsplit(f['url']).path.lower().endswith(('.m3u8', '.mpd'))]
    if not candidates: raise ValueError('未找到可下载的 TikTok 视频，请检查帖子是否公开后重试')
    def score(fmt):
        return (fmt.get('preference') if fmt.get('preference') is not None else -1,
                int(fmt.get('height') or 0), int(fmt.get('width') or 0),
                float(fmt.get('tbr') or 0), int(fmt.get('filesize') or 0))
    best = max(candidates, key=score)
    return [(_http_url(best['url']), 'video', _http_url(thumbnail) or '')]


def _configure_tiktok_certificates(ydl, folder):
    """libcurl on Windows cannot open a CA file under a non-ASCII path.

    Use a private copy for this downloader only, retaining certificate checking
    and avoiding process-wide environment or dependency changes during YT jobs.
    """
    import certifi
    source = Path(certifi.where())
    if os.name != 'nt' or str(source).isascii(): return
    handler = ydl._request_director.handlers.get('CurlCFFI')
    if handler is None: return
    target = Path(folder) / 'cacert.pem'
    shutil.copyfile(source, target)
    factory = handler._create_instance
    def create_instance(*args, **kwargs):
        session = factory(*args, **kwargs)
        session.verify = str(target)
        return session
    handler._create_instance = create_instance


class TikTokMediaExtractor:
    def __init__(self, cookies_path=None):
        self.cookies_path = cookies_path
        self.resolved_link = None
        self._request_headers = {}
        self.proxy = None

    def request_headers(self, url):
        return dict(self._request_headers.get(url, {}))

    def extract(self, url, progress_callback=None, proxy=None):
        import yt_dlp
        from yt_dlp.extractor.tiktok import TikTokIE, TikTokVMIE
        link = parse_post_link(url)
        if link.platform != 'TikTok': raise ValueError('需要 TikTok 帖子链接')
        self.resolved_link = None
        self._request_headers = {}
        self.proxy = proxy
        if progress_callback: progress_callback('正在读取 TikTok 帖子…')
        opts = {'quiet': True, 'no_warnings': True, 'cachedir': False, 'noplaylist': True,
                'socket_timeout': 25, 'retries': 1, 'extractor_retries': 1}
        if proxy: opts['proxy'] = proxy
        try:
            with tempfile.TemporaryDirectory(prefix='harmony-tiktok-') as folder, yt_dlp.YoutubeDL(opts) as ydl:
                _configure_tiktok_certificates(ydl, folder)
                extractor = TikTokIE(ydl)
                # Keep credentials in memory, scoped to their TikTok domain.
                if self.cookies_path and Path(self.cookies_path).is_file():
                    try: payload = json.loads(Path(self.cookies_path).read_text(encoding='utf-8'))
                    except (OSError, ValueError): payload = []
                    cookies = payload if isinstance(payload, list) else payload.get('cookies', []) if isinstance(payload, dict) else []
                    for cookie in cookies:
                        if not isinstance(cookie, dict): continue
                        domain = str(cookie.get('domain', '')).lstrip('.').lower()
                        if (domain == 'tiktok.com' or domain.endswith('.tiktok.com')) and cookie.get('name'):
                            extractor._set_cookie(cookie['domain'], cookie['name'], cookie.get('value', ''),
                                                  path=cookie.get('path', '/'), secure=cookie.get('secure', True))
                if link.is_short:
                    if progress_callback: progress_callback('正在展开 TikTok 分享链接…')
                    short = TikTokVMIE(ydl); short.initialize()
                    link = parse_post_link(short._real_extract(link.url)['url'])
                    if link.platform != 'TikTok' or link.is_short:
                        raise ValueError('TikTok 分享链接未能跳转到有效帖子')
                extractor.initialize()
                # Photo pages can be client-rendered. The corresponding video
                # route exposes the same post's imagePost data to yt-dlp.
                fetch_url = link.url.replace('/photo/', '/video/', 1)
                status, code = extractor._extract_web_data_and_status(fetch_url, link.post_id)
                if code == 10204:
                    raise ValueError('TikTok 拒绝了当前网络，请在设置中配置可用代理或更换网络后重试')
                if code != 0 or not status:
                    raise ValueError('无法读取这个 TikTok 帖子，可能已删除、需要登录或受地区限制')
                media = tiktok_photos_from_status(status)
                if not media:
                    if status.get('imagePost') or status.get('image_post_info'):
                        raise ValueError('未能读取 TikTok 图片帖中的图片，请稍后重试')
                    info = extractor._parse_aweme_video_web(status, link.url, link.post_id)
                    thumbnails = info.get('thumbnails') or []
                    thumb = next((t['url'] for t in thumbnails if _http_url(t.get('url')) and t.get('id') != 'dynamicCover'), '')
                    media = tiktok_video_from_formats(info.get('formats') or [], thumb)
                for media_url, _, thumb_url in media:
                    for resource in (media_url, thumb_url):
                        if not resource: continue
                        headers = {'Referer': link.url, 'User-Agent': ydl.params['http_headers']['User-Agent']}
                        cookie = ydl.cookiejar.get_cookie_header(resource)
                        if cookie: headers['Cookie'] = cookie
                        self._request_headers[resource] = headers
                self.resolved_link = link
                return media
        except ValueError:
            raise
        except Exception as error:
            raise ValueError('TikTok 提取失败：请检查网络或代理；帖子也可能需要登录、已删除或受地区限制') from error


def _cdn_url(url, host):
    if not isinstance(url, str): return None
    parts = urlsplit(url)
    return url if parts.scheme == 'https' and parts.hostname == host else None


def original_x_image(url):
    url = _cdn_url(url, 'pbs.twimg.com')
    if not url: return None
    parts = urlsplit(url)
    path = parts.path.split(':', 1)[0]
    query = parse_qs(parts.query)
    suffix = Path(path).suffix.lower().lstrip('.')
    if suffix in ('jpg', 'jpeg', 'png', 'webp'):
        path = path.rsplit('.', 1)[0]
        query['format'] = ['jpg' if suffix == 'jpeg' else suffix]
    query['name'] = ['orig']
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query, doseq=True), ''))


def x_media_from_status(status):
    # The syndication adapter also appends quoted media to extended_entities.
    # Prefer the original post's mediaDetails so quoted posts stay excluded.
    media = status.get('mediaDetails')
    if not isinstance(media, list):
        media = [] if 'quoted_tweet' in status else (status.get('extended_entities') or {}).get('media') or []
        if not media:
            media = [{'type': 'photo', 'media_url_https': photo.get('url')}
                     for photo in status.get('photos', []) if isinstance(photo, dict)]
    result, seen = [], set()
    for item in media:
        thumb = item.get('media_url_https') or item.get('media_url')
        kind = item.get('type')
        if kind == 'photo':
            url = original_x_image(thumb)
            media_type = 'image'
        elif kind in ('video', 'animated_gif'):
            variants = (item.get('video_info') or {}).get('variants') or []
            variants = [v for v in variants if _cdn_url(v.get('url'), 'video.twimg.com')
                        and (v.get('content_type') == 'video/mp4' or urlsplit(v['url']).path.endswith('.mp4'))]
            if not variants:
                raise ValueError('这个 X 视频暂时无法提取，请稍后重试')
            url = max(variants, key=lambda v: int(v.get('bitrate') or v.get('bit_rate') or 0))['url']
            media_type = 'video'
        else:
            continue
        if url and url not in seen:
            result.append((url, media_type, _cdn_url(thumb, 'pbs.twimg.com') or ''))
            seen.add(url)
    return result


class XMediaExtractor:
    def __init__(self, cookies_path=None):
        self.cookies_path = cookies_path

    def extract(self, url, progress_callback=None, proxy=None):
        import yt_dlp
        from yt_dlp.extractor.twitter import TwitterIE
        link = parse_post_link(url)
        if link.platform != 'X': raise ValueError('需要 X 帖子链接')
        if progress_callback: progress_callback('正在读取 X 帖子…')
        cookies = []
        if self.cookies_path and Path(self.cookies_path).is_file():
            try:
                payload = json.loads(Path(self.cookies_path).read_text(encoding='utf-8'))
                cookies = payload if isinstance(payload, list) else payload.get('cookies', []) if isinstance(payload, dict) else []
                cookies = [cookie for cookie in cookies if isinstance(cookie, dict)]
            except (OSError, ValueError): pass
        last_error = None
        had_status = False
        for api in ('graphql', 'syndication'):
            opts = {'quiet': True, 'no_warnings': True, 'cachedir': False,
                    'socket_timeout': 25, 'retries': 1, 'extractor_retries': 1,
                    'extractor_args': {'twitter': {'api': [api]}}}
            if proxy: opts['proxy'] = proxy
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    extractor = TwitterIE(ydl)
                    for cookie in cookies:
                        domain = cookie.get('domain', '').lstrip('.')
                        if domain in ('x.com', 'twitter.com') and cookie.get('name'):
                            extractor._set_cookie(cookie['domain'], cookie['name'], cookie.get('value', ''),
                                                  path=cookie.get('path', '/'), secure=cookie.get('secure', True))
                    extractor.initialize()
                    status = extractor._extract_status(link.post_id)
                    had_status = had_status or bool(status)
                    media = x_media_from_status(status)
                    if media: return media
            except Exception as error:
                last_error = error
        if had_status: return []
        raise ValueError('无法读取这个 X 帖子，可能已删除、需要登录或暂时受限') from last_error
