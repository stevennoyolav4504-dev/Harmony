"""Retained page graphics with native text editing.

Page decoration and actions share one Tk canvas. Layout changes move retained
items instead of resizing a tree of native frame/canvas/label windows. Dialogs
continue to use CustomTkinter; this renderer is confined to the two main pages.
"""
from __future__ import annotations

from functools import lru_cache
import math
import sys
from types import SimpleNamespace
import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from harmony_surfaces import _scaled_hero, _wash_base, wash, button_surface

if sys.platform=='win32':
    from windows_scene import Canvas as WindowsCanvas, Bitmap as WindowsBitmap
else:
    WindowsCanvas=WindowsBitmap=None


def _pair(value):
    return tuple(value) if isinstance(value, (tuple, list)) else (value, value)


def _anchor(anchor, width, height):
    if anchor == 'center': return width/2, height/2
    return (0 if 'w' in anchor else width if 'e' in anchor else width / 2,
            0 if 'n' in anchor else height if 's' in anchor else height / 2)


class _MeasuredFont:
    """Unchanged captions need no repeat Windows font fallback/measurement."""
    def __init__(self,font):
        self.font=font;self._widths={};self._metrics={};self._actual=None;self._settings={}
    def __str__(self):return str(self.font)
    def measure(self,text):
        text=str(text)
        if text not in self._widths:
            if len(self._widths)>=1024:self._widths.clear()
            self._widths[text]=self.font.measure(text)
        return self._widths[text]
    def metrics(self,*options):
        if options not in self._metrics:self._metrics[options]=self.font.metrics(*options)
        return self._metrics[options]
    def actual(self):
        if self._actual is None:self._actual=self.font.actual()
        return self._actual
    def cget(self,name):
        if name not in self._settings:self._settings[name]=self.font.cget(name)
        return self._settings[name]


@lru_cache(maxsize=12)
def _visible_wash(width,height,total_height,offset,dark):
    source=_wash_base(dark)
    return source.resize((width,height),Image.Resampling.BICUBIC,
        box=(0,offset*source.height/total_height,source.width,(offset+height)*source.height/total_height))


@lru_cache(maxsize=128)
def _corner_tiles(radius, border, fill, outline, background):
    """Opaque, small corner tiles avoid Windows' per-pixel alpha draw path."""
    r = max(1, radius); size = 2 * r; scale = 4
    image = Image.new('RGB', (size * scale, size * scale), background)
    painter = ImageDraw.Draw(image)
    painter.rounded_rectangle((0, 0, size*scale-1, size*scale-1), r*scale,
                              fill=outline if border else fill)
    if border:
        painter.rounded_rectangle((border*scale, border*scale,
                                   (size-border)*scale-1, (size-border)*scale-1),
                                  max(0, r-border)*scale, fill=fill)
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    return tuple(image.crop(box) for box in (
        (0, 0, r, r), (r, 0, size, r), (r, r, size, size), (0, r, r, size)))


