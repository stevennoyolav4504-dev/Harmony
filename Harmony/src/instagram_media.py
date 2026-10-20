"""Conservative Instagram fast path: exact post identity and complete media."""
import json
from urllib.parse import urlsplit


def instagram_media_identity(media):
    """A media filename survives CDN host, signature and image-format changes."""
    return media[1], urlsplit(media[0]).path.rsplit('/', 1)[-1].split('.')[0]


def map_instagram_recovery(original, legacy):
    """Map old DOM results without dropping videos or shifting a partial post."""
    matches = {}
    for index, item in enumerate(original):
        key = instagram_media_identity((item[0], item[4]))
        candidates = [j for j, candidate in enumerate(legacy) if instagram_media_identity(candidate) == key]
        if len(candidates) == 1:
            matches[index] = candidates[0]
    # A full, consistently ordered traversal can also refresh changed filenames.
    # Partial traversals use identities only, so a missing video cannot shift
    # subsequent images onto the wrong cards.
    if (len(original) == len(legacy) and
            all(item[4] == candidate[1] for item, candidate in zip(original, legacy)) and
            all(index == candidate for index, candidate in matches.items()) and
            len({instagram_media_identity(item) for item in legacy}) == len(legacy)):
        matches = {index: index for index in range(len(original))}
    return {index: legacy[candidate] for index, candidate in matches.items()}


def _media_url(value):
    if not isinstance(value, str): return None
    parts = urlsplit(value)
    host = (parts.hostname or '').lower()
    if parts.scheme == 'https' and not parts.username and not parts.password and (
            host == 'cdninstagram.com' or host.endswith('.cdninstagram.com') or
            host == 'fbcdn.net' or host.endswith('.fbcdn.net')):
        return value
    return None


def _image(node):
    versions = node.get('image_versions2') or {}
    candidates = node.get('display_resources') or (versions.get('candidates') if isinstance(versions, dict) else versions) or []
    valid = [c for c in candidates if isinstance(c, dict) and _media_url(c.get('src') or c.get('url'))]
    if valid:
        best = max(valid, key=lambda c: (int(c.get('width') or c.get('config_width') or 0) *
                                        int(c.get('height') or c.get('config_height') or 0)))
        return best.get('src') or best['url']
    return _media_url(node.get('display_url')) or _media_url(node.get('thumbnail_src'))


def _single(node):
    kind = node.get('__typename', '')
    is_video = node.get('is_video') is True or node.get('media_type') == 2 or kind in ('GraphVideo', 'XDTGraphVideo')
    is_image = node.get('is_video') is False or node.get('media_type') == 1 or kind in ('GraphImage', 'XDTGraphImage')
    if is_video:
        versions = [v for v in node.get('video_versions') or [] if isinstance(v, dict) and _media_url(v.get('url'))]
        url = _media_url(node.get('video_url'))
        if versions:
            best = max(versions, key=lambda v: (int(v.get('width') or 0) * int(v.get('height') or 0), v.get('type') == 102))
            url = best['url']
        return (url, 'video', _image(node) or '') if url else None
    if is_image:
        url = _image(node)
        return (url, 'image', url) if url else None
    return None


def complete_instagram_media(payload, shortcode):
    """Return only a matching full post; ambiguous/partial payloads use DOM."""
    stack, inspected = [payload], 0
    while stack and inspected < 50000:
        node = stack.pop(); inspected += 1
        if isinstance(node, list):
            stack.extend(reversed(node)); continue
        if not isinstance(node, dict): continue
        if node.get('shortcode') == shortcode or node.get('code') == shortcode:
            side = node.get('edge_sidecar_to_children')
            if isinstance(side, dict):
                edges = side.get('edges') or []
                children = [e.get('node') for e in edges if isinstance(e, dict)]
                count = side.get('count') or node.get('carousel_media_count')
                page_info = side.get('page_info') or {}
                complete = page_info.get('has_next_page') is False or (isinstance(count, int) and count == len(children))
                complete = complete and page_info.get('has_next_page') is not True
                if count is not None: complete = complete and count == len(children)
            elif isinstance(node.get('carousel_media'), list):
                children = node['carousel_media']
                count = node.get('carousel_media_count')
                complete = isinstance(count, int) and count == len(children)
            elif node.get('media_type') == 8 or 'Sidecar' in str(node.get('__typename', '')):
                children, complete = [], False
            else:
                children, complete = [node], True
            if complete and children and all(isinstance(child, dict) for child in children):
                media = [_single(child) for child in children]
                # Do not drop unavailable children, substitute covers for videos,
                # include the sidecar parent cover, or merge recommended posts.
                if all(media) and len({item[0] for item in media}) == len(media):
                    return media
            continue
        stack.extend(reversed([v for v in node.values() if isinstance(v, (dict, list))]))
    return None


def read_complete_instagram_post(page, shortcode):
    scripts = page.evaluate("""shortcode => Array.from(document.querySelectorAll('script[type="application/json"]'))
        .map(script => script.textContent || '').filter(text => text.includes(shortcode) && text.length <= 5000000)""", shortcode)
    for script in scripts:
        try:
            media = complete_instagram_media(json.loads(script), shortcode)
            if media: return media
        except (ValueError, TypeError, AttributeError):
            continue
    return None
