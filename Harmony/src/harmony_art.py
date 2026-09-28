"""Resolution-independent UI artwork, drawn from simple vector geometry."""
import math
from PIL import Image, ImageDraw
from harmony_brand import app_icon
from harmony_theme import BLUE, PINK, GREEN, COLOR_SCHEMES


def icon(name, color="#252228", size=24):
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
        rect((3,3,21,21),5,outline="#C13584")
        arc((7.5,7.5,16.5,16.5),0,360,fill="#E4405F")
        d.ellipse((16*k,5.5*k,18.5*k,8*k), fill="#F77737")
    elif name in ("youtube", "play"):
        rect((2,5,22,19),4,fill="#E62117" if name=="youtube" else color,outline=None)
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


def hero(platform, width=210, height=114, dark=False):
    """Flat segmented orbit: a UI pattern, separate from the official logo."""
    s=3
    c=COLOR_SCHEMES["Dark" if dark else "Light"]
    im=Image.new("RGBA",(210*s,114*s))
    d=ImageDraw.Draw(im)
    for start,end,color in [(155,245,BLUE),(270,350,PINK),(15,115,GREEN)]:
        points=[((105+82*math.cos(math.radians(t)))*s,
                 (57+43*math.sin(math.radians(t)))*s) for t in range(start,end+1)]
        d.line(points,fill=color,width=5*s,joint="curve")
        for x,y in (points[0],points[-1]):
            d.ellipse((x-2.5*s,y-2.5*s,x+2.5*s,y+2.5*s),fill=color)
    d.rounded_rectangle((75*s,27*s,135*s,87*s),radius=18*s,
                        fill=c["bg_card"],outline=c["border"],width=s)
    im.alpha_composite(icon(platform.lower(),size=34*s),(88*s,40*s))
    return im.resize((width,height),Image.Resampling.LANCZOS)


def empty_art(video=False, dark=False):
    s=3
    im=Image.new("RGBA",(128*s,80*s))
    for color,angle,x,y in [("#DCE5FF",18,14,18),("#FCE0EF",-17,66,4)]:
        tile=Image.new("RGBA",(52*s,59*s))
        ImageDraw.Draw(tile).rounded_rectangle((2*s,2*s,50*s,57*s),radius=5*s,fill=color)
        tile=tile.rotate(angle,Image.Resampling.BICUBIC,expand=True)
        im.alpha_composite(tile,(x*s,y*s))
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((43*s,22*s,99*s,76*s),radius=6*s,fill="#FFC0E2",outline="white",width=2*s)
    if video:
        d.polygon([(63*s,35*s),(63*s,62*s),(83*s,49*s)],fill="white")
    else:
        d.ellipse((68*s,32*s,80*s,44*s),fill="white")
        d.polygon([(49*s,66*s),(62*s,49*s),(73*s,60*s),(81*s,53*s),(94*s,66*s)],fill="white")
    return im.resize((128,80),Image.Resampling.LANCZOS)