class Node:
    """Small layout node; it owns canvas items, never a native child window."""
    def __init__(self, parent, **options):
        self.master = parent
        self.scene = parent.scene
        self.tk = self.scene.canvas.tk
        self.options = dict(width=0, height=0, fg_color='transparent',
                            border_width=0, corner_radius=0, state='normal')
        self.options.update(options)
        self.children = []
        parent.children.append(self)
        self.manager = ''
        self.geometry = {}
        self.rect = (0., 0., 0., 0.)
        self._exists = True
        self._visible = False
        self._propagate = True
        self._bindings = {}
        self._columns = {}
        self._rows = {}
        self._items = {}
        self._photos = {}
        self._item_styles = {}
        self._item_coordinates = {}
        self._paint_visible = None
        self._paint_dirty = True
        self._tag = f'node_{id(self)}'
        self._image = options.get('image')
        self._font = options.get('font', ('Microsoft YaHei UI', 13))
        self.scene.invalidate()

    def configure(self, require_redraw=False, **options):
        changed = any(self.options.get(k) != v for k, v in options.items())
        self.options.update(options)
        if 'image' in options: self._image = options['image']
        if 'font' in options: self._font = options['font']
        if changed: self._paint_dirty=True; self.scene.invalidate()
    config = configure

    def cget(self, name): return self.options.get(name)

    def _manage(self, manager, options):
        self.manager = manager
        self.geometry = dict(options)
        before = options.get('before')
        if before in self.master.children:
            self.master.children.remove(self)
            self.master.children.insert(self.master.children.index(before), self)
        self.scene.invalidate()

    def pack(self, **options): self._manage('pack', options)
    def grid(self, **options): self._manage('grid', options)
    def place(self, **options): self._manage('place', options)
    def pack_forget(self): self.manager = ''; self.scene.invalidate()
    grid_forget = grid_remove = place_forget = pack_forget
    def grid_configure(self, **options):
        self.geometry.update(options); self.manager = 'grid'; self.scene.invalidate()
    def grid_info(self): return dict(self.geometry)
    pack_info = place_info = grid_info
    def pack_configure(self,**options):
        self.geometry.update(options);self.manager='pack';self.scene.invalidate()
    def place_configure(self,**options):
        self.geometry.update(options);self.manager='place';self.scene.invalidate()
    def pack_propagate(self, enabled): self._propagate = bool(enabled)
    grid_propagate = pack_propagate
    def grid_columnconfigure(self, columns, **options):
        for index in columns if isinstance(columns, (tuple, list)) else (columns,):
            self._columns[index] = options
        self.scene.invalidate()
    columnconfigure = grid_columnconfigure
    def grid_rowconfigure(self, rows, **options):
        for index in rows if isinstance(rows, (tuple, list)) else (rows,):
            self._rows[index] = options
        self.scene.invalidate()
    rowconfigure = grid_rowconfigure

    def bind(self, sequence, callback, add=None):
        if add == '+': self._bindings.setdefault(sequence, []).append(callback)
        else: self._bindings[sequence] = [callback]
        return sequence
    def unbind(self, sequence, _id=None): self._bindings.pop(sequence, None)
    def _event(self, sequence, event=None):
        event = event or SimpleNamespace(widget=self)
        for callback in tuple(self._bindings.get(sequence, ())):
            callback(event)
    def after(self, *args): return self.scene.canvas.after(*args)
    def after_idle(self, *args): return self.scene.canvas.after_idle(*args)
    def after_cancel(self, *args): return self.scene.canvas.after_cancel(*args)
    def update(self): self.scene.canvas.update()
    def update_idletasks(self): self.scene.canvas.update_idletasks()
    def winfo_exists(self): return self._exists
    def winfo_ismapped(self): return self._visible and self.scene.canvas.winfo_ismapped()
    winfo_viewable = winfo_ismapped
    def winfo_children(self): return list(self.children)
    def winfo_width(self): return round(self.rect[2] * self.scene.scale)
    def winfo_height(self): return round(self.rect[3] * self.scene.scale)
    def winfo_rootx(self): return self.scene.canvas.winfo_rootx() + round(self.rect[0]*self.scene.scale)
    def winfo_rooty(self):
        return self.scene.canvas.winfo_rooty() + round(self.rect[1]*self.scene.scale - self.scene.canvas.canvasy(0))
    def winfo_toplevel(self): return self.scene.canvas.winfo_toplevel()
    def focus_get(self): return self.scene.canvas.focus_get()
    def _get_widget_scaling(self): return self.scene.scale
    def _get_appearance_mode(self): return self.scene.mode.lower()
    def _apply_appearance_mode(self, color): return self.scene.color(color)

    def destroy(self):
        if not self._exists: return
        self._event('<Destroy>')
        for child in list(self.children): child.destroy()
        self.scene.canvas.delete(self._tag)
        if self.scene._hovered is self:self.scene._set_hover(None)
        self._photos.clear()
        self._exists = False
        self.master.children.remove(self)
        self.scene.invalidate()

    def background(self):
        color = self.options.get('fg_color', 'transparent')
        return self.master.background() if color == 'transparent' else self.scene.color(color)

    def font(self): return self.scene.font(self._font)

    def measure(self):
        if not self._propagate or not any(c.manager in ('pack', 'grid') for c in self.children):
            return self.options.get('width', 0), self.options.get('height', 0)
        packed = [child for child in self.children if child.manager == 'pack']
        needed_w = needed_h = used_w = used_h = 0
        for child in packed:
            w, h = child.measure(); g = child.geometry
            w += sum(_pair(g.get('padx', 0))) + 2*g.get('ipadx', 0)
            h += sum(_pair(g.get('pady', 0))) + 2*g.get('ipady', 0)
            needed_w = max(needed_w, used_w + w)
            needed_h = max(needed_h, used_h + h)
            if g.get('side', 'top') in ('left', 'right'): used_w += w
            else: used_h += h
        cols, rows = self._grid_sizes()
        return max(needed_w, sum(cols)), max(needed_h, sum(rows))

    def _grid_sizes(self):
        children = [c for c in self.children if c.manager == 'grid']
        columns = max([c.geometry.get('column', 0)+1 for c in children] + [0])
        rows = max([c.geometry.get('row', 0)+1 for c in children] + [0])
        widths, heights = [0]*columns, [0]*rows
        for child in children:
            w, h = child.measure(); g = child.geometry
            col, row = g.get('column', 0), g.get('row', 0)
            widths[col] = max(widths[col], w+sum(_pair(g.get('padx', 0))))
            heights[row] = max(heights[row], h+sum(_pair(g.get('pady', 0))))
        groups = {}
        for index, config in self._columns.items():
            if index < len(widths) and config.get('uniform'):
                groups.setdefault(config['uniform'], []).append(index)
        for indices in groups.values():
            maximum = max(widths[i] for i in indices)
            for index in indices: widths[index] = maximum
        return widths, heights

    def _layout(self, rect, visible=True):
        previous = self.rect
        was_visible=self._visible
        self.rect = rect
        self._visible = visible
        if visible:
            if isinstance(self,Button):self.scene._hit_regions.append(self)
            if (not isinstance(self,Label) or isinstance(self,Button) or self._paint_dirty
                    or not was_visible or previous!=rect or self.options.get('fg_color')!='transparent'
                    or getattr(self,'_paint_scale',None)!=self.scene.scale):
                self.paint();self._paint_dirty=False;self._paint_scale=self.scene.scale
        else: self.show(False)
        if previous[2:] != rect[2:] and visible:
            self._event('<Configure>', SimpleNamespace(widget=self, width=self.winfo_width(), height=self.winfo_height()))
        x, y, width, height = rect
        cavity = [x, y, max(0, width), max(0, height)]
        packed = [c for c in self.children if c.manager == 'pack']
        horizontal = [c for c in packed if c.geometry.get('side', 'top') in ('left', 'right')]
        vertical = [c for c in packed if c not in horizontal]
        extra_w = max(0, width - sum(c.measure()[0]+sum(_pair(c.geometry.get('padx', 0))) for c in horizontal))
        extra_h = max(0, height - sum(c.measure()[1]+sum(_pair(c.geometry.get('pady', 0))) for c in vertical))
        expand_w = sum(bool(c.geometry.get('expand')) for c in horizontal)
        expand_h = sum(bool(c.geometry.get('expand')) for c in vertical)
        for child in packed:
            g = child.geometry; side = g.get('side', 'top'); w, h = child.measure()
            px, py = _pair(g.get('padx', 0)), _pair(g.get('pady', 0))
            if side in ('left', 'right'):
                extent = w+sum(px)+(extra_w/expand_w if g.get('expand') and expand_w else 0)
                parcel = (cavity[0] if side == 'left' else cavity[0]+cavity[2]-extent, cavity[1], extent, cavity[3])
                if side == 'left': cavity[0] += extent
                cavity[2] = max(0, cavity[2]-extent)
            else:
                extent = h+sum(py)+(extra_h/expand_h if g.get('expand') and expand_h else 0)
                parcel = (cavity[0], cavity[1] if side == 'top' else cavity[1]+cavity[3]-extent, cavity[2], extent)
                if side == 'top': cavity[1] += extent
                cavity[3] = max(0, cavity[3]-extent)
            area = (parcel[0]+px[0], parcel[1]+py[0], max(0, parcel[2]-sum(px)), max(0, parcel[3]-sum(py)))
            fill = g.get('fill', '')
            actual_w = area[2] if fill in ('x', 'both') else min(w, area[2])
            actual_h = area[3] if fill in ('y', 'both') else min(h, area[3])
            ox, oy = _anchor(g.get('anchor', 'center'), area[2]-actual_w, area[3]-actual_h)
            child._layout((area[0]+ox, area[1]+oy, actual_w, actual_h), visible)
        widths, heights = self._grid_sizes()
        for sizes, available, settings in ((widths, width, self._columns), (heights, height, self._rows)):
            total_weight = sum(settings.get(i, {}).get('weight', 0) for i in range(len(sizes)))
            extra = max(0, available-sum(sizes))
            if total_weight:
                for i in range(len(sizes)): sizes[i] += extra*settings.get(i, {}).get('weight', 0)/total_weight
        for child in self.children:
            if child.manager == 'grid':
                g = child.geometry; col, row = g.get('column', 0), g.get('row', 0)
                px, py = _pair(g.get('padx', 0)), _pair(g.get('pady', 0))
                area = (x+sum(widths[:col])+px[0], y+sum(heights[:row])+py[0], max(0, widths[col]-sum(px)), max(0, heights[row]-sum(py)))
                w, h = child.measure(); sticky = g.get('sticky', '')
                w = area[2] if 'e' in sticky and 'w' in sticky else min(w, area[2])
                h = area[3] if 'n' in sticky and 's' in sticky else min(h, area[3])
                ox, oy = _anchor(sticky, area[2]-w, area[3]-h)
                child._layout((area[0]+ox, area[1]+oy, w, h), visible)
            elif child.manager == 'place':
                g = child.geometry; w, h = child.measure()
                w, h = g.get('width', w), g.get('height', h)
                ax, ay = _anchor(g.get('anchor', 'nw'), w, h)
                child._layout((x+g.get('x', 0)+g.get('relx', 0)*width-ax, y+g.get('y', 0)+g.get('rely', 0)*height-ay, w, h), visible)
            elif not child.manager: child._layout(child.rect, False)

    def item(self, name, kind, coordinates, **style):
        canvas = self.scene.canvas
        if name not in self._items:
            self._items[name] = getattr(canvas, 'create_'+kind)(*coordinates, tags=self._tag, **style)
            self._item_styles[name] = style
        else:
            item = self._items[name]
            if self._item_coordinates.get(name) != tuple(coordinates): canvas.coords(item, *coordinates)
            if self._item_styles.get(name) != style:
                canvas.itemconfigure(item, **style); self._item_styles[name] = style
        self._item_coordinates[name] = tuple(coordinates)
        return self._items[name]

    def show(self, visible=True):
        if self._paint_visible != visible:
            self.scene.canvas.itemconfigure(self._tag, state='normal' if visible else 'hidden')
            self._paint_visible=visible

    def paint(self):
        self.show()
        fill = self.options.get('fg_color', 'transparent')
        if fill == 'transparent' and not self.options.get('border_width'): return
        x, y, w, h = (round(v*self.scene.scale) for v in self.rect)
        y-=self.scene._viewport_y
        if y+h<0 or y>=self.scene._backdrop.height:return
        if min(w, h) <= 0: return
        r = min(round(self.options.get('corner_radius', 0)*self.scene.scale), w//2, h//2)
        b = round(self.options.get('border_width', 0)*self.scene.scale)
        fg = self.background(); bg = self.master.background()
        border = self.scene.color(self.options.get('border_color', fg))
        # All card surfaces are composed into one opaque page bitmap. Text,
        # media and interactive hit regions remain separate retained items.
        painter=ImageDraw.Draw(self.scene._backdrop)
        painter.rectangle((x+r,y,x+w-r,y+h),fill=border if b else fg)
        painter.rectangle((x,y+r,x+w,y+h-r),fill=border if b else fg)
        if b:
            painter.rectangle((x+r,y+b,x+w-r,y+h-b),fill=fg)
            painter.rectangle((x+b,y+r,x+w-b,y+h-r),fill=fg)
        if r:
            for tile,point in zip(_corner_tiles(r,b,fg,border,bg),((x,y),(x+w-r,y),(x+w-r,y+h-r),(x,y+h-r))):
                self.scene._backdrop.paste(tile,point)
        dash=self.options.get('dash_color')
        if dash:
            radius=max(2,round(10*self.scene.scale))
            for left in range(x+radius,x+w-radius,7):
                painter.line((left,y+1,min(left+4,x+w-radius),y+1),fill=dash)
                painter.line((left,y+h-1,min(left+4,x+w-radius),y+h-1),fill=dash)
            for top in range(y+radius,y+h-radius,7):
                painter.line((x+1,top,x+1,min(top+4,y+h-radius)),fill=dash)
                painter.line((x+w-1,top,x+w-1,min(top+4,y+h-radius)),fill=dash)
            for box,start in (((x+1,y+1,x+2*radius,y+2*radius),180),((x+w-2*radius,y+1,x+w-1,y+2*radius),270),((x+w-2*radius,y+h-2*radius,x+w-1,y+h-1),0),((x+1,y+h-2*radius,x+2*radius,y+h-1),90)):
                for angle in range(start,start+90,30):painter.arc(box,angle,angle+15,fill=dash)



class Label(Node):
    def __init__(self,parent,**options):
        options.setdefault('height',28)
        super().__init__(parent,**options)
    def measure(self):
        text = str(self.options.get('text', ''))
        font = self.font(); wrap = self.options.get('wraplength', 0)
        lines = text.split('\n')
        width = max((font.measure(line) for line in lines), default=0)/self.scene.scale
        height = font.metrics('linespace')*len(lines)/self.scene.scale
        if wrap and width > wrap:
            height *= math.ceil(width/wrap); width = wrap
        image = self.options.get('image')
        iw, ih = image.cget('size') if isinstance(image, ctk.CTkImage) else (0, 0)
        compound = self.options.get('compound', 'center')
        width = width+iw if compound in ('left', 'right') else max(width, iw)
        height = height+ih if compound in ('top', 'bottom') else max(height, ih)
        return max(self.options.get('width', 0), width+2*self.options.get('padx', 0)), max(self.options.get('height', 28), height)

    def paint(self):
        super().paint()
        s = self.scene.scale; x, y, w, h = (v*s for v in self.rect)
        font = self.font(); text = self.options.get('text', ''); image = self.options.get('image')
        iw, ih = image.cget('size') if isinstance(image, ctk.CTkImage) else (0, 0)
        iw *= s; ih *= s
        compound = self.options.get('compound', 'center')
        tw = max((font.measure(line) for line in str(text).split('\n')), default=0)
        gap=self.options.get('image_gap',0)*s if image and text else 0
        total = tw+iw+gap if compound in ('left', 'right') else max(tw, iw)
        anchor = self.options.get('anchor', 'center'); padding = self.options.get('padx', 0)*s
        if anchor == 'center': anchor = ''
        left = x+padding if 'w' in anchor else x+w-padding-total if 'e' in anchor else x+(w-total)/2
        text_x = left+iw+gap if image and compound == 'left' else left
        if image:
            if self.scene.native_renderer:
                key=(id(image),s,self.scene.mode)
                if self._photos.get('image_key')!=key:
                    source=image.cget('dark_image' if self.scene.mode=='Dark' else 'light_image')
                    if source is None:source=image.cget('light_image' if self.scene.mode=='Dark' else 'dark_image')
                    self._photo=WindowsBitmap(source.resize((round(iw),round(ih)),Image.Resampling.LANCZOS))
                    self._photos['image_key']=key
                photo=self._photo
            else:photo = image.create_scaled_photo_image(s, self.scene.mode.lower())
            self._photo = photo
            self.item('image', 'image', (left+iw/2 if compound != 'right' else left+tw+gap+iw/2, y+h/2), image=photo)
        color = self.scene.color(self.options.get('text_color', '#14162F'))
        available=max(0,round(x+w-text_x-padding))
        if not self.options.get('wraplength') and '\n' not in str(text) and font.measure(str(text))>available:
            original=str(text);left_index,right_index=0,len(original)
            while left_index<right_index:
                middle=(left_index+right_index+1)//2
                if font.measure(original[:middle]+'…')<=available:left_index=middle
                else:right_index=middle-1
            text=original[:left_index]+'…' if available>font.measure('…') else ''
        self.item('text', 'text', (text_x, y+h/2), text=text, font=font,
                  anchor='w', fill=color, justify=self.options.get('justify', 'center'),
                  width=min(round(self.options.get('wraplength', 0)*s),tw) if self.options.get('wraplength') else 0)


class Button(Label):
    def __init__(self, parent, **options):
        options.setdefault('width', 140); options.setdefault('height', 28)
        options.setdefault('compound', 'left'); options.setdefault('corner_radius', 6)
        options.setdefault('image_gap',10 if options.get('gradient') else 6)
        options.setdefault('padx',6)
        super().__init__(parent, **options)
        self._enabled_fill=options.get('fg_color','transparent')
        self._enabled_image=options.get('image')
        self._mouse_inside = False

    def configure(self,require_redraw=False,**options):
        if 'fg_color' in options:self._enabled_fill=options['fg_color']
        if 'image' in options:self._enabled_image=options['image']
        state=options.get('state',self.options.get('state'))
        if 'disabled_fg_color' in self.options:
            options['fg_color']=self.options['disabled_fg_color'] if state=='disabled' else self._enabled_fill
        super().configure(require_redraw,**options)

    def measure(self): return self.options.get('width', 140), self.options.get('height', 28)
    def invoke(self):
        if self.options.get('state') != 'disabled' and self.options.get('command'):
            return self.options['command']()
    def _hover(self, inside):
        if inside != self._mouse_inside:
            self._mouse_inside = inside; self.scene.invalidate()
    def paint(self):
        original = self.options.copy()
        disabled = self.options.get('state') == 'disabled'
        if disabled:
            self.options['fg_color'] = self.options.get('disabled_fg_color', '#E7E8EF')
            self.options['text_color'] = self.options.get('text_color_disabled', '#9B9FB5')
        elif self._mouse_inside: self.options['fg_color'] = self.options.get('hover_color', self.background())
        gradient = self.options.get('gradient')
        if gradient:
            self.show()
            x, y, w, h = (round(v*self.scene.scale) for v in self.rect)
            start, end = gradient
            if disabled: start, end = ('#FFB7D0', '#F47BBB') if start == '#FF9FB5' else ('#AFCEEF', '#92B7E9')
            elif self._mouse_inside: start, end = end, self.scene.color(self.options.get('hover_color', end))
            key = (w, h, start, end)
            if self._photos.get('gradient_key') != key:
                self._gradient_photo = self.scene.photo(button_surface(max(1,w),max(1,h),round(10*self.scene.scale),start,end))
                self._photos['gradient_key'] = key
            self.item('gradient', 'image', (x, y), image=self._gradient_photo, anchor='nw')
            self.options['fg_color'] = 'transparent'
            self.options['text_color'] = '#FFFFFF'
        Label.paint(self)
        self.options = original


class NativeControl(Node):
    native = None
    def paint(self):
        super().paint()
        if not self.native: return
        x, y, w, h = self.native_rect()
        item = self.item('native', 'window', (round(x), round(y)), window=self.native,
                         width=max(1,round(w)), height=max(1,round(h)), anchor='nw')
        self.scene.canvas.tag_raise(item)
    def native_rect(self):
        return tuple(v*self.scene.scale for v in self.rect)
    def bind(self, sequence, callback, add=None):
        if sequence in ('<Configure>', '<Destroy>'): return super().bind(sequence, callback, add)
        return self.native.bind(sequence, callback, add)
    def focus_set(self): return self.native.focus_set()
    def destroy(self):
        if self._exists:
            super().destroy(); self.native.destroy()


class Entry(NativeControl):
    def __init__(self, parent, **options):
        options.setdefault('width', 140); options.setdefault('height', 28)
        options.setdefault('corner_radius', 6)
        super().__init__(parent, **options)
        self.native = self._entry = tk.Entry(self.scene.canvas, borderwidth=0, highlightthickness=0,
            font=self.font(), textvariable=options.get('textvariable'), exportselection=True)
        self._native_key = None
    def native_rect(self):
        x, y, w, h = self.rect; inset = min(max(6, self.options.get('corner_radius', 6)), h/2)
        return tuple(v*self.scene.scale for v in (x+inset, y+1, max(1,w-2*inset), max(1,h-3)))
    def paint(self):
        key = (self.scene.scale, self.background(), self.options.get('text_color', '#10132B'), self.options.get('state', 'normal'),str(self._font))
        if self._native_key != key:
            self.native.configure(font=self.font(), bg=key[1], fg=self.scene.color(key[2]),
                insertbackground=self.scene.color(key[2]), disabledbackground=key[1],
                disabledforeground='#9297AA', state=key[3])
            self._native_key = key
            for child in self.native.winfo_children():
                if isinstance(child,Hint):child.configure(font=self.font())
        super().paint()
    def get(self): return self.native.get()
    def insert(self, *args): return self.native.insert(*args)
    def delete(self, *args): return self.native.delete(*args)
    def icursor(self, *args): return self.native.icursor(*args)


class Hint(tk.Label):
    """The only overlaid label is a real child of its native editable field."""
    def __init__(self, parent, **options):
        self.scene = parent.scene
        self._label = self
        super().__init__(parent.native, text=options.get('text', ''), font=parent.font(),
            fg=self.scene.color(options.get('text_color', '#999EBB')),
            bg=parent.background(), bd=0, padx=0, pady=0, anchor='w', cursor='xterm')


class Textbox(NativeControl):
    def __init__(self, parent, **options):
        options.setdefault('width', 200); options.setdefault('height', 200)
        super().__init__(parent, **options)
        self.native = tk.Text(self.scene.canvas, borderwidth=0, highlightthickness=0,
            font=self.font(), wrap='word', undo=True, bg=self.background(),
            fg=self.scene.color(options.get('text_color', '#10132B')), padx=3, pady=3)
        self._native_scale=self.scene.scale
    def paint(self):
        if self._native_scale!=self.scene.scale:
            self.native.configure(font=self.font());self._native_scale=self.scene.scale
        super().paint()
    def native_rect(self):
        x, y, w, h = self.rect
        return tuple(v*self.scene.scale for v in (x+7, y+3, max(1,w-14), max(1,h-6)))
    def get(self, *args): return self.native.get(*args)
    def insert(self, *args): return self.native.insert(*args)
    def delete(self, *args): return self.native.delete(*args)


class CheckBox(Button):
    def __init__(self, parent, **options):
        options.setdefault('width', 100); options.setdefault('height', 24)
        super().__init__(parent, **options)
        self.variable = options.get('variable') or tk.IntVar(master=self.scene.canvas)
        self._trace = self.variable.trace_add('write', lambda *_: self.scene.invalidate())
    def get(self): return self.variable.get()
    def select(self): self.variable.set(1)
    def deselect(self): self.variable.set(0)
    def invoke(self):
        if self.options.get('state') == 'disabled': return
        self.variable.set(not self.get())
        if self.options.get('command'): self.options['command']()
    def paint(self):
        self.show()
        s = self.scene.scale; x,y,w,h = (v*s for v in self.rect)
        size = self.options.get('checkbox_width', 20)*s
        selected = bool(self.get()); fill = self.scene.color(self.options.get('fg_color', '#348AFF')) if selected else self.master.background()
        border = fill if selected else self.scene.color(self.options.get('border_color', '#737B95'))
        left,top=round(x),round(y+(h-size)/2)-self.scene._viewport_y;size=round(size);radius=round(self.options.get('corner_radius',5)*s)
        painter=ImageDraw.Draw(self.scene._backdrop)
        painter.rounded_rectangle((left,top,left+size-1,top+size-1),radius=radius,fill=fill,outline=border,width=round(2*s))
        self.item('check_mark', 'text', (x+size/2,y+h/2), text='✓' if selected else '', font=self.scene.font(('Segoe UI',16,'bold')), fill=self.scene.color(self.options.get('checkmark_color','#FFFFFF')))
        self.item('text', 'text', (x+size+8*s,y+h/2), text=self.options.get('text',''), anchor='w', font=self.font(), fill=self.scene.color(self.options.get('text_color','#10132B')))
    def destroy(self):
        if self._exists: self.variable.trace_remove('write', self._trace)
        super().destroy()


class OptionMenu(Button):
    def __init__(self, parent, **options):
        options.setdefault('width', 140); options.setdefault('height', 28)
        options.setdefault('corner_radius', 6)
        super().__init__(parent, **options)
        self.variable = options.get('variable') or tk.StringVar(master=self.scene.canvas)
        self._trace = self.variable.trace_add('write', lambda *_: self.scene.invalidate())
        self.menu = tk.Menu(self.scene.canvas, tearoff=False, bg=self.background(),
            fg=self.scene.color(options.get('dropdown_text_color','#10132B')),
            activebackground=self.scene.color(options.get('dropdown_hover_color','#E8F1FF')),
            font=self.scene.font(options.get('dropdown_font', self._font)))
        for value in options.get('values', ()):
            self.menu.add_command(label=value, command=lambda v=value:self.set(v, notify=True))
    def set(self, value, notify=False):
        self.variable.set(value)
        if notify and self.options.get('command'): self.options['command'](value)
    def get(self): return self.variable.get()
    def invoke(self):
        if self.options.get('state') != 'disabled':
            self.menu.tk_popup(self.winfo_rootx(), self.winfo_rooty()+self.winfo_height())
    def paint(self):
        self.options['text'] = self.variable.get(); self.options['anchor'] = 'w'; self.options['padx'] = 16
        super().paint()
        x,y,w,h = (v*self.scene.scale for v in self.rect)
        self.item('arrow', 'text', (x+w-18*self.scene.scale,y+h/2), text='⌄', font=self.font(), fill=self.scene.color(self.options.get('text_color','#10132B')))
    def destroy(self):
        if self._exists:
            self.variable.trace_remove('write', self._trace); self.menu.destroy()
        super().destroy()


class ProgressBar(Node):
    def __init__(self, parent, **options):
        options.setdefault('height', 8); options.setdefault('width', 200)
        super().__init__(parent, **options); self.value = 0
    def get(self): return self.value
    def set(self, value):
        value = max(0,min(1,float(value)))
        if value != self.value: self.value = value; self.scene.invalidate()
    def paint(self):
        self.show()
        x,y,w,h = (round(v*self.scene.scale) for v in self.rect)
        self.item('track','rectangle',(x,y,x+w,y+h),fill=self.background(),outline='',width=0)
        self.item('progress','rectangle',(x,y,x+w*self.value,y+h),fill=self.scene.color(self.options.get('progress_color','#348AFF')),outline='',width=0)


class ActivityLabel(Label):
    def __init__(self, *args, on_message, **options):
        self._on_message = on_message; super().__init__(*args,**options)
    def configure(self, require_redraw=False, **options):
        super().configure(require_redraw, **options)
        if 'text' in options: self._on_message(options['text'])


class Header(Node):
    def __init__(self, parent, platform, colors, font, **options):
        super().__init__(parent, **options)
        self.platform, self.colors, self.face = platform, colors, font
        self._paint_key = None
        self._canvas = self.scene.canvas
        ig = platform == 'Instagram'
        self.title = Label(self, text='社交媒体提取器' if ig else 'YouTube 下载器', font=(font,32,'bold'),text_color=colors['text_heading'],anchor='w')
        self.title.place(x=10,y=21)
        self.subtitle = Label(self,text='Instagram · Threads · X · TikTok · 小红书' if ig else '粘贴 YouTube / B站 等链接，支持多个视频同时下载',font=(font,17),text_color=colors['text_secondary'],anchor='w')
        self.subtitle.place(x=11,y=72)
        self.script = Label(self,text='Save what inspires you  ✦' if ig else 'Videos for a brighter tomorrow  ✦',font=('Segoe Print',18),text_color='#EE81B5' if self.scene.mode=='Light' else '#F0A7CB',anchor='w')
        self.script.place(x=11,y=112)
        self.right = Label(self,text='Collect\n  Inspire\n    Anywhere' if ig else 'Watch\n  Download\n    Keep Forever',font=('Segoe Print',14),text_color='#EF89BD' if self.scene.mode=='Light' else '#EAA8C9',anchor='w',justify='left')
        self.right.place(relx=1,x=-103,y=56)
        self._propagate = False
    def paint(self):
        self.show()
        s=self.scene.scale;x,y,w,h=(v*s for v in self.rect)
        # Artwork is precomposited into the page's opaque background. Tk's
        # Windows alpha path otherwise blends this large image on every paint.
        self._photo=self.scene._wash._photo
        end=self.title.measure()[0]+24
        self.item('capsule','line',(x+(end+13)*s,y+44*s,x+(end+89)*s,y+44*s),width=29*s,capstyle='round',fill=self.colors['pink_bg'])
        self.item('capsule_text','text',(x+(end+13)*s,y+39*s),text='图片 · 视频' if self.platform=='Instagram' else '视频 · 音频',anchor='w',font=self.scene.font((self.face,13,'bold')),fill=self.colors['pink_text'])
        self._paint_key=(round(w),round(h),s,self.scene.mode)


class _Root(Node):
    def __init__(self, scene):
        self.scene=scene;self.children=[];self._columns={};self._rows={};self.options={};self._propagate=True
        self.rect=(0,0,0,0);self._visible=True;self._bindings={};self._tag='scene_root'
    def background(self): return self.scene.background
    def paint(self):
        radius=round(self.scene.root_radius*self.scene.scale)
        if not radius:return
        image=self.scene._backdrop;w,h=image.size;fill=self.scene.background
        painter=ImageDraw.Draw(image)
        painter.rectangle((radius,0,w-radius,h),fill=fill)
        painter.rectangle((0,radius,w,h-radius),fill=fill)
        for tile,point in zip(_corner_tiles(radius,0,fill,fill,self.scene.outer_background),((0,0),(w-radius,0),(w-radius,h-radius),(0,h-radius))):
            image.paste(tile,point)


class SlimScrollbar(tk.Canvas):
    def __init__(self,parent,command,color,background):
        super().__init__(parent,width=12,highlightthickness=0,bd=0,bg=background)
        self.command=command;self.first=0;self.last=1;self.start=None
        self.thumb=self.create_line(6,4,6,20,fill=color,width=6,capstyle='round')
        self.bind('<Configure>',lambda e:self.set(self.first,self.last))
        self.bind('<ButtonPress-1>',self._press)
        self.bind('<B1-Motion>',self._drag)
    def set(self,first,last):
        self.first,self.last=float(first),float(last)
        height=max(1,self.winfo_height()-8)
        self.coords(self.thumb,6,4+self.first*height,6,max(4+self.first*height+12,4+self.last*height))
        self.itemconfigure(self.thumb,state='hidden' if self.last-self.first>=.999 else 'normal')
    def _press(self,event):
        height=max(1,self.winfo_height()-8)
        if self.first*height<=event.y<=self.last*height:self.start=(event.y,self.first)
        else:self.command('moveto',max(0,(event.y-4)/height-(self.last-self.first)/2))
    def _drag(self,event):
        if self.start:
            self.command('moveto',self.start[1]+(event.y-self.start[0])/max(1,self.winfo_height()-8))


class Page(tk.Frame):
    """One scrollable display list, with only entries/text as native children."""
    def __init__(self, parent, decorated=True, scrollable=True, **options):
        self.mode=ctk.get_appearance_mode()
        self.background='#201D23' if self.mode=='Dark' else '#FFF2F8'
        self.background=self.color(options.get('background',self.background))
        self.outer_background=options.get('outer_background',self.background)
        self.root_radius=options.get('root_radius',0)
        self.scale=parent.winfo_toplevel()._get_window_scaling()
        super().__init__(parent,bg=self.outer_background,bd=0,width=round(options.get('width',200)*self.scale),height=round(options.get('height',200)*self.scale))
        self.native_renderer=WindowsCanvas is not None
        self.canvas=(WindowsCanvas if self.native_renderer else tk.Canvas)(self,highlightthickness=0,bd=0,bg=self.outer_background)
        self.canvas.pack(side='left',fill='both',expand=True)
        self._parent_canvas=self.canvas
        self.scene=self
        self._layout_root=_Root(self)
        self._pending=None;self._layout_running=False;self._dirty=False;self._closed=False
        self._fonts={};self._wash=SimpleNamespace(_photo=None)
        self._wash_key=None;self._wash_item=self.canvas.create_image(0,0,anchor='nw')
        self.decorated=decorated
        self._scrollbar=SlimScrollbar(self,self.canvas.yview,options.get('scrollbar_button_color','#DBE2F2'),self.background)
        if scrollable:self._scrollbar.pack(side='right',fill='y')
        self.canvas.configure(yscrollcommand=self._scrollbar.set)
        self.canvas.bind('<Configure>',lambda e:self.invalidate(),add='+')
        self.canvas.bind('<Map>',lambda e:self.invalidate())
        self.canvas.bind('<MouseWheel>',self._wheel)
        self._hit_regions=[];self._hovered=None
        self.canvas.bind('<Motion>',self._motion)
        self.canvas.bind('<Leave>',lambda e:self._set_hover(None))
        self.canvas.bind('<ButtonRelease-1>',self._click)
        self.canvas.bind('<Button-3>',self._right_click)
        self._wheel_binding=self.winfo_toplevel().bind('<MouseWheel>',self._wheel,add='+')
        self.bind('<Destroy>',self._destroyed,add='+')
        self._epoch=0
        self._viewport_y=0
    @property
    def nodes(self): return self._layout_root.children
    def winfo_children(self): return list(self.nodes)
    def color(self, value):
        if isinstance(value,(tuple,list)): return value[0 if self.mode=='Light' else 1]
        return value
    def photo(self,image):
        return WindowsBitmap(image) if self.native_renderer else ImageTk.PhotoImage(image,master=self.canvas)
    def font(self, specification):
        if isinstance(specification,ctk.CTkFont):specification=(specification.cget('family'),specification.cget('size'),specification.cget('weight'))
        specification=tuple(specification)
        key=(specification,self.scale)
        if key not in self._fonts:
            family,size,*style=specification
            self._fonts[key]=_MeasuredFont(tkfont.Font(root=self.canvas,font=(family,-round(abs(size)*self.scale),*style)))
        return self._fonts[key]
    def invalidate(self):
        if self._closed:return
        self._dirty=True
        if self._pending is None and not self._layout_running:self._pending=self.after_idle(self._flush)
    def _flush(self):
        self._pending=None
        if self._closed or not self.canvas.winfo_ismapped():return
        self._layout_running=True;self._dirty=False
        try:
            self._epoch+=1
            self._hit_regions=[]
            self.scale=self.winfo_toplevel()._get_window_scaling()
            width=self.canvas.winfo_width()/self.scale
            height=max(self.canvas.winfo_height()/self.scale,self._layout_root.measure()[1])
            key=(round(width*self.scale),round(height*self.scale),self.mode=='Dark')
            self.canvas.configure(scrollregion=(0,0,key[0],key[1]))
            self._viewport_y=round(self.canvas.canvasy(0)) if self.native_renderer else 0
            visible_height=max(1,self.canvas.winfo_height()) if self.native_renderer else key[1]
            self._backdrop=(_visible_wash(key[0],visible_height,key[1],self._viewport_y,key[2]).copy()
                           if self.decorated else Image.new('RGB',(key[0],visible_height),self.outer_background))
            header=next((node for node in self.nodes if isinstance(node,Header)),None)
            if header is not None:
                self._backdrop.paste(wash(key[0],round(header.options['height']*self.scale),self.mode=='Dark'),(0,-self._viewport_y))
                art=_scaled_hero(header.platform,round(332*self.scale),round(221*self.scale))
                self._backdrop.paste(art,(key[0]-round(410*self.scale),-round(8*self.scale)-self._viewport_y),art)
            self._layout_root._layout((0,0,width,height))
            if self.native_renderer:
                self.canvas.present(self._backdrop,self._wash_item)
                self._wash._photo=self.canvas.buffer
            elif self._wash._photo is None:
                self._wash._photo=ImageTk.PhotoImage(self._backdrop,master=self.canvas)
                self.canvas.itemconfigure(self._wash_item,image=self._wash._photo)
            else:
                self._wash._photo.paste(self._backdrop)
            self._wash_key=key
            if header is not None:header._photo=self._wash._photo
            self.canvas.tag_lower(self._wash_item)
        finally:
            self._layout_running=False
        if self._dirty:self.invalidate()
    def pack(self,*args,**kwargs):
        for name in ('padx','pady'):
            if name in kwargs:
                value=kwargs[name]
                kwargs[name]=tuple(round(v*self.scale) for v in value) if isinstance(value,(tuple,list)) else round(value*self.scale)
        super().pack(*args,**kwargs);self.invalidate()
    def configure(self,**options):
        if 'height' in options: options['height']=round(options['height']*getattr(self,'scale',1))
        super().configure(**options)
    def _wheel(self,event):
        if not self.winfo_ismapped():return
        widget=event.widget
        while widget is not None and not isinstance(widget,Page):
            widget=getattr(widget,'master',None)
        if widget is self:
            self.canvas.yview_scroll(-int(event.delta/120)*3,'units')
            return 'break'
    def _hit(self,event):
        x,y=self.canvas.canvasx(event.x)/self.scale,self.canvas.canvasy(event.y)/self.scale
        return next((node for node in reversed(self._hit_regions) if node._visible and node.rect[0]<=x<node.rect[0]+node.rect[2] and node.rect[1]<=y<node.rect[1]+node.rect[3]),None)
    def _set_hover(self,node):
        if node is self._hovered:return
        if self._hovered and self._hovered.winfo_exists():self._hovered._hover(False)
        self._hovered=node
        if node:node._hover(True)
        self.canvas.configure(cursor='hand2' if node and node.cget('state')!='disabled' else '')
    def _motion(self,event):self._set_hover(self._hit(event))
    def _click(self,event):
        node=self._hit(event)
        if node:node.invoke()
    def _right_click(self,event):
        node=self._hit(event)
        if node:node._event('<Button-3>',event)
    def _destroyed(self,event):
        if event.widget is not self:return
        self._closed=True
        if self._pending is not None:
            self.after_cancel(self._pending);self._pending=None
        self.winfo_toplevel().unbind('<MouseWheel>',self._wheel_binding)
    def destroy(self):
        for node in list(self.nodes):node.destroy()
        super().destroy()


def is_scene(parent): return isinstance(parent,(Node,Page))


def frame(parent, fallback, **options):
    return Node(parent_node(parent),**options) if is_scene(parent) else fallback(parent,**options)


def control(kind, parent, fallback, **options):
    if not is_scene(parent):return fallback(parent,**options)
    if kind=='label' and isinstance(parent,Entry):return Hint(parent,**options)
    return {'label':Label,'button':Button,'entry':Entry,'textbox':Textbox,'checkbox':CheckBox,
            'menu':OptionMenu,'progress':ProgressBar}[kind](parent_node(parent),**options)


class NestedPage(NativeControl):
    def __init__(self,parent,**options):
        super().__init__(parent,**options)
        self.native=Page(self.scene.canvas,decorated=False,background=parent.background(),
                         scrollbar_button_color=options.get('scrollbar_button_color','#DBE2F2'))
        self._parent_canvas=self.native.canvas
    def measure(self): return self.options.get('width',200),self.options.get('height',88)


def parent_node(parent):
    if isinstance(parent,NestedPage): return parent.native._layout_root
    return parent._layout_root if isinstance(parent,Page) else parent


class Controls:
    """Select scene controls only inside pages; retain native CTk dialogs."""
    _kinds={'CTkLabel':'label','CTkButton':'button','CTkEntry':'entry','CTkTextbox':'textbox',
            'CTkCheckBox':'checkbox','CTkOptionMenu':'menu','CTkProgressBar':'progress'}
    def __getattr__(self,name):
        fallback=getattr(ctk,name)
        if name=='CTkScrollableFrame':
            return lambda parent,**kw:NestedPage(parent_node(parent),**kw) if is_scene(parent) else fallback(parent,**kw)
        if name not in self._kinds:return fallback
        return lambda parent,**kw:control(self._kinds[name],parent,fallback,**kw)


controls=Controls()


def _cache_measure(method):
    def measured(self):
        if getattr(self,'_measure_epoch',None)!=self.scene._epoch:
            self._measured=method(self);self._measure_epoch=self.scene._epoch
        return self._measured
    return measured


for _node_type in (Node,Label,Button,NestedPage):
    _node_type.measure=_cache_measure(_node_type.measure)


