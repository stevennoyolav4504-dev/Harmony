"""Decorative surfaces; all form controls remain real, interactive widgets."""
from functools import lru_cache
from pathlib import Path
import math
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk


@lru_cache(maxsize=8)
def _hero_asset(platform):
    with Image.open(Path(__file__).parent / "assets" / "ui" / f"{platform.lower()}-hero.png") as image:
        return image.convert("RGBA")


@lru_cache(maxsize=20)
def wash(width, height, dark=False):
    """A soft mesh surface, generated at low resolution and smoothly enlarged."""
    w,h=160,120
    base=(32,29,35) if dark else (255,242,248)
    glows=[(.23,.12,(70,43,63) if dark else (255,217,235),.22),
           (.73,.15,(40,43,68) if dark else (234,241,255),.25),
           (.92,.80,(65,35,56) if dark else (255,225,241),.23),
           (.15,.89,(57,36,53) if dark else (255,222,239),.23)]
    pixels=[]
    for y in range(h):
        for x in range(w):
            rgb=list(base)
            for gx,gy,color,radius in glows:
                weight=.72*math.sin(math.pi*x/w)*math.sin(math.pi*y/h)*math.exp(-((x/w-gx)**2+(y/h-gy)**2)/(2*radius**2))
                rgb=[v+(target-v)*weight for v,target in zip(rgb,color)]
            pixels.append(tuple(round(v) for v in rgb))
    im=Image.new("RGB",(w,h));im.putdata(pixels)
    return im.resize((max(1,width),max(1,height)),Image.Resampling.BICUBIC)


class PageWash(tk.Canvas):
    """A background under page widgets, never a layer over input controls."""
    def __init__(self,parent,dark=False):
        super().__init__(parent,highlightthickness=0,bd=0)
        self.dark=dark
        self.place(x=0,y=0,relwidth=1,relheight=1)
        self.tk.call("lower",self._w)
        self.bind("<Configure>",self._paint)

    def _paint(self,event):
        self._photo=ImageTk.PhotoImage(wash(event.width,event.height,self.dark),master=self)
        self.delete("all");self.create_image(0,0,image=self._photo,anchor="nw")


class HeroHeader(ctk.CTkFrame):
    """Canvas typography avoids opaque label patches over the soft illustration."""
    def __init__(self,parent,platform,colors,font,**kwargs):
        self.platform,self.colors,self.face=platform,colors,font
        self._ready=False
        super().__init__(parent,fg_color=colors["bg_root"],corner_radius=0,**kwargs)
        self._ready=True
        self._draw()

    def _draw(self,no_color_updates=False):
        super()._draw(no_color_updates)
        if not self._ready:return
        s=self._get_widget_scaling()
        w,h=max(1,round(self._current_width*s)),max(1,round(self._current_height*s))
        dark=self._get_appearance_mode()=="dark"
        background=wash(w,h,dark).convert("RGBA")
        # The art stays right-aligned and behind the header's noninteractive text.
        art=_hero_asset(self.platform)
        aw,ah=round(332*s),round(221*s)
        art=art.resize((aw,ah),Image.Resampling.LANCZOS)
        background.alpha_composite(art,(w-round(410*s),round(-8*s)))
        self._photo=ImageTk.PhotoImage(background,master=self)
        canvas=self._canvas
        canvas.delete("hero")
        canvas.create_image(0,0,image=self._photo,anchor="nw",tags="hero")
        def text(x,y,value,size,color,bold=False,font=None):
            return canvas.create_text(x*s,y*s,text=value,anchor="nw",fill=color,
                font=(font or self.face,-round(size*s),"bold" if bold else "normal"),tags="hero")
        ig=self.platform=="Instagram"
        title=text(10,21,"Instagram 媒体提取器" if ig else "YouTube 下载器",32,self.colors["text_heading"],True)
        end=canvas.bbox(title)[2]/s+14
        # Capsule uses a single rounded stroke, so its corners stay smooth at any DPI.
        canvas.create_line((end+13)*s,44*s,(end+89)*s,44*s,width=29*s,
            capstyle="round",fill=self.colors["pink_bg"],tags="hero")
        text(end+13,33,"图片 · 视频" if ig else "视频 · 音频",13,self.colors["pink_text"],True)
        text(11,72,"粘贴 Instagram 帖子链接，提取图片与视频" if ig else "粘贴 YouTube / B站 等链接，下载视频或音频",17,self.colors["text_secondary"])
        text(11,112,"Save what inspires you  ✦" if ig else "Videos for a brighter tomorrow  ✦",18,
             "#EE81B5" if not dark else "#F0A7CB",font="Segoe Print")
        text(w/s-103,56,"Collect\n  Inspire\n    Anywhere" if ig else "Watch\n  Download\n    Keep Forever",14,
             "#EF89BD" if not dark else "#EAA8C9",font="Segoe Print")


class DashedFrame(ctk.CTkFrame):
    def __init__(self,*args,dash_color,**kwargs):
        self._dash_color=dash_color
        super().__init__(*args,**kwargs)

    def _draw(self,no_color_updates=False):
        super()._draw(no_color_updates)
        s=self._get_widget_scaling()
        w,h=self._current_width*s,self._current_height*s
        r=10*s;c=self._canvas
        c.delete("dash_outline")
        common=dict(fill=self._dash_color,width=max(1,s),dash=(round(4*s),round(3*s)),tags="dash_outline")
        for coordinates in [(r,1,w-r,1),(r,h-1,w-r,h-1),(1,r,1,h-r),(w-1,r,w-1,h-r)]:
            c.create_line(*coordinates,**common)
        for box,start in [((1,1,2*r,2*r),90),((w-2*r,1,w-1,2*r),0),
                          ((1,h-2*r,2*r,h-1),180),((w-2*r,h-2*r,w-1,h-1),270)]:
            c.create_arc(*box,start=start,extent=90,style="arc",outline=self._dash_color,
                         width=max(1,s),dash=(3,3),tags="dash_outline")


class ActivityLabel(ctk.CTkLabel):
    """Show the progress area only when there is activity or a useful message."""
    def __init__(self,*args,on_message,**kwargs):
        self._on_message=on_message
        super().__init__(*args,**kwargs)

    def configure(self,require_redraw=False,**kwargs):
        super().configure(require_redraw=require_redraw,**kwargs)
        if "text" in kwargs:self._on_message(kwargs["text"])


@lru_cache(maxsize=40)
def button_surface(width,height,radius,start,end):
    s=2
    w,h=max(2,width*s),max(2,height*s)
    a=tuple(int(start[i:i+2],16) for i in (1,3,5))
    b=tuple(int(end[i:i+2],16) for i in (1,3,5))
    # A small diagonal ramp is scaled before masking to keep corners antialiased.
    ramp=Image.new("RGB",(80,40))
    ramp.putdata([tuple(round(x+(y-x)*(.58*i/79+.42*j/39)) for x,y in zip(a,b))
                  for j in range(40) for i in range(80)])
    im=ramp.resize((w,h),Image.Resampling.BILINEAR).convert("RGBA")
    mask=Image.new("L",(w,h));ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=radius*s,fill=255)
    im.putalpha(mask)
    return im.resize((width,height),Image.Resampling.LANCZOS)
