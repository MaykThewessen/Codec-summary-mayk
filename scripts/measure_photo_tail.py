"""Extends the photographic ladders upward so every codec spans the whole
quality range.

Without this the high-quality end of the comparison is an artefact of where
each ladder happened to stop, and a codec would look incapable of reaching
visually-lossless when in fact it was simply never asked to.

Merges its rows into rd_photo.json.
"""

import json
import os
import sys
from pathlib import Path

from PIL import Image
import pillow_avif  # noqa: F401
import pillow_jxl  # noqa: F401
import pillow_heif
from ssimulacra2 import compute_ssimulacra2

pillow_heif.register_heif_opener()

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TESTDATA = ROOT / "testdata"
WORK = ROOT / ".work" / "tail"
WORK.mkdir(parents=True, exist_ok=True)

TAIL = {
    "JPEG": dict(ext="jpg", qs=[97, 98], opts=lambda q: dict(quality=q, optimize=True, progressive=True)),
    "WEBP": dict(ext="webp", qs=[97, 99], opts=lambda q: dict(quality=q, method=6)),
    "AVIF": dict(ext="avif", qs=[85, 90, 95], opts=lambda q: dict(quality=q, speed=4)),
    "HEIF": dict(ext="heic", qs=[85, 90], opts=lambda q: dict(quality=q)),
    "JXL":  dict(ext="jxl", qs=[98, 99], opts=lambda q: dict(quality=q, effort=7)),
}


def main(sources):
    rows = json.loads((DATA / "rd_photo.json").read_text())
    have = {(r["image"], r["codec"], r["quality"]) for r in rows}
    added = 0
    for src in sources:
        im = Image.open(src).convert("RGB")
        px = im.size[0] * im.size[1]
        stem = Path(src).stem
        ref = WORK / f"ref_{stem}.png"
        im.save(ref, "PNG")
        for codec, spec in TAIL.items():
            for q in spec["qs"]:
                if (stem, codec, q) in have:
                    continue
                out = WORK / f"{stem}_{codec}_{q}.{spec['ext']}"
                try:
                    im.save(out, codec, **spec["opts"](q))
                except Exception as e:
                    print(f"  {codec} q{q}: {e}", file=sys.stderr)
                    continue
                size = os.path.getsize(out)
                dec = WORK / f"dec_{stem}_{codec}_{q}.png"
                Image.open(out).convert("RGB").save(dec, "PNG")
                rows.append(dict(image=stem, codec=codec, quality=q, bytes=size,
                                 pixels=px, bpp=size * 8 / px,
                                 ssimulacra2=round(compute_ssimulacra2(str(ref), str(dec)), 3)))
                added += 1
                out.unlink()
                dec.unlink()
        ref.unlink()
        print(stem, "tail done", flush=True)
    (DATA / "rd_photo.json").write_text(json.dumps(rows, indent=1))
    print(f"added {added} rows, {len(rows)} total")


if __name__ == "__main__":
    main(sys.argv[1:])
