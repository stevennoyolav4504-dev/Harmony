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

    @unittest.skipUnless(sys.platform == 'win32','Windows icon integration')
    def test_dialogs_keep_harmony_icons_after_library_default_callback(self):
        a=self.app
        for open_dialog in (a._show_settings,a._show_help,a._show_cookie_guide,a._open_proxy_dialog):
            before=set(a.winfo_children())
            open_dialog();a.update()
            dialogs=[child for child in a.winfo_children() if child not in before and isinstance(child,main.ctk.CTkToplevel)]
            self.assertEqual(len(dialogs),1)
            dialog=dialogs[0]
            try:
                self.assertTrue(dialog._iconbitmap_method_called)
                dialog._windows_set_titlebar_icon()
                sizes=inspect_window_icon_sizes(dialog)
                self.assertEqual(sizes['large'],dialog._windows_icon_state['large_size'])
                self.assertEqual(sizes['small'],dialog._windows_icon_state['small_size'])
            finally:
                dialog.destroy()
                a.focus_force();a.update()

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

    def test_action_buttons_restore_brand_colors_after_disabled_state(self):
        a=self.app
        for button,fill in [(a.fetch_btn,'accent'),(a.yt_download_btn,'download')]:
            button.configure(state='disabled')
            self.assertEqual(button.cget('fg_color'),a.c['disabled_bg'])
            button.configure(state='normal')
            self.assertEqual(button.cget('fg_color'),a.c[fill])
            self.assertEqual(button.cget('text_color'),a.c['on_'+fill])

    def test_gradient_surface_dispatches_clicks_and_respects_disabled_state(self):
        a=self.app
        a._switch_platform('Instagram');a.update()
        button=a.fetch_btn
        previous=button.cget('command')
        called=Mock()
        try:
            button.configure(command=called,state='normal',text='提取')
            button._canvas.event_generate('<Enter>')
            button._canvas.event_generate('<ButtonRelease-1>',x=button.winfo_width()//2,y=button.winfo_height()//2)
            a.update()
            called.assert_called_once()
            button.configure(state='disabled')
            button._canvas.event_generate('<Enter>')
            button._canvas.event_generate('<ButtonRelease-1>',x=5,y=5)
            a.update()
            called.assert_called_once()
        finally:
            button.configure(command=previous,state='normal')

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
        for message,tone in [('下载完成: Example','success_text'),('下载失败: Example','error'),('正在下载…','accent_text')]:
            a._set_yt_status(message)
            self.assertEqual(a.yt_status_label.cget('text'),message)
            self.assertEqual(a.yt_status_label.cget('text_color'),a.c[tone])

    def test_activity_messages_are_visible_and_idle_area_collapses(self):
        a=self.app
        a._switch_platform('Instagram');a.clear_all();a.update()
        self.assertFalse(a.status_label.winfo_ismapped())
        a.status_label.configure(text='请输入有效的 Instagram 链接');a.update()
        self.assertTrue(a.status_label.winfo_ismapped())
        a.clear_all();a.update()
        self.assertFalse(a.status_label.winfo_ismapped())

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

    @unittest.skipUnless(sys.platform=='win32','Windows minimize/restore')
    def test_restore_preserves_widgets_inputs_and_cached_surfaces(self):
        a=self.app
        from harmony_surfaces import HeroHeader
        a.geometry('1200x740');a.update()
        a.url_var.set('https://www.instagram.com/p/restore/')
        a.yt_url_var.set('https://www.youtube.com/watch?v=restore')
        controls=(a.url_entry,a.yt_url_entry,a.fetch_btn,a.download_btn)
        for platform in ('Instagram','YouTube'):
            a._switch_platform(platform);a.update()
            page=a.pages[platform]
            page._parent_canvas.yview_moveto(.15);a.update()
            before_scroll=page._parent_canvas.yview()
            header=next(x for x in page.winfo_children() if isinstance(x,HeroHeader))
            photos=(header._photo,page._wash._photo,a.fetch_btn._gradient_photo)
            with patch.object(a,'_build_ui') as rebuild,patch.object(a,'_build_main') as build_main,patch.object(a,'_build_sidebar') as build_sidebar:
                for _ in range(3):
                    a.iconify();a.update()
                    self.assertEqual(a.state(),'iconic')
                    a.deiconify();a.update()
                    self.assertEqual(a.state(),'normal')
                rebuild.assert_not_called();build_main.assert_not_called();build_sidebar.assert_not_called()
            self.assertEqual(controls,(a.url_entry,a.yt_url_entry,a.fetch_btn,a.download_btn))
            self.assertEqual(photos,(header._photo,page._wash._photo,a.fetch_btn._gradient_photo))
            self.assertEqual(before_scroll,page._parent_canvas.yview())
        self.assertEqual(a.url_var.get(),'https://www.instagram.com/p/restore/')
        self.assertEqual(a.yt_url_var.get(),'https://www.youtube.com/watch?v=restore')
        a._switch_platform('Instagram');a.pages['Instagram']._parent_canvas.yview_moveto(0)

    @unittest.skipUnless(sys.platform=='win32','Windows transparency mode')
    def test_theme_switch_does_not_leave_a_layered_window(self):
        import ctypes
        from ctypes import wintypes
        a=self.app
        getter=ctypes.windll.user32.GetWindowLongW
        getter.argtypes=[wintypes.HWND,ctypes.c_int];getter.restype=wintypes.LONG
        parent=ctypes.windll.user32.GetParent
        parent.argtypes=[wintypes.HWND];parent.restype=wintypes.HWND
        mode=main.ctk.get_appearance_mode()
        a.yt_running=False;a.running=False;a.yt_parsing=False
        a.url_var.set('https://www.instagram.com/p/theme/')
        for _ in range(2):
            a._toggle_theme();a.update()
            self.assertFalse(getter(parent(a.winfo_id()),-20)&0x80000)
            self.assertEqual(a.url_var.get(),'https://www.instagram.com/p/theme/')
        self.assertEqual(main.ctk.get_appearance_mode(),mode)

    @unittest.skipUnless(sys.platform=='win32','Windows retained client surfaces')
    def test_first_mapped_frame_matches_complete_ui(self):
        from test_windows_rendering import assert_first_mapped_frame
        assert_first_mapped_frame(self,self.app)

    @unittest.skipUnless(sys.platform=='win32','Windows retained client surfaces')
    def test_native_minimize_retains_and_releases_complete_frame(self):
        import ctypes
        from ctypes import wintypes
        from windows_integration import _window_handle
        a=self.app;a.update()
        buffer=a._restore_buffer
        self.assertIsNotNone(buffer)
        u=ctypes.windll.user32
        u.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        previous=buffer.capture_count
        # Dispatch through Tk's normal native message pump, as system buttons do.
        u.PostMessageW(_window_handle(a),0x112,0xF020,0);a.update()
        self.assertEqual(a.state(),'iconic')
        self.assertEqual(buffer.capture_count,previous+1)
        self.assertIsNotNone(buffer.bitmap)
        paints=buffer.paint_count
        u.PostMessageW(_window_handle(a),0x112,0xF120,0);a.update()
        self.assertEqual(a.state(),'normal')
        self.assertGreater(buffer.paint_count,paints)
        self.assertIsNone(buffer.bitmap)
        self.assertIsNone(buffer.memory_dc)
        self.assertFalse(buffer.errors)

    @unittest.skipUnless(sys.platform=='win32','Windows GDI resource lifetime')
    def test_restore_buffer_does_not_accumulate_native_graphics_resources(self):
        import ctypes
        from ctypes import wintypes
        a=self.app;a.update()
        buffer=a._restore_buffer
        kernel=ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype=wintypes.HANDLE
        getter=ctypes.windll.user32.GetGuiResources
        getter.argtypes=[wintypes.HANDLE,wintypes.DWORD];getter.restype=wintypes.DWORD
        process=kernel.GetCurrentProcess()
        before=getter(process,0)
        for _ in range(20):
            a.iconify();a.update();a.deiconify();a.update()
            self.assertIsNone(buffer.bitmap)
            self.assertIsNone(buffer.memory_dc)
        self.assertLessEqual(getter(process,0),before+2)
        self.assertFalse(buffer.errors)

    @unittest.skipUnless(sys.platform=='win32','Windows live restored controls')
    def test_restore_displays_input_and_progress_changes_made_while_minimized(self):
        from test_windows_rendering import client_image
        from PIL import ImageChops,ImageStat
        a=self.app;a._switch_platform('YouTube')
        previous_url=a.yt_url_var.get()
        try:
            a.yt_url_var.set('https://www.youtube.com/watch?v=before')
            a._set_yt_status('正在下载…');a._set_yt_progress(.42);a.update()
            before=client_image(a)
            a.iconify();a.update()
            a.yt_url_var.set('https://www.youtube.com/watch?v=after')
            a._set_yt_progress(.64)
            a.deiconify();a.update()
            self.assertIsNone(a._restore_buffer.bitmap)
            self.assertEqual(a.yt_url_entry.get(),'https://www.youtube.com/watch?v=after')
            self.assertEqual(a.yt_percent_label.cget('text'),'64%')
            # A released backing frame must show the updated pixels, not freeze.
            difference=ImageChops.difference(before,client_image(a))
            self.assertGreater(sum(ImageStat.Stat(difference).mean),.01)
        finally:
            a.yt_url_var.set(previous_url)
            a._set_yt_status('就绪');a._set_yt_progress(0)
            a._switch_platform('Instagram');a.update()

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
