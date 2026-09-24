"""Resolution-independent UI artwork, drawn from simple vector geometry."""
import math
from PIL import Image, ImageDraw, ImageFilter
from harmony_brand import app_icon


def icon(name, color="#253064", size=24):
    if name == "logo":
        return app_icon(size)
    scale = 4
    im = Image.new("RGBA", (size * scale, size * scale))
    d = ImageDraw.Draw(im)
    k = size * scale / 24

    def line(points, fill=color, width=1.8):
        xy = [(x*k, y*k) for x, y in points]
        w = max(1, round(width*k))
        d.line(xy, fill=fill, width=w, joint="curve")
        for x, y in (xy[0], xy[-1]):
            d.ellipse((x-w/2, y-w/2, x+w/2, y+w/2), fill=fill)

    def arc(box, start, end, fill=color, width=1.8):
        x0,y0,x1,y1 = box
        points = [((x0+x1)/2+(x1-x0)/2*math.cos(math.radians(t)),
                   (y0+y1)/2+(y1-y0)/2*math.sin(math.radians(t)))
                  for t in range(start, end+1, 2)]
        line(points, fill, width)

    def rect(box, radius=2, fill=None, outline=color, width=1.8):
        d.rounded_rectangle(tuple(v*k for v in box), radius*k, fill, outline, round(width*k))

    if name == "folder":
        line([(3,20),(3,5),(9,5),(11,8),(21,8),(20,20),(3,20)])
    elif name in ("clock", "history"):
        arc((3,3,21,21),0,360)
        line([(12,6),(12,12),(16,14)])
    elif name == "link":
        arc((3,10,13,20),45,280)
        arc((11,3,21,13),225,460)
        line([(8,16),(16,8)])
    elif name == "settings":
        points=[]
        for i in range(49):
            a=math.pi*2*i/48
            r=9 if i%6 in (0,1,4,5) else 7
            points.append((12+r*math.cos(a),12+r*math.sin(a)))
        line(points, width=1.5)
        arc((8.5,8.5,15.5,15.5),0,360,width=1.5)
    elif name == "help":
        arc((3,3,21,21),0,360)
        arc((9,7,15,13),180,460)
        line([(12,13),(12,14)])
        line([(12,17),(12,17.1)])
    elif name == "instagram":
        rect((3,3,21,21),5,outline="#CB46D9")
        arc((7.5,7.5,16.5,16.5),0,360,fill="#EC5AA9")
        d.ellipse((16*k,5.5*k,18.5*k,8*k), fill="#AC50F4")
    elif name in ("youtube", "play"):
        rect((2,5,22,19),4,fill="#FF3158" if name=="youtube" else color,outline=None)
        d.polygon([(10*k,8*k),(16*k,12*k),(10*k,16*k)], fill="white")
    elif name == "download":
        line([(12,3),(12,15)])
        line([(7,10),(12,15),(17,10)])
        line([(4,16),(4,21),(20,21),(20,16)])
    elif name == "arrow":
        line([(4,12),(20,12)])
        line([(14,6),(20,12),(14,18)])
    elif name == "copy":
        rect((8,3,20,17),2)
        rect((4,7,16,21),2)
    elif name == "trash":
        line([(4,6),(20,6)])
        line([(8,6),(8,3),(16,3),(16,6)])
        line([(6,6),(7,21),(17,21),(18,6)])
        line([(10,10),(10,17)])
        line([(14,10),(14,17)])
    elif name == "layers":
        line([(3,8),(12,3),(21,8),(12,13),(3,8)])
        line([(3,12),(12,17),(21,12)])
        line([(3,16),(12,21),(21,16)])
    elif name == "image":
        rect((3,3,21,21),3,fill=color,outline=None)
        d.ellipse((14*k,6*k,18*k,10*k), fill="white")
        d.polygon([(5*k,18*k),(10*k,11*k),(14*k,16*k),(17*k,12*k),(20*k,18*k)],fill="white")
    elif name == "crown":
        d.polygon([(3*k,6*k),(8*k,11*k),(12*k,3*k),(16*k,11*k),(21*k,6*k),(18*k,21*k),(6*k,21*k)],fill="#FFBF61")
    return im.resize((size,size), Image.Resampling.LANCZOS)


def hero(platform, width=470, height=175):
    """Soft orbit illustration, with scalable platform tiles."""
    s=2
    im=Image.new("RGBA",(width*s,height*s))
    glow=Image.new("RGBA", im.size)
    gd=ImageDraw.Draw(glow)
    gd.ellipse((80*s,20*s,380*s,200*s),fill=(192,173,255,65))
    im=Image.alpha_composite(im,glow.filter(ImageFilter.GaussianBlur(28*s)))
    d=ImageDraw.Draw(im)
    d.ellipse((30*s,45*s,360*s,142*s),outline=(255,255,255,220),width=2*s)
    for x,y,sz,angle,primary in [(92,91,66,20,False),(290,115,49,20,False),(180,30,126,17,True)]:
        tile=Image.new("RGBA",(sz*s,sz*s))
        mask=Image.new("L",tile.size)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,sz*s-1,sz*s-1),radius=20*s,fill=255)
        td=ImageDraw.Draw(tile)
        a,b=((255,164,201),(185,130,246)) if platform=="Instagram" else ((255,166,203),(247,83,150))
        if not primary: a,b=(221,217,255),(180,177,248)
        for yy in range(sz*s):
            t=yy/(sz*s)
            td.line((0,yy,sz*s,yy),fill=tuple(int(a[i]*(1-t)+b[i]*t) for i in range(3))+((230 if primary else 140),))
        tile.putalpha(mask)
        if primary and platform=="Instagram":
            inset=sz*.25*s
            td=ImageDraw.Draw(tile)
            td.rounded_rectangle((inset,inset,sz*s-inset,sz*s-inset),radius=15*s,outline="white",width=5*s)
            td.ellipse((sz*.38*s,sz*.38*s,sz*.62*s,sz*.62*s),outline="white",width=4*s)
            td.ellipse((sz*.62*s,sz*.29*s,sz*.68*s,sz*.35*s),fill="white")
        else:
            td=ImageDraw.Draw(tile)
            td.polygon([(sz*.40*s,sz*.30*s),(sz*.40*s,sz*.70*s),(sz*.72*s,sz*.5*s)], fill=(255,255,255,235))
        tile=tile.rotate(angle,Image.Resampling.BICUBIC,expand=True)
        im.alpha_composite(tile,(int(x*s),int(y*s)))
    return im.resize((width,height),Image.Resampling.LANCZOS)


def empty_art(video=False):
    im=Image.new("RGBA",(128,80))
    for x,y,sz,angle in [(13,18,50,18),(63,6,54,-18),(38,24,55,0)]:
        tile=icon("play" if video else "image", "#D5CAFF",sz)
        tile=tile.rotate(angle,Image.Resampling.BICUBIC,expand=True)
        im.alpha_composite(tile,(x,y))
    return im
