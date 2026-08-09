"""Collect the three derived files into the single payload build_page.py wants.

    python3 scripts/audio/assemble.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "audio"


def main():
    payload = dict(
        measured=json.loads((DATA / "analysis.json").read_text()),
        tests=json.loads((DATA / "listening_tests.json").read_text()),
        prose=json.loads((DATA / "prose.json").read_text()),
    )
    out = DATA / "page_data.json"
    out.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {out}  ({out.stat().st_size/1024:.0f} kB)")


if __name__ == "__main__":
    main()
