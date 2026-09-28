"""Harmony's REV.06 desktop presentation layer."""
import os
import threading
import tkinter.font as tkfont
import customtkinter as ctk
from PIL import ImageTk
from harmony_art import icon, hero, empty_art
from harmony_surfaces import HeroHeader, PageWash, DashedFrame, ActivityLabel, button_surface
from harmony_brand import PRIMARY_BACKGROUND, artwork
from version import __version__

class BrandButton(ctk.CTkButton):
    """Keep disabled actions visibly distinct while using CTk's normal state API."""
    def __init__(self, *args, disabled_fg_color, disabled_image=None, gradient=None, **kwargs):
        self._gradient=gradient
        self._enabled_fill = kwargs["fg_color"]
        self._disabled_fill = disabled_fg_color
        self._enabled_image = kwargs.get("image")
        self._disabled_image = disabled_image
        super().__init__(*args, **kwargs)

    def _draw(self,no_color_updates=False):
        super()._draw(no_color_updates)
        if not self._gradient:return
        # Paint on the button's own canvas. CTk's canvas bindings and disabled
        # handling remain in charge; no decoration can intercept a click.
        for label in (self._text_label,self._image_label):
            if label is not None:label.grid_remove()
        s=self._get_widget_scaling()
        width,height=max(1,round(self._current_width*s)),max(1,round(self._current_height*s))
        disabled=self._state=="disabled"
        start,end=self._gradient
        if disabled:
            start,end=("#FFB7D0","#F47BBB") if self._gradient[0]=="#FF9FB5" else ("#AFCEEF","#92B7E9")
        elif self._mouse_inside:
            start,end=end,self._apply_appearance_mode(self._hover_color)
        self._gradient_photo=ImageTk.PhotoImage(button_surface(width,height,round(10*s),start,end),master=self)
        canvas=self._canvas;canvas.delete("gradient")
        canvas.create_image(0,0,image=self._gradient_photo,anchor="nw",tags="gradient")
        font=tkfont.Font(root=self,font=self._apply_font_scaling(self._font))
        text_width=font.measure(self._text)
        gap=10*s if self._image else 0
        image_width=20*s if self._image else 0
        x=(width-text_width-image_width-gap)/2
        if self._image:
            # Keep the action glyph white on both enabled and muted pastel fills.
            img=self._enabled_image
            self._gradient_icon=img.create_scaled_photo_image(s,self._get_appearance_mode())
            canvas.create_image(x+image_width/2,height/2,image=self._gradient_icon,tags="gradient")
        canvas.create_text(x+image_width+gap,height/2,text=self._text,font=self._apply_font_scaling(self._font),
                           anchor="w",fill="#FFFFFF",tags="gradient")

    def _on_enter(self,event=None):
        super()._on_enter(event)
        if self._gradient:self._draw()

    def _on_leave(self,event=None):
        super()._on_leave(event)
        if self._gradient:self._draw()

    def configure(self, require_redraw=False, **kwargs):
        if "fg_color" in kwargs:
            self._enabled_fill = kwargs["fg_color"]
        if "image" in kwargs:
            self._enabled_image = kwargs["image"]
        if "state" in kwargs or "fg_color" in kwargs:
            state = kwargs.get("state", self.cget("state"))
            kwargs["fg_color"] = self._disabled_fill if state == "disabled" else self._enabled_fill
        if self._disabled_image is not None and ("state" in kwargs or "image" in kwargs):
            state = kwargs.get("state", self.cget("state"))
            kwargs["image"] = self._disabled_image if state == "disabled" else self._enabled_image
        super().configure(require_redraw=require_redraw, **kwargs)


