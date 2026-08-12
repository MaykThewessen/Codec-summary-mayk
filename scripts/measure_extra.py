"""Fills the three gaps the two main sweeps leave open.

1. Photographic lossless: PNG vs WebP-lossless vs JXL-lossless on the same
   photos, because the flat-graphics result does not transfer to photos.
2. The high-quality tail on flat graphics: where does a lossy codec finally
   reach visually-lossless on text and hairlines.
3. PNG-8 palette quantisation: the "lossy PNG" path, measured.
"""

import json
import os
from pathlib import Path

from PIL import Image
import pillow_avif  # noqa: F401
import pillow_jxl  # noqa: F401
from ssimulacra2 import compute_ssimulacra2

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TESTDATA = ROOT / "testdata"
WORK = ROOT / ".work" / "extra"
WORK.mkdir(parents=True, exist_ok=True)
out = {}

# --- 1. photographic lossless -------------------------------------------------
photo_ll = []
for src in sorted((TESTDATA / "photos").glob("*.png")):
    im = Image.open(src).convert("RGB")
    px = im.size[0] * im.size[1]
    row = {"image": src.stem, "pixels": px}
    for codec, ext, kw in [("PNG", "png", dict(optimize=True)),
                           ("WEBP", "webp", dict(lossless=True, quality=100, method=6)),
                           ("JXL", "jxl", dict(lossless=True, effort=9))]:
        p = WORK / f"{src.stem}_ll.{ext}"
        im.save(p, codec, **kw)
        row[codec] = os.path.getsize(p) * 8 / px
        p.unlink()
    photo_ll.append(row)
    print("ll", src.stem, flush=True)
out["photo_lossless"] = photo_ll

# --- 2. flat-graphics high-quality tail --------------------------------------
syn = Image.open(DATA / "synthetic_source.png").convert("RGB")
ref = WORK / "ref.png"
syn.save(ref, "PNG")
spx = syn.size[0] * syn.size[1]
tail = []
for codec, ext, qs, mk in [
        ("WEBP", "webp", [92, 95, 98, 100], lambda q: dict(quality=q, method=6)),
        ("AVIF", "avif", [85, 90, 95, 100], lambda q: dict(quality=q, speed=4)),
        # q=100 is rejected by the encoder; true lossless goes through lossless=True.
        ("JXL", "jxl", [96, 98, 99], lambda q: dict(quality=q, effort=9)),
        ("JPEG", "jpg", [96, 98, 100], lambda q: dict(quality=q, optimize=True, subsampling=0))]:
    for q in qs:
        p = WORK / f"t_{codec}_{q}.{ext}"
        syn.save(p, codec, **mk(q))
        d = WORK / f"t_{codec}_{q}.png"
        Image.open(p).convert("RGB").save(d, "PNG")
        tail.append(dict(codec=codec, quality=q, bytes=os.path.getsize(p),
                         bpp=os.path.getsize(p) * 8 / spx,
                         ssimulacra2=round(compute_ssimulacra2(str(ref), str(d)), 3)))
        d.unlink()
    print("tail", codec, flush=True)
out["synthetic_tail"] = tail

# --- 3. PNG-8 palette --------------------------------------------------------
pal = []
for n in [256, 128, 64, 32]:
    q = syn.quantize(colors=n, method=Image.Quantize.MEDIANCUT,
                     dither=Image.Dither.FLOYDSTEINBERG)
    p = WORK / f"pal{n}.png"
    q.save(p, "PNG", optimize=True)
    d = WORK / f"pal{n}_rgb.png"
    q.convert("RGB").save(d, "PNG")
    pal.append(dict(colors=n, bytes=os.path.getsize(p),
                    bpp=os.path.getsize(p) * 8 / spx,
                    ssimulacra2=round(compute_ssimulacra2(str(ref), str(d)), 3)))
    d.unlink()
out["synthetic_palette"] = pal
out["synthetic_pixels"] = spx

(DATA / "extra.json").write_text(json.dumps(out, indent=1))
print("wrote extra.json")
