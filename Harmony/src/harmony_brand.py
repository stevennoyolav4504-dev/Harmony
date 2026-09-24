"""Official Harmony REV.06 artwork; never redraw or recolor the brand mark."""
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

PRIMARY_BACKGROUND = "#F9ECF3"
SYMBOL_WIDTH_RATIO = 0.72  # REV.06, page 12: 68–74% of the icon container.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
ASSET_DIR = Path(__file__).resolve().parent / "assets" / "brand"
ASSETS = {
    "symbol": "Harmony_Symbol_FullColor_Transparent.png",
    "symbol_dark": "Harmony_Symbol_Official_Dark.png",
    "symbol_white": "Harmony_Symbol_Official_White.png",
    "logo": "Harmony_Logo_Full_Transparent.png",
    "logo_dark": "Harmony_Logo_Monochrome_Dark.png",
    "logo_white": "Harmony_Logo_Monochrome_White.png",
    "wordmark": "Harmony_Wordmark_Transparent.png",
}


@lru_cache(maxsize=len(ASSETS))
def artwork(kind):
    """Load the original RGBA artwork, trimming only empty outer margins.

    __file__ also resolves inside PyInstaller's _internal directory. White is
    part of the mark, so transparency must come from alpha, never RGB color.
    Callers provide the prescribed clear space and background around the image.
    """
    with Image.open(ASSET_DIR / ASSETS[kind]) as source:
        image = source.convert("RGBA")
    return image.crop(image.getchannel("A").getbbox())


@lru_cache(maxsize=1)
def _app_icon_master():
    """Place the supplied symbol unchanged on the primary background tile."""
    side = 1024
    tile = Image.new("RGBA", (side, side), PRIMARY_BACKGROUND)
    mask = Image.new("L", tile.size)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, side - 1, side - 1), radius=round(side * 0.22), fill=255
    )
    tile.putalpha(mask)
    symbol = artwork("symbol")
    width = round(side * SYMBOL_WIDTH_RATIO)
    height = round(width * symbol.height / symbol.width)
    symbol = symbol.resize((width, height), Image.Resampling.LANCZOS)
    tile.alpha_composite(symbol, ((side - width) // 2, (side - height) // 2))
    return tile


def app_icon(size=256):
    return _app_icon_master().resize((size, size), Image.Resampling.LANCZOS)
