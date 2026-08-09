"""Rate-distortion sweep across image codecs on pristine photographic sources.

Encodes each source at a ladder of quality settings, then scores the decoded
result against the original with SSIMULACRA2 (the perceptual metric libjxl
ships; 100 = identical, 90 = visually lossless, 70 = high, 50 = medium).

Emits one row per (image, codec, quality) to rd_photo.json.
"""

import json
import os
import sys
from pathlib import Path

from PIL import Image
import pillow_avif  # noqa: F401  registers AVIF
import pillow_jxl  # noqa: F401   registers JXL
import pillow_heif
from ssimulacra2 import compute_ssimulacra2

pillow_heif.register_heif_opener()

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TESTDATA = ROOT / "testdata"
WORK = ROOT / ".work" / "photo"
WORK.mkdir(parents=True, exist_ok=True)

# Quality ladders are per-codec because the scales are not comparable.
# We compare at matched SSIMULACRA2, not at matched "quality number".
LADDERS = {
    "JPEG": dict(ext="jpg", qs=[30, 40, 50, 60, 65, 70, 75, 80, 85, 90, 95],
                 opts=lambda q: dict(quality=q, optimize=True, progressive=True)),
    "WEBP": dict(ext="webp", qs=[30, 40, 50, 60, 65, 70, 75, 80, 85, 90, 95],
                 opts=lambda q: dict(quality=q, method=6)),
    "AVIF": dict(ext="avif", qs=[25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80],
                 opts=lambda q: dict(quality=q, speed=4)),
    "HEIF": dict(ext="heic", qs=[25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80],
                 opts=lambda q: dict(quality=q)),
    "JXL":  dict(ext="jxl", qs=[55, 60, 65, 70, 75, 80, 85, 88, 90, 93, 96],
                 opts=lambda q: dict(quality=q, effort=7)),
}


def main(sources):
    rows = []
    for src in sources:
        im = Image.open(src).convert("RGB")
        px = im.size[0] * im.size[1]
        ref = WORK / f"ref_{Path(src).stem}.png"
        im.save(ref, "PNG")
        for codec, spec in LADDERS.items():
            for q in spec["qs"]:
                out = WORK / f"{Path(src).stem}_{codec}_{q}.{spec['ext']}"
                try:
                    im.save(out, codec, **spec["opts"](q))
                except Exception as e:
                    print(f"  encode fail {codec} q{q}: {e}", file=sys.stderr)
                    continue
                size = os.path.getsize(out)
                # Decode back to PNG so the metric compares pixels, not containers.
                dec = WORK / f"dec_{Path(src).stem}_{codec}_{q}.png"
                Image.open(out).convert("RGB").save(dec, "PNG")
                try:
                    s2 = compute_ssimulacra2(str(ref), str(dec))
                except Exception as e:
                    print(f"  metric fail {codec} q{q}: {e}", file=sys.stderr)
                    continue
                rows.append(dict(image=Path(src).stem, codec=codec, quality=q,
                                 bytes=size, pixels=px, bpp=size * 8 / px,
                                 ssimulacra2=round(s2, 3)))
                out.unlink()
                dec.unlink()
            print(f"{Path(src).stem} {codec} done", flush=True)
        ref.unlink()
    (DATA / "rd_photo.json").write_text(json.dumps(rows, indent=1))
    print(f"wrote {len(rows)} rows")


if __name__ == "__main__":
    main(sys.argv[1:])
