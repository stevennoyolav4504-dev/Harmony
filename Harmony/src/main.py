# Instagram 图片提取器 - 最终融合版
# 提取逻辑：Marvis 精准 DOM 提取（div._aagu + 推荐帖过滤）
# UI 设计：Harmony REV.06 品牌主题（侧边栏、卡片与蓝粉绿白配色）
# 功能：多选、全选、分辨率显示、暗色切换、批量下载

import os
import sys
import json
import time
import random
import base64
import ctypes
import logging
import shutil
import subprocess
import glob
import threading
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import tkinter as tk

import requests
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from logging.handlers import RotatingFileHandler
from version import __version__
from windows_integration import apply_window_icons, apply_titlebar_theme, set_app_user_model_id, refresh_restored_window
from windows_rendering import install_restore_buffer
from harmony_theme import COLOR_SCHEMES, select_font
from media_sources import XMediaExtractor, TikTokMediaExtractor, parse_post_link
from instagram_media import read_complete_instagram_post
from video_tasks import VideoTaskQueue, VideoOptions, TaskCancelled, parse_video_links, run_media_process, validate_clip

# ---------- 打包路径兼容 ----------
def _get_base_dir():
    """源码运行时返回项目根目录；PyInstaller 打包后返回 exe 所在目录

    源码布局已收拢为 <项目根>/src/main.py，故需由脚本目录再上移一级，
    保证 config.json / cookies.json / youtube_cookies.txt 等运行数据仍落在项目根。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _get_internal_dir():
    """PyInstaller --onedir 时 _internal 与 exe 同级"""
    base = _get_base_dir()
    internal = os.path.join(base, "_internal")
    if os.path.isdir(internal):
        return internal
    return base

# 设置 Playwright 浏览器路径（打包后指向 _internal\browsers）
_internal = _get_internal_dir()
_browsers_dir = os.path.join(_internal, "browsers")

def _ensure_browsers():
    """确保 Playwright Chromium 浏览器可用。
    打包后依赖打包脚本随附的 browsers 目录；源码运行时尝试自动安装。"""
    import glob as _glob
    chrome_exe = _glob.glob(os.path.join(_browsers_dir, "chromium-*", "chrome-win64", "chrome.exe"))
    if chrome_exe and os.path.isfile(chrome_exe[0]):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir
        return True

    # 浏览器缺失，尝试自动安装
    if not getattr(sys, 'frozen', False):
        try:
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True, timeout=900,
                env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": _browsers_dir}
            )
            chrome_exe = _glob.glob(os.path.join(_browsers_dir, "chromium-*", "chrome-win64", "chrome.exe"))
            if chrome_exe and os.path.isfile(chrome_exe[0]):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir
                return True
        except Exception:
            pass

    # 安装失败 — 仍设 env 供 Playwright 报清晰错误
    if os.path.isdir(_browsers_dir):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir
    return False

_browsers_ready = _ensure_browsers()

# ---------- 持久化配置 ----------
BASE_DIR = _get_base_dir()
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

def load_config():
    """加载配置，返回 dict"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_config(key, value):
    """保存单个配置项"""
    cfg = load_config()
    cfg[key] = value
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def save_full_config(cfg):
    """完整写入配置 dict"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ---------- 日志配置 ----------
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "harmony.log")

logger = logging.getLogger("InstaDownloader")
logger.setLevel(logging.DEBUG)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(threadName)s - %(message)s')
file_handler.setFormatter(file_formatter)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_formatter = logging.Formatter('%(levelname)s: %(message)s')
console_handler.setFormatter(console_formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ---------- 主题设置 ----------
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


# ============================================================
#  核心提取函数（Marvis 修复版 - 稳定可靠）
# ============================================================

class InstagramExtractor:
    """Instagram 媒体提取器 - 业务逻辑层"""

    def __init__(self, cookies_path: str, proxy: str = None):
        self.cookies_path = cookies_path
        self.proxy = proxy
        self._browser = None
        self._context = None
        self._playwright = None

    def _init_browser(self):
        """后台运行提取内核，不创建可见的浏览器窗口。"""
        if not _browsers_ready:
            raise RuntimeError("Chromium 浏览器未就绪，请确认 _internal\\browsers 目录存在且包含 chromium-*")
        self._playwright = sync_playwright().start()
        launch_options = {
            "headless": True,
            # Use the bundled full Chromium's headless mode. Default headless
            # needs a separate headless-shell download that releases omit.
            "channel": "chromium",
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1280,900",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--hide-scrollbars",
                "--mute-audio",
            ]
        }
        if self.proxy:
            launch_options["proxy"] = {"server": self.proxy}

        try:
            self._browser = self._playwright.chromium.launch(**launch_options)
        except Exception as e:
            self._playwright.stop()
            self._playwright = None
            raise RuntimeError(f"启动 Chromium 失败: {e}") from e
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="Asia/Shanghai",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
        )

        # 加载 Cookie
        try:
            with open(self.cookies_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            SAME_SITE_MAP = {"no_restriction": "None", "lax": "Lax",
                            "strict": "Strict", "none": "None",
                            "unspecified": "Lax"}
            for c in cookies:
                raw = c.get("sameSite")
                c["sameSite"] = SAME_SITE_MAP.get(str(raw).lower(), "Lax")
                c.pop("hostOnly", None)
                c.pop("storeId", None)
                c.pop("session", None)
            self._context.add_cookies(cookies)
            logger.info(f"成功加载 {len(cookies)} 个 Cookie")
        except Exception as e:
            logger.warning(f"Cookie 加载失败: {e}")

        page = self._context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
            window.chrome = { runtime: {} };
        """)
        Stealth().apply_stealth_sync(page)
        return page

    def extract(self, url: str, progress_callback=None) -> list:
        """提取 Instagram 帖子中的图片与视频，返回 [(url, type, thumb_url), ...]"""
        logger.info(f"开始真人模拟提取，URL: {url}")
        collected_media = []

        page = self._init_browser()
        started = time.monotonic()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            _check_instagram_access(page.url)

            shortcode = parse_post_link(url).post_id
            initial, complete = _wait_instagram_ready(page, shortcode)
            if complete:
                logger.info('IG 完整数据提取: %s 项, %.3f 秒（含导航与页面等待，不含浏览器启动）', len(initial), time.monotonic() - started)
                if progress_callback: progress_callback(f'已读取完整帖子：{len(initial)} 项')
                return initial

            # 检查轮播图
            next_btn_selector = (
                'button[aria-label="下一步"], button[aria-label="Next"], '
                'div[role="button"]:has(svg[aria-label="Next"]), '
                'div[role="button"]:has(svg[aria-label="下一页"])'
            )
            has_carousel = page.locator(next_btn_selector).count() > 0

            if has_carousel:
                logger.info("检测到轮播图，开始遍历切换...")
                seen_urls = set()
                for idx in range(20):
                    current = extract_current_visible_media(page)
                    new_items = [item for item in current if item[0] not in seen_urls]
                    seen_urls.update(item[0] for item in current)
                    collected_media.extend(new_items)
                    if progress_callback:
                        progress_callback(
                            f"轮播第 {idx+1} 页: +{len(new_items)} 项 (累计 {len(seen_urls)})")

                    try:
                        next_btn = page.locator(next_btn_selector).first
                        if not next_btn.is_visible():
                            break
                        prev_srcs = set(item[0] for item in current)
                        next_btn.click()
                        # 等待新帧图片渲染稳定后再提取，避免懒加载未完成导致漏图
                        _wait_carousel_ready(page, prev_srcs)
                    except Exception:
                        break
            else:
                collected_media.extend(initial or extract_current_visible_media(page))

            # 诊断: 打印 DOM 提取结果概况
            dom_imgs = sum(1 for item in collected_media if item[1] == 'image')
            dom_vids = sum(1 for item in collected_media if item[1] == 'video')
            logger.info(f"DOM 提取结果: {dom_imgs} 张图片, {dom_vids} 个视频")

            # JSON 降级
            is_reel = '/reel/' in url
            has_video = any(item[1] == 'video' for item in collected_media)
            if is_reel and not has_video:
                json_results = extract_post_media_from_json(page)
                if json_results:
                    collected_media.extend(json_results)
            elif not collected_media:
                collected_media = extract_post_media_from_json(page)

            # 去重
            seen = set()
            unique = []
            for item in collected_media:
                if item[0] not in seen:
                    seen.add(item[0])
                    unique.append(item)
            logger.info(f"共提取到 {len(unique)} 个媒体")
            logger.info('IG DOM 提取耗时: %.3f 秒（含导航与页面等待，不含浏览器启动）', time.monotonic() - started)
            return unique

        except Exception as e:
            logger.exception("提取异常")
            raise RuntimeError(f"提取失败: {str(e)}")

    def close(self):
        """清理浏览器资源"""
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._playwright = None

def _check_instagram_access(url):
    path = urlsplit(url).path.lower()
    if path.startswith('/accounts/login'):
        raise RuntimeError('Instagram 登录已失效，请到「设置 → Instagram 登录与 Cookie」主动登录后重试')
    if path.startswith(('/challenge', '/checkpoint', '/accounts/suspended', '/accounts/disabled', '/accounts/confirm_email')):
        raise RuntimeError('Instagram 需要账号验证，请到「设置 → Instagram 登录与 Cookie」完成验证后重试')


def _wait_instagram_ready(page, shortcode, timeout=15):
    """Wait for full post data or stable, actually loaded DOM media."""
    deadline = time.monotonic() + timeout
    last, stable_since, scrolled = None, None, False
    next_scan = 0.0
    current = []
    while time.monotonic() < deadline:
        _check_instagram_access(page.url)
        now = time.monotonic()
        if now >= next_scan:
            try:
                complete = read_complete_instagram_post(page, shortcode)
                if complete: return complete, True
            except Exception:
                pass  # An unavailable schema must never disable the DOM path.
            next_scan = now + .35
        if not scrolled:
            scrolled = page.evaluate("""() => {
                const target = document.querySelector('article') || document.querySelector('main');
                if (target) target.scrollIntoView({behavior: 'instant', block: 'start'});
                return !!target;
            }""")
        current = extract_current_visible_media(page, ready_only=True)
        # Include the next button in the signature: rendering carousel controls
        # restarts the settling interval rather than mistaking slide 1 for a post.
        signature = (tuple(item[0] for item in current), page.locator(_IG_NEXT_BUTTON).count())
        if current and signature == last:
            if time.monotonic() - stable_since >= .5: return current, False
        else:
            last, stable_since = signature, time.monotonic()
        page.wait_for_timeout(100)
    return current, False


_IG_NEXT_BUTTON = ('button[aria-label="下一步"], button[aria-label="Next"], '
                   'div[role="button"]:has(svg[aria-label="Next"]), '
                   'div[role="button"]:has(svg[aria-label="下一页"])')


def _wait_carousel_ready(page, prev_srcs, timeout=15):
    """等待轮播切换完成且新帧图片渲染稳定，避免懒加载未完成导致漏图。

    轮询当前已加载的 CDN 图片和直连视频 URL 集合：
    1) 内容需与点击前(prev_srcs)不同，确认切换成功；
    2) 连续 2 次检测集合一致，确认渲染稳定后再返回。
    """
    deadline = time.monotonic() + timeout
    last = set()
    stable = 0
    while time.monotonic() < deadline:
        try:
            srcs = [item[0] for item in extract_current_visible_media(page, ready_only=True)]
        except Exception:
            srcs = []
        srcs = set(srcs)
        if srcs and srcs != prev_srcs:
            if srcs == last:
                stable += 1
                if stable >= 2:
                    return srcs
            else:
                stable = 0
                last = srcs
        page.wait_for_timeout(100)
    return last


