"""Render the application icon from the master artwork.

The icon is drawn once, at 1024 px, and lives in 'assets'. Everything
the application and the installer need is rendered from it by this
script into 'src/dapkel_rtp/resources', which is the only copy that
ships: the master is artwork no user of the package has any use for.

Run it after the artwork changes, and commit what it writes — the
release build has no image library available to it and does not render
anything itself:

    pip install pillow
    python tools/make_icons.py

Qt is handed every PNG size rather than one large one because it scales
whatever it is given: a 16 px title-bar icon downscaled on the fly from
1024 px loses the hit pattern to blur, while the same size resampled
here, once, with a proper filter, keeps its shape. The '.ico' is what
Windows itself reads — the executable, the desktop shortcut, the
Explorer listing — and holds the same set in one file.

The master is a browser render of 'assets/dapkel-rtp-icon.svg' at
1024 px. Rendering it here instead was tried and rejected twice over:
the SVG's glow is an 'feGaussianBlur' filter, which Qt's own SVG
renderer silently drops, and Pillow reads no SVG at all. To redo it
after the artwork changes, wrap the SVG in a page that sizes it to
1024 px and screenshot that with a headless browser:

    chrome --headless --disable-gpu --window-size=1024,1024
        --default-background-color=00000000
        --screenshot=assets/dapkel-rtp-icon.png file:///<that page>

(one line; a transparent default background is what keeps the tile's
rounded corners from being filled in with white).

The wordmark that the first version of this artwork carried is gone on
purpose: at 16 px it resampled to an illegible smear across the bottom
third of the tile, and it crowded the sensor grid — the one part of the
icon that still reads at that size — into the top.

The SVG's viewBox is cropped to the tile rather than the 512 canvas the
tile was drawn on, and that is deliberate: a transparent margin baked
into artwork is margin Windows still counts as part of the icon, so the
earlier version drew 30px in the 32px slot a taskbar gives, against a
full 32 for VS Code and Paint.

That crop was only half of why this icon read a size smaller than its
neighbours. The other half is that the tile is darker than the taskbar
itself, so the squircle has no silhouette against it and only the lit
cells register as the icon at all -- and on the first artwork those
cells were small. Hence the 5x4 matrix of large cells filling the tile
rather than the 8x6 of small ones it started as: measured on a #1f1f1f
taskbar, it roughly doubled the share of the icon that actually glows.
Shrinking the cells or re-adding the outer margin would undo it.

"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "assets" / "dapkel-rtp-icon.png"
OUT_DIR = ROOT / "src" / "dapkel_rtp" / "resources"

# Sizes Qt is given to choose between. 16 is the title bar, 32 the task
# bar, 256 the largest Explorer view; the rest are the steps in between
# that Windows and the Linux desktops actually ask for.
PNG_SIZES = (16, 32, 48, 64, 128, 256)

# The '.ico' carries 24 as well: Windows uses it for small toolbar and
# jump-list entries, and an icon that lacks a size is stretched to it.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(master: Image.Image, size: int) -> Image.Image:
    """The master at 'size', resampled rather than scaled by Qt."""
    return master.resize((size, size), Image.LANCZOS)


def main() -> int:
    if not MASTER.is_file():
        print("No master artwork at {}".format(MASTER), file=sys.stderr)
        return 1

    master = Image.open(MASTER).convert("RGBA")
    if master.width != master.height:
        print(
            "The master is {}x{}; an icon has to be square.".format(
                master.width, master.height
            ),
            file=sys.stderr,
        )
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for size in PNG_SIZES:
        path = OUT_DIR / "dapkel-rtp-{}.png".format(size)
        render(master, size).save(path, format="PNG", optimize=True)
        print("{:>6} bytes  {}".format(path.stat().st_size, path.name))

    # Pillow would resample these itself, but only from the image it is
    # handed and with a filter of its choosing; rendering them here uses
    # the same path as the PNGs, so the two sets cannot differ.
    frames = [render(master, size) for size in ICO_SIZES]
    ico = OUT_DIR / "dapkel-rtp.ico"
    frames[-1].save(
        ico,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=frames[:-1],
    )
    print("{:>6} bytes  {}".format(ico.stat().st_size, ico.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
