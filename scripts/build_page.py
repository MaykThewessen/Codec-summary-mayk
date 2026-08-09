"""Inject the inline fonts and the measured data into the page template.

Keeps the template readable: the template carries @@TOKENS@@, this script
swaps in ~400 KB of base64 font payload and the measurement JSON so the
published page stays self-contained (the Artifact CSP blocks font CDNs).
"""

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TESTDATA = ROOT / "testdata"
FONTS = ROOT / "assets" / "fonts"

FACES = {
    "FONT_DISPLAY": "Tektur-Medium.ttf",
    "FONT_BODY": "InstrumentSans-Regular.ttf",
    "FONT_BODY_BOLD": "InstrumentSans-Bold.ttf",
    "FONT_MONO": "GeistMono-Regular.ttf",
}


def main(template, out):
    html = Path(template).read_text()
    for token, fname in FACES.items():
        b64 = base64.b64encode((FONTS / fname).read_bytes()).decode()
        html = html.replace(f"@@{token}@@", b64)
    data = dict(
        photo=json.loads((DATA / "analysis.json").read_text()),
        synthetic=json.loads((DATA / "rd_synthetic.json").read_text()),
        extra=json.loads((DATA / "extra.json").read_text()),
    )
    html = html.replace("@@DATA@@", json.dumps(data, separators=(",", ":")))
    Path(out).write_text(html)
    print(f"wrote {out}  ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    import sys
    main(sys.argv[1], sys.argv[2])
