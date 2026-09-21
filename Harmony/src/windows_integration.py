"""Small Windows-specific helpers for taskbar identity and native icons."""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes


APP_USER_MODEL_ID = "StevenNoyolav.Harmony"


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Give source and packaged runs the same Windows taskbar identity."""
    if sys.platform != "win32":
        return False
    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return result >= 0
    except (AttributeError, OSError):
        return False


def _window_handle(tk_window) -> int:
    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    client = int(tk_window.winfo_id())
    wrapper = user32.GetParent(wintypes.HWND(client))
    return int(wrapper or client)


def _metric_for_dpi(metric: int, dpi: int) -> int:
    user32 = ctypes.windll.user32
    try:
        user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
        user32.GetSystemMetricsForDpi.restype = ctypes.c_int
        value = user32.GetSystemMetricsForDpi(metric, dpi)
    except AttributeError:
        value = user32.GetSystemMetrics(metric)
    return max(1, int(value))


def apply_window_icons(tk_window, icon_path: str) -> dict | None:
    """Install separate DPI-sized Win32 icons for the title bar and taskbar."""
    if sys.platform != "win32" or not os.path.isfile(icon_path):
        return None

    user32 = ctypes.windll.user32
    hwnd = _window_handle(tk_window)
    try:
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        dpi = int(user32.GetDpiForWindow(wintypes.HWND(hwnd)) or 96)
    except AttributeError:
        dpi = 96

    # SM_CXICON/SM_CYICON and SM_CXSMICON/SM_CYSMICON.
    large_size = (_metric_for_dpi(11, dpi), _metric_for_dpi(12, dpi))
    small_size = (_metric_for_dpi(49, dpi), _metric_for_dpi(50, dpi))

    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                  wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    load_from_file = 0x0010
    image_icon = 1
    large_icon = user32.LoadImageW(None, icon_path, image_icon,
                                   large_size[0], large_size[1], load_from_file)
    small_icon = user32.LoadImageW(None, icon_path, image_icon,
                                   small_size[0], small_size[1], load_from_file)
    if not large_icon or not small_icon:
        if large_icon:
            user32.DestroyIcon(large_icon)
        if small_icon:
            user32.DestroyIcon(small_icon)
        raise ctypes.WinError()

    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    wm_seticon = 0x0080
    user32.SendMessageW(hwnd, wm_seticon, 1, large_icon)  # ICON_BIG
    user32.SendMessageW(hwnd, wm_seticon, 0, small_icon)  # ICON_SMALL
    # ICON_SMALL2 is a WM_GETICON fallback selector, not a WM_SETICON target.

    # Keep the handles alive for the lifetime of the window. Windows releases
    # the remaining process resources at exit.
    return {
        "hwnd": hwnd,
        "dpi": dpi,
        "large_size": large_size,
        "small_size": small_size,
        "large_icon": int(large_icon),
        "small_icon": int(small_icon),
    }


def inspect_window_icon_sizes(tk_window) -> dict:
    """Return the native pixel sizes Windows currently sees; used by tests."""
    if sys.platform != "win32":
        return {}
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = _window_handle(tk_window)

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                    ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                    ("hbmColor", wintypes.HBITMAP)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                    ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                    ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", wintypes.LPVOID)]

    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
    user32.GetIconInfo.restype = wintypes.BOOL
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL

    def dimensions(handle: int):
        if not handle:
            return None
        info = ICONINFO()
        if not user32.GetIconInfo(wintypes.HICON(handle), ctypes.byref(info)):
            return None
        bitmap = BITMAP()
        source = info.hbmColor or info.hbmMask
        gdi32.GetObjectW(source, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
        if info.hbmColor:
            gdi32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            gdi32.DeleteObject(info.hbmMask)
        return bitmap.bmWidth, bitmap.bmHeight

    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    return {
        "large": dimensions(user32.SendMessageW(hwnd, 0x007F, 1, 0)),
        "small": dimensions(user32.SendMessageW(hwnd, 0x007F, 0, 0)),
        "small2": dimensions(user32.SendMessageW(hwnd, 0x007F, 2, 0)),
    }
