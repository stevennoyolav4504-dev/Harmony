"""Retain Tk child surfaces while Windows restores the native window.

Tk schedules canvas/label exposure work for a later idle pass. A native child
window can therefore be presented before that work has run. During restore,
paint its last complete client image until Tk has drained the exposure work.
The backing bitmap is memory-only and exists just for one minimize/restore.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import sys

from windows_integration import _window_handle


class _BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
        ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
        ("image_size", w.DWORD), ("xppm", w.LONG), ("yppm", w.LONG),
        ("used", w.DWORD), ("important", w.DWORD),
    ]


class _WindowPosition(ctypes.Structure):
    _fields_ = [("hwnd", w.HWND), ("after", w.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                ("flags", w.UINT)]


class RestoreBuffer:
    """Own native hooks and one complete client bitmap on the Tk UI thread."""

    def __init__(self, window):
        self.window = window
        self.hwnd = _window_handle(window)
        self.bitmap = self.memory_dc = self.previous_bitmap = None
        self.size = None
        self.children = set()
        self.restoring = False
        self.capturing = False
        self.closed = False
        self.capture_count = self.paint_count = 0
        self.errors = []
        self._release_pending = None
        self.user = ctypes.windll.user32
        self.gdi = ctypes.windll.gdi32
        self.common = ctypes.windll.comctl32
        self._declare_api()
        self._callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM,
            ctypes.c_size_t, ctypes.c_size_t,
        )
        self._callback = self._callback_type(self._procedure)
        self.common.SetWindowSubclass.argtypes = [
            w.HWND, self._callback_type, ctypes.c_size_t, ctypes.c_size_t,
        ]
        self.common.SetWindowSubclass.restype = w.BOOL
        self.common.RemoveWindowSubclass.argtypes = self.common.SetWindowSubclass.argtypes[:3]
        self.common.DefSubclassProc.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.common.DefSubclassProc.restype = ctypes.c_ssize_t
        self._id = id(self)
        if not self.common.SetWindowSubclass(self.hwnd, self._callback, self._id, 0):
            raise ctypes.WinError()

    def _declare_api(self):
        u, g = self.user, self.gdi
        u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.MapWindowPoints.argtypes = [w.HWND, w.HWND, ctypes.POINTER(w.POINT), w.UINT]
        u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
        u.ReleaseDC.argtypes = [w.HWND, w.HDC]
        u.IsWindowVisible.argtypes = [w.HWND]
        u.IsWindow.argtypes = [w.HWND]
        u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        u.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
        u.PrintWindow.restype = w.BOOL
        u.RedrawWindow.argtypes = [w.HWND, ctypes.c_void_p, w.HRGN, w.UINT]
        u.RedrawWindow.restype = w.BOOL
        g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
        g.CreateDIBSection.argtypes = [w.HDC, ctypes.c_void_p, w.UINT,
                                      ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
        g.CreateDIBSection.restype = w.HBITMAP
        g.SelectObject.argtypes = [w.HDC, w.HANDLE]; g.SelectObject.restype = w.HANDLE
        g.DeleteObject.argtypes = [w.HANDLE]
        g.DeleteDC.argtypes = [w.HDC]
        g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD]
        g.BitBlt.restype = w.BOOL

    def _hook_children(self):
        callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        self.user.EnumChildWindows.argtypes = [w.HWND, callback_type, w.LPARAM]

        @callback_type
        def visit(hwnd, _):
            if not self.user.IsWindowVisible(hwnd):
                return True
            name = ctypes.create_unicode_buffer(128)
            self.user.GetClassNameW(hwnd, name, 128)
            if name.value == "TkChild" and hwnd not in self.children:
                if self.common.SetWindowSubclass(hwnd, self._callback, self._id, 0):
                    self.children.add(hwnd)
            return True

        self.user.EnumChildWindows(self.hwnd, visit, 0)

    def capture(self):
        """Take a complete client frame before Windows discards child surfaces."""
        if self.closed or self.capturing or self.bitmap:
            return False
        rect = w.RECT()
        if not self.user.GetClientRect(self.hwnd, ctypes.byref(rect)):
            return False
        width, height = rect.right, rect.bottom
        if min(width, height) <= 1:
            return False
        self.capturing = True
        dc = self.user.GetDC(self.hwnd)
        try:
            memory = self.gdi.CreateCompatibleDC(dc)
            pixels = ctypes.c_void_p()
            header = _BitmapHeader(ctypes.sizeof(_BitmapHeader), width, -height,
                                   1, 32, 0, 0, 0, 0, 0, 0)
            bitmap = self.gdi.CreateDIBSection(dc, ctypes.byref(header), 0,
                                              ctypes.byref(pixels), None, 0)
            if not memory or not bitmap:
                if bitmap: self.gdi.DeleteObject(bitmap)
                if memory: self.gdi.DeleteDC(memory)
                return False
            previous = self.gdi.SelectObject(memory, bitmap)
            # PW_CLIENTONLY | PW_RENDERFULLCONTENT: only this application's UI.
            if not self.user.PrintWindow(self.hwnd, memory, 3):
                self.gdi.SelectObject(memory, previous)
                self.gdi.DeleteObject(bitmap); self.gdi.DeleteDC(memory)
                return False
            self.bitmap, self.memory_dc, self.previous_bitmap = bitmap, memory, previous
            self.size = (width, height)
            self._hook_children()
            self.capture_count += 1
            return True
        finally:
            self.user.ReleaseDC(self.hwnd, dc)
            self.capturing = False

    def _paint_cached(self, hwnd, dc):
        if not self.bitmap or self.capturing or not dc:
            return False
        rect = w.RECT(); self.user.GetClientRect(hwnd, ctypes.byref(rect))
        root_rect = w.RECT(); self.user.GetClientRect(self.hwnd, ctypes.byref(root_rect))
        if (root_rect.right, root_rect.bottom) != self.size:
            return False  # A DPI/size change must use the newly laid-out controls.
        point = w.POINT(0, 0)
        self.user.MapWindowPoints(hwnd, self.hwnd, ctypes.byref(point), 1)
        left, top = max(0, -point.x), max(0, -point.y)
        width = min(rect.right, self.size[0] - point.x) - left
        height = min(rect.bottom, self.size[1] - point.y) - top
        if min(width, height) <= 0:
            return False
        result = self.gdi.BitBlt(dc, left, top, width, height, self.memory_dc,
                                 point.x + left, point.y + top, 0x00CC0020)
        if result: self.paint_count += 1
        return bool(result)

    def _procedure(self, hwnd, message, wp, lp, _id, _data):
        try:
            if hwnd == self.hwnd:
                if message == 0x0112 and wp & 0xFFF0 == 0xF020:  # SC_MINIMIZE
                    self.capture()
                elif message == 0x0046 and lp and not self.bitmap:  # WINDOWPOSCHANGING
                    position = ctypes.cast(lp, ctypes.POINTER(_WindowPosition)).contents
                    if position.x <= -30000 and position.y <= -30000:
                        self.capture()
                elif message == 0x0005 and wp != 1 and self.bitmap:  # SIZE restored
                    self.restoring = True
            elif self.bitmap and not self.capturing:
                if message == 0x0014 and self._paint_cached(hwnd, wp):  # ERASEBKGND
                    return 1
                if message == 0x000F:  # PAINT: Tk queues its actual draw for idle.
                    result = self.common.DefSubclassProc(hwnd, message, wp, lp)
                    dc = self.user.GetDC(hwnd)
                    try: self._paint_cached(hwnd, dc)
                    finally: self.user.ReleaseDC(hwnd, dc)
                    return result
            if message == 0x0082:  # NCDESTROY
                self.children.discard(hwnd)
                if hwnd == self.hwnd: self.close()
        except Exception as error:
            self.errors.append(str(error))
        return self.common.DefSubclassProc(hwnd, message, wp, lp)

    def finish_restore(self):
        """Drain Tk exposure work before releasing the retained native frame."""
        if self.closed:
            return
        # This must run from Tk idle, never from a reentrant native callback.
        self.user.RedrawWindow(self.hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)
        self.window.update_idletasks()
        if self._release_pending is None:
            self._release_pending = self.window.after_idle(self._release)

    def _release(self):
        self._release_pending = None
        if self.closed:
            return
        if self.window.state() in ("iconic", "withdrawn"):
            return  # A second minimize arrived before the pending idle release.
        self.window.update_idletasks()
        self._free_bitmap()
        self.restoring = False

    def _free_bitmap(self):
        if self.bitmap:
            self.gdi.SelectObject(self.memory_dc, self.previous_bitmap)
            self.gdi.DeleteObject(self.bitmap)
            self.gdi.DeleteDC(self.memory_dc)
        self.bitmap = self.memory_dc = self.previous_bitmap = self.size = None

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self._release_pending is not None:
            try: self.window.after_cancel(self._release_pending)
            except Exception: pass
            self._release_pending = None
        for hwnd in tuple(self.children) + (self.hwnd,):
            if self.user.IsWindow(hwnd):
                self.common.RemoveWindowSubclass(hwnd, self._callback, self._id)
        self.children.clear()
        self._free_bitmap()


def install_restore_buffer(window):
    if sys.platform != "win32":
        return None
    try:
        return RestoreBuffer(window)
    except (AttributeError, OSError):
        return None
