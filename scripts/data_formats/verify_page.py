"""Render the built page and check it, per CONTRIBUTING.

Three viewports: 1280 light, 1280 dark, 420 narrow. Each must have zero console
errors and no horizontal document overflow. Full-page screenshots are sliced so
the result can actually be looked at rather than asserted about.

    python3 scripts/data_formats/verify_page.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "data_format_tradeoff_map.html"
SHOTS = Path("/tmp/claude-0/-home-user-Codec-summary-mayk/"
             "d9ea6b69-4351-597a-a52f-7b931cebb400/scratchpad/shots")

VIEWS = [("light", 1280, 900), ("dark", 1280, 900), ("narrow", 420, 900)]
SLICE_H = 1500


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    for f in SHOTS.glob("*.png"):
        f.unlink()
    bad = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        for name, w, h in VIEWS:
            scheme = "dark" if name == "dark" else "light"
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      color_scheme=scheme, device_scale_factor=1)
            page = ctx.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(f"{m.type}: {m.text}")
                    if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(PAGE.as_uri())
            page.wait_for_timeout(900)
            metrics = page.evaluate("""() => ({
                sw: document.documentElement.scrollWidth,
                cw: document.documentElement.clientWidth,
                bh: document.body.scrollHeight,
                wide: [...document.querySelectorAll('*')]
                    .filter(n => n.getBoundingClientRect().right >
                                 document.documentElement.clientWidth + 1)
                    .slice(0, 6)
                    .map(n => n.tagName + '.' + (n.className || '').toString().slice(0, 40)
                              + ' @' + Math.round(n.getBoundingClientRect().right))
            })""")
            overflow = metrics["sw"] > metrics["cw"]
            print(f"[{name}] {w}px  height {metrics['bh']}  "
                  f"scrollWidth {metrics['sw']} vs {metrics['cw']}  "
                  f"{'OVERFLOW' if overflow else 'no overflow'}  "
                  f"{len(errors)} console problems")
            for e in errors[:8]:
                print("    ", e)
            if overflow:
                # Tables inside .tbl-scroll are meant to be wider than the page,
                # so this list is only meaningful when the document itself
                # actually scrolls sideways.
                for n in metrics["wide"]:
                    print("     wide:", n)
            if overflow or errors:
                bad += 1
            total = metrics["bh"]
            i = 0
            while i * SLICE_H < total:
                h_slice = min(SLICE_H, total - i * SLICE_H)
                if h_slice > 4:
                    page.screenshot(path=str(SHOTS / f"{name}_{i:02d}.png"),
                                    full_page=True,
                                    clip={"x": 0, "y": i * SLICE_H, "width": w,
                                          "height": h_slice})
                i += 1
            ctx.close()
        browser.close()
    print(f"\nscreenshots in {SHOTS}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
