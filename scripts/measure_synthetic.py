"""Screenshot / synthetic-graphics comparison.

Two questions this answers that the photographic sweep cannot:
  1. Lossless: what does each codec cost on flat UI graphics, where PNG is
     the incumbent and losing detail is not acceptable.
  2. Lossy on text: how far can you push before glyph edges break.

Renders a pristine synthetic UI (no prior compression history), then measures.
"""

import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pillow_avif  # noqa: F401
import pillow_jxl  # noqa: F401
import pillow_heif
from ssimulacra2 import compute_ssimulacra2

pillow_heif.register_heif_opener()

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TESTDATA = ROOT / "testdata"
WORK = ROOT / ".work" / "syn"
WORK.mkdir(parents=True, exist_ok=True)

SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

W, H = 1440, 900


def render_ui():
    """A dense app screenshot: flat panels, small text, hairlines, a chart."""
    im = Image.new("RGB", (W, H), (247, 248, 250))
    d = ImageDraw.Draw(im)
    f_sm = ImageFont.truetype(SANS, 13)
    f_md = ImageFont.truetype(SANS, 15)
    f_b = ImageFont.truetype(SANS_B, 19)
    f_mono = ImageFont.truetype(MONO, 12)

    # Top chrome
    d.rectangle([0, 0, W, 56], fill=(255, 255, 255))
    d.line([0, 56, W, 56], fill=(224, 227, 233))
    d.text((28, 18), "Storage Analytics", font=f_b, fill=(17, 20, 24))
    for i, tab in enumerate(["Overview", "Buckets", "Transfers", "Policies"]):
        x = 260 + i * 108
        d.text((x, 21), tab, font=f_md, fill=(90, 98, 110) if i else (26, 90, 200))
    d.rectangle([260, 50, 336, 52], fill=(26, 90, 200))

    # Sidebar
    d.rectangle([0, 57, 216, H], fill=(255, 255, 255))
    d.line([216, 57, 216, H], fill=(224, 227, 233))
    for i, item in enumerate(["Dashboard", "Objects", "Lifecycle", "Replication",
                              "Access keys", "Audit log", "Billing", "Settings"]):
        y = 88 + i * 38
        if i == 1:
            d.rectangle([12, y - 8, 204, y + 22], fill=(238, 243, 253))
        d.rectangle([28, y + 3, 40, y + 15], outline=(140, 150, 165))
        d.text((54, y), item, font=f_md, fill=(40, 48, 60))

    # Stat cards
    for i, (label, val, delta) in enumerate([
            ("Objects stored", "48.221.904", "+2.4%"),
            ("Bytes at rest", "912.4 TiB", "+0.8%"),
            ("Egress this month", "38.1 TiB", "-11.2%"),
            ("Requests / s", "14.802", "+5.6%")]):
        x = 244 + i * 296
        d.rectangle([x, 84, x + 272, 176], fill=(255, 255, 255),
                    outline=(224, 227, 233))
        d.text((x + 18, 102), label.upper(), font=f_sm, fill=(122, 130, 142))
        d.text((x + 18, 124), val, font=ImageFont.truetype(SANS_B, 26),
               fill=(17, 20, 24))
        d.text((x + 18, 154), delta, font=f_sm,
               fill=(20, 130, 70) if delta.startswith("+") else (190, 60, 55))

    # Chart panel with gridlines, an area fill and a line
    cx0, cy0, cx1, cy1 = 244, 204, 900, 500
    d.rectangle([cx0, cy0, cx1, cy1], fill=(255, 255, 255), outline=(224, 227, 233))
    d.text((cx0 + 18, cy0 + 16), "Egress by day", font=f_b, fill=(17, 20, 24))
    px0, py0, px1, py1 = cx0 + 56, cy0 + 56, cx1 - 24, cy1 - 40
    for g in range(5):
        y = py0 + g * (py1 - py0) / 4
        d.line([px0, y, px1, y], fill=(236, 239, 244))
        d.text((cx0 + 18, y - 7), f"{(4 - g) * 25}", font=f_sm, fill=(150, 158, 170))
    pts = [12, 28, 21, 44, 39, 58, 51, 47, 63, 72, 68, 84, 79, 91, 74, 88]
    poly = [(px0 + i * (px1 - px0) / (len(pts) - 1),
             py1 - v / 100 * (py1 - py0)) for i, v in enumerate(pts)]
    d.polygon([(px0, py1)] + poly + [(px1, py1)], fill=(232, 240, 253))
    d.line(poly, fill=(26, 90, 200), width=2, joint="curve")

    # Data table with hairline rules and mono figures
    tx0, ty0 = 920, 204
    d.rectangle([tx0, ty0, W - 24, cy1], fill=(255, 255, 255), outline=(224, 227, 233))
    d.text((tx0 + 18, ty0 + 16), "Top buckets", font=f_b, fill=(17, 20, 24))
    for i, (name, sz) in enumerate([("prod-media", "184.2 TiB"), ("archive-2024", "121.9 TiB"),
                                    ("ingest-raw", "88.4 TiB"), ("db-snapshots", "61.0 TiB"),
                                    ("cdn-cache", "44.7 TiB"), ("logs-hot", "12.3 TiB")]):
        y = ty0 + 56 + i * 34
        d.line([tx0 + 18, y - 8, W - 42, y - 8], fill=(238, 241, 246))
        d.text((tx0 + 18, y), name, font=f_md, fill=(40, 48, 60))
        d.text((W - 42 - d.textlength(sz, f_mono), y + 2), sz, font=f_mono,
               fill=(90, 98, 110))

    # Code / log panel: dense small mono text on a dark ground
    d.rectangle([244, 524, W - 24, H - 24], fill=(24, 27, 33))
    lines = [
        "2026-08-09T11:04:12Z  INFO   lifecycle: evaluated 48221904 objects in 12.4s",
        "2026-08-09T11:04:12Z  INFO   lifecycle: 1204 objects -> GLACIER (rule=archive-90d)",
        "2026-08-09T11:04:13Z  WARN   replication: lag 42s on eu-west-1 -> us-east-2",
        "2026-08-09T11:04:15Z  INFO   transfer: PUT prod-media/2026/08/frame_00412.webp 2.1MB",
        "2026-08-09T11:04:15Z  ERROR  policy: denied s3:DeleteObject for key=archive-2024/*",
        "2026-08-09T11:04:16Z  INFO   compaction: merged 18 segments, reclaimed 9.4 GiB",
        "2026-08-09T11:04:18Z  INFO   scrub: verified 128000 checksums, 0 mismatches",
        "2026-08-09T11:04:21Z  WARN   quota: bucket=ingest-raw at 91% of 96.0 TiB",
    ]
    for i, ln in enumerate(lines):
        col = (210, 216, 226)
        if "WARN" in ln:
            col = (235, 190, 90)
        elif "ERROR" in ln:
            col = (240, 130, 120)
        d.text((266, 546 + i * 22), ln, font=f_mono, fill=col)
    return im


