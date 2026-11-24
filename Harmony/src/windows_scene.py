"""Windows backing surfaces for Harmony's retained pages.

The display list is drawn into an application-owned DIB, then presented with
one BitBlt. Native entry/text widgets stay above the surface and keep their
normal editing, focus, IME and clipboard behavior. No screen capture, layered
window, global hook or redraw suppression is used.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import itertools
from collections import deque
import tkinter as tk

from PIL import Image, ImageChops


class _BitmapInfo(C.Structure):
    _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),
              ('planes',W.WORD),('bits',W.WORD),('compression',W.DWORD),
              ('image_size',W.DWORD),('xppm',W.LONG),('yppm',W.LONG),
              ('used',W.DWORD),('important',W.DWORD)]


class _Paint(C.Structure):
    _fields_=[('dc',W.HDC),('erase',W.BOOL),('rect',W.RECT),
              ('restore',W.BOOL),('update',W.BOOL),('reserved',C.c_byte*32)]


class _TrackMouse(C.Structure):
    _fields_=[('size',W.DWORD),('flags',W.DWORD),('hwnd',W.HWND),('hover',W.DWORD)]


_PROC=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)


class _WindowClass(C.Structure):
    _fields_=[('size',W.UINT),('style',W.UINT),('procedure',_PROC),
              ('class_extra',C.c_int),('window_extra',C.c_int),('instance',W.HINSTANCE),
              ('icon',W.HICON),('cursor',W.HANDLE),('background',W.HBRUSH),
              ('menu',W.LPCWSTR),('name',W.LPCWSTR),('small_icon',W.HICON)]


u=C.windll.user32;g=C.windll.gdi32;k=C.windll.kernel32;a=C.windll.msimg32


def _declare(library,name,arguments,result):
    method=getattr(library,name);method.argtypes=arguments;method.restype=result
    return method


_declare(k,'GetModuleHandleW',[W.LPCWSTR],W.HMODULE)
_declare(u,'RegisterClassExW',[C.POINTER(_WindowClass)],W.ATOM)
_declare(u,'CreateWindowExW',[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p],W.HWND)
_declare(u,'DefWindowProcW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],C.c_ssize_t)
_declare(u,'SetWindowPos',[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT],W.BOOL)
_declare(u,'BeginDeferWindowPos',[C.c_int],W.HANDLE)
_declare(u,'DeferWindowPos',[W.HANDLE,W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT],W.HANDLE)
_declare(u,'EndDeferWindowPos',[W.HANDLE],W.BOOL)
_declare(u,'DestroyWindow',[W.HWND],W.BOOL)
_declare(u,'BeginPaint',[W.HWND,C.POINTER(_Paint)],W.HDC)
_declare(u,'EndPaint',[W.HWND,C.POINTER(_Paint)],W.BOOL)
_declare(u,'InvalidateRect',[W.HWND,C.c_void_p,W.BOOL],W.BOOL)
_declare(u,'GetClientRect',[W.HWND,C.POINTER(W.RECT)],W.BOOL)
_declare(u,'GetAncestor',[W.HWND,W.UINT],W.HWND)
_declare(u,'MapWindowPoints',[W.HWND,W.HWND,C.POINTER(W.POINT),W.UINT],C.c_int)
_declare(u,'SendMessageW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],C.c_ssize_t)
_declare(u,'IsWindowVisible',[W.HWND],W.BOOL)
_declare(u,'TrackMouseEvent',[C.POINTER(_TrackMouse)],W.BOOL)
_declare(u,'LoadCursorW',[W.HINSTANCE,C.c_void_p],W.HANDLE)
_declare(u,'SetCursor',[W.HANDLE],W.HANDLE)
_declare(u,'FillRect',[W.HDC,C.POINTER(W.RECT),W.HBRUSH],C.c_int)
_declare(u,'DrawTextW',[W.HDC,W.LPCWSTR,C.c_int,C.POINTER(W.RECT),W.UINT],C.c_int)
_declare(g,'CreateCompatibleDC',[W.HDC],W.HDC)
_declare(g,'CreateDIBSection',[W.HDC,C.POINTER(_BitmapInfo),W.UINT,C.POINTER(C.c_void_p),W.HANDLE,W.DWORD],W.HBITMAP)
_declare(g,'SelectObject',[W.HDC,W.HANDLE],W.HANDLE)
_declare(g,'DeleteObject',[W.HANDLE],W.BOOL)
_declare(g,'DeleteDC',[W.HDC],W.BOOL)
_declare(g,'GdiFlush',[],W.BOOL)
_declare(g,'BitBlt',[W.HDC,C.c_int,C.c_int,C.c_int,C.c_int,W.HDC,C.c_int,C.c_int,W.DWORD],W.BOOL)
_declare(g,'SetBkMode',[W.HDC,C.c_int],C.c_int)
_declare(g,'SetTextColor',[W.HDC,W.COLORREF],W.COLORREF)
_declare(g,'CreateSolidBrush',[W.COLORREF],W.HBRUSH)
_declare(g,'GetStockObject',[C.c_int],W.HANDLE)
_declare(g,'SetDCBrushColor',[W.HDC,W.COLORREF],W.COLORREF)
_declare(g,'SetViewportOrgEx',[W.HDC,C.c_int,C.c_int,C.c_void_p],W.BOOL)
_declare(g,'GetViewportOrgEx',[W.HDC,C.POINTER(W.POINT)],W.BOOL)
_declare(g,'SaveDC',[W.HDC],C.c_int)
_declare(g,'RestoreDC',[W.HDC,C.c_int],W.BOOL)
_declare(g,'IntersectClipRect',[W.HDC,C.c_int,C.c_int,C.c_int,C.c_int],C.c_int)
_declare(g,'ExcludeClipRect',[W.HDC,C.c_int,C.c_int,C.c_int,C.c_int],C.c_int)
_declare(g,'CreatePen',[C.c_int,C.c_int,W.COLORREF],W.HPEN)
_declare(g,'MoveToEx',[W.HDC,C.c_int,C.c_int,C.c_void_p],W.BOOL)
_declare(g,'LineTo',[W.HDC,C.c_int,C.c_int],W.BOOL)
_declare(g,'CreateFontW',[C.c_int,C.c_int,C.c_int,C.c_int,C.c_int,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.LPCWSTR],W.HFONT)
_declare(a,'AlphaBlend',[W.HDC,C.c_int,C.c_int,C.c_int,C.c_int,W.HDC,C.c_int,C.c_int,C.c_int,C.c_int,W.DWORD],W.BOOL)


def _color(value):
    if isinstance(value,str) and value.startswith('#'):
        value=value[1:]
        return int(value[:2],16)|(int(value[2:4],16)<<8)|(int(value[4:6],16)<<16)
    return 0


class Bitmap:
    """Own a DC and its selected top-down bitmap, with deterministic release."""
    def __init__(self,image=None,growable=False):
        self.dc=g.CreateCompatibleDC(None)
        if not self.dc:raise C.WinError()
        self.handle=self.previous=self.bits=None;self.size=(0,0)
        self.allocation=(0,0);self.growable=growable
        self.alpha=False
        if image is not None:self.paste(image)
    def paste(self,image):
        width,height=image.size
        if (width>self.allocation[0] or height>self.allocation[1]
                or not self.growable and self.size!=(width,height)):
            if self.handle:
                g.SelectObject(self.dc,self.previous);g.DeleteObject(self.handle)
                self.handle=None
            pointer=C.c_void_p()
            allocated_width=((width+127)//128)*128 if self.growable else width
            allocated_height=((height+127)//128)*128 if self.growable else height
            info=_BitmapInfo(C.sizeof(_BitmapInfo),allocated_width,-allocated_height,1,32,0,0,0,0,0,0)
            handle=g.CreateDIBSection(self.dc,C.byref(info),0,C.byref(pointer),None,0)
            if not handle:raise C.WinError()
            self.previous=g.SelectObject(self.dc,handle)
            self.handle,self.bits,self.allocation=handle,pointer.value,(allocated_width,allocated_height)
        self.size=(width,height)
        if image.mode=='RGBA' and image.getextrema()[3][0]<255:
            r,green,b,alpha=image.split()
            image=Image.merge('RGBA',(ImageChops.multiply(r,alpha),ImageChops.multiply(green,alpha),ImageChops.multiply(b,alpha),alpha))
            pixels=image.tobytes('raw','BGRA',self.allocation[0]*4);self.alpha=True
        else:
            if image.mode!='RGB':image=image.convert('RGB')
            pixels=image.tobytes('raw','BGRX',self.allocation[0]*4);self.alpha=False
        # DIB memory is also used by GDI batches; finish those before CPU writes.
        g.GdiFlush()
        C.memmove(self.bits,pixels,len(pixels))
    def close(self):
        if self.dc:
            if self.handle:
                g.SelectObject(self.dc,self.previous);g.DeleteObject(self.handle)
            g.DeleteDC(self.dc)
        self.dc=self.handle=self.bits=None
    def exchange_storage(self,other):
        """Swap complete DC/bitmap pairs while keeping their owners stable."""
        for name in ('dc','handle','previous','bits','size','allocation','alpha'):
            value=getattr(self,name);setattr(self,name,getattr(other,name));setattr(other,name,value)
    def __del__(self):
        try:self.close()
        except Exception:pass


_owners={}
_class_name='Harmony.RetainedPage.v1'
_registered=False


@_PROC
def _procedure(hwnd,message,wp,lp):
    owner=_owners.get(hwnd)
    if owner is not None:
        try:
            result=owner._message(message,wp,lp)
            if result is not None:return result
        except Exception as error:
            owner.errors.append(str(error))
    return u.DefWindowProcW(hwnd,message,wp,lp)


def _register():
    global _registered
    if _registered:return
    definition=_WindowClass(C.sizeof(_WindowClass),0,_procedure,0,0,k.GetModuleHandleW(None),None,
                            u.LoadCursorW(None,C.c_void_p(32512)),None,None,_class_name,None)
    if not u.RegisterClassExW(C.byref(definition)):raise C.WinError()
    _registered=True


class Canvas(tk.Frame):
    """Canvas-compatible retained items, presented through a native DIB child."""
    def __init__(self,parent,**options):
        for key in ('highlightthickness','bd'):options.pop(key,None)
        super().__init__(parent,bd=0,highlightthickness=0,**options)
        self._background=options.get('bg','#FFF2F8')
        _register()
        self._scene_items={};self._ids=itertools.count(1);self._order=[]
        self._region=(0,0,1,1);self._offset=0.;self._yscroll=None
        self._cursor='';self._fonts={};self._font_info={};self.buffer=None
        self._back_buffer=None;self._committing=False
        self.errors=[];self._closed=False
        self.print_count=0
        self._native_events=deque();self._event_poll=None
        self._tracking_mouse=False
        self.surface=u.CreateWindowExW(0,_class_name,'',0x50000000|0x04000000|0x02000000,
                         0,0,1,1,self.winfo_id(),None,k.GetModuleHandleW(None),None)
        if not self.surface:raise C.WinError()
        _owners[self.surface]=self
        common=C.windll.comctl32
        self._subclass_type=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM,C.c_size_t,C.c_size_t)
        self._print_callback=self._subclass_type(self._print_frame)
        _declare(common,'SetWindowSubclass',[W.HWND,self._subclass_type,C.c_size_t,C.c_size_t],W.BOOL)
        _declare(common,'RemoveWindowSubclass',[W.HWND,self._subclass_type,C.c_size_t],W.BOOL)
        _declare(common,'DefSubclassProc',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],C.c_ssize_t)
        self._common=common;self._print_hosts=set()
        super().bind('<Configure>',self._size,add='+')
        self._event_poll=self.after(8,self._dispatch_events)
    def _size(self,event):
        self._install_print_hosts()
        if self.surface:
            u.SetWindowPos(self.surface,W.HWND(1),0,0,max(1,event.width),max(1,event.height),0x10)
        self._scroll_changed()
    def _install_print_hosts(self):
        client=self.winfo_toplevel().winfo_id()
        for handle in (client,u.GetAncestor(client,2)):
            if handle and handle not in self._print_hosts:
                if not self._common.SetWindowSubclass(handle,self._print_callback,id(self),0):raise C.WinError()
                self._print_hosts.add(handle)
    def _print_frame(self,hwnd,message,wp,lp,_id,_data):
        result=self._common.DefSubclassProc(hwnd,message,wp,lp)
        if message in (0x0317,0x0318) and wp and self.surface and u.IsWindowVisible(self.surface):
            # Complete Tk's top-level print traversal with our native surface.
            # Keep the editor pixels Tk already rendered, including IME/hints.
            saved=g.SaveDC(wp)
            try:
                self.print_count+=1
                point=W.POINT();u.MapWindowPoints(self.surface,hwnd,C.byref(point),1)
                origin=W.POINT();g.GetViewportOrgEx(wp,C.byref(origin))
                g.SetViewportOrgEx(wp,origin.x+point.x,origin.y+point.y,None)
                rect=W.RECT();u.GetClientRect(self.surface,C.byref(rect))
                g.IntersectClipRect(wp,0,0,rect.right,rect.bottom)
                for item in self._scene_items.values():
                    if item['kind']!='window' or item['options'].get('state')=='hidden' or not item.get('_placed'):continue
                    child=item.get('hwnd')
                    if not child or not u.IsWindowVisible(child):continue
                    x,y,width,height=item['_placed']
                    g.ExcludeClipRect(wp,x,y,x+width,y+height)
                self._present(wp)
            except Exception as error:self.errors.append(str(error))
            finally:g.RestoreDC(wp,saved)
        return result
    def _message(self,message,wp,lp):
        if message==0x0014:return 1
        if message==0x000F:
            paint=_Paint();dc=u.BeginPaint(self.surface,C.byref(paint))
            try:self._present(dc)
            finally:u.EndPaint(self.surface,C.byref(paint))
            return 0
        if message in (0x0317,0x0318):self._present(wp);return 0
        if message==0x0020:
            u.SetCursor(u.LoadCursorW(None,C.c_void_p(32649 if self._cursor=='hand2' else 32512)))
            return 1
        sequence={0x0200:'<Motion>',0x0201:'<ButtonPress-1>',0x0202:'<ButtonRelease-1>',0x0204:'<Button-3>'}.get(message)
        if sequence:
            x=C.c_short(lp&0xFFFF).value;y=C.c_short((lp>>16)&0xFFFF).value
            if message==0x0200 and not self._tracking_mouse:
                track=_TrackMouse(C.sizeof(_TrackMouse),2,self.surface,0)
                self._tracking_mouse=bool(u.TrackMouseEvent(C.byref(track)))
            if sequence=='<Motion>' and self._native_events and self._native_events[-1][0]=='<Motion>':self._native_events.pop()
            self._native_events.append((sequence,{'x':x,'y':y}))
            return 0
        if message==0x02A3:
            self._tracking_mouse=False;self._native_events.append(('<Leave>',{}));return 0
        if message==0x020A:
            self._native_events.append(('<MouseWheel>',{'delta':C.c_short((wp>>16)&0xFFFF).value}))
            return 0
        if message==0x0082:_owners.pop(self.surface,None)
        return None
    def _present(self,dc):
        if not dc:return
        rect=W.RECT();u.GetClientRect(self.surface,C.byref(rect))
        width=height=0
        if self.buffer and self.buffer.dc:
            width=min(rect.right,self.buffer.size[0]);height=min(rect.bottom,self.buffer.size[1])
            if width>0 and height>0:g.BitBlt(dc,0,0,width,height,self.buffer.dc,0,0,0x00CC0020)
        # Never erase the area about to receive a complete frame. A separate
        # clear can reach the compositor between GDI operations during scroll.
        if width<rect.right or height<rect.bottom:
            saved=g.SaveDC(dc)
            try:
                g.ExcludeClipRect(dc,0,0,width,height)
                brush=g.GetStockObject(18);g.SetDCBrushColor(dc,_color(self._background))
                u.FillRect(dc,C.byref(rect),brush)
            finally:g.RestoreDC(dc,saved)
    def configure(self,cnf=None,**options):
        if cnf:options.update(cnf)
        if 'yscrollcommand' in options:self._yscroll=options.pop('yscrollcommand')
        if 'scrollregion' in options:self._region=tuple(options.pop('scrollregion'));self._scroll_changed()
        if 'cursor' in options:self._cursor=options['cursor']
        if 'bg' in options:self._background=options['bg']
        if options:super().configure(**options)
    config=configure
    def cget(self,key):
        if key=='scrollregion':return ' '.join(map(str,self._region))
        return super().cget(key)
    def _find(self,target):
        if target=='all':return list(self._order)
        if isinstance(target,int):return [target] if target in self._scene_items else []
        return [i for i in self._order if target in self._scene_items[i]['tags']]
    def _dispatch_events(self):
        self._event_poll=None
        if self._closed:return
        events=list(self._native_events);self._native_events.clear()
        # Native callbacks never enter Tcl: _tkinter's saved thread state is
        # not reentrant from a ctypes WndProc. Dispatch through a normal timer.
        for sequence,options in events:
            if self._closed:break
            self.event_generate(sequence,**options)
        if not self._closed:self._event_poll=self.after(8,self._dispatch_events)
    def _create(self,kind,coordinates,options):
        identity=next(self._ids);tags=options.pop('tags',())
        if isinstance(tags,str):tags=(tags,)
        self._scene_items[identity]={'kind':kind,'coords':tuple(coordinates),'options':options,'tags':tags}
        self._order.append(identity)
        if kind=='window':
            self._scene_items[identity]['hwnd']=options['window'].winfo_id()
            self._place(self._scene_items[identity])
        return identity
    def create_text(self,*coordinates,**options):return self._create('text',coordinates,options)
    def create_image(self,*coordinates,**options):return self._create('image',coordinates,options)
    def create_rectangle(self,*coordinates,**options):return self._create('rectangle',coordinates,options)
    def create_line(self,*coordinates,**options):return self._create('line',coordinates,options)
    def create_window(self,*coordinates,**options):return self._create('window',coordinates,options)
    def coords(self,target,*coordinates):
        items=self._find(target)
        if not items:return []
        if coordinates:
            for identity in items:
                item=self._scene_items[identity];item['coords']=tuple(coordinates)
                if item['kind']=='window':self._place(item)
        return list(self._scene_items[items[0]]['coords'])
    def itemconfigure(self,target,**options):
        for identity in self._find(target):
            item=self._scene_items[identity];item['options'].update(options)
            if item['kind']=='window':self._place(item)
    itemconfig=itemconfigure
    def find_withtag(self,target):return tuple(self._find(target))
    def find_all(self):return tuple(self._order)
    def delete(self,target):
        for identity in self._find(target):
            item=self._scene_items.pop(identity);self._order.remove(identity)
            if item['kind']=='window':item['options']['window'].place_forget()
    def tag_lower(self,target):
        items=self._find(target);self._order=items+[i for i in self._order if i not in items]
    def tag_raise(self,target):
        items=self._find(target);self._order=[i for i in self._order if i not in items]+items
    def _place(self,item):
        # Layout and scroll requests may precede rendering. Editors must stay
        # with the displayed frame until its replacement is completely drawn.
        if not self._committing:return
        options=item['options'];widget=options['window']
        if options.get('state')=='hidden':
            if item.get('_placed') is not None:widget.place_forget();item['_placed']=None
            return
        x,y=item['coords'];w=options.get('width',widget.winfo_reqwidth());h=options.get('height',widget.winfo_reqheight())
        geometry=(round(x),round(y-self._rendered_offset),round(w),round(h))
        if item.get('_placed')!=geometry:
            widget.place(x=geometry[0],y=geometry[1],width=geometry[2],height=geometry[3]);item['_placed']=geometry
            self._window_moves.append((item['hwnd'],geometry))
    def _move_windows(self):
        if not self._window_moves:return
        # Tk's place manager applies geometry in a later idle callback. Commit
        # the native positions in the same frame now; place keeps Tk's layout
        # bookkeeping in agreement when that callback subsequently runs.
        batch=u.BeginDeferWindowPos(len(self._window_moves))
        flags=0x4|0x10|0x100  # NOZORDER | NOACTIVATE | NOCOPYBITS
        if batch:
            for hwnd,geometry in self._window_moves:
                batch=u.DeferWindowPos(batch,hwnd,None,*geometry,flags)
                if not batch:break
        if batch and u.EndDeferWindowPos(batch):return
        for hwnd,geometry in self._window_moves:
            if not u.SetWindowPos(hwnd,None,*geometry,flags):raise C.WinError()
    def canvasx(self,value):return float(value)
    def canvasy(self,value):return float(value)+self._offset
    def yview(self,*arguments):
        if arguments:
            if arguments[0]=='moveto':self.yview_moveto(float(arguments[1]))
            elif arguments[0]=='scroll':self.yview_scroll(int(arguments[1]),arguments[2])
        height=max(1,self._region[3]);return self._offset/height,min(1,(self._offset+self.winfo_height())/height)
    def yview_moveto(self,fraction):
        self._offset=float(fraction)*max(1,self._region[3]);self._scroll_changed()
    def yview_scroll(self,amount,units):
        self._offset+=amount*(self.winfo_height()*.9 if units=='pages' else 20)
        self._scroll_changed()
    def _scroll_changed(self):
        self._offset=max(0,min(self._offset,max(0,self._region[3]-self.winfo_height())))
        if (round(self._offset)!=getattr(self,'_rendered_offset',None)
                and not self.master._layout_running):
            self.master.invalidate()
    def _font(self,font):
        key=str(font)
        if key not in self._font_info:
            settings=font.actual();size=int(font.cget('size'))
            height=size if size<0 else -round(size*self.winfo_fpixels('1i')/72)
            handle=g.CreateFontW(height,0,0,0,700 if settings['weight']=='bold' else 400,
                int(settings['slant']=='italic'),int(settings['underline']),int(settings['overstrike']),
                1,0,0,5,0,settings['family'])
            if not handle:raise C.WinError()
            self._fonts[key]=handle
            self._font_info[key]=(handle,font.metrics('linespace'))
        return self._font_info[key]
    def present(self,background,background_item):
        if self._back_buffer is None:self._back_buffer=Bitmap(growable=True)
        offset=round(self._offset)
        self._back_buffer.paste(background)
        try:self._draw(self._back_buffer.dc,background,background_item,offset)
        finally:g.SetViewportOrgEx(self._back_buffer.dc,0,0,None)
        g.GdiFlush()
        # WM_PAINT always reads the last complete front buffer, including when
        # native messages arrive while layout/text drawing is still in flight.
        if self.buffer is None:self.buffer=Bitmap(growable=True)
        self.buffer.exchange_storage(self._back_buffer)
        self._rendered_offset=offset
        self._window_moves=[]
        self._committing=True
        try:
            for item in self._scene_items.values():
                if item['kind']=='window':self._place(item)
            self._move_windows()
        finally:self._committing=False
        if self._yscroll:self._yscroll(*self.yview())
        u.InvalidateRect(self.surface,None,False)
    def _draw(self,dc,background,background_item,offset):
        g.SetViewportOrgEx(dc,0,-offset,None)
        for identity in self._order:
            if identity==background_item:continue
            item=self._scene_items[identity];options=item['options'];coordinates=item['coords']
            if options.get('state')=='hidden':continue
            kind=item['kind']
            if kind=='image':
                image=options.get('image')
                if not isinstance(image,Bitmap) or not image.dc:continue
                width,height=image.size;x,y=coordinates
                if options.get('anchor','center')!='nw':x-=width/2;y-=height/2
                if y+height<offset or y>offset+background.height:continue
                if image.alpha:a.AlphaBlend(dc,round(x),round(y),width,height,image.dc,0,0,width,height,0x01FF0000)
                else:g.BitBlt(dc,round(x),round(y),width,height,image.dc,0,0,0x00CC0020)
            elif kind=='rectangle':
                if options.get('fill'):
                    rect=W.RECT(*(round(v) for v in coordinates))
                    g.SetDCBrushColor(dc,_color(options['fill']));u.FillRect(dc,C.byref(rect),g.GetStockObject(18))
            elif kind=='line':
                pen=g.CreatePen(0,max(1,round(options.get('width',1))),_color(options['fill']));old=g.SelectObject(dc,pen)
                g.MoveToEx(dc,round(coordinates[0]),round(coordinates[1]),None)
                for index in range(2,len(coordinates),2):g.LineTo(dc,round(coordinates[index]),round(coordinates[index+1]))
                g.SelectObject(dc,old);g.DeleteObject(pen)
            elif kind=='text' and options.get('text'):
                text=str(options['text']);font=options['font'];handle,line_height=self._font(font)
                old=g.SelectObject(dc,handle);g.SetBkMode(dc,1);g.SetTextColor(dc,_color(options.get('fill','#000000')))
                x,y=coordinates;wrap=round(options.get('width',0));flags=0x800  # NOPREFIX
                flags|=0x10 if wrap else 0
                rect=W.RECT(0,0,wrap or 32767,0)
                u.DrawTextW(dc,text,-1,C.byref(rect),flags|0x400)
                width,height=rect.right,rect.bottom
                anchor=options.get('anchor','center')
                left=x if 'w' in anchor else x-width if 'e' in anchor and anchor!='center' else x-width/2
                top=y if 'n' in anchor and anchor!='center' else y-height if 's' in anchor else y-height/2
                rect=W.RECT(round(left),round(top),round(left+(wrap or width)+2),round(top+height+2))
                if options.get('justify')=='center':flags|=1
                elif options.get('justify')=='right':flags|=2
                u.DrawTextW(dc,text,-1,C.byref(rect),flags)
                g.SelectObject(dc,old)
    def destroy(self):
        if self._closed:return
        self._closed=True
        if self._event_poll is not None:
            self.after_cancel(self._event_poll);self._event_poll=None
        if self.surface:
            for handle in self._print_hosts:self._common.RemoveWindowSubclass(handle,self._print_callback,id(self))
            self._print_hosts.clear()
            u.DestroyWindow(self.surface);_owners.pop(self.surface,None);self.surface=None
        if self.buffer:self.buffer.close();self.buffer=None
        if self._back_buffer:self._back_buffer.close();self._back_buffer=None
        for font in self._fonts.values():g.DeleteObject(font)
        self._fonts.clear();self._font_info.clear();self._scene_items.clear()
        super().destroy()
