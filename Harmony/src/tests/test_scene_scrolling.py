"""Windows scroll frames stay complete while the next frame is prepared."""
import ctypes
import sys
import unittest
from unittest.mock import patch

import customtkinter as ctk
from PIL import Image

from harmony_scene import Page, Entry, Label
if sys.platform == 'win32':
    import windows_scene as native


def pixels(bitmap):
    native.g.GdiFlush()
    return Image.frombytes('RGB', bitmap.size,
        ctypes.string_at(bitmap.bits, bitmap.allocation[0]*4*bitmap.size[1]),
        'raw', 'BGRX', bitmap.allocation[0]*4).tobytes()


@unittest.skipUnless(sys.platform == 'win32', 'Windows retained page scrolling')
class SceneScrolling(unittest.TestCase):
    def setUp(self):
        self.root = ctk.CTk()
        self.root.geometry('620x420+0+0')
        self.page = Page(self.root, decorated=False)
        self.page.pack(fill='both', expand=True)
        self.entry = Entry(self.page._layout_root, width=400, height=40)
        self.entry.pack(fill='x', padx=20, pady=20)
        self.entry.insert(0, '编辑内容在滚动后保留')
        for index in range(12):
            Label(self.page._layout_root, text=f'滚动内容 {index}', height=60,
                  fg_color='#F8C8DD' if index % 2 else '#DBEFFF').pack(fill='x', pady=6)
        self.root.update()
        self.canvas = self.page.canvas

    def tearDown(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        self.root.destroy()

    def test_wheel_keeps_editors_with_the_displayed_frame_until_commit(self):
        canvas = self.canvas
        editor = next(item for item in canvas._scene_items.values() if item['kind'] == 'window')
        self.entry._entry.focus_force()
        self.entry._entry.selection_range(1, 4)
        self.entry._entry.icursor(3)
        previous = editor['_placed']
        old_frame = pixels(canvas.buffer)
        for _ in range(3):
            canvas.event_generate('<MouseWheel>', delta=-120)
        self.assertGreater(canvas.canvasy(0), 0)
        self.assertEqual(editor['_placed'], previous,
                         'native editor moved while the page still displays the old scroll frame')
        self.assertEqual(pixels(canvas.buffer), old_frame)
        self.root.update()
        self.assertEqual(editor['_placed'][1], round(editor['coords'][1] - canvas._rendered_offset))
        self.assertEqual(self.entry.get(), '编辑内容在滚动后保留')
        self.assertEqual(self.root.focus_get(), self.entry._entry)
        self.assertEqual(self.entry._entry.index('insert'), 3)
        self.assertEqual((self.entry._entry.index('sel.first'), self.entry._entry.index('sel.last')), (1, 4))
        self.assertNotEqual(pixels(canvas.buffer), old_frame)
        self.assertFalse(canvas.errors)

    def test_reentrant_paint_during_render_uses_the_last_complete_frame(self):
        canvas = self.canvas
        previous = pixels(canvas.buffer)
        capture = native.Bitmap(Image.new('RGB', canvas.buffer.size))
        frames = []
        original_font = canvas._font
        def paint_while_drawing(font):
            if not frames:
                canvas._present(capture.dc)
                frames.append(pixels(capture))
            return original_font(font)
        try:
            with patch.object(canvas, '_font', side_effect=paint_while_drawing):
                canvas.yview_scroll(3, 'units')
                self.root.update()
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0], previous,
                             'a paint request saw a partially drawn scroll frame')
            self.assertNotEqual(pixels(canvas.buffer), previous)
        finally:
            capture.close()

    def test_first_native_paint_uses_matching_editor_positions(self):
        from ctypes import wintypes as w
        canvas = self.canvas
        host = canvas.winfo_id()
        native.u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        original = canvas._present
        positions = []
        def inspect_paint(dc):
            # Called from WndProc: only cached IDs and Win32, never Tcl/Tk.
            for item in canvas._scene_items.values():
                if item['kind'] != 'window' or not item.get('_placed'):continue
                rect = w.RECT();native.u.GetWindowRect(item['hwnd'], ctypes.byref(rect))
                point = w.POINT(rect.left, rect.top)
                native.u.MapWindowPoints(None, host, ctypes.byref(point), 1)
                positions.append(((point.x, point.y), item['_placed'][:2]))
            return original(dc)
        with patch.object(canvas, '_present', side_effect=inspect_paint):
            canvas.event_generate('<MouseWheel>', delta=-120)
            self.root.update()
        self.assertTrue(positions)
        self.assertTrue(all(actual == expected for actual, expected in positions), positions)
        self.assertFalse(canvas.errors)

    def test_failed_render_keeps_the_displayed_frame_and_editor_position(self):
        canvas = self.canvas
        previous = pixels(canvas.buffer)
        offset = canvas._rendered_offset
        editors = [item for item in canvas._scene_items.values() if item['kind'] == 'window']
        positions = [item['_placed'] for item in editors]
        canvas.yview_scroll(3, 'units')
        with patch.object(canvas, '_draw', side_effect=RuntimeError('interrupted drawing')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted drawing'):
                canvas.present(self.page._backdrop, self.page._wash_item)
        self.assertEqual(pixels(canvas.buffer), previous)
        self.assertEqual(canvas._rendered_offset, offset)
        self.assertEqual([item['_placed'] for item in editors], positions)
        self.root.update()
        self.assertNotEqual(canvas._rendered_offset, offset)

    def test_paint_does_not_clear_pixels_already_covered_by_the_complete_frame(self):
        canvas = self.canvas
        capture = native.Bitmap(Image.new('RGB', canvas.buffer.size))
        expected = pixels(canvas.buffer)
        native.g.BitBlt(capture.dc, 0, 0, *capture.size, canvas.buffer.dc, 0, 0, 0x00CC0020)
        intermediate = []
        fill = native.u.FillRect
        def inspect_fill(dc, rect, brush):
            result = fill(dc, rect, brush)
            if dc == capture.dc:
                intermediate.append(pixels(capture))
            return result
        try:
            with patch.object(native.u, 'FillRect', side_effect=inspect_fill):
                canvas._present(capture.dc)
            self.assertTrue(all(frame == expected for frame in intermediate),
                            'painting briefly clears the complete frame to a flat background')
            self.assertEqual(pixels(capture), expected)
        finally:
            capture.close()


if __name__ == '__main__':
    unittest.main()