def extract_current_visible_media(page, ready_only=False):
    """从 div._aagu 容器精准提取图片+视频，排除推荐帖。返回 [(url, type, thumb_url), ...]"""
    results = page.evaluate("""
        readyOnly => {
            const results = [];
            const debug = [];
            const MIN_SIZE = 150;
            const cdn = (s) => s && (s.includes('cdninstagram.com') || s.includes('scontent.cdninstagram.com'));

            // --- 图片提取 ---
            const imgs = document.querySelectorAll('div._aagu img[src*="cdninstagram.com"], div._aagu img[src*="scontent.cdninstagram.com"]');
            debug.push('_aagu img 总数: ' + imgs.length);
            for (let img of imgs) {
                if (readyOnly && (!img.complete || img.naturalWidth < MIN_SIZE)) continue;
                const aagu = img.closest('div._aagu');
                if (aagu && aagu.parentElement && aagu.parentElement.tagName === 'A') {
                    debug.push('跳过(父A): ' + img.src.slice(0,80));
                    continue;
                }
                const rect = img.getBoundingClientRect();
                if (rect.width < MIN_SIZE || rect.height < MIN_SIZE) {
                    debug.push('跳过(尺寸' + rect.width + 'x' + rect.height + '): ' + img.src.slice(0,80));
                    continue;
                }
                let src = img.src;
                if (src.includes('/v/t51.') && src.includes('-19/')) {
                    debug.push('跳过(t51头像): ' + src.slice(0,80));
                    continue;
                }
                if (img.srcset) {
                    const m = img.srcset.match(/(https?:\\/\\/[^\\s]+)/g);
                    if (m && m.length > 0) src = m[m.length - 1];
                }
                if (cdn(src)) {
                    results.push({url: src, type: 'image', thumb: src});
                    debug.push('采纳图片: ' + src.slice(0,80));
                } else {
                    debug.push('跳过(非CDN): ' + src.slice(0,80));
                }
            }

            // --- 视频提取 ---
            // Reel 页面只取 article 内视频，避免侧栏推荐视频污染
            const isReelPage = location.href.includes('/reel/') || location.href.includes('/reels/');
            const videoSelector = isReelPage ? 'article video' : 'div._aagu video, article video, main video';
            const videos = document.querySelectorAll(videoSelector);
            debug.push('video 标签总数: ' + videos.length);
            for (let vid of videos) {
                const aagu = vid.closest('div._aagu');
                if (aagu && aagu.parentElement && aagu.parentElement.tagName === 'A') {
                    debug.push('跳过视频(父A)');
                    continue;
                }
                const srcEl = vid.querySelector('source[src]');
                const src = srcEl ? srcEl.src : vid.src;
                if (cdn(src)) {
                    const poster = vid.poster || '';
                    results.push({url: src, type: 'video', thumb: poster});
                    debug.push('采纳视频: ' + src.slice(0,80));
                } else if (src) {
                    debug.push('跳过视频(非CDN): ' + src.slice(0,80));
                } else {
                    debug.push('跳过视频(无src)');
                }
            }

            // 降级全页扫描（限定在帖子内容区域内，Reel 页面跳过——视频只靠 JSON）
            if (results.length === 0 && !isReelPage) {
                const container = document.querySelector('article') || document.querySelector('main') || document;
                const allImgs = container.querySelectorAll('img[src*="cdninstagram.com"], img[src*="scontent.cdninstagram.com"]');
                debug.push('全页扫描 img 总数: ' + allImgs.length);
                for (let img of allImgs) {
                    if (readyOnly && (!img.complete || img.naturalWidth < MIN_SIZE)) continue;
                    const aagu = img.closest('div._aagu');
                    if (aagu && aagu.parentElement && aagu.parentElement.tagName === 'A') continue;
                    const rect = img.getBoundingClientRect();
                    if (rect.width < MIN_SIZE || rect.height < MIN_SIZE) continue;
                    let src = img.src;
                    if (src.includes('/v/t51.') && src.includes('-19/')) {
                        debug.push('全扫跳过(t51头像): ' + src.slice(0,80));
                        continue;
                    }
                    if (img.srcset) {
                        const m = img.srcset.match(/(https?:\\/\\/[^\\s]+)/g);
                        if (m && m.length > 0) src = m[m.length - 1];
                    }
                    if (cdn(src)) results.push({url: src, type: 'image', thumb: src});
                }
            }

            return {results, debug};
        }
    """, ready_only)
    if isinstance(results, dict):
        debug_lines = results.get('debug', [])
        for line in debug_lines:
            logger.debug(f"DOM诊断: {line}")
        results = results['results']
    logger.debug(f"DOM 提取到 {len(results)} 个媒体")
    return [(r['url'], r['type'], r['thumb']) for r in results]


def extract_post_media_from_json(page):
    """JSON 降级提取图片+视频，返回 [(url, type, thumb_url), ...]"""
    result = page.evaluate("""
        () => {
            const debug = [];
            const scripts = document.querySelectorAll('script[type="application/json"]');
            debug.push('JSON script标签总数: ' + scripts.length);
            for (let s of scripts) {
                try {
                    const data = JSON.parse(s.innerText);
                    const topKeys = Object.keys(data).join(',');
                    // Post 页面
                    if (data?.graphql?.shortcode_media) {
                        debug.push('命中: graphql.shortcode_media (topKeys: ' + topKeys + ')');
                        return {data: data.graphql.shortcode_media, debug};
                    }
                    if (data?.entry_data?.PostPage?.[0]?.graphql?.shortcode_media) {
                        debug.push('命中: entry_data.PostPage (topKeys: ' + topKeys + ')');
                        return {data: data.entry_data.PostPage[0].graphql.shortcode_media, debug};
                    }
                    // Reel / Clips 页面
                    if (data?.entry_data?.ClipsPage?.[0]?.graphql?.shortcode_media) {
                        debug.push('命中: entry_data.ClipsPage (topKeys: ' + topKeys + ')');
                        return {data: data.entry_data.ClipsPage[0].graphql.shortcode_media, debug};
                    }
                    // 检查 entry_data 和 graphql 的子键
                    if (data?.entry_data) {
                        const subKeys = Object.keys(data.entry_data).join(',');
                        debug.push('entry_data子键: ' + subKeys);
                    }
                    if (data?.graphql) {
                        const subKeys = Object.keys(data.graphql).join(',');
                        debug.push('graphql子键: ' + subKeys);
                    }
                    // xdt 路径
                    if (data?.xdt_api__v1__media__shortcode__web_info) {
                        const xdt = data.xdt_api__v1__media__shortcode__web_info;
                        debug.push('命中: xdt_api__v1__media__shortcode__web_info, items数=' + (xdt.items?.length || 0));
                        if (xdt.items?.[0]) return {data: xdt.items[0], debug};
                    }
                    // xdt_graphql
                    if (data?.data?.xdt_shortcode_media) {
                        debug.push('命中: data.xdt_shortcode_media');
                        return {data: data.data.xdt_shortcode_media, debug};
                    }
                    // 通用递归搜索: 找含 video_versions / display_url / thumbnail_src / image_versions2 的节点
                    function findMedia(obj, depth) {
                        if (!obj || typeof obj !== 'object' || depth > 25) return null;
                        if (obj.video_versions || obj.display_url || obj.thumbnail_src || obj.image_versions2)
                            return obj;
                        for (let key of Object.keys(obj)) {
                            if (key === '_owner' || key === '__fragments' || key === '__id') continue;
                            const found = findMedia(obj[key], depth + 1);
                            if (found) return found;
                        }
                        return null;
                    }
                    const found = findMedia(data, 0);
                    if (found) {
                        const vv = found.video_versions ? '有video_versions(' + found.video_versions.length + ')' : '无video';
                        const du = found.display_url ? '有display_url' : '无display';
                        const ts = found.thumbnail_src ? '有thumb_src' : '无thumb_src';
                        const iv = found.image_versions2 ? '有image_versions2(' + (found.image_versions2.candidates?.length||found.image_versions2.length||0) + ')' : '无image_versions2';
                        debug.push('命中: findMedia -> ' + (found.__typename || 'unknown') + ' ' + vv + ' ' + du + ' ' + ts + ' ' + iv + ' (topKeys: ' + topKeys + ')');
                        return {data: found, debug};
                    }
                } catch(e) {
                    // 只记录前几个错误
                    if (debug.filter(l=>l.startsWith('JSON解析')).length < 3)
                        debug.push('JSON解析错误: ' + e.message);
                }
            }
            debug.push('JSON: 未找到任何媒体数据');
            return {data: null, debug};
        }
    """)

    debug_lines = result.get('debug', [])
    for line in debug_lines:
        logger.debug(f"JSON诊断: {line}")
    media_data = result.get('data')

    if not media_data:
        return []

    results = []

    def _add(url, media_type, thumb_url=""):
        if url and 'cdninstagram.com' in url:
            # 视频缩略图回退: 没有真实缩略图时不回退到视频 URL（PIL 打不开 mp4）
            final_thumb = thumb_url if thumb_url else (url if media_type != 'video' else '')
            results.append((url, media_type, final_thumb))

    def _extract_node(node):
        # 视频检测: is_video 字段 或 video_versions 数组 或 __typename 含 Video/Clip
        is_video_flag = node.get('is_video', False)
        video_versions = node.get('video_versions') or []
        typename = node.get('__typename', '')
        is_video_node = is_video_flag or len(video_versions) > 0 or 'Video' in typename or 'Clip' in typename

        # 缩略图 URL 提取：优先 thumbnail_src，其次 image_versions2.candidates[0].url，再 display_url
        thumb_src = node.get('thumbnail_src', '')
        if not thumb_src:
            iv2 = node.get('image_versions2', None)
            if iv2:
                candidates = iv2.get('candidates') or iv2 if isinstance(iv2, list) else []
                if candidates and isinstance(candidates, list) and len(candidates) > 0:
                    thumb_src = candidates[0].get('url', '') if isinstance(candidates[0], dict) else ''
        if not thumb_src:
            thumb_src = node.get('display_url', '')

        if is_video_node:
            # 优先从 video_versions 取无水印版 (type=102)，其次 type=101
            video_url = node.get('video_url', '')
            if video_versions:
                preferred = next((v for v in video_versions if v.get('type') == 102), None)
                if not preferred:
                    preferred = video_versions[0]
                video_url = preferred.get('url', video_url)
            _add(video_url, 'video', thumb_src)
        else:
            _add(node.get('display_url', thumb_src), 'image', thumb_src)

    _extract_node(media_data)
    thumb_info = "thumb_src" if media_data.get('thumbnail_src') else ("image_versions2" if media_data.get('image_versions2') else "none")
    logger.info(f"JSON节点解析: __typename={media_data.get('__typename','?')}, is_video={media_data.get('is_video','?')}, video_versions数={len(media_data.get('video_versions',[]) or [])}, thumb来源={thumb_info}")

    if 'edge_sidecar_to_children' in media_data:
        sides = media_data['edge_sidecar_to_children'].get('edges', [])
        logger.info(f"JSON轮播子节点数: {len(sides)}")
        for edge in sides:
            node = edge.get('node', {})
            _extract_node(node)

    seen = set()
    deduped = []
    for item in results:
        if item[0] not in seen:
            seen.add(item[0])
            deduped.append(item)
    logger.info(f"JSON最终结果: {len(deduped)} 个媒体 ({sum(1 for i in deduped if i[1]=='video')}视频, {sum(1 for i in deduped if i[1]=='image')}图片)")
    return deduped


# ---------- 多线程下载 ----------
def download_media_parallel(media_list, save_dir, prefix="post", progress_callback=None, request_headers=None, proxy=None):
    """media_list: [(url, type, thumb_url), ...]"""
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": "https://www.instagram.com/"
    }

    def _download_single(args):
        idx, (url, media_type, _thumb) = args
        partial_path = None
        try:
            item_headers = dict(headers)
            if (urlsplit(url).hostname or '').endswith('twimg.com'):
                item_headers['Referer'] = 'https://x.com/'
            if request_headers: item_headers.update(request_headers(url))
            ext = ".jpg"
            if media_type == 'video' or '.mp4' in url.lower():
                ext = ".mp4"
            elif ".png" in url.lower():
                ext = ".png"
            elif ".webp" in url.lower():
                ext = ".webp"
            image_format = (parse_qs(urlsplit(url).query).get('format') or [''])[0]
            if media_type != 'video' and image_format in ('jpg', 'jpeg', 'png', 'webp'):
                ext = '.' + ('jpg' if image_format == 'jpeg' else image_format)
            request_options = {'headers': item_headers, 'timeout': InstagramDownloaderApp.REQUEST_TIMEOUT, 'stream': True}
            if proxy: request_options['proxies'] = {'http': proxy, 'https': proxy}
            with requests.get(url, **request_options) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get('Content-Type', '')
                if isinstance(content_type, str):
                    mime = content_type.split(';', 1)[0].lower()
                    if mime.startswith('text/'): raise ValueError('服务器未返回媒体文件，请重新提取链接')
                    if media_type != 'video':
                        ext = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}.get(mime, ext)
                out_path = os.path.join(save_dir, f"{prefix}_{idx+1}{ext}")
                partial_path = out_path + '.part'
                with open(partial_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=256*1024):
                        if chunk: f.write(chunk)
                os.replace(partial_path, out_path)
                if ext == ".webp":
                    try:
                        png_path = out_path.replace(".webp", ".png")
                        with Image.open(out_path) as img:
                            img.save(png_path, "PNG")
                        os.remove(out_path)
                    except Exception:
                        pass
                return True, idx
        except Exception as e:
            logger.error(f"下载失败 {url}: {e}")
            if partial_path and os.path.isfile(partial_path): os.remove(partial_path)
        return False, idx

    completed = 0
    succeeded = 0
    total = len(media_list)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_download_single, item) for item in enumerate(media_list)]
        for future in as_completed(futures):
            if future.result()[0]: succeeded += 1
            completed += 1
            if progress_callback:
                progress_callback(completed, total)
    return succeeded, total


