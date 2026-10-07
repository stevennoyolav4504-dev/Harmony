"""Inspect the first native client image on real Map events, before Tk idle."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from PIL import Image, ImageChops, ImageStat
from windows_integration import _window_handle


def client_image(window):
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
    u.ReleaseDC.argtypes = [w.HWND, w.HDC]
    u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    u.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
    g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
    g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
    g.CreateCompatibleBitmap.restype = w.HBITMAP
    g.SelectObject.argtypes = [w.HDC, w.HANDLE]; g.SelectObject.restype = w.HANDLE
    g.DeleteObject.argtypes = [w.HANDLE]; g.DeleteDC.argtypes = [w.HDC]
    g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT,
                           ctypes.c_void_p, ctypes.c_void_p, w.UINT]
    hwnd = _window_handle(window)
    rect = w.RECT(); u.GetClientRect(hwnd, ctypes.byref(rect))
    width, height = rect.right, rect.bottom
    dc = u.GetDC(hwnd); memory = g.CreateCompatibleDC(dc)
    bitmap = g.CreateCompatibleBitmap(dc, width, height)
    previous = g.SelectObject(memory, bitmap)
    try:
        if not u.PrintWindow(hwnd, memory, 3): raise ctypes.WinError()
        g.SelectObject(memory, previous)
        # BITMAPINFOHEADER followed by no palette, for a top-down RGB DIB.
        import struct
        header = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40,
                width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0))
        pixels = ctypes.create_string_buffer(width*height*4)
        if g.GetDIBits(memory, bitmap, 0, height, pixels, header, 0) != height:
            raise ctypes.WinError()
        return Image.frombytes('RGB', (width, height), pixels.raw, 'raw', 'BGRX')
    finally:
        g.SelectObject(memory, previous)
        g.DeleteObject(bitmap); g.DeleteDC(memory); u.ReleaseDC(hwnd, dc)


def assert_first_mapped_frame(test, app):
    app.geometry('1200x740'); app.update()
    frames, errors = [], []
    original_error_handler = app.report_callback_exception
    original_mode = main.ctk.get_appearance_mode()
    app.report_callback_exception = lambda *args: errors.append(str(args))

    def first_frame(event):
        if event.widget is app:
            # The buffer must still exist; checking after idle misses flicker.
            frames.append((app._restore_buffer.bitmap, client_image(app)))

    binding = app.bind('<Map>', first_frame, add='+')
    u = ctypes.windll.user32
    u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    try:
        for mode in ('Light', 'Dark'):
            if main.ctk.get_appearance_mode() != mode: app._toggle_theme()
            for platform in ('Instagram', 'YouTube'):
                app._switch_platform(platform); app.focus_set(); app.update()
                for native in (False, True):
                    with test.subTest(mode=mode, platform=platform, native=native):
                        before = client_image(app); frames.clear()
                        test.assertGreater(max(ImageStat.Stat(before).stddev), 12)
                        if native:
                            u.PostMessageW(_window_handle(app), 0x112, 0xF020, 0)
                        else: app.iconify()
                        app.update(); test.assertEqual(app.state(), 'iconic')
                        if native:
                            u.PostMessageW(_window_handle(app), 0x112, 0xF120, 0)
                        else: app.deiconify()
                        app.update()
                        test.assertEqual(len(frames), 1)
                        test.assertIsNotNone(frames[0][0])
                        difference = ImageChops.difference(before, frames[0][1])
                        test.assertLess(sum(ImageStat.Stat(difference).mean)/3, .1)
                        test.assertIsNone(app._restore_buffer.bitmap)
                        test.assertFalse(app._restore_buffer.errors)
        test.assertFalse(errors)
    finally:
        app.unbind('<Map>', binding)
        app.report_callback_exception = original_error_handler
        if main.ctk.get_appearance_mode() != original_mode: app._toggle_theme()
        app._switch_platform('Instagram'); app.geometry('1280x940'); app.update()
