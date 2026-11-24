"""Read images and playable video from the public HTML for one note."""

from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

import requests
from yt_dlp.utils import js_to_json

from media_sources import parse_post_link


USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')
_STATE = re.compile(r'^\s*(?:window\.)?__INITIAL_STATE__\s*=\s*(\{.*\})\s*;?\s*$', re.DOTALL)
_IMAGE_ORIGIN = 'https://ci.xiaohongshu.com/'
# Regional storage keys can include both an oss region and an image namespace.
_IMAGE_KEY = re.compile(r'(?:[A-Za-z0-9_-]{1,64}/){0,2}[A-Za-z0-9_-]{20,128}(?:\.[A-Za-z0-9]{2,5})?')
_IMAGE_DELIVERY_PREFIX = re.compile(r'^\d{8,14}/[0-9a-fA-F]{32}/')
_MAX_PAGE_BYTES = 12_000_000
_UNAVAILABLE = '小红书笔记暂时无法读取，请在小红书里重新复制分享链接。笔记也可能已删除或需要登录'


class _NotePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.states = []
        self._script = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self._script = []

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._script is not None:
            match = _STATE.fullmatch(''.join(self._script))
            if match:
                self.states.append(match[1])
            self._script = None


def _object(value):
    return value if isinstance(value, dict) else {}


def _items(value):
    return value if isinstance(value, list) else []


