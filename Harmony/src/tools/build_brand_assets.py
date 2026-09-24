"""Rebuild Windows and PNG icons from the bundled official REV.06 artwork."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))
from harmony_brand import ICON_SIZES, app_icon


def build():
    master = app_icon(1024)
    master.save(SRC / "assets" / "harmony-icon.png")
    master.save(SRC / "icon.ico", sizes=[(size, size) for size in ICON_SIZES])
    print("Built REV.06 icons: " + ", ".join(map(str, ICON_SIZES)))


if __name__ == "__main__":
    build()
