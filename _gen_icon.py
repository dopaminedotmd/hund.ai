"""Dev-only: generate hund.ico from the single-frame mascot PNG.

Run with the repo venv (Pillow is a dev dependency, not a runtime dep):
    .venv/Scripts/python.exe _gen_icon.py
"""
from pathlib import Path

from PIL import Image

SRC = Path("hund/assets/mascot/Dog_Sit_Idle.png")
OUT = Path("hund/assets/mascot/hund.ico")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)]


def main() -> None:
    src = Image.open(SRC).convert("RGBA")
    # Dog_Sit_Idle.png is a single 48x48 frame (no sprite grid to crop).
    frames = [src.resize(size, Image.NEAREST) for size in SIZES]
    # Base image must be the largest size (ICO plugin skips sizes bigger than
    # the base); the exact-size NEAREST frames are matched via append_images.
    frames[-1].save(
        OUT,
        format="ICO",
        sizes=SIZES,
        append_images=frames[:-1],
    )
    # Verify
    ico = Image.open(OUT)
    got = sorted(ico.ico.sizes())
    print("wrote", OUT, "bytes=", OUT.stat().st_size, "sizes=", got)
    assert set(got) == set(SIZES), got


if __name__ == "__main__":
    main()
