"""Downloads the reference photographs.

The Kodak set is the long-standing reference corpus for still-image codec
comparison: 24 pristine film scans with no prior compression history, which
matters because re-encoding an already-lossy source measures the wrong thing.
Not committed here, only fetched, so the repository stays small.
"""

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "testdata" / "photos"
BASE = "https://r0k.us/graphics/kodak/kodak/kodim{:02d}.png"

# The 14 used for the published numbers: a spread of skin tones, foliage,
# architecture, water and flat sky, which stress different parts of a codec.
DEFAULT = [1, 2, 3, 4, 5, 7, 8, 13, 14, 19, 20, 21, 23, 24]


def main(which):
    DEST.mkdir(parents=True, exist_ok=True)
    for n in which:
        out = DEST / f"kodim{n:02d}.png"
        if out.exists():
            print(f"have  {out.name}")
            continue
        urllib.request.urlretrieve(BASE.format(n), out)
        print(f"got   {out.name}  {out.stat().st_size} bytes")


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or DEFAULT)
