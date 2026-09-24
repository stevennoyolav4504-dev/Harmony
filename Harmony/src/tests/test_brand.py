"""Regressions for official artwork, safe space, and Windows icon frames."""
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageChops

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))
from harmony_brand import ICON_SIZES, PRIMARY_BACKGROUND, app_icon, artwork


class BrandRegression(unittest.TestCase):
    def test_white_is_artwork_not_transparency(self):
        symbol = artwork("symbol")
        self.assertEqual(symbol.getpixel((symbol.width // 2, symbol.height - 20)), (255, 255, 255, 255))
        self.assertEqual(symbol.getchannel("A").getextrema(), (0, 255))
        rendered = app_icon(1024)
        self.assertEqual(rendered.getpixel((512, 747)), (255, 255, 255, 255))
        self.assertEqual(rendered.getpixel((512, 100)), (249, 236, 243, 255))
        self.assertEqual(rendered.getpixel((0, 0))[3], 0)

    def test_symbol_has_prescribed_clear_space_and_proportions(self):
        rendered = app_icon(1024).convert("RGB")
        background = Image.new("RGB", rendered.size, PRIMARY_BACKGROUND)
        # Ignore sub-pixel resampling halos when measuring the visible symbol.
        difference = ImageChops.difference(rendered, background)
        mask = difference.convert("L").point(lambda value: 255 if value > 10 else 0)
        left, top, right, bottom = mask.getbbox()
        self.assertTrue(0.68 <= (right - left) / rendered.width <= 0.74)
        self.assertAlmostEqual((right - left) / (bottom - top),
                               artwork("symbol").width / artwork("symbol").height, delta=0.02)
        self.assertLessEqual(abs(left - (1024 - right)), 2)
        self.assertLessEqual(abs(top - (1024 - bottom)), 2)

    def test_packaged_icon_frames_match_the_brand_renderer(self):
        with Image.open(SRC / "icon.ico") as ico:
            self.assertEqual(ico.ico.sizes(), {(size, size) for size in ICON_SIZES})
            for size in ICON_SIZES:
                actual = ico.ico.getimage((size, size)).convert("RGBA")
                self.assertEqual(actual.tobytes(), app_icon(size).tobytes())
        with Image.open(SRC / "assets" / "harmony-icon.png") as png:
            self.assertEqual(png.size, (1024, 1024))
            self.assertEqual(png.tobytes(), app_icon(1024).tobytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
