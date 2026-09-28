"""Readability guardrails for the two brand themes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harmony_theme import COLOR_SCHEMES

def luminance(color):
    values=[int(color[i:i+2],16)/255 for i in (1,3,5)]
    channels=[v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in values]
    return sum(v*k for v,k in zip(channels,(0.2126,0.7152,0.0722)))

class ThemeRegression(unittest.TestCase):
    def test_text_remains_readable_on_brand_surfaces(self):
        pairs=[('text_primary','bg_card'),('text_secondary','bg_root'),
               ('text_muted','bg_input'),('on_accent','accent'),('on_success','success'),
               ('accent_text','accent_bg'),('pink_text','pink_bg'),('success_text','success_bg'),
               ('error','bg_card'),('warning','bg_card')]
        for mode,colors in COLOR_SCHEMES.items():
            for foreground,background in pairs:
                bright,dark=sorted((luminance(colors[foreground]),luminance(colors[background])),reverse=True)
                with self.subTest(mode=mode,foreground=foreground,background=background):
                    self.assertGreaterEqual((bright+0.05)/(dark+0.05),4.5)

if __name__=='__main__':unittest.main(verbosity=2)
