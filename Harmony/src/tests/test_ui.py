"""Offline interaction regressions; no network, downloads, or user config writes."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main
from PIL import Image
from windows_integration import inspect_window_icon_sizes


class UIRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=main.InstagramDownloaderApp()
        cls.app._save_cache=Mock()
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def test_platform_preserves_inputs_and_local_directory(self):
        a=self.app
        a.url_var.set('https://www.instagram.com/p/example/')
        a.yt_url_var.set('https://www.youtube.com/watch?v=example')
        a._switch_platform('YouTube');a.update()
        self.assertTrue(a.yt_url_entry.winfo_ismapped())
        self.assertFalse(a.url_entry.winfo_ismapped())
        with patch.object(main.os,'startfile',create=True) as opened,patch.object(main.os.path,'exists',return_value=True):
            a._open_save_dir()
            opened.assert_called_once_with(a.yt_dir_var.get())
        a._switch_platform('Instagram');a.update()
        self.assertEqual(a.url_var.get(),'https://www.instagram.com/p/example/')

    def test_link_placeholder_does_not_block_input(self):
        a=self.app
        for platform,var,entry,hint in [
            ('Instagram',a.url_var,a.url_entry,a.url_hint),
            ('YouTube',a.yt_url_var,a.yt_url_entry,a.yt_url_hint),
        ]:
            a._switch_platform(platform)
            var.set('')
            entry._entry.event_generate('<FocusOut>')
            a.update()
            self.assertTrue(hint.winfo_ismapped())
            self.assertLess(hint.winfo_width(),entry.winfo_width())
            hint._label.event_generate('<ButtonPress-1>',x=5,y=5)
            a.update()
            self.assertEqual(a.focus_get(),entry._entry)
            self.assertFalse(hint.winfo_ismapped())
            entry.insert(0,'https://example.com/test')
            self.assertEqual(var.get(),'https://example.com/test')

    @unittest.skipUnless(sys.platform == 'win32','Windows icon integration')
    def test_windows_uses_separate_native_icon_sizes(self):
        a=self.app
        a.update()
        expected=a._windows_icon_state
        actual=inspect_window_icon_sizes(a)
        self.assertEqual(actual['large'],expected['large_size'])
        self.assertEqual(actual['small'],expected['small_size'])
        self.assertEqual(actual['small2'],expected['small_size'])
        self.assertNotEqual(expected['large_icon'],expected['small_icon'])

    def test_selection_clear_restores_empty_state(self):
        a=self.app
        a.image_data=[('https://example.com/image.jpg',300,200,Image.new('RGB',(300,200),'pink'),'image')]
        a._render_thumbnails();a.update()
        self.assertEqual(len(a.card_buttons),1)
        self.assertEqual(a.selected_indices,{0})
        a.toggle_card_selection(0)
        self.assertEqual(a.download_btn.cget('state'),'disabled')
        self.assertFalse(a.select_all_chk.get())
        a.select_all_chk.select();a.toggle_select_all()
        self.assertEqual(a.selected_indices,{0})
        a.clear_all();a.update()
        self.assertFalse(a.image_data)
        self.assertTrue(a.preview_grid.winfo_children())

    def test_clip_entries_and_download_dispatch(self):
        a=self.app
        a.yt_clip_enabled.set(True);a._sync_clip()
        self.assertEqual(a.yt_clip_start_entry.cget('state'),'normal')
        a.yt_clip_enabled.set(False);a._sync_clip()
        self.assertEqual(a.yt_clip_start_entry.cget('state'),'disabled')
        a.yt_url_var.set('https://www.youtube.com/watch?v=example')
        a.yt_fmt_var.set('1080p')
        with patch.object(main.threading,'Thread') as worker:
            a._yt_download()
            self.assertEqual(worker.call_args.kwargs['args'][2],'1080p')
            worker.return_value.start.assert_called_once()
        a._yt_download_reset()

    def test_parse_validation_and_stale_result(self):
        a=self.app
        a.yt_url_var.set('invalid');a._yt_parse()
        self.assertIn('有效',a.yt_status_label.cget('text'))
        a.yt_url_var.set('https://example.com/new')
        a._yt_parse_done('https://example.com/old','Old title',None)
        self.assertIn('链接已更改',a.yt_status_label.cget('text'))
        a._yt_parse_done('https://example.com/new','New title',None)
        self.assertEqual(a.yt_info_label.cget('text'),'New title')
        a._set_yt_progress(.42)
        self.assertEqual(a.yt_percent_label.cget('text'),'42%')

    def test_responsive_control_bounds(self):
        a=self.app
        for width,height in [(1280,940),(1120,740)]:
            a.geometry(f'{width}x{height}');a.update()
            for platform,entries in [('Instagram',[a.url_entry,a.dir_entry]),('YouTube',[a.yt_url_entry,a.yt_fmt_menu,a.yt_codec_menu])]:
                a._switch_platform(platform);a.update()
                for entry in entries:
                    self.assertGreater(entry.winfo_width(),80)
                    self.assertLessEqual(entry.winfo_rootx()+entry.winfo_width(),a.winfo_rootx()+a.winfo_width())
        a.geometry('1280x940');a._switch_platform('Instagram');a.update()

    def test_theme_rebuild_keeps_inputs_without_stale_callbacks(self):
        a=self.app
        errors=[]
        previous=a.report_callback_exception
        a.report_callback_exception=lambda *args:errors.append(args)
        try:
            before=len(a.url_var.trace_info())
            a._dismiss_history_popup()
            a.sidebar.destroy();a.main_container.destroy()
            main.ctk.set_appearance_mode('Dark')
            a._build_ui();a._render_history();a.update()
            a.url_var.set('https://www.instagram.com/p/after-theme/')
            self.assertEqual(len(a.url_var.trace_info()),before)
            self.assertFalse(errors)
        finally:
            a.report_callback_exception=previous
            main.ctk.set_appearance_mode('Light')


if __name__=='__main__':unittest.main(verbosity=2)