# ---------- 通用：等比例缩放 + 居中粘贴 ----------
def _get_pil_font(size):
    """获取跨 Windows PIL 字体，按优先级尝试。
    打包后其他电脑可能没有中文语言包，不依赖 msyh。"""
    candidates = [
        "segoeui.ttf",   # Win10+ 所有语言版本均有，CJK 支持较好
        "arial.ttf",     # 所有 Windows 均有，CJK 字形可能缺失但不崩溃
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _scale_and_paste(source_img, target_size=(120, 150), bg_color=(0, 0, 0, 0)):
    """将图片等比例缩放后居中绘制在指定尺寸的画布上，返回 RGBA 图像"""
    orig_w, orig_h = source_img.size
    target_w, target_h = target_size
    scale = min(target_w / orig_w, target_h / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    scaled = source_img.resize((new_w, new_h), Image.Resampling.LANCZOS).convert("RGBA")
    canvas = Image.new("RGBA", target_size, bg_color)
    paste_x = (target_w - new_w) // 2
    paste_y = (target_h - new_h) // 2
    canvas.paste(scaled, (paste_x, paste_y))
    return canvas


# ---------- PIL 图像卡片渲染 ----------
def create_card_thumbnail(pil_img, resolution_str="1080 × 1350", is_selected=True, target_size=(120, 150)):
    # 等比例缩放 + 居中粘贴到透明画布
    canvas = _scale_and_paste(pil_img, target_size)
    draw = ImageDraw.Draw(canvas)
    w, h = target_size

    # 左下角分辨率标签
    pill_w, pill_h = 68, 18
    draw.rounded_rectangle([6, h - 24, 6 + pill_w, h - 24 + pill_h], radius=4, fill=(0, 0, 0, 170))
    font = _get_pil_font(9)
    draw.text((10, h - 21), resolution_str, fill=(255, 255, 255, 240), font=font)

    # 右上角选中徽章
    if is_selected:
        badge_x, badge_y = w - 22, 6
        draw.ellipse([badge_x, badge_y, badge_x + 16, badge_y + 16], fill=(244, 84, 164, 255))
        draw.line([badge_x + 4, badge_y + 8, badge_x + 7, badge_y + 11], fill=(255, 255, 255), width=2)
        draw.line([badge_x + 7, badge_y + 11, badge_x + 12, badge_y + 5], fill=(255, 255, 255), width=2)

    return canvas


def _make_video_placeholder_card(res_str, is_selected=True, target_size=(120, 150), media_type='video'):
    """生成视频占位图（灰色背景 + 播放三角 + 标签 + 徽章）"""
    w, h = target_size
    colors = COLOR_SCHEMES[ctk.get_appearance_mode()]
    card = Image.new("RGBA", target_size, colors['bg_input'] if media_type == 'image' else (37, 34, 40, 255))
    draw = ImageDraw.Draw(card)
    # 居中播放三角，大小随卡片缩放
    tri_size = max(4, min(w, h) // 6)
    cx, cy = w // 2, h // 2
    triangle = [(cx - tri_size, cy - tri_size), (cx - tri_size, cy + tri_size), (cx + tri_size, cy)]
    if media_type == 'video':
        draw.polygon(triangle, fill=(7, 186, 238, 255))
    else:
        draw.rounded_rectangle((cx-2*tri_size, cy-2*tri_size, cx+2*tri_size, cy+tri_size),
                               radius=3, outline=(244,84,164,255), width=2)
        draw.line((cx-2*tri_size, cy, cx-tri_size, cy-tri_size, cx+tri_size, cy+tri_size,
                   cx+2*tri_size, cy), fill=(244,84,164,255), width=2)

    # 左下角标签
    pill_w, pill_h = min(w - 12, int(w * 0.6)), max(12, int(h * 0.12))
    font_size = max(7, int(min(w, h) * 0.07))
    draw.rounded_rectangle([6, h - pill_h - 6, 6 + pill_w, h - 6], radius=4, fill=(0, 0, 0, 170))
    font = _get_pil_font(font_size)
    display_text = res_str
    if media_type == 'image':
        try: font = ImageFont.truetype('msyh.ttc', font_size)
        except OSError: display_text = 'Loading...' if '加载' in res_str else 'No preview'
    draw.text((10, h - pill_h - 3), display_text, fill=(255, 255, 255, 240), font=font)

    # 选中徽章
    badge_size = max(10, int(min(w, h) * 0.13))
    if is_selected:
        badge_x, badge_y = w - badge_size - 6, 6
        draw.ellipse([badge_x, badge_y, badge_x + badge_size, badge_y + badge_size], fill=(244, 84, 164, 255))
        draw.line([badge_x + badge_size * 0.25, badge_y + badge_size * 0.5,
                    badge_x + badge_size * 0.45, badge_y + badge_size * 0.68], fill=(255, 255, 255), width=2)
        draw.line([badge_x + badge_size * 0.45, badge_y + badge_size * 0.68,
                    badge_x + badge_size * 0.75, badge_y + badge_size * 0.3], fill=(255, 255, 255), width=2)
    return card


# ---------- 主应用 ----------
class YouTubeDownloader:
    """YouTube 视频下载器 - 业务逻辑层"""
    _cookie_lock = threading.Lock()

    def __init__(self, ffmpeg_path: str = None, cookie_file=None):
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
        self.cookie_file = cookie_file

    @staticmethod
    def _find_ffmpeg():
        """查找 ffmpeg 可执行文件路径（优先项目自带完整版）"""
        # 1) 项目内 browsers/ffmpeg/（源码或打包后 _internal/browsers/ffmpeg/）
        for probe in [_get_base_dir(), _get_internal_dir()]:
            bundled = os.path.join(probe, "browsers", "ffmpeg", "ffmpeg.exe")
            if os.path.isfile(bundled):
                return bundled
        # 2) 系统 PATH
        path = shutil.which("ffmpeg")
        if path:
            return path
        # 3) Program Files 兜底
        for base in [os.environ.get("ProgramFiles", "C:\\Program Files"),
                     os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")]:
            try:
                for root, dirs, files in os.walk(base):
                    if "ffmpeg" in root.lower():
                        for f in files:
                            if f.lower() == "ffmpeg.exe":
                                return os.path.join(root, f)
            except Exception:
                continue
        return None

    def _ensure_yt_cookies(self):
        with self._cookie_lock:
            return self._export_yt_cookies()

    def _export_yt_cookies(self):
        """从 cookies.json 提取 YouTube/Google 域 cookie，转为 Netscape 格式供 yt-dlp 使用。

        返回 cookie 文件路径；无 YouTube 相关 cookie 或转换失败时返回 None（不启用）。
        """
        src = os.path.join(_get_base_dir(), "cookies.json")
        dst = os.path.join(_get_base_dir(), "youtube_cookies.txt")
        if not os.path.isfile(src):
            return dst if os.path.isfile(dst) else None
        # 源 cookie 未更新时复用已生成的 cookie 文件
        if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            return dst
        try:
            with open(src, "r", encoding="utf-8") as f:
                cookies = json.load(f)
        except Exception as e:
            logger.warning(f"YouTube cookie 读取失败: {e}")
            return None
        lines = ["# Netscape HTTP Cookie File"]
        count = 0
        for c in cookies:
            domain = (c.get("domain") or "").strip()
            if not ("youtube.com" in domain or "google.com" in domain):
                continue
            name = (c.get("name") or "").strip()
            value = c.get("value") or ""
            if not name or "\t" in value or "\n" in value:
                continue
            path = c.get("path") or "/"
            secure = "TRUE" if c.get("secure") else "FALSE"
            try:
                expires = int(float(c.get("expires") or 0))
            except (TypeError, ValueError):
                expires = 0
            include_sub = "TRUE" if domain.startswith(".") else "FALSE"
            lines.append(f"{domain}\t{include_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
            count += 1
        if count == 0:
            return None
        try:
            with open(dst + '.tmp', "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(dst + '.tmp', dst)
            logger.info(f"已生成 YouTube cookie 文件: {dst} ({count} 个 cookie)")
        except Exception as e:
            logger.warning(f"YouTube cookie 写入失败: {e}")
            return None
        return dst

    # ── 编码/容器互斥联动 ──

    def download(self, url: str, save_dir: str, fmt_key: str,
                 codec_choice: str, container_choice: str = "mkv",
                 clip_enabled: bool = False, clip_start: str = "",
                 clip_end: str = "", subtitle_enabled: bool = False,
                 progress_callback=None, info_callback=None, cancel_event=None) -> bool:
        """下载 YouTube 视频，返回文件路径。进度和状态通过回调传递。"""

        def _report(msg):
            if cancel_event and cancel_event.is_set(): raise TaskCancelled()
            if progress_callback:
                progress_callback(msg)

        def _report_pct(pct: float):
            if cancel_event and cancel_event.is_set(): raise TaskCancelled()
            if progress_callback:
                progress_callback(float(pct))

        def _report_info(text: str):
            if info_callback:
                info_callback(text)

        import yt_dlp
        import yt_dlp.utils

        clip_workspace = None
        try:
            logger.info(f"YouTube 下载开始: {url} (格式={fmt_key}, 编码={codec_choice}, 目录={save_dir})")
            _report("解析视频信息...")

            ffmpeg_path = self.ffmpeg_path
            has_ffmpeg = ffmpeg_path is not None
            os.makedirs(save_dir, exist_ok=True)
            if clip_enabled:
                if not has_ffmpeg: raise ValueError('下载片段需要 ffmpeg，请安装后重试')
                clip_workspace = tempfile.TemporaryDirectory(prefix='.harmony-clip-', dir=save_dir)
            output_dir = clip_workspace.name if clip_workspace else save_dir
            runtime_opts = {}
            nodes = glob.glob(os.path.join(BASE_DIR, 'runtime', 'node', '*', 'node.exe'))
            if nodes: runtime_opts['js_runtimes'] = {'node': {'path': nodes[0]}}
            yt_cookie_file = self.cookie_file if self.cookie_file is not None else self._ensure_yt_cookies()
            if yt_cookie_file: runtime_opts['cookiefile'] = yt_cookie_file

            # 编码筛选映射（匹配 YouTube 实际 codec 前缀）
            codec_map = {
                "H.264": "avc1",
                "H.265 (HEVC)": "hvc1",
                "AV1": "av01",
                "VP9": "vp0",
            }
            # 反向映射：codec 前缀 -> 编码显示名（用于探测阶段）
            codec_reverse = {
                "avc1": "H.264",
                "hvc1": "H.265",
                "av01": "AV1",
                "vp09": "VP9",
                "vp9": "VP9",
                "vp0": "VP9",
            }
            codec_filter = codec_map.get(codec_choice)  # None for "不限制"

            # ---------- 编码探测（指定编码时先探测可用编码）----------
            if codec_filter:
                _report("探测可用编码...")
                probe_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True,
                    'no_check_certificate': True,
                }
                probe_opts.update(runtime_opts)
                try:
                    with yt_dlp.YoutubeDL(probe_opts) as probe_ydl:
                        probe_info = probe_ydl.extract_info(url, download=False)
                except Exception as e:
                    logger.exception(f"编码探测网络请求失败: {e}")
                    _report(f"探测失败: 网络请求超时或异常")
                    return

                available_codecs = set()
                for fmt in probe_info.get('formats', []):
                    vcodec = fmt.get('vcodec', '')
                    if vcodec and vcodec != 'none':
                        for prefix, display in codec_reverse.items():
                            if vcodec.startswith(prefix):
                                available_codecs.add(display)
                                break

                logger.info(f"编码探测结果: 可用编码={sorted(available_codecs)}, 请求编码={codec_choice}")

                if codec_choice not in available_codecs:
                    available_str = ", ".join(sorted(available_codecs))
                    msg = f"该视频不提供 {codec_choice} 编码"
                    logger.warning(f"YouTube 编码不可用: {msg}，可用：{available_str}")
                    _report(msg)
                    _report_info(f"编码 {codec_choice} 不可用\n可用编码：{available_str}")
                    return ""

                _report(f"编码 {codec_choice} 可用，开始下载...")

            # 构建 ydl_opts 基础配置
            ydl_opts = {
                'outtmpl': os.path.join(output_dir, '%(title).150s [%(extractor_key)s_%(id)s]_%(format_id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'no_check_certificate': True,
            }
            ydl_opts.update(runtime_opts)
            ydl_opts['socket_timeout'] = 30

            # 配置 JS 运行时（node），新版 yt-dlp 需要它执行 botguard/po_token 才能获取 YouTube 流
            node_candidates = glob.glob(os.path.join(BASE_DIR, "runtime", "node", "*", "node.exe"))
            if node_candidates and os.path.isfile(node_candidates[0]):
                ydl_opts['js_runtimes'] = {'node': {'path': node_candidates[0]}}
                logger.info(f"YouTube 下载启用 JS 运行时: {node_candidates[0]}")

            # YouTube 登录 cookie（降低被风控/403 概率）
            yt_cookie_file = runtime_opts.get('cookiefile')
            if yt_cookie_file:
                ydl_opts['cookiefile'] = yt_cookie_file
                logger.info(f"YouTube 下载启用 cookie: {yt_cookie_file}")
            else:
                logger.warning("cookies.json 中未找到 YouTube/Google 域 cookie，YouTube 下载将不带登录态")

            if has_ffmpeg:
                ydl_opts['ffmpeg_location'] = ffmpeg_path

            # 分辨率映射
            height_map = {
                "4K": 2160,
                "2K": 1440,
                "1080p": 1080,
                "720p": 720,
                "480p": 480,
                "360p": 360,
            }

            if fmt_key == 'audio':
                ydl_opts['format'] = 'bestaudio/best'
                if has_ffmpeg:
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
            elif codec_filter:
                # ────── 遍历格式列表精确匹配 format_id ──────
                target_height = 99999 if fmt_key == 'best' else height_map.get(fmt_key, 99999)

                # 分类收集格式：视频流 / 音频流 / 混合流（无 ffmpeg 备用）
                video_streams = []   # (fmt_dict, height, tbr, ext)
                audio_streams = []   # (fmt_dict, tbr, ext)
                mixed_streams = []   # (fmt_dict, height, tbr) — 音视频合一的 mp4 流

                for fmt in probe_info['formats']:
                    vcodec = (fmt.get('vcodec') or '').strip()
                    acodec = (fmt.get('acodec') or '').strip()
                    ext = (fmt.get('ext') or '').strip()

                    vcodec_match = vcodec.startswith(codec_filter) or (codec_filter == 'vp0' and vcodec == 'vp9')
                    if vcodec and vcodec != 'none' and vcodec_match:
                        h = fmt.get('height') or 0
                        if h > target_height:
                            continue
                        tbr = fmt.get('tbr') or 0
                        if acodec and acodec != 'none':
                            mixed_streams.append((fmt, h, tbr))
                        else:
                            video_streams.append((fmt, h, tbr, ext))
                    elif (not vcodec or vcodec == 'none') and acodec and acodec != 'none':
                        tbr = fmt.get('tbr') or 0
                        audio_streams.append((fmt, tbr, ext))

                # 排序：视频流 height↓ → tbr↓ → webm 优先于 mp4
                video_streams.sort(key=lambda x: (-x[1], -x[2], 0 if x[3] == 'webm' else 1))
                audio_streams.sort(key=lambda x: -x[1])
                mixed_streams.sort(key=lambda x: (-x[1], -x[2]))

                if not video_streams:
                    msg = f"该视频的 {codec_choice} 编码没有匹配的视频流（分辨率 ≤ {target_height}p）"
                    logger.warning(msg)
                    _report(msg)
                    return

                best_video_id = video_streams[0][0]['format_id']
                video_ext = video_streams[0][3]  # webm or mp4

                # 音频流按容器兼容性重排序：同容器优先 + tbr 降序
                # webm 视频优先 webm/opus 音频(249/250/251)；mp4 视频优先 m4a 音频
                # 匹配不到同容器时降级用其他格式，后续 merge_output_format 设为 mkv
                if audio_streams:
                    audio_streams.sort(key=lambda x: (0 if x[2] == video_ext else 1, -x[1]))
                best_audio_id = audio_streams[0][0]['format_id'] if audio_streams else None
                audio_ext = audio_streams[0][2] if best_audio_id else None

                logger.info(
                    f"精确匹配: video_id={best_video_id} "
                    f"(height={video_streams[0][1]}, tbr={video_streams[0][2]}, ext={video_ext}), "
                    f"audio_id={best_audio_id}, audio_ext={audio_ext}"
                )

                if has_ffmpeg:
                    if best_audio_id:
                        ydl_opts['format'] = f'{best_video_id}+{best_audio_id}'
                    else:
                        ydl_opts['format'] = best_video_id
                    ydl_opts['merge_output_format'] = container_choice
                else:
                    # 无 ffmpeg：优先含音频的 mp4 混合流
                    if mixed_streams:
                        ydl_opts['format'] = mixed_streams[0][0]['format_id']
                        logger.info(f"无 ffmpeg，使用混合流: {mixed_streams[0][0]['format_id']}")
                    else:
                        # 降级：选 mp4 封装的纯视频流
                        mp4_videos = [v for v in video_streams if v[3] == 'mp4']
                        ydl_opts['format'] = mp4_videos[0][0]['format_id'] if mp4_videos else best_video_id
                        logger.info(f"无 ffmpeg 且无混合流，降级为纯视频流: {ydl_opts['format']}")
            elif fmt_key == 'best':
                if has_ffmpeg:
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                    ydl_opts['merge_output_format'] = container_choice
                else:
                    ydl_opts['format'] = 'best[ext=mp4]/best'
            else:
                height = height_map.get(fmt_key, int(fmt_key.replace('p', '')))
                if has_ffmpeg:
                    ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'
                    ydl_opts['merge_output_format'] = container_choice
                else:
                    ydl_opts['format'] = f'best[height<={height}][ext=mp4]/best[height<={height}]/best'

            # --- 嵌入封面缩略图（有 ffmpeg 时，webm 除外） ---
            if has_ffmpeg:
                if ydl_opts.get('merge_output_format') != 'webm':
                    ydl_opts['writethumbnail'] = True
                    if 'postprocessors' not in ydl_opts:
                        ydl_opts['postprocessors'] = []
                    ydl_opts['postprocessors'].append({'key': 'EmbedThumbnail'})

            # --- 下载字幕 ---
            if subtitle_enabled:
                ydl_opts['writesubtitles'] = True
                ydl_opts['writeautomaticsub'] = False
                ydl_opts['subtitleslangs'] = ['en', 'zh-Hans', 'zh-Hant']
                ydl_opts['subtitlesformat'] = 'srt'
                _report("字幕下载已启用")

            # 进度条以视频流为准：bestvideo+bestaudio 时视频流占绝对主导（如 4K 视频
            # 几百 MB vs 音频几 MB），直接用视频流进度即可，音频流误差可忽略不计。
            # DASH fragment 流（如 4K 60fps）用 fragment_index/fragment_count 作为进度，
            # 完全不受 total_bytes_estimate 估算波动影响；yt-dlp 首帧会把 total 抬到
            # downloaded 导致比例=100%，必须规避。渐进式下载用真实 total_bytes 比例。
            # 视频流进度封顶 99%，音频下载与 ffmpeg 合并阶段给出文字提示，
            # 真正 100% 由主流程在 ydl.download 全部返回后统一上报。
            # 纯音频模式（无视频流）进度条保持不动，下载完成由主流程统一报 100%。
            self._yt_video_total = 0
            self._yt_last_pct = 0.0
            self._yt_seen_video = False
            self._yt_audio_hint = False

            def _hook(d):
                if cancel_event and cancel_event.is_set(): raise TaskCancelled()
                details = d.get('info_dict') or {}
                if details.get('title'):
                    _report_info(f"标题: {details['title']}")
                info = d.get('info_dict') or {}
                status = d.get('status')
                is_video = bool(info.get('vcodec') and info.get('vcodec') != 'none')
                is_audio = bool(info.get('acodec') and info.get('acodec') != 'none' and not is_video)

                if status == 'finished':
                    if is_video and self._yt_seen_video:
                        frag_idx = d.get('fragment_index')
                        frag_cnt = d.get('fragment_count')
                        if frag_cnt and frag_idx is not None and frag_cnt > 0 and frag_idx < frag_cnt:
                            # DASH 流：只是单个 fragment 完成，进度由 fragment_index 推进
                            return
                        # 视频流整体下载完成，后面还有音频下载与 ffmpeg 合并
                        _report("视频流下载完成，正在处理音频与合并...")
                    elif is_audio and self._yt_seen_video:
                        frag_idx = d.get('fragment_index')
                        frag_cnt = d.get('fragment_count')
                        if frag_cnt and frag_idx is not None and frag_cnt > 0 and frag_idx < frag_cnt:
                            return
                        _report("正在合并视频与音频...")
                    return

                if status != 'downloading':
                    return

                if not is_video:
                    # 非视频流（音频等）不参与进度
                    if not self._yt_audio_hint:
                        self._yt_audio_hint = True
                        if not self._yt_seen_video:
                            _report("下载中(音频)...")
                        else:
                            _report("正在下载音频...")
                    return

                self._yt_seen_video = True
                speed = d.get('_speed_str', '')

                frag_idx = d.get('fragment_index')
                frag_cnt = d.get('fragment_count')
                if frag_cnt and frag_idx is not None and frag_cnt > 0:
                    # DASH fragment 流：以已完成 fragment 数/总数为进度，
                    # 完全不受 total_bytes_estimate 估算波动影响
                    pct = frag_idx / frag_cnt
                else:
                    # 渐进式下载：total_bytes 为真实值
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    if total <= 0 or downloaded <= 0:
                        return
                    if not d.get('total_bytes') and downloaded >= total:
                        # 仅估算值且已达 100%：yt-dlp 首帧会把 total 抬到 downloaded，
                        # 比例=1 不可信，忽略本次回调等更可信的数据
                        return
                    pct = downloaded / total

                # 单调保护：进度只前进不回退
                if pct < self._yt_last_pct:
                    pct = self._yt_last_pct
                else:
                    self._yt_last_pct = pct
                # 封顶 99%：真实 100% 由主流程在 ydl.download 全部返回后统一上报
                pct = min(pct, 0.99)
                _report_pct(pct)
                _report(f"下载中... {pct*100:.0f}% {speed}")

            ydl_opts['progress_hooks'] = [_hook]
            if cancel_event:
                def check_postprocessor(_):
                    if cancel_event.is_set(): raise TaskCancelled()
                ydl_opts['postprocessor_hooks'] = [check_postprocessor]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', '未知')
                duration = info.get('duration') or 0
                mins, secs = divmod(duration, 60)

                _report_info(f"标题: {title}\n时长: {mins}分{secs}秒")
                logger.info(f"YouTube 视频信息解析成功: {title} (时长={mins}分{secs}秒)")


            # 片段模式：下载完成后用 ffmpeg 裁剪
            if clip_enabled and clip_start and clip_end:
                if not has_ffmpeg:
                    _report("下载片段需要 ffmpeg，请安装后重试")
                    return
                _report("正在裁剪片段...")
                _report_pct(0.5)
                candidates = [info.get('filepath'), ydl.prepare_filename(info)]
                candidates += [item.get('filepath') for item in info.get('requested_downloads', [])]
                outfile = next((path for path in candidates if path and os.path.isfile(path)), None)
                if not outfile: raise ValueError('未找到下载后的片段源文件')
                clip_name = Path(outfile).stem + '_clip_' + clip_start.replace(':', '-') + '_' + clip_end.replace(':', '-') + Path(outfile).suffix
                clip_outfile = os.path.join(save_dir, clip_name)
                logger.info(f"ffmpeg 裁剪: {clip_start} - {clip_end}, 输入={outfile}, 输出={clip_outfile}")

                # 先尝试 -c copy（无损裁剪，快速）
                cmd = [
                    ffmpeg_path, '-ss', clip_start, '-to', clip_end,
                    '-i', outfile, '-c', 'copy', '-avoid_negative_ts', 'make_zero',
                    clip_outfile, '-y'
                ]
                result = run_media_process(cmd, cancel_event, timeout=300)
                if result.returncode != 0:
                    logger.warning(f"ffmpeg -c copy 裁剪失败，回退到重新编码: {result.stderr[:200]}")
                    # 回退到重新编码（慢但精确）
                    cmd = [
                        ffmpeg_path, '-ss', clip_start, '-to', clip_end,
                        '-i', outfile, '-c:v', 'libx264', '-c:a', 'aac',
                        clip_outfile, '-y'
                    ]
                    result = run_media_process(cmd, cancel_event, timeout=600)
                    if result.returncode != 0:
                        raise RuntimeError(f"ffmpeg 裁剪失败: {result.stderr[:200]}")

                # 裁剪成功，删除原文件保留 clip
                os.remove(outfile)
                logger.info(f"裁剪完成，原文件已删除: {outfile}")
                _report(f"片段下载完成: {title}")
            else:
                _report(f"下载完成: {title}")
            _report_pct(1)
            logger.info(f"YouTube {'片段' if clip_enabled else ''}下载成功: {title} -> {save_dir}")
            return True

        except TaskCancelled:
            raise
        except yt_dlp.utils.DownloadError as e:
            if cancel_event and cancel_event.is_set(): raise TaskCancelled()
            err = str(e)
            logger.error(f"YouTube 下载失败 [{url}]: {err}")
            # 字幕 429 限流：自动回退无字幕重试
            if subtitle_enabled and ('429' in err or 'subtitles' in err.lower()):
                logger.info("字幕下载被限流，回退无字幕重试")
                _report("字幕受限，回退无字幕下载...")
                return self.download(url, save_dir, fmt_key, codec_choice,
                                     container_choice, clip_enabled,
                                     clip_start, clip_end,
                                     subtitle_enabled=False,
                                     progress_callback=progress_callback,
                                     info_callback=info_callback, cancel_event=cancel_event)
            _report(f"下载失败: {err[:100]}")
        except Exception as e:
            err = str(e)
            logger.exception(f"YouTube 下载异常 [{url}]: {err}")
            _report(f"错误: {err[:100]}")
        finally:
            if clip_workspace: clip_workspace.cleanup()



from harmony_ui import HarmonyUI


class InstagramDownloaderApp(HarmonyUI, ctk.CTk):
    # ────────── 类级常量 ──────────
    # 窗口常量
    WINDOW_WIDTH = 1280
    WINDOW_HEIGHT = 940
    MIN_WIDTH = 1120
    MIN_HEIGHT = 740

    # UI 常量
    PAD_X = 25
    PAD_Y = 20
    CORNER_RADIUS = 12
    CARD_WIDTH = 120
    CARD_HEIGHT = 150
    MAX_HISTORY = 10

    # 网络常量
    REQUEST_TIMEOUT = 60
    PROGRESS_UPDATE_INTERVAL = 150

    COLOR_SCHEMES = COLOR_SCHEMES

    def _get_colors(self):
        return self.COLOR_SCHEMES.get(ctk.get_appearance_mode(), self.COLOR_SCHEMES["Light"])

    def _apply_colors(self):
        self.c = self._get_colors()
        self.configure(fg_color=self.c["bg_root"])

    def __init__(self):
        # Set this before Tk creates the native window so source runs are not
        # grouped under pythonw.exe in the Windows taskbar.
        set_app_user_model_id()
        super().__init__()
        self._closing = False
        self.ui_font = select_font(self)
        self.title(f"Harmony {__version__}")
        self.geometry(f"{min(self.WINDOW_WIDTH, int(self.winfo_screenwidth() / self._get_window_scaling()) - 60)}x{min(self.WINDOW_HEIGHT, int(self.winfo_screenheight() / self._get_window_scaling()) - 80)}")
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)

        # 设置窗口图标
        self._set_window_icon()

        self._apply_colors()

        # 状态变量
        self.url_var = ctk.StringVar()
        saved_dir = load_config().get("save_dir", "")
        default_dir = saved_dir if saved_dir else os.path.join(os.path.expanduser("~"), "Pictures", "Instagram")
        self.dir_var = ctk.StringVar(value=default_dir)
        self.proxy_var = ctk.StringVar()
        self.image_data = []  # [(url, width, height, raw_pil_img)]
        self.selected_indices = set()
        self.card_buttons = []
        self.running = False
        self._thumbnail_generation = 0
        self._thumbnail_loading = False
        self.history_expanded = False
        self._history_popup = None
        self._on_configure_id = None
        self.card_w = self.CARD_WIDTH
        self.card_h = self.CARD_HEIGHT
        self.col_count = 6
        self._resize_after_id = None

        # ── 业务逻辑层实例 ──
        cookies_path = os.path.join(BASE_DIR, "cookies.json")
        ig_proxy = self.proxy_var.get().strip() or None
        self.ig_extractor = InstagramExtractor(cookies_path, ig_proxy)
        self.x_extractor = XMediaExtractor(cookies_path)
        self.tiktok_extractor = TikTokMediaExtractor(cookies_path)
        self.yt_downloader = YouTubeDownloader()
        self.video_queue = VideoTaskQueue(self._run_video_task, concurrency=3)
        self._yt_queue_poll_id = None

        # YouTube 状态
        self.yt_url_var = ctk.StringVar()
        self.yt_concurrency_var = ctk.StringVar(value='3')
        yt_saved_dir = load_config().get("yt_save_dir", "")
        yt_default_dir = yt_saved_dir if yt_saved_dir else os.path.join(os.path.expanduser("~"), "Downloads", "YouTube")
        self.yt_dir_var = ctk.StringVar(value=yt_default_dir)
        self.yt_fmt_var = ctk.StringVar(value="最佳画质 (自动)")
        self.yt_codec_var = ctk.StringVar(value="不限制")
        self.yt_container_var = ctk.StringVar(value="mkv")
        self._suppress_trace = False
        self.yt_running = False
        self.yt_clip_enabled = tk.BooleanVar(value=False)
        self.yt_clip_start = ctk.StringVar(value="0:00")
        self.yt_clip_end = ctk.StringVar(value="5:00")
        self.yt_subtitle_enabled = tk.BooleanVar(value=False)

        self._build_ui()
        self._render_history()
        self._restore_was_unmapped=False
        self._restore_refresh_pending=None
        self._restore_buffer=install_restore_buffer(self)
        self.bind("<Unmap>",self._on_window_unmapped,add="+")
        self.bind("<Map>",self._on_window_mapped,add="+")
        self._poll_video_queue()
        # 缺少 cookies.json 时自动弹出引导
        cookies_path = os.path.join(BASE_DIR, "cookies.json")
        if not os.path.exists(cookies_path):
            self.after(500, self._show_cookie_guide)

    # ---------- 窗口图标 ----------
    def _set_window_icon(self, window=None):
        """Set a Tk fallback plus DPI-correct native Windows icon handles."""
        target = self if window is None else window
        icon_ico = None
        if getattr(sys, 'frozen', False):
            internal_dir = _get_internal_dir()
            frozen_icon = os.path.join(internal_dir, "icon.ico")
            if os.path.exists(frozen_icon):
                icon_ico = frozen_icon
        if icon_ico is None:
            for _icon_dir in (os.path.dirname(os.path.abspath(__file__)), BASE_DIR):
                candidate = os.path.join(_icon_dir, "icon.ico")
                if os.path.exists(candidate):
                    icon_ico = candidate
                    break
        if icon_ico:
            try:
                if target is self:
                    target.iconbitmap(default=icon_ico)
                else:
                    target.iconbitmap(icon_ico)
            except Exception:
                pass
            if sys.platform == "win32":
                def apply_native_icons():
                    try:
                        target._windows_icon_state = apply_window_icons(target, icon_ico)
                        apply_titlebar_theme(target, ctk.get_appearance_mode()=="Dark")
                    except (OSError, ctypes.ArgumentError) as error:
                        logger.warning("Windows 图标设置失败，使用 Tk 回退图标: %s", error)
                target.after_idle(apply_native_icons)

    def _build_ui(self):
        self._apply_colors()
        self._build_sidebar()
        self._build_main()

    def _on_window_unmapped(self,event):
        if event.widget is self:
            self._restore_was_unmapped=True

    def _on_window_mapped(self,event):
        if event.widget is not self:return
        # A hidden Windows launch can already have a retained frame before its
        # first Map event. Release it through the same path as a normal restore.
        has_frame=getattr(getattr(self,"_restore_buffer",None),"bitmap",None) is not None
        if not self._restore_was_unmapped and not has_frame:return
        self._restore_was_unmapped=False
        if self._restore_refresh_pending is None:
            self._restore_refresh_pending=self.after_idle(self._refresh_restored_window)

    def _refresh_restored_window(self):
        self._restore_refresh_pending=None
        if self.winfo_exists() and self.state() not in ("iconic","withdrawn"):
            if self._restore_buffer is not None:
                self._restore_buffer.finish_restore()
            else:
                refresh_restored_window(self)

    def iconify(self):
        buffer=getattr(self,"_restore_buffer",None)
        if buffer is not None:
            buffer.capture()
        return super().iconify()

    def destroy(self):
        self._closing = True
        if hasattr(self, 'video_queue'): self.video_queue.close()
        if getattr(self, '_yt_queue_poll_id', None) is not None:
            self.after_cancel(self._yt_queue_poll_id)
            self._yt_queue_poll_id = None
        buffer=getattr(self,"_restore_buffer",None)
        if buffer is not None:
            buffer.close()
        return super().destroy()

    # ========== YouTube 功能 ==========

    def _yt_browse_dir(self):
        dir_selected = ctk.filedialog.askdirectory()
        if dir_selected:
            self.yt_dir_var.set(dir_selected)
            save_config("yt_save_dir", dir_selected)

    def _yt_download(self):
        self._enqueue_video_text(self.yt_url_var.get())

    def _yt_batch_download(self):
        if self._enqueue_video_text(self.yt_batch_entry.get('1.0', 'end')):
            self.yt_batch_entry.delete('1.0', 'end')

    def _enqueue_video_text(self, text):
        try:
            urls = parse_video_links(text)
            save_dir = self.yt_dir_var.get().strip()
            if not save_dir: raise ValueError('请先设置保存目录')
            save_dir = os.path.abspath(os.path.expanduser(save_dir))
            if self.yt_clip_enabled.get():
                validate_clip(self.yt_clip_start.get(), self.yt_clip_end.get())
                if not self.yt_downloader.ffmpeg_path: raise ValueError('下载片段需要 ffmpeg，请安装后重试')
            fmt_map = {'最佳画质 (自动)': 'best', '仅音频 (MP3)': 'audio'}
            choice = self.yt_fmt_var.get()
            cookie_path = self.yt_downloader._ensure_yt_cookies()
            options = VideoOptions(save_dir, fmt_map.get(choice, choice), self.yt_codec_var.get(),
                self.yt_container_var.get(), self.yt_clip_enabled.get(),
                self.yt_clip_start.get().strip(), self.yt_clip_end.get().strip(),
                self.yt_subtitle_enabled.get(), Path(cookie_path).read_bytes() if cookie_path else None)
            added, duplicates = self.video_queue.add(urls, options)
            self._render_video_queue(self.video_queue.snapshots())
            self.yt_batch_hint.configure(text=f'已加入 {len(added)} 个任务' + (f'，跳过 {duplicates} 个队列中的重复链接' if duplicates else ''))
            return bool(added)
        except (ValueError, OSError) as error:
            self.yt_status_label.configure(text=str(error), text_color=self.c['warning'])
            return False

    def _run_video_task(self, task, progress, info):
        # Every job owns its downloader, cookie copy and progress bookkeeping.
        with tempfile.TemporaryDirectory(prefix='harmony-video-') as folder:
            cookie_path = False
            if task.options.cookie_data:
                cookie_path = str(Path(folder) / 'cookies.txt')
                Path(cookie_path).write_bytes(task.options.cookie_data)
            downloader = YouTubeDownloader(self.yt_downloader.ffmpeg_path, cookie_file=cookie_path)
            o = task.options
            return downloader.download(task.url, o.save_dir, o.fmt_key, o.codec, o.container,
                                       o.clip, o.start, o.end, o.subtitles, progress, info,
                                       cancel_event=task.cancel)

    def _poll_video_queue(self):
        self._yt_queue_poll_id = None
        if self._closing: return
        tasks = self.video_queue.drain_changes()
        if tasks is not None: self._render_video_queue(tasks)
        self._yt_queue_poll_id = self.after(100, self._poll_video_queue)

    def _yt_set_concurrency(self, value):
        self.video_queue.set_concurrency(int(value))
        self._render_video_queue(self.video_queue.snapshots())

    def _yt_clear_finished(self):
        self.video_queue.clear_finished()
        self._render_video_queue(self.video_queue.snapshots())

    def _yt_cancel_task(self, task_id):
        self.video_queue.cancel_task(task_id)
        self._render_video_queue(self.video_queue.snapshots())

    def _yt_retry_task(self, task_id):
        self.video_queue.retry(task_id)
        self._render_video_queue(self.video_queue.snapshots())

    def _yt_open_task_dir(self, task_id):
        task = next((t for t in self.video_queue.snapshots() if t.id == task_id), None)
        if task and os.path.isdir(task.options.save_dir): os.startfile(task.options.save_dir)
        else: self.yt_status_label.configure(text='这个任务的保存目录已不存在',text_color=self.c['warning'])

    def _yt_download_reset(self):
        self._render_video_queue(self.video_queue.snapshots())


    def _open_save_dir(self):
        path = (self.yt_dir_var if self.active_platform == "YouTube" else self.dir_var).get().strip()
        if path and os.path.exists(path):
            os.startfile(path)
        else:
            (self.yt_status_label if self.active_platform == "YouTube" else self.status_label).configure(text="目录不存在，请先选择有效目录")

    def _toggle_theme(self):
        """切换外观；保持窗口不透明，避免 Windows 分层窗口恢复时闪黑。"""
        if self.running or self.yt_running or getattr(self, "yt_parsing", False):
            (self.yt_status_label if self.active_platform == "YouTube" else self.status_label).configure(text="任务进行中，请完成后切换外观")
            return
        draft = self.yt_batch_entry.get('1.0', 'end-1c')
        self._dismiss_history_popup()
        # Remove old controls first so CTk doesn't repaint an entire outgoing
        # page before we create the replacement with the new palette.
        self.sidebar.destroy()
        self.main_container.destroy()
        current = ctk.get_appearance_mode()
        ctk.set_appearance_mode("Dark" if current=="Light" else "Light")
        self._apply_colors()
        self._build_sidebar()
        self._build_main()
        self.yt_batch_entry.insert('1.0', draft)
        self._render_history()
        if self.image_data:
            self._render_thumbnails(is_relayout=True)
            self.download_btn.configure(state="normal" if self.selected_indices else "disabled")

    def browse_dir(self):
        dir_selected = ctk.filedialog.askdirectory()
        if dir_selected:
            self.dir_var.set(dir_selected)
            save_config("save_dir", dir_selected)

    def fetch_images(self):
        if self.running:
            return

        url = self.url_var.get().strip()
        try:
            link = parse_post_link(url)
        except ValueError as error:
            self.status_label.configure(text=str(error),text_color=self.c["warning"])
            return
        self.current_shortcode = link.cache_key
        self._fetch_url = url
        self.clear_all()

        self.running = True
        self.status_label.configure(text="正在提取…",text_color=self.c["accent_text"])
        self.progress_bar.configure(progress_color=self.c["accent"])
        self.progress_bar.set(0.2)
        self.download_btn.configure(state="disabled")

        proxy = self.proxy_var.get().strip() or None
        threading.Thread(target=self._fetch_worker, args=(url, proxy), daemon=True).start()

    def _fetch_worker(self, url, proxy):
        link = parse_post_link(url)
        try:
            def status_callback(msg):
                self.after(0, lambda: self.status_label.configure(text=msg))

            if link.platform == 'X':
                media_list = self.x_extractor.extract(url, status_callback, proxy=proxy)
            elif link.platform == 'TikTok':
                media_list = self.tiktok_extractor.extract(url, status_callback, proxy=proxy)
                self.after(0, self._fetch_complete, media_list, None, self.tiktok_extractor.resolved_link)
                return
            else:
                self.ig_extractor.proxy = proxy
                media_list = self.ig_extractor.extract(url, status_callback)
            self.after(0, self._fetch_complete, media_list, None)
        except Exception as e:
            self.after(0, self._fetch_complete, [], str(e))
        finally:
            if link.platform == 'Instagram': self.ig_extractor.close()

    def _fetch_complete(self, media_list, error, resolved_link=None):
        if error:
            self.running = False
            self.status_label.configure(text=f"错误: {error}",text_color=self.c["error"])
            return
        if not media_list:
            self.running = False
            self.status_label.configure(text="未提取到媒体内容",text_color=self.c["text_secondary"])
            return

        if resolved_link:
            self.current_shortcode = resolved_link.cache_key
            self._fetch_url = resolved_link.url
            self.url_var.set(resolved_link.url)

        img_count = sum(1 for m in media_list if m[1] == 'image')
        vid_count = sum(1 for m in media_list if m[1] == 'video')
        parts = []
        if img_count: parts.append(f"{img_count} 张图片")
        if vid_count: parts.append(f"{vid_count} 个视频")
        self.count_label.configure(text=f"已找到 {'，'.join(parts)}")
        self.status_label.configure(text="加载缩略图...")
        self.progress_bar.set(0.5)

        self._add_to_history(getattr(self, '_fetch_url', self.url_var.get().strip()), len(media_list))

        try: is_instagram = parse_post_link(getattr(self, '_fetch_url', self.url_var.get())).platform == 'Instagram'
        except ValueError: is_instagram = False
        if is_instagram:
            self._thumbnail_generation += 1
            self._thumbnail_loading = True
            self.image_data = [(url, 0, 0, None, kind) for url, kind, _ in media_list]
            self._render_thumbnails(previews_pending=True)
            proxy = self.proxy_var.get().strip() or None
            threading.Thread(target=self._load_instagram_previews,
                args=(media_list, self._thumbnail_generation, proxy), daemon=True).start()
            return
        threading.Thread(target=self._load_thumbnails_parallel, args=(media_list,), daemon=True).start()

    def _schedule_media_callback(self, callback, *args):
        if self._closing: return
        try: self.after(0, callback, *args)
        except (RuntimeError, tk.TclError): pass

    def _load_instagram_previews(self, media_list, generation, proxy):
        def fetch(item):
            index, (url, kind, thumb) = item
            if self._closing or generation != self._thumbnail_generation: return index, None
            resource = thumb if kind == 'video' else url
            try:
                if not resource: raise ValueError('No preview')
                options = {'headers': {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.instagram.com/'}, 'timeout': 10}
                if proxy: options['proxies'] = {'http': proxy, 'https': proxy}
                response = requests.get(resource, **options); response.raise_for_status()
                with Image.open(BytesIO(response.content)) as source:
                    image = source.copy()
                return index, (url, image.width, image.height, image, kind)
            except Exception:
                return index, (url, 0, 0, None, kind)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(fetch, item) for item in enumerate(media_list)]
            for completed, future in enumerate(as_completed(futures), 1):
                if self._closing or generation != self._thumbnail_generation:
                    for pending in futures: pending.cancel()
                    break
                index, item = future.result()
                if item is not None:
                    self._schedule_media_callback(self._apply_instagram_preview, index, item, generation, completed, len(media_list))
        self._schedule_media_callback(self._finish_instagram_previews, generation)

    def _apply_instagram_preview(self, index, item, generation, completed, total):
        if self._closing or generation != self._thumbnail_generation or index >= len(self.image_data): return
        if self.image_data[index][0] != item[0]: return
        self.image_data[index] = item
        self._refresh_media_card(index)
        if not self.running:
            self.status_label.configure(text=f'已提取 {total} 项，预览 {completed}/{total}')
            self.progress_bar.set(.5 + .5 * completed / total)

    def _finish_instagram_previews(self, generation):
        if self._closing or generation != self._thumbnail_generation: return
        self._thumbnail_loading = False
        for index, item in enumerate(self.image_data):
            if item[3] is None: self._refresh_media_card(index)
        if not self.running:
            missing = sum(item[3] is None for item in self.image_data)
            self.status_label.configure(text=f'完成；{missing} 项预览不可用，仍可下载' if missing else '完成',text_color=self.c['text_secondary' if missing else 'success_text'])
            self.progress_bar.set(1)
        self._save_cache(getattr(self, 'current_shortcode', 'post'))

    def _refresh_media_card(self, index):
        if index >= len(self.card_buttons): return
        _, width, height, image, kind = self.image_data[index]
        label = '视频' if kind == 'video' else f'{width} × {height}' if width and height else '预览加载中' if self._thumbnail_loading else '预览不可用'
        row = self.card_buttons[index]
        row['raw_pil'], row['res_str'] = image, label
        selected = index in self.selected_indices
        size = (self.card_w, self.card_h)
        card = create_card_thumbnail(image, resolution_str=label, is_selected=selected, target_size=size) if image is not None else _make_video_placeholder_card(label, selected, size, kind)
        row['btn'].configure(image=ctk.CTkImage(light_image=card, size=size))

    def _load_thumbnails_parallel(self, media_list):
        self.image_data = []
        total = len(media_list)

        def fetch_thumb(item):
            idx, (url, media_type, thumb_url) = item
            # 视频：用缩略图 URL；无缩略图时跳过（mp4 不能被 PIL 打开）
            if media_type == 'video':
                if thumb_url and urlsplit(thumb_url).scheme in ('http', 'https'):
                    fetch_url = thumb_url
                else:
                    return idx, None, None, None, url, media_type
            else:
                fetch_url = url
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                context_headers = self.tiktok_extractor.request_headers(fetch_url)
                headers.update(context_headers)
                request_options = {'headers': headers, 'timeout': 10}
                if context_headers and self.tiktok_extractor.proxy:
                    request_options['proxies'] = {'http': self.tiktok_extractor.proxy, 'https': self.tiktok_extractor.proxy}
                resp = requests.get(fetch_url, **request_options)
                resp.raise_for_status()
                pil_img = Image.open(BytesIO(resp.content))
                w, h = pil_img.size
                return idx, pil_img, w, h, url, media_type
            except Exception:
                return idx, None, None, None, url, media_type

        completed = 0
        slot = [None] * total
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(fetch_thumb, item) for item in enumerate(media_list)]
            for future in as_completed(futures):
                idx, pil_img, w, h, url, media_type = future.result()
                completed += 1
                slot[idx] = (url, w, h, pil_img, media_type)
                self.after(0, self.progress_bar.set, 0.5 + (completed / total) * 0.5)

        # 按原始顺序组装，保持与 Instagram 轮播顺序一致
        for item in slot:
            if item is None:
                continue
            url, w, h, pil_img, media_type = item
            if pil_img is not None:
                self.image_data.append((url, w, h, pil_img, media_type))
            elif media_type == 'video':
                self.image_data.append((url, 0, 0, None, media_type))

        self.after(0, self._render_thumbnails)

    def _calc_grid(self):
        grid_width = self.preview_grid.winfo_width()
        if grid_width < 50:
            # 初始未渲染时用窗口宽 - 侧边栏(260) - 外层 padx(25*2) - 安全余量(50)
            grid_width = self.winfo_width() - 360
        # 安全余量：CTkScrollableFrame 滚动条叠加在内容上方，需扣除
        grid_width = max(0, grid_width - 100)
        gap = 12
        col_count = max(1, (grid_width - gap) // (self.CARD_WIDTH + gap))
        card_w = self.CARD_WIDTH
        card_h = self.CARD_HEIGHT
        if col_count < 3:
            card_w = max(70, (grid_width - gap * (col_count + 1)) // col_count)
            card_h = int(card_w * 1.25)
        return col_count, card_w, card_h

    def _on_preview_resize(self, event):
        if not self.image_data:
            return
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(self.PROGRESS_UPDATE_INTERVAL, self._relayout_thumbnails)

    def _relayout_thumbnails(self):
        nc, nw, nh = self._calc_grid()
        if nc == self.col_count and nw == self.card_w:
            return
        self.col_count, self.card_w, self.card_h = nc, nw, nh
        self._render_thumbnails(is_relayout=True)

    def _render_thumbnails(self, is_relayout=False, previews_pending=False):
        c = self.c
        for widget in self.preview_grid.winfo_children():
            widget.destroy()
        self.card_buttons.clear()
        if not is_relayout:
            self.selected_indices = set(range(len(self.image_data)))

        self.col_count, self.card_w, self.card_h = self._calc_grid()
        if not self.image_data:
            self._show_media_empty()

        for idx, (url, w, h, raw_pil, media_type) in enumerate(self.image_data):
            row, col = idx // self.col_count, idx % self.col_count
            label = "视频" if media_type == 'video' else (f"{w} × {h}" if (w and h) else "预览加载中" if self._thumbnail_loading else "预览不可用")
            res_str = f"🎬 {label}" if media_type == 'video' else label
            target = (self.card_w, self.card_h)

            is_sel = idx in self.selected_indices
            if raw_pil is None:
                card_img = _make_video_placeholder_card(res_str, is_selected=is_sel, target_size=target, media_type=media_type)
            else:
                card_img = create_card_thumbnail(raw_pil, resolution_str=res_str, is_selected=is_sel, target_size=target)
            ctk_img = ctk.CTkImage(light_image=card_img, size=target)

            btn = ctk.CTkButton(
                self.preview_grid, image=ctk_img, text="", width=self.card_w, height=self.card_h,
                fg_color="transparent", hover_color=c["accent_bg"], corner_radius=8,
                command=lambda i=idx: self.toggle_card_selection(i)
            )
            btn.grid(row=row, column=col, padx=6, pady=6)
            btn.bind("<Button-3>", lambda e, i=idx: self._show_preview(i))
            self.card_buttons.append({"btn": btn, "raw_pil": raw_pil, "res_str": res_str})

        if is_relayout:
            self.update_selection_summary()
            return

        self.running = False
        if previews_pending:
            self.status_label.configure(text='提取完成，可选择或下载；预览正在加载',text_color=self.c['accent_text'])
            self.update_selection_summary()
            return
        self.status_label.configure(text="完成",text_color=self.c["success_text"])
        self.progress_bar.configure(progress_color=self.c["success"])
        self.progress_bar.set(1.0)
        self.download_btn.configure(state="normal")
        self.update_selection_summary()
        shortcode = getattr(self, "current_shortcode", "post")
        self._save_cache(shortcode)

    def toggle_card_selection(self, idx):
        if idx in self.selected_indices:
            self.selected_indices.remove(idx)
            is_sel = False
        else:
            self.selected_indices.add(idx)
            is_sel = True

        item = self.card_buttons[idx]
        target = (self.card_w, self.card_h)
        if item["raw_pil"] is None:
            card_img = _make_video_placeholder_card(item["res_str"], is_selected=is_sel, target_size=target, media_type=self.image_data[idx][4])
        else:
            card_img = create_card_thumbnail(item["raw_pil"], resolution_str=item["res_str"], is_selected=is_sel, target_size=target)
        ctk_img = ctk.CTkImage(light_image=card_img, size=target)
        item["btn"].configure(image=ctk_img)

        self.update_selection_summary()

    def _show_preview(self, idx):
        """右键预览：弹出窗口显示原图"""
        if idx >= len(self.image_data):
            return
        url, w, h, raw_pil, media_type = self.image_data[idx]
        if raw_pil is None and media_type == 'image':
            self.status_label.configure(text='预览正在加载，请稍后再试' if self._thumbnail_loading else '该图片预览不可用，仍可直接下载')
            return
        c = self.c

        preview = ctk.CTkToplevel(self)
        self._set_window_icon(preview)
        preview.title("预览")
        preview.grab_set()
        preview.configure(fg_color=c["bg_root"])

        # 按屏幕 85% 尺寸缩放
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        max_w = int(screen_w * 0.85)
        max_h = int(screen_h * 0.85)

        if raw_pil is None:
            # 视频：无缩略图无法预览，直接用占位
            img_display = _make_video_placeholder_card("视频无预览", is_selected=False, target_size=(400, 300))
            preview.geometry("420x380")
        else:
            img = raw_pil.copy()
            scale = min(max_w / img.width, max_h / img.height, 1.0)
            if scale < 1.0:
                new_w = int(img.width * scale)
                new_h = int(img.height * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            else:
                new_w, new_h = img.width, img.height

            photo = ImageTk.PhotoImage(img)
            preview.geometry(f"{new_w + 40}x{new_h + 60}")

            label = ctk.CTkLabel(preview, image=photo, text="")
            label.image = photo  # 保持引用防 GC
            label.pack(padx=20, pady=(20, 5))

        type_label = "视频" if media_type == 'video' else "图片"
        res_text = f"{type_label}  |  {w} × {h}" if (w and h) else type_label
        info = ctk.CTkLabel(preview, text=res_text, font=(self.ui_font, 12), text_color=c["text_secondary"])
        info.pack(pady=(0, 10))

        preview.bind("<Escape>", lambda e: preview.destroy())
        preview.bind("<Button-1>", lambda e: preview.destroy())

    def toggle_select_all(self):
        is_all = bool(self.select_all_chk.get())
        if is_all:
            self.selected_indices = set(range(len(self.image_data)))
        else:
            self.selected_indices.clear()

        target = (self.card_w, self.card_h)
        for idx, item in enumerate(self.card_buttons):
            if item["raw_pil"] is None:
                card_img = _make_video_placeholder_card(item["res_str"], is_selected=is_all, target_size=target, media_type=self.image_data[idx][4])
            else:
                card_img = create_card_thumbnail(item["raw_pil"], resolution_str=item["res_str"], is_selected=is_all, target_size=target)
            ctk_img = ctk.CTkImage(light_image=card_img, size=target)
            item["btn"].configure(image=ctk_img)

        self.update_selection_summary()

    def update_selection_summary(self):
        count = len(self.selected_indices)
        self.selection_summary.configure(text=f"已选择 {count} 个媒体")
        self.download_btn.configure(state="normal" if count and not self.running else "disabled")
        if count and count == len(self.image_data):
            self.select_all_chk.select()
        else:
            self.select_all_chk.deselect()

    def clear_all(self):
        if self.running: return
        self._thumbnail_generation += 1
        self._thumbnail_loading = False
        for widget in self.preview_grid.winfo_children():
            widget.destroy()
        self.image_data.clear()
        self.card_buttons.clear()
        self.selected_indices.clear()
        self.download_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.count_label.configure(text="")
        self.status_label.configure(text="就绪",text_color=self.c["text_secondary"])
        self.progress_bar.configure(progress_color=self.c["accent"])
        self.update_selection_summary()
        self._show_media_empty()

    def copy_selected_links(self):
        urls = [self.image_data[i][0] for i in self.selected_indices if i < len(self.image_data)]
        if urls:
            self.clipboard_clear()
            self.clipboard_append("\n".join(urls))
            self.status_label.configure(text=f"已复制 {len(urls)} 个链接到剪贴板",text_color=self.c["success_text"])
        else:
            self.status_label.configure(text="请先选择媒体",text_color=self.c["warning"])

    def download_all(self):
        if not self.image_data or self.running:
            return

        save_dir = self.dir_var.get().strip()
        if not save_dir:
            self.status_label.configure(text="请选择保存目录",text_color=self.c["warning"])
            return

        selected = [self.image_data[i] for i in self.selected_indices if i < len(self.image_data)]
        if not selected:
            self.status_label.configure(text="没有选中媒体",text_color=self.c["warning"])
            return

        media_list = [(url, media_type, "") for url, w, h, pil, media_type in selected]

        self.running = True
        self.download_btn.configure(state="disabled")
        self.status_label.configure(text=f"正在下载 {len(media_list)} 个媒体…",text_color=self.c["accent_text"])
        self.progress_bar.configure(progress_color=self.c["accent"])
        self.progress_bar.set(0)

        threading.Thread(target=self._download_worker, args=(media_list, save_dir), daemon=True).start()

    def _download_worker(self, media_list, save_dir):
        def progress_callback(completed, total):
            self.after(0, self.progress_bar.set, completed / total)
            self.after(0, lambda: self.status_label.configure(text=f"下载中 {completed}/{total}"))

        prefix = getattr(self, "current_shortcode", "post")
        try:
            succeeded, total = download_media_parallel(media_list, save_dir, prefix, progress_callback,
                                                      self.tiktok_extractor.request_headers,
                                                      self.tiktok_extractor.proxy if prefix.startswith('tiktok_') else None)
            self.after(0, self._download_complete, succeeded, total)
        except Exception as error:
            self.after(0, self._download_complete, 0, len(media_list), str(error))

    def _download_complete(self, succeeded=None, total=None, error=None):
        self.running = False
        self.download_btn.configure(state="normal")
        failed = total - succeeded if total is not None else 0
        message = f'下载完成：成功 {succeeded}，失败 {failed}' if total is not None else '下载完成！'
        self.status_label.configure(text=error or message,text_color=self.c['error' if failed or error else 'success_text'])
        self.progress_bar.configure(progress_color=self.c["success"])
        self.progress_bar.set(1.0)

    # ---------- Cookie 引导 ----------
    def _show_cookie_guide(self):
        c = self.c
        dialog = ctk.CTkToplevel(self)
        self._set_window_icon(dialog)
        dialog.title("如何获取 Cookie")
        dialog.geometry("580x420")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.configure(fg_color=c["bg_card"])

        guide_text = (
            "只需三步，轻松完成：\n\n"
            "1️⃣ 安装 Cookie-Editor 扩展\n"
            "Chrome 用户：\n"
            "https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm\n\n"
            "2️⃣ 登录需要使用的网站\n"
            "Instagram：打开 instagram.com 并登录你的账号。\n"
            "YouTube：打开 youtube.com 并登录你的账号（可选，但能显著降低下载被 403 的概率）。\n\n"
            "3️⃣ 导出 Cookie\n"
            "点击浏览器地址栏右侧的 🍪 图标 → 点击 Export → 选择 JSON 格式。\n"
            "将复制到的内容粘贴到程序目录下的 cookies.json 文件中保存。\n"
            "程序会自动提取 YouTube/Google 域的 Cookie 用于 YouTube 下载。\n\n"
            "✅ 完成后重启本程序即可正常使用。\n\n"
            "提示：Cookie 通常 1~3 个月过期，过期后按上述步骤重新获取即可。"
        )

        frame = ctk.CTkScrollableFrame(dialog, fg_color="transparent",scrollbar_button_color=c["border"],scrollbar_button_hover_color=c["text_muted"])
        frame.pack(fill="both", expand=True, padx=20, pady=(20, 10))

        self._label(frame,"如何获取 Cookie",20,True).pack(anchor="w",pady=(0,12))
        self._label(frame,guide_text,13,color=c["text_button"],wraplength=500,justify="left").pack(anchor="w")

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        self._button(btn_row,"一键登录",lambda: [dialog.destroy(), self._login_with_browser()],True,width=140,height=36).pack(side="left")
        self._button(btn_row,"关闭",dialog.destroy,width=100,height=36).pack(side="right")

    # ---------- 一键登录 ----------
    def _login_with_browser(self):
        """用有头浏览器打开 Instagram，用户手动登录后自动捕获 Cookie 并保存"""
        self.status_label.configure(text="正在启动浏览器，请手动登录 Instagram...")
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self):
        cookies_path = os.path.join(BASE_DIR, "cookies.json")
        proxy = self.proxy_var.get().strip() or None
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
            if not _browsers_ready:
                self.after(0, lambda: self.status_label.configure(
                    text="错误：Chromium 浏览器未就绪，请确认 _internal\\browsers 目录完整"))
                return
            p = sync_playwright().start()
            launch_options = {
                "headless": False,
                "args": [
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars", "--window-size=1280,900",
                    "--disable-dev-shm-usage", "--disable-gpu",
                    "--hide-scrollbars",
                ]
            }
            if proxy:
                launch_options["proxy"] = {"server": proxy}

            browser = p.chromium.launch(**launch_options)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="Asia/Shanghai",
                extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
            )
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)
            Stealth().apply_stealth_sync(page)

            self.after(0, lambda: self.status_label.configure(
                text="浏览器已打开，请在浏览器中登录 Instagram..."))

            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)

            # 等页面稳定后再开始检测
            time.sleep(5)

            # 轮询检测登录成功（最多等待 5 分钟）
            max_wait = 300
            logged_in = False
            for _ in range(max_wait):
                time.sleep(1)
                try:
                    url = page.url
                    # URL 不在任何登录/注册/验证流程中
                    url_ok = ("instagram.com" in url
                              and "accounts/login" not in url
                              and "accounts/signup" not in url
                              and "accounts/onetap" not in url
                              and "challenge" not in url)
                    if not url_ok:
                        continue

                    # 关键验证：必须拿到 sessionid Cookie 才算真正登录
                    cookies = context.cookies()
                    has_session = any("sessionid" in c.get("name", "") for c in cookies)
                    if has_session:
                        logged_in = True
                        break
                except Exception:
                    # 浏览器被关闭
                    self.after(0, lambda: self.status_label.configure(text="浏览器已关闭，登录未完成"))
                    p.stop()
                    return

            if not logged_in:
                self.after(0, lambda: self.status_label.configure(
                    text="登录超时（5 分钟），请重试"))
                browser.close()
                p.stop()
                return

            # 登录成功，等待页面稳定后处理弹窗
            time.sleep(3)
            # 尝试关闭 "Save Your Login Info" 弹窗
            try:
                not_now = page.query_selector("//button[contains(text(),'Not Now') or contains(text(),'Not now')]")
                if not_now:
                    not_now.click()
                    time.sleep(1)
            except Exception:
                pass
            try:
                save_info_not_now = page.query_selector("//button[contains(text(),'Save Info')]/following-sibling::button")
                if save_info_not_now:
                    save_info_not_now.click()
                    time.sleep(1)
            except Exception:
                pass
            try:
                # 关闭通知弹窗
                notif_not_now = page.query_selector("button:has-text('Not Now')")
                if notif_not_now:
                    notif_not_now.click()
                    time.sleep(1)
            except Exception:
                pass

            # 捕获 Cookie
            cookies = context.cookies()
            if cookies:
                with open(cookies_path, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                self.after(0, lambda: self.status_label.configure(
                    text=f"登录成功！已保存 {len(cookies)} 个 Cookie，可以开始提取了"))
                logger.info(f"一键登录成功，保存 {len(cookies)} 个 Cookie 到 {cookies_path}")
            else:
                self.after(0, lambda: self.status_label.configure(
                    text="登录检测成功但未捕获到 Cookie，请重试"))

            browser.close()
            p.stop()

        except Exception as e:
            logger.exception(f"一键登录失败: {e}")
            self.after(0, lambda: self.status_label.configure(
                text=f"一键登录失败: {e}"))

    # ---------- 代理弹窗 ----------
    def _open_proxy_dialog(self):
        c = self.c
        dialog = ctk.CTkToplevel(self)
        self._set_window_icon(dialog)
        dialog.title("代理设置")
        dialog.geometry("420x150")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.configure(fg_color=c["bg_card"])

        self._label(dialog,"HTTP 代理",16,True).pack(anchor="w",padx=20,pady=(20,8))

        entry = ctk.CTkEntry(dialog, textvariable=self.proxy_var, placeholder_text="http://user:pass@ip:port", height=36, corner_radius=8, border_width=1,border_color=c["border"],fg_color=c["bg_input"],text_color=c["text_primary"],placeholder_text_color=c["text_muted"],font=(self.ui_font,13))
        entry.pack(fill="x", padx=20, pady=(0, 12))

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=20)
        self._button(btn_row,"取消",dialog.destroy,width=80,height=32).pack(side="right",padx=4)
        self._button(btn_row,"确定",dialog.destroy,True,width=80,height=32).pack(side="right",padx=4)

    # ---------- 缓存 ----------
    CACHE_DIR = os.path.join(BASE_DIR, ".image_cache")

    def _save_cache(self, shortcode):
        """保存提取结果到磁盘缓存，含缩略图 + 元数据"""
        if not self.image_data:
            return
        cache_path = os.path.join(self.CACHE_DIR, shortcode)
        os.makedirs(cache_path, exist_ok=True)
        meta = []
        for idx, (url, w, h, pil, media_type) in enumerate(self.image_data):
            filename = f"{idx}.png"
            if pil is not None:
                img = pil.copy()
                if max(img.size) > 400:
                    scale = 400 / max(img.size)
                    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
                img.save(os.path.join(cache_path, filename), "PNG")
            else:
                filename = None
            meta.append({"url": url, "w": w, "h": h, "media_type": media_type, "filename": filename})
        with open(os.path.join(cache_path, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        # 更新历史记录缩略图
        if self.image_data and self.image_data[0][3] is not None:
            thumb = self.image_data[0][3].copy()
            thumb.thumbnail((60, 60), Image.LANCZOS)
            buf = BytesIO()
            thumb.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            cfg = load_config()
            history = cfg.get("history", [])
            for h in history:
                if h.get("shortcode") == shortcode:
                    h["thumbnail"] = b64
                    break
            cfg["history"] = history
            save_full_config(cfg)
            self._render_history()

    def _load_from_cache(self, shortcode):
        """从磁盘缓存加载 image_data，失败返回 None"""
        cache_path = os.path.join(self.CACHE_DIR, shortcode)
        meta_file = os.path.join(cache_path, "meta.json")
        if not os.path.exists(meta_file):
            return None
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            data = []
            for item in meta:
                pil = None
                if item.get("filename"):
                    img_path = os.path.join(cache_path, item["filename"])
                    if os.path.exists(img_path):
                        pil = Image.open(img_path).copy()
                data.append((item["url"], item["w"], item["h"], pil, item["media_type"]))
            return data if data else None
        except Exception:
            return None

    # ---------- 提取历史记忆 ----------
    HISTORY_CACHE_DIR = os.path.join(BASE_DIR, ".history_thumbnails")

    def _add_to_history(self, url, count=0):
        cfg = load_config()
        history = cfg.get("history", [])
        history = [h for h in history if h.get("url") != url]
        import datetime
        entry = {
            "url": url,
            "shortcode": getattr(self, "current_shortcode", "post"),
            "count": count,
            "timestamp": datetime.datetime.now().strftime("%m-%d %H:%M")
        }
        history.insert(0, entry)
        overflow = history[self.MAX_HISTORY:]
        history = history[:self.MAX_HISTORY]
        cfg["history"] = history
        save_full_config(cfg)
        # 清理被挤出 10 条之外的缓存
        for old in overflow:
            sc = old.get("shortcode", "")
            if sc:
                import shutil
                old_cache = os.path.join(self.CACHE_DIR, sc)
                if os.path.isdir(old_cache):
                    shutil.rmtree(old_cache, ignore_errors=True)
        self._render_history()

    def _load_history(self):
        cfg = load_config()
        return cfg.get("history", [])[:self.MAX_HISTORY]

    def _render_history(self):
        """刷新历史：折叠显示最新一条内联，展开弹出下拉菜单"""
        history = self._load_history()

        if not history:
            self.history_btn.configure(text="查看全部 ›")
            self._hide_inline()
            self._label(self.hist_inline, "  暂无提取记录", 13, color=self.c["text_secondary"],
                        image=self._img("instagram",size=23),compound="left",height=50,
                        fg_color=self.c["history_bg"],corner_radius=10).pack(fill="x",pady=3)
            self.hist_inline.pack(fill="x", padx=20, pady=(0,12))
            if self.history_expanded:
                self._dismiss_history_popup()
            return

        self.history_btn.configure(text="收起记录 ‹" if self.history_expanded else "查看全部 ›")

        if self.history_expanded:
            self._hide_inline()
            self._show_history_dropdown(history)
        else:
            self._show_inline(history[0])

    def _show_inline(self, first_item):
        """折叠态：在标题栏下方显示最新一条历史记录"""
        self._hide_inline()
        c = self.c
        short = first_item.get("shortcode", "")[:12]
        ts = first_item.get("timestamp", "")
        count = first_item.get("count", 0)
        url = first_item.get("url", "")
        platform = 'TikTok' if short.startswith('tiktok_') else 'X' if short.startswith('x_') else ''
        label = f"{platform + ' · ' if platform else ''}{short}...  {count}项  {ts}"
        btn = ctk.CTkButton(
            self.hist_inline, text=label, font=(self.ui_font, 12), anchor="w", image=self._img("link" if platform else "instagram",size=21),
            fg_color=c["history_bg"], text_color=c["text_button_dim"],
            hover_color=c["ghost_hover"], corner_radius=10, height=50,
            command=lambda u=url: self._on_history_click(u)
        )
        btn.pack(fill="x", padx=5, pady=2)
        self.hist_inline.pack(fill="x", padx=10, pady=(0, 5))

    def _hide_inline(self):
        for w in self.hist_inline.winfo_children():
            w.destroy()
        self.hist_inline.pack_forget()

    def _show_history_dropdown(self, history):
        """弹出下拉浮动菜单，点击外部关闭"""
        if self._history_popup and self._history_popup.winfo_exists():
            self._history_popup.destroy()

        c = self.c
        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.configure(fg_color=c["border"])
        popup.attributes("-topmost", True)

        x = self.hist_header.winfo_rootx()
        y = self.hist_header.winfo_rooty() + self.hist_header.winfo_height()
        w = self.hist_header.winfo_width()
        popup.geometry(f"{w}x{len(history) * 36 + 6}+{x}+{y}")

        inner = ctk.CTkFrame(popup, fg_color=c["bg_card"], corner_radius=4)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        for h in history:
            short = h.get("shortcode", "")[:12]
            ts = h.get("timestamp", "")
            count = h.get("count", 0)
            url = h.get("url", "")
            label = f"{short}...  {count}项  {ts}"
            btn = ctk.CTkButton(
                inner, text=label, font=(self.ui_font, 11), anchor="w",
                fg_color="transparent", text_color=c["text_button"],
                hover_color=c["ghost_hover"], corner_radius=6, height=30,
                command=lambda u=url: self._on_dropdown_click(u)
            )
            btn.pack(fill="x", padx=4, pady=2)

        popup.bind("<FocusOut>", lambda e: self._dismiss_history_popup())
        popup.bind("<Escape>", lambda e: self._dismiss_history_popup())
        popup.focus_set()
        self._history_popup = popup

        # 主窗口移动/缩放时自动关闭菜单，避免错位
        self._on_configure_id = self.bind("<Configure>", self._on_window_configure, "+")

    def _on_dropdown_click(self, url):
        self._dismiss_history_popup()
        self._on_history_click(url)

    def _on_window_configure(self, event):
        """主窗口移动/缩放时自动关闭下拉菜单"""
        # 仅处理主窗口自身的 Configure 事件，过滤子控件
        if event.widget is self:
            self._dismiss_history_popup()

    def _dismiss_history_popup(self):
        """关闭下拉菜单，恢复折叠态内联显示"""
        self.history_expanded = False
        if self._history_popup and self._history_popup.winfo_exists():
            self._history_popup.destroy()
            self._history_popup = None
        # 清理主窗口移动监听
        if hasattr(self, "_on_configure_id") and self._on_configure_id:
            self.unbind("<Configure>", self._on_configure_id)
            self._on_configure_id = None
        history = self._load_history()
        self.history_btn.configure(text="查看全部 ›")
        if history:
            self._show_inline(history[0])

    def _toggle_history(self):
        if self.history_expanded:
            self._dismiss_history_popup()
        else:
            self.history_expanded = True
            self._render_history()

    def _on_history_click(self, url):
        if self.running:
            self.status_label.configure(text='正在处理媒体，请完成后再打开历史记录')
            return
        try:
            link = parse_post_link(url)
            shortcode = link.cache_key
            if link.platform == 'TikTok':
                # Signed CDN URLs and their request cookies expire. Refresh the
                # post instead of reviving stale links or persisting credentials.
                self.url_var.set(link.url)
                self.fetch_images()
                return
        except ValueError: shortcode = None

        if shortcode:
            cached = self._load_from_cache(shortcode)
            if cached:
                self._thumbnail_generation += 1
                self._thumbnail_loading = False
                self.current_shortcode = shortcode
                self.image_data = cached
                self.url_var.set(url)
                self._render_thumbnails()
                self.status_label.configure(text=f"从缓存加载 {len(cached)} 个媒体")
                return

        # fallback: 仅填入 URL，需重新提取
        self.url_var.set(url)
        self.status_label.configure(text="已填入历史链接，点击「提取」开始")


# ---------- 启动 ----------
if __name__ == "__main__":
    app = InstagramDownloaderApp()
    app.mainloop()
