"""Renders the built page at three widths and reports anything wrong.

Checks console errors and horizontal document overflow, then writes full-page
screenshots and horizontal slices of them, because the only reliable way to
catch a clipped label or an empty grid cell is to look at it.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "compression_tradeoff_map.html"
OUT = Path("/tmp/compression_shots")

VIEWS = [("wide-light", 1280, "light"), ("wide-dark", 1280, "dark"), ("narrow", 420, "light")]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        for name, width, scheme in VIEWS:
            ctx = browser.new_context(viewport={"width": width, "height": 1000},
                                      color_scheme=scheme, device_scale_factor=2)
            page = ctx.new_page()
            errs = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(PAGE.as_uri())
            page.wait_for_timeout(900)
            over = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            wide = page.evaluate("""() => [...document.querySelectorAll('*')]
                .filter(n => n.scrollWidth > n.clientWidth + 2 && getComputedStyle(n).overflowX === 'visible')
                .slice(0, 6).map(n => n.tagName + '.' + n.className + ' ' + n.scrollWidth + '>' + n.clientWidth)""")
            shot = OUT / f"{name}.png"
            page.screenshot(path=str(shot), full_page=True)
            h = page.evaluate("() => document.documentElement.scrollHeight")
            print(f"{name:<12} {width}px  console errors: {len(errs)}  "
                  f"document overflow: {over}px  height {h}px")
            for e in errs[:6]:
                print("   ERR", e[:200])
            for w in wide:
                print("   WIDE", w)
            if errs or over > 0:
                ok = False
            # slices, so each one is small enough to actually read
            step = 1400
            page.set_viewport_size({"width": width, "height": step})
            for i, top in enumerate(range(0, h, step)):
                page.evaluate(f"window.scrollTo(0, {top})")
                page.wait_for_timeout(120)
                page.screenshot(path=str(OUT / f"{name}_{i:02d}.png"))
            ctx.close()
        browser.close()
    print("\nshots in", OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