def _cdn_url(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit('https:' + value if value.startswith('//') else value)
        host = parts.hostname or ''
        if (parts.scheme in ('http', 'https') and not parts.username and not parts.password
                and parts.port in (None, 80, 443)
                and host.endswith(('.xhscdn.com', '.xhsimg.com')) and parts.path):
            return parts._replace(scheme='https', netloc=host, fragment='').geturl()
    except ValueError:
        pass
    return None


def _image_url(image):
    image = _object(image)
    variants = [_object(info) for info in _items(image.get('infoList'))]
    candidates = [image.get('urlDefault')]
    candidates.extend(info.get('url') for info in variants if info.get('imageScene') == 'WB_DFT')
    candidates.extend([image.get('url'), image.get('urlPre')])
    candidates.extend(info.get('url') for info in variants)
    return next((url for value in candidates if (url := _cdn_url(value))), '')


def is_original_image_url(url):
    return url.startswith(_IMAGE_ORIGIN) and _IMAGE_KEY.fullmatch(url[len(_IMAGE_ORIGIN):]) is not None


def _original_image_url(image, display_url):
    key = _object(image).get('fileId')
    if not isinstance(key, str) or not _IMAGE_KEY.fullmatch(key):
        path = urlsplit(display_url).path.lstrip('/').partition('!')[0]
        # The date and signature identify the display rendition. The namespace
        # after them (e.g. notes_pre_post) is part of the original object key.
        key = _IMAGE_DELIVERY_PREFIX.sub('', path)
    return _IMAGE_ORIGIN + key if _IMAGE_KEY.fullmatch(key) else ''


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _video_url(note):
    video = _object(note.get('video'))
    streams = _object(_object(video.get('media')).get('stream'))
    candidates = []
    for codec, variants in streams.items():
        for stream in map(_object, _items(variants)):
            if (str(stream.get('format') or 'mp4').lower() != 'mp4'
                    or stream.get('audioCodec') == 'none' or stream.get('videoCodec') == 'none'):
                continue
            for value in [stream.get('masterUrl'), *_items(stream.get('backupUrls'))]:
                url = _cdn_url(value)
                if url and not urlsplit(url).path.lower().endswith(('.m3u8', '.mpd')):
                    score = (codec.lower() in ('h264', 'avc'),
                             _number(stream.get('width')) * _number(stream.get('height')),
                             _number(stream.get('avgBitrate')))
                    candidates.append((score, url))
                    break
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else ''


def note_media_from_page(html, note_id, *, original_sizes=None):
    page = _NotePage()
    page.feed(html)
    for state in page.states:
        if note_id not in state.lower():
            continue
        try:
            try:
                data = json.loads(state)
            except ValueError:
                data = json.loads(js_to_json(state))
        except (ValueError, RecursionError):
            continue
        detail = _object(_object(_object(data).get('note')).get('noteDetailMap'))
        note = _object(_object(detail.get(note_id)).get('note'))
        if not note or str(note.get('noteId') or note_id).lower() != note_id:
            continue
        images = [(image, _image_url(image)) for image in _items(note.get('imageList'))]
        if note.get('type') == 'video' or note.get('video'):
            video = _video_url(note)
            if video:
                return [(video, 'video', next((display for _, display in images if display), ''))]
            raise ValueError('这篇小红书笔记未提供可直接下载的 MP4 视频')
        gallery = [(_original_image_url(image, display) or display, 'image', display)
                   for image, display in images]
        if gallery and all(url for url, _, _ in gallery):
            if original_sizes is not None:
                for (image, _), (url, _, _) in zip(images, gallery):
                    if is_original_image_url(url):
                        width = _number(_object(image).get('width'))
                        height = _number(_object(image).get('height'))
                        if width > 0 and height > 0:
                            original_sizes[url] = (width, height)
            return gallery
        raise ValueError('小红书笔记的图片数据不完整，请重新复制分享链接后提取')
    raise ValueError(_UNAVAILABLE)


class XiaohongshuMediaExtractor:
    def __init__(self):
        self.proxy = None
        self.resolved_link = None
        self._request_headers = {}
        self._original_sizes = {}

    def request_headers(self, url):
        return dict(self._request_headers.get(url, {}))

    def original_size(self, url):
        return self._original_sizes.get(url, (0, 0))

    def _load_note(self, session, link):
        expected_id = None if link.is_short else link.post_id
        url = link.url
        for _ in range(7):
            with session.get(url, timeout=(6, 18), stream=True, allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    if not location:
                        raise ValueError(_UNAVAILABLE)
                    target = urljoin(url, location)
                    try:
                        redirected = parse_post_link(target)
                    except ValueError:
                        raise ValueError(_UNAVAILABLE) from None
                    if redirected.platform != 'Xiaohongshu' or (expected_id and (
                            redirected.is_short or redirected.post_id != expected_id)):
                        raise ValueError('小红书链接跳转到了其他页面，请重新复制笔记分享链接')
                    link = redirected
                    if not link.is_short:
                        expected_id = link.post_id
                    # Validate first, then use the site's complete redirect URL.
                    # Normalize the scheme so signed parameters travel over HTTPS.
                    url = urlsplit(link.url)._replace(query=urlsplit(target).query).geturl()
                    continue
                if link.is_short or response.status_code in (401, 403, 404, 410, 429):
                    raise ValueError(_UNAVAILABLE)
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > _MAX_PAGE_BYTES:
                        raise ValueError('小红书笔记页面过大，暂时无法解析')
                return link, body.decode('utf-8', errors='replace')
        raise ValueError('小红书分享链接跳转过多，请复制完整笔记链接')

    def extract(self, url, progress_callback=None, proxy=None):
        self.proxy = proxy
        self.resolved_link = None
        self._request_headers.clear()
        self._original_sizes.clear()
        link = parse_post_link(url)
        if link.platform != 'Xiaohongshu':
            raise ValueError('需要小红书笔记链接')
        if progress_callback:
            progress_callback('正在展开小红书分享链接…' if link.is_short else '正在读取小红书笔记…')
        try:
            with requests.Session() as session:
                session.headers.update({'User-Agent': USER_AGENT, 'Accept-Language': 'zh-CN,zh;q=0.9',
                                        'Accept': 'text/html,application/xhtml+xml'})
                if proxy:
                    session.proxies.update({'http': proxy, 'https': proxy})
                link, html = self._load_note(session, link)
        except requests.RequestException:
            raise ValueError('小红书连接失败，请检查网络或代理后重试') from None
        media = note_media_from_page(html, link.post_id, original_sizes=self._original_sizes)
        origin = f'https://{urlsplit(link.url).hostname}/'
        self._request_headers = {resource: {'User-Agent': USER_AGENT, 'Referer': origin}
                                 for url, _, thumb in media for resource in (url, thumb) if resource}
        self.resolved_link = link
        return media