class HarmonyUI:
    def _brand_image(self, kind, width):
        pil = artwork(kind)
        height = round(width * pil.height / pil.width)
        return ctk.CTkImage(light_image=pil, dark_image=pil, size=(width,height))

    def _img(self, name, color=None, size=23):
        pil = icon(name, color or self.c["text_button"], size*2)
        return ctk.CTkImage(light_image=pil, dark_image=pil, size=(size,size))

    def _label(self, parent, text, size=14, bold=False, color=None, **kw):
        return ctk.CTkLabel(parent, text=text, font=(self.ui_font,size,"bold" if bold else "normal"),
                            text_color=color or self.c["text_primary"], **kw)

    def _button(self, parent, text, command, primary=False, image=None, width=100, height=42, tone=None):
        c=self.c
        action="download" if primary and image=="download" else "accent"
        foreground=c["on_"+action] if primary else c["pink_text"] if tone=="pink" else c["text_button"]
        return BrandButton(parent,text=text,command=command,width=width,height=height,
            corner_radius=10, font=(self.ui_font,16 if primary else 14,"bold" if primary or tone else "normal"),
            fg_color=c[action] if primary else c["pink_bg"] if tone=="pink" else c["bg_card"],
            hover_color=c[action+"_hover"] if primary else c["ghost_hover"],
            text_color=foreground, disabled_fg_color=c["disabled_bg"],
            disabled_image=self._img(image,c["disabled_text"],20) if image else None,
            text_color_disabled=c["disabled_text"], border_width=0 if primary else 2,
            border_color=c["pink_border"], image=self._img(image,foreground,20) if image else None,
            gradient=(("#FF9FB5","#F348B3") if action=="download" else ("#52B5FF","#3385FF")) if primary else None)

    def _card(self, parent):
        return ctk.CTkFrame(parent, fg_color=self.c["bg_card"], corner_radius=16,
                            border_width=0,border_color=self.c["border"])

    def _step(self, parent, number, title, subtitle, actions=None):
        row=ctk.CTkFrame(parent,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=(15,13))
        tone={1:"accent",2:"pink",3:"success"}.get(number,"accent")
        disc=ctk.CTkFrame(row,width=44,height=44,fg_color=self.c[tone+"_bg"],corner_radius=22)
        disc.pack(side="left",padx=(0,17));disc.pack_propagate(False)
        self._label(disc,str(number),24,True,color=self.c[tone+"_text"],height=28).place(relx=.5,rely=.5,anchor="center")
        if actions: actions(row)
        texts=ctk.CTkFrame(row,fg_color="transparent")
        texts.pack(side="left",fill="x",expand=True)
        self._label(texts,title,20,True,anchor="w",height=29).pack(fill="x")
        self._label(texts,subtitle,15,color=self.c["text_secondary"],anchor="w",height=23).pack(fill="x",pady=(2,0))
        return row

    def _build_sidebar(self):
        c=self.c
        self.sidebar=ctk.CTkFrame(self,width=184,fg_color=c["bg_sidebar"],corner_radius=18)
        self.sidebar.pack(side="left",fill="y",padx=(10,0),pady=10)
        self.sidebar.pack_propagate(False)
        self.brand_header=ctk.CTkFrame(self.sidebar,fg_color="transparent")
        self.brand_header.pack(fill="x",padx=15,pady=(13,29))
        self._label(self.brand_header,"",image=self._img("logo",size=28)).pack(side="left")
        self.brand_wordmark=self._label(self.brand_header,"Harmony",16,True)
        self.brand_wordmark.pack(side="left",padx=9)
        for name,text,cmd,active in [
            ("link","媒体提取",self._focus_media,True),
            ("folder","本地文件",self._open_save_dir,False),
            ("clock","历史记录",self._sidebar_history,False),
            ("settings","设置",self._show_settings,False),
            ("help","帮助",self._show_help,False)]:
            ctk.CTkButton(self.sidebar,text="  "+text,image=self._img(name,c["accent_text"] if active else c["text_button"]),
                command=cmd,width=158,height=53,corner_radius=12,anchor="w",font=(self.ui_font,16,"bold" if active else "normal"),
                fg_color=c["accent_bg"] if active else "transparent",hover_color=c["ghost_hover"],
                text_color=c["accent_text"] if active else c["text_button"]).pack(padx=12,pady=6)
        footer=ctk.CTkFrame(self.sidebar,fg_color=c["bg_sidebar"],border_color=c["pink_border"],border_width=2,corner_radius=12)
        footer.pack(side="bottom",fill="x",padx=13,pady=16)
        self._label(footer,"Harmony",14,True,image=self._img("crown",size=25),compound="left",padx=9).pack(pady=(10,0))
        self._label(footer,"高效 · 简单 · 美观",11,color=c["text_secondary"]).pack(pady=(0,11))

    def _build_main(self):
        c=self.c
        self.main_container=ctk.CTkFrame(self,fg_color="transparent")
        self.main_container.pack(side="right",fill="both",expand=True,padx=(18,14),pady=(12,8))
        switchrow=ctk.CTkFrame(self.main_container,fg_color="transparent",height=44)
        switchrow.pack(fill="x")
        switch=ctk.CTkFrame(switchrow,fg_color=c["bg_ghost"],corner_radius=12,border_width=0)
        switch.pack(side="right")
        self.platform_buttons={}
        for platform in ("Instagram","YouTube"):
            b=ctk.CTkButton(switch,text=platform,image=self._img(platform.lower(),size=22),width=148,height=40,
                corner_radius=10,font=(self.ui_font,13),command=lambda p=platform:self._switch_platform(p))
            b.pack(side="left",padx=3,pady=3)
            self.platform_buttons[platform]=b
        self.page_host=ctk.CTkFrame(self.main_container,fg_color="transparent")
        self.page_host.pack(fill="both",expand=True)
        self.pages={}
        for platform in ("Instagram","YouTube"):
            page=ctk.CTkScrollableFrame(self.page_host,fg_color="transparent",corner_radius=0,
                scrollbar_button_color=c["border"],scrollbar_button_hover_color=c["text_muted"])
            self.pages[platform]=page
            page._wash=PageWash(page,dark=ctk.get_appearance_mode()=="Dark")
            self._hero(page,platform)
        self._build_instagram(self.pages["Instagram"])
        self._build_youtube(self.pages["YouTube"])
        self._switch_platform(getattr(self,"active_platform","Instagram"))

    def _hero(self,parent,platform):
        header=HeroHeader(parent,platform,self.c,self.ui_font,height=156 if platform=="Instagram" else 140)
        header.pack(fill="x")
        header.pack_propagate(False)

    def _link_row(self,parent,yt=False):
        c=self.c
        row=ctk.CTkFrame(parent,fg_color=c["bg_card"],border_color=c["pink_border"],border_width=2,corner_radius=12)
        row.pack(fill="x",padx=24,pady=(3,20 if yt else 26))
        self._label(row,"",image=self._img("link",c["text_muted"])).pack(side="left",padx=(18,8))
        var=self.yt_url_var if yt else self.url_var
        entry=ctk.CTkEntry(row,textvariable=var,placeholder_text="https://www.youtube.com/watch?v=..." if yt else "https://www.instagram.com/p/...",
            height=54,border_width=0,fg_color=c["bg_card"],font=(self.ui_font,16),text_color=c["text_primary"],placeholder_text_color=c["placeholder"])
        btn=self._button(row,"解析视频" if yt else "提取",self._yt_parse if yt else self.fetch_images,True,"arrow",158,56)
        btn.pack(side="right",padx=4,pady=4)
        clear=self._button(row,"×",lambda:var.set(""),width=34,height=34)
        clear.pack(side="right",padx=12)
        entry.pack(side="left",fill="x",expand=True,pady=4)
        # CTkEntry doesn't display its own placeholder with a StringVar attached.
        hint=self._label(entry,"https://www.youtube.com/watch?v=..." if yt else "https://www.instagram.com/p/...",
                         16,color=c["placeholder"],fg_color=c["bg_card"],anchor="w",cursor="xterm")
        def focus_entry_from_hint(_event=None):
            # The placeholder is a label placed over the native entry. Hide it
            # before transferring focus so it never becomes a click-blocking
            # layer over the editable area.
            hint.place_forget()
            entry.focus_set()
            entry.icursor("end")
            return "break"
        hint.bind("<ButtonPress-1>",focus_entry_from_hint)
        def sync_hint(*_):
            if var.get() or entry._entry == entry.focus_get():hint.place_forget()
            else:hint.place(x=7,rely=0.5,anchor="w")
        trace_id=var.trace_add("write",sync_hint)
        entry.bind("<FocusIn>",sync_hint,add="+")
        entry.bind("<FocusOut>",sync_hint,add="+")
        entry.bind("<Destroy>",lambda e:var.trace_remove("write",trace_id),add="+")
        sync_hint()
        entry.bind("<Return>",lambda e:self._yt_parse() if yt else self.fetch_images())
        if yt: self.yt_url_entry,self.yt_url_hint,self.yt_parse_btn=entry,hint,btn
        else: self.url_entry,self.url_hint,self.fetch_btn,self.clear_url_btn=entry,hint,btn,clear

    def _directory_row(self,parent,yt=False):
        c=self.c
        row=ctk.CTkFrame(parent,fg_color="transparent")
        row.pack(fill="x",padx=24,pady=(3,26))
        self._button(row,"浏览",self._yt_browse_dir if yt else self.browse_dir,width=100,height=50,tone="pink").pack(side="right",padx=(10,0))
        field=ctk.CTkFrame(row,fg_color=c["bg_input"],border_width=2,border_color=c["border"],corner_radius=8)
        field.pack(side="left",fill="x",expand=True)
        self._label(field,"",image=self._img("folder")).pack(side="left",padx=12)
        entry=ctk.CTkEntry(field,textvariable=self.yt_dir_var if yt else self.dir_var,height=44,border_width=0,
            fg_color=c["bg_input"],text_color=c["text_button"],font=(self.ui_font,16))
        entry.pack(side="left",fill="x",expand=True,padx=(0,3),pady=3)
        if yt:self.yt_dir_entry=entry
        else:self.dir_entry=entry

    def _build_instagram(self,page):
        c=self.c
        card=self._card(page); card.pack(fill="x",pady=(0,16))
        self._step(card,1,"粘贴 Instagram 帖子链接","支持帖子、Reels、图集等多种内容类型",
            lambda row:self._button(row,"?",self._show_cookie_guide,width=32,height=32).pack(side="right"))
        self._link_row(card)
        pair=ctk.CTkFrame(page,fg_color="transparent"); pair.pack(fill="x",pady=(0,16))
        pair.grid_columnconfigure((0,1),weight=1,uniform="pair")
        directory=self._card(pair);directory.grid(row=0,column=0,sticky="nsew",padx=(0,7))
        self._step(directory,2,"保存目录","选择提取文件的保存位置")
        self._directory_row(directory)
        hist=self._card(pair);hist.grid(row=0,column=1,sticky="nsew",padx=(7,0))
        self.hist_header=ctk.CTkFrame(hist,fg_color="transparent");self.hist_header.pack(fill="x",padx=20,pady=(16,10))
        disc=ctk.CTkFrame(self.hist_header,width=44,height=44,corner_radius=22,
            fg_color="#EFEBFF" if ctk.get_appearance_mode()=="Light" else c["pink_bg"])
        disc.pack(side="left",padx=(0,17));disc.pack_propagate(False)
        self._label(disc,"",image=self._img("clock","#5028FF" if ctk.get_appearance_mode()=="Light" else c["pink_text"])).place(relx=.5,rely=.5,anchor="center")
        self.history_btn=self._button(self.hist_header,"查看全部 ›",self._toggle_history,width=92,height=34)
        self.history_btn.pack(side="right")
        ht=ctk.CTkFrame(self.hist_header,fg_color="transparent");ht.pack(side="left")
        self.hist_title_label=self._label(ht,"历史记录",20,True,height=29);self.hist_title_label.pack(anchor="w")
        self._label(ht,"最近的提取记录",15,color=c["text_secondary"],height=23).pack(anchor="w")
        self.hist_inline=ctk.CTkFrame(hist,fg_color="transparent")
        card3=self._card(page);card3.pack(fill="x",pady=(0,8))
        def actions(row):
            box=ctk.CTkFrame(row,fg_color="transparent");box.pack(side="right")
            self.select_all_chk=ctk.CTkCheckBox(box,text="全选",width=75,font=(self.ui_font,12),checkbox_width=21,checkbox_height=21,
                border_width=2,corner_radius=5,fg_color=c["selection"],hover_color=c["download_hover"],
                checkmark_color=c["on_download"],border_color=c["text_muted"],text_color=c["text_button"],command=self.toggle_select_all)
            self.select_all_chk.select();self.select_all_chk.pack(side="left",padx=8)
            self._button(box,"清空列表",self.clear_all,image="trash",width=105,height=34).pack(side="left")
        self._step(card3,3,"提取到的媒体（左键选择 · 右键预览）","选择需要下载的图片或视频",actions)
        self.preview_grid=DashedFrame(card3,fg_color=c["bg_card"],corner_radius=12,border_width=0,dash_color=c["pink_border"])
        self.preview_grid.pack(fill="x",padx=22,pady=(3,8))
        self.preview_grid.bind("<Configure>",self._on_preview_resize)
        self._show_media_empty()
        progress=ctk.CTkFrame(card3,fg_color="transparent")
        bottom=ctk.CTkFrame(card3,fg_color="transparent");bottom.pack(fill="x",padx=24,pady=(4,16))
        def show_activity(message):
            if message and message!="就绪":progress.pack(fill="x",padx=24,pady=(0,8),before=bottom)
            else:progress.pack_forget()
        line=ctk.CTkFrame(progress,fg_color="transparent");line.pack(fill="x")
        self.status_label=ActivityLabel(line,text="就绪",font=(self.ui_font,11),text_color=c["text_secondary"],height=22,on_message=show_activity)
        self.status_label.pack(side="left")
        self.count_label=self._label(line,"",11,color=c["text_secondary"],height=22);self.count_label.pack(side="right")
        self.progress_bar=ctk.CTkProgressBar(progress,height=3,progress_color=c["accent"],fg_color=c["progress_track"])
        self.progress_bar.set(0);self.progress_bar.pack(fill="x")
        self.selection_summary=self._label(bottom,"已选择 0 个媒体",14,True,image=self._img("layers",c["text_secondary"]),compound="left",padx=8)
        self.selection_summary.pack(side="left")
        self.download_btn=self._button(bottom,"下载选中媒体",self.download_all,True,"download",195,52)
        self.download_btn.configure(state="disabled");self.download_btn.pack(side="right",padx=(10,0))
        self._button(bottom,"复制链接",self.copy_selected_links,image="copy",width=160,height=52).pack(side="right")

    def _show_media_empty(self):
        art=empty_art(dark=ctk.get_appearance_mode()=="Dark")
        box=ctk.CTkFrame(self.preview_grid,fg_color="transparent",height=144)
        box.pack(fill="x",padx=8,pady=10);box.pack_propagate(False)
        self._label(box,"",image=ctk.CTkImage(light_image=art,dark_image=art,size=(115,72))).pack(pady=(10,2))
        self._label(box,"尚未提取任何媒体",16,color=self.c["text_button"]).pack()
        self._label(box,"粘贴链接并点击「提取」开始获取内容",14,color=self.c["text_secondary"]).pack(pady=(1,10))

    def _build_youtube(self,page):
        c=self.c
        card=self._card(page);card.pack(fill="x",pady=(0,14))
        self._step(card,1,"粘贴链接","粘贴 YouTube / B站 等视频链接，开始解析")
        self._link_row(card,True)
        card=self._card(page);card.pack(fill="x",pady=(0,14))
        self._step(card,2,"保存目录","选择下载文件的保存位置")
        self._directory_row(card,True)
        card=self._card(page);card.pack(fill="x",pady=(0,14))
        self._step(card,3,"选择格式与编码","设置下载的画质、格式和编码选项")
        formats=ctk.CTkFrame(card,fg_color="transparent");formats.pack(fill="x",padx=22)
        formats.grid_columnconfigure((0,1,2),weight=1,uniform="format")
        for col,(label,var,values,attr) in enumerate([
            ("画质",self.yt_fmt_var,["最佳画质 (自动)","4K","2K","1080p","720p","480p","360p","仅音频 (MP3)"],"yt_fmt_menu"),
            ("格式",self.yt_container_var,["mp4","mkv","webm"],"yt_container_menu"),
            ("编码 / 容器",self.yt_codec_var,["H.264","H.265 (HEVC)","AV1","VP9","不限制"],"yt_codec_menu")]):
            field=ctk.CTkFrame(formats,fg_color="transparent");field.grid(row=0,column=col,sticky="ew",padx=(0 if col==0 else 7,0 if col==2 else 7))
            self._label(field,label,11,color=c["text_secondary"]).pack(anchor="w",padx=12,pady=(0,4))
            menu=ctk.CTkOptionMenu(field,variable=var,values=values,height=42,corner_radius=10,font=(self.ui_font,13),
                fg_color=c["bg_input"],button_color=c["bg_input"],button_hover_color=c["ghost_hover"],
                text_color=c["text_primary"],dropdown_fg_color=c["bg_card"],dropdown_text_color=c["text_primary"],
                dropdown_hover_color=c["accent_bg"],dropdown_font=(self.ui_font,13),dynamic_resizing=False)
            menu.pack(fill="x");setattr(self,attr,menu)
        options=ctk.CTkFrame(card,fg_color="transparent");options.pack(fill="x",padx=24,pady=(10,14))
        self.yt_download_btn=self._button(options,"下载",self._yt_download,True,"download",175,48)
        self.yt_download_btn.pack(side="right",anchor="s")
        left=ctk.CTkFrame(options,fg_color="transparent");left.pack(side="left")
        clip=ctk.CTkFrame(left,fg_color="transparent");clip.pack(anchor="w")
        self.yt_clip_chk=ctk.CTkCheckBox(clip,text="下载片段",variable=self.yt_clip_enabled,command=self._sync_clip,
            font=(self.ui_font,13),text_color=c["text_primary"],fg_color=c["accent"],hover_color=c["accent_hover"],
            checkmark_color=c["on_accent"],border_color=c["text_muted"],corner_radius=5,checkbox_width=20,checkbox_height=20,border_width=2,width=105)
        self.yt_clip_chk.pack(side="left")
        for label,var,attr in [("起始",self.yt_clip_start,"yt_clip_start_entry"),("结束",self.yt_clip_end,"yt_clip_end_entry")]:
            self._label(clip,label,11,color=c["text_secondary"]).pack(side="left",padx=(14,8))
            entry=ctk.CTkEntry(clip,textvariable=var,width=78,height=32,corner_radius=8,border_width=1,border_color=c["border"],fg_color=c["bg_input"],text_color=c["text_primary"],font=(self.ui_font,13))
            entry.pack(side="left");setattr(self,attr,entry)
        self._sync_clip()
        self.yt_sub_chk=ctk.CTkCheckBox(left,text="下载字幕 (SRT)",variable=self.yt_subtitle_enabled,font=(self.ui_font,13),
            text_color=c["text_primary"],fg_color=c["accent"],hover_color=c["accent_hover"],checkmark_color=c["on_accent"],
            border_color=c["text_muted"],corner_radius=5,checkbox_width=20,checkbox_height=20,border_width=2)
        self.yt_sub_chk.pack(anchor="w",pady=(8,0))
        status=self._card(page);status.pack(fill="x",pady=(0,8))
        top=ctk.CTkFrame(status,fg_color="transparent");top.pack(fill="x",padx=22,pady=(9,0))
        self._label(top,"",image=self._img("clock")).pack(side="left",padx=(0,12))
        self.yt_status_label=self._label(top,"就绪",11,color=c["text_secondary"]);self.yt_status_label.pack(side="left")
        self.yt_percent_label=self._label(top,"0%",11,color=c["text_secondary"]);self.yt_percent_label.pack(side="right")
        self.yt_progress_bar=ctk.CTkProgressBar(status,height=4,progress_color=c["accent"],fg_color=c["progress_track"])
        self.yt_progress_bar.pack(fill="x",padx=24,pady=(3,10));self.yt_progress_bar.set(0)
        info=ctk.CTkFrame(status,fg_color=c["bg_input"],border_width=1,border_color=c["border"],corner_radius=10)
        info.pack(fill="x",padx=22,pady=(0,14))
        art=empty_art(True,dark=ctk.get_appearance_mode()=="Dark")
        self._label(info,"",image=ctk.CTkImage(light_image=art,dark_image=art,size=(80,50))).pack(side="left",padx=(20,15),pady=10)
        self.yt_info_label=self._label(info,"暂无下载任务\n粘贴链接并点击「解析视频」开始下载",12,color=c["text_secondary"],justify="left",anchor="w",wraplength=620)
        self.yt_info_label.pack(side="left",fill="x",expand=True,padx=(0,15))

    def _switch_platform(self,platform):
        self.active_platform=platform
        for name,page in self.pages.items():
            page.pack_forget()
            self.platform_buttons[name].configure(fg_color=self.c["bg_card"] if name==platform else "transparent",
                hover_color=self.c["ghost_hover"],text_color=self.c["pink_text"] if name==platform else self.c["text_secondary"])
        self.pages[platform].pack(fill="both",expand=True)

    def _focus_media(self):
        (self.yt_url_entry if self.active_platform=="YouTube" else self.url_entry).focus_set()

    def _sidebar_history(self):
        self._switch_platform("Instagram")
        self.pages["Instagram"]._parent_canvas.yview_moveto(0)
        self.after(60,self._toggle_history)

    def _sync_clip(self):
        for entry in (self.yt_clip_start_entry,self.yt_clip_end_entry):
            entry.configure(state="normal" if self.yt_clip_enabled.get() else "disabled")

    def _show_settings(self):
        popup=ctk.CTkToplevel(self);popup.title("Harmony · 设置");popup.geometry("400x280")
        self._set_window_icon(popup)
        popup.configure(fg_color=self.c["bg_root"]);popup.transient(self);popup.grab_set()
        self._label(popup,"设置",23,True).pack(anchor="w",padx=25,pady=22)
        self._button(popup,"切换浅色 / 深色外观",lambda:(popup.destroy(),self._toggle_theme()),width=340).pack(pady=6)
        self._button(popup,"代理设置",lambda:(popup.destroy(),self._open_proxy_dialog()),width=340).pack(pady=6)
        self._button(popup,"Instagram 登录与 Cookie",lambda:(popup.destroy(),self._show_cookie_guide()),width=340).pack(pady=6)

    def _show_help(self):
        popup=ctk.CTkToplevel(self);popup.title("Harmony · 帮助");popup.geometry("490x520")
        self._set_window_icon(popup)
        popup.configure(fg_color=self.c["bg_root"]);popup.transient(self);popup.grab_set()
        brand=ctk.CTkFrame(popup,fg_color=PRIMARY_BACKGROUND,corner_radius=16)
        brand.pack(fill="x",padx=25,pady=(20,0))
        self._label(brand,"",image=self._brand_image("logo",200)).pack(padx=30,pady=22)
        self._label(popup,"让喜欢的内容，留在身边。",22,True).pack(anchor="w",padx=25,pady=(18,16))
        self._label(popup,"Instagram\n粘贴帖子链接 → 提取 → 选择媒体 → 下载\n左键选择媒体，右键查看预览。\n\nYouTube / B站\n粘贴链接 → 解析视频 → 选择格式 → 下载\n可按需下载片段或 SRT 字幕。",14,justify="left").pack(anchor="w",padx=25)
        self._button(popup,"Instagram 登录帮助",lambda:(popup.destroy(),self._show_cookie_guide()),width=200).pack(anchor="w",padx=25,pady=20)

    def _yt_parse(self):
        if self.yt_running or getattr(self,"yt_parsing",False):return
        url=self.yt_url_var.get().strip()
        if not url:
            self.yt_status_label.configure(text="请先粘贴视频链接",text_color=self.c["warning"]);return
        from urllib.parse import urlparse
        parsed=urlparse(url)
        if parsed.scheme not in ("http","https") or not parsed.netloc:
            self.yt_status_label.configure(text="请输入有效的视频链接",text_color=self.c["warning"]);return
        self.yt_parsing=True
        self.yt_parse_btn.configure(state="disabled",text="解析中…")
        self.yt_download_btn.configure(state="disabled")
        self.yt_status_label.configure(text="正在解析视频信息…",text_color=self.c["accent_text"])
        self._set_yt_progress(0)
        threading.Thread(target=self._yt_parse_worker,args=(url,),daemon=True).start()

    def _yt_parse_worker(self,url):
        try:
            import yt_dlp
            import glob
            import sys
            # 源码布局为 <项目根>/src/harmony_ui.py，上移一级以定位 youtube_cookies.txt / runtime
            BASE_DIR=os.path.dirname(sys.executable) if getattr(sys,"frozen",False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            opts={"quiet":True,"no_warnings":True,"noplaylist":True,"skip_download":True,"socket_timeout":30}
            cookie_path=os.path.join(BASE_DIR,"youtube_cookies.txt")
            if os.path.isfile(cookie_path):opts["cookiefile"]=cookie_path
            nodes=glob.glob(os.path.join(BASE_DIR,"runtime","node","*","node.exe"))
            if nodes:opts["js_runtimes"]={"node":{"path":nodes[0]}}
            with yt_dlp.YoutubeDL(opts) as ydl:info=ydl.extract_info(url,download=False)
            if not info:raise ValueError("未能获取视频信息")
            duration=int(info.get("duration") or 0)
            heights=sorted({f.get("height") for f in info.get("formats",[]) if f.get("height")},reverse=True)
            quality=" / ".join(f"{h}p" for h in heights[:6])
            summary=f"{info.get('title','视频')}\n时长 {duration//60}:{duration%60:02d}"+(f"  ·  可用画质 {quality}" if quality else "")
            self.after(0,lambda:self._yt_parse_done(url,summary,None))
        except Exception as exc:
            self.after(0,lambda message=str(exc):self._yt_parse_done(url,None,message))

    def _yt_parse_done(self,url,summary,error):
        self.yt_parsing=False
        self.yt_parse_btn.configure(state="normal",text="解析视频")
        self.yt_download_btn.configure(state="normal")
        if url!=self.yt_url_var.get().strip():
            self.yt_status_label.configure(text="链接已更改，请重新解析",text_color=self.c["warning"]);return
        self.yt_status_label.configure(text="解析失败，请检查链接或网络" if error else "解析完成，请选择格式后下载",
                                        text_color=self.c["error" if error else "success_text"])
        self.yt_info_label.configure(text=(error[:240] if error else summary))

    def _set_yt_status(self,message):
        # Downloader reports its outcome through messages, not a return value.
        if message.startswith(("下载失败:","错误:","内部错误:")):
            tone="error"
        elif message.startswith(("下载完成:","片段下载完成:")):
            tone="success_text"
        else:
            tone="accent_text"
        self.yt_status_label.configure(text=message,text_color=self.c[tone])

    def _set_yt_progress(self,value):
        value=max(0,min(1,float(value)))
        self.yt_progress_bar.set(value)
        self.yt_progress_bar.configure(progress_color=self.c["success" if value>=1 else "accent"])
        self.yt_percent_label.configure(text=f"{value:.0%}")