LOSSLESS = {
    "PNG":  ("png",  dict(optimize=True)),
    "WEBP": ("webp", dict(lossless=True, quality=100, method=6)),
    "AVIF": ("avif", dict(quality=100, speed=4)),
    # effort 9 to match the tuning the other lossless encoders get here
    "JXL":  ("jxl",  dict(lossless=True, effort=9)),
}

LOSSY = {
    "JPEG": ("jpg",  [60, 70, 75, 80, 85, 90, 95], lambda q: dict(quality=q, optimize=True, progressive=True)),
    "WEBP": ("webp", [60, 70, 75, 80, 85, 90, 95], lambda q: dict(quality=q, method=6)),
    "AVIF": ("avif", [35, 45, 50, 55, 60, 70, 80], lambda q: dict(quality=q, speed=4)),
    "HEIF": ("heic", [35, 45, 50, 55, 60, 70, 80], lambda q: dict(quality=q)),
    "JXL":  ("jxl",  [70, 75, 80, 85, 90, 93, 96], lambda q: dict(quality=q, effort=7)),
}


def main():
    im = render_ui()
    ref = WORK / "ref.png"
    im.save(ref, "PNG", optimize=True)
    px = W * H
    out = {"pixels": px, "lossless": [], "lossy": []}

    for codec, (ext, opts) in LOSSLESS.items():
        p = WORK / f"ll_{codec}.{ext}"
        im.save(p, codec, **opts)
        dec = Image.open(p).convert("RGB")
        exact = list(dec.getdata()) == list(im.getdata())
        out["lossless"].append(dict(codec=codec, bytes=os.path.getsize(p),
                                    bpp=os.path.getsize(p) * 8 / px, exact=exact))
        print(codec, os.path.getsize(p), "exact" if exact else "NOT EXACT", flush=True)

    for codec, (ext, qs, opts) in LOSSY.items():
        for q in qs:
            p = WORK / f"ly_{codec}_{q}.{ext}"
            im.save(p, codec, **opts(q))
            dec = WORK / f"dec_{codec}_{q}.png"
            Image.open(p).convert("RGB").save(dec, "PNG")
            s2 = compute_ssimulacra2(str(ref), str(dec))
            out["lossy"].append(dict(codec=codec, quality=q, bytes=os.path.getsize(p),
                                     bpp=os.path.getsize(p) * 8 / px,
                                     ssimulacra2=round(s2, 3)))
            dec.unlink()
        print(codec, "lossy done", flush=True)

    (DATA / "rd_synthetic.json").write_text(json.dumps(out, indent=1))
    im.save(DATA / "synthetic_source.png", "PNG", optimize=True)
    print("wrote rd_synthetic.json")


if __name__ == "__main__":
    main()
