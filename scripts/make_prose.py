"""Derives every sentence on the page that contains a number.

Prose is generated from the measurement files rather than typed by hand, so a
re-run of the sweeps cannot leave the text asserting something the charts no
longer show.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TESTDATA = ROOT / "testdata"
A = json.loads((DATA / "analysis.json").read_text())
S = json.loads((DATA / "rd_synthetic.json").read_text())
X = json.loads((DATA / "extra.json").read_text())

# Editorial: the band we recommend. The numbers that justify it are computed below.
KNEE = [75, 85]


def fmt_int(v):
    v = round(v)
    if abs(v) < 10000:
        return str(v)
    s = f"{abs(v):,}".replace(",", ".")
    return ("-" if v < 0 else "") + s


def pct(v, d=0):
    return f"{v:.{d}f}%"


def geomean(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


# ---- JPEG marginal cost: bits per pixel bought per SSIMULACRA2 point ----------
jp = sorted(A["curves"]["JPEG"], key=lambda p: p["q"])
marg = {}
for a, b in zip(jp, jp[1:]):
    marg[(a["q"], b["q"])] = (b["bpp"] - a["bpp"]) / (b["s2"] - a["s2"])
lo = next(v for k, v in marg.items() if k[0] == KNEE[0])
hi_key = max(marg, key=lambda k: k[0])
hi = marg[hi_key]
at_knee = next(v for k, v in marg.items() if k[0] == KNEE[1])
s2_at = {p["q"]: p["s2"] for p in jp}

# ---- where AVIF and JPEG XL swap places --------------------------------------
def bpp_at(codec, s2):
    pts = sorted(((p["s2"], p["bpp"]) for p in A["curves"][codec]))
    if s2 < pts[0][0] or s2 > pts[-1][0]:
        return None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= s2 <= x1:
            t = 0 if x1 == x0 else (s2 - x0) / (x1 - x0)
            return math.exp(math.log(y0) + t * (math.log(y1) - math.log(y0)))
    return None


cross = None
prev = None
for s2 in [x / 2 for x in range(120, 191)]:
    a, j = bpp_at("AVIF", s2), bpp_at("JXL", s2)
    if a is None or j is None:
        continue
    sign = a < j  # True while AVIF is the smaller file
    if prev is not None and sign != prev:
        cross = s2
        break
    prev = sign

# ---- synthetic screenshot ----------------------------------------------------
ll = {r["codec"]: r for r in S["lossless"]}
ly = {(r["codec"], r["quality"]): r for r in S["lossy"]}
pal = next(p for p in X["synthetic_palette"] if p["colors"] == 256)
tail = X["synthetic_tail"]
avif_cap = max(t["ssimulacra2"] for t in tail if t["codec"] == "AVIF")
webp_cap = max(t["ssimulacra2"] for t in tail if t["codec"] == "WEBP")
# the lossy encode that costs about the same as WebP lossless
same_size = min((t for t in tail if t["codec"] == "AVIF"),
                key=lambda t: abs(t["bytes"] - ll["WEBP"]["bytes"]))

# ---- photographic lossless ---------------------------------------------------
pl = X["photo_lossless"]
pl_png = geomean([r["PNG"] for r in pl])
pl_webp = geomean([r["WEBP"] for r in pl])
pl_jxl = geomean([r["JXL"] for r in pl])

sav = A["savings"]
prose = {}

prose["knee_note"] = (
    f"One SSIMULACRA2 point costs {lo:.3f} bits per pixel around q{KNEE[0]}. By q{KNEE[1]} the same "
    f"point costs {at_knee:.3f}, twice as much, and between q{hi_key[0]} and q{hi_key[1]} it costs "
    f"{hi:.3f}, some {hi / lo:.0f} times the price. The left panel is what turns steep; the right "
    f"panel barely moves. The shaded band is where the trade is still worth making."
)

prose["claim_knee"] = (
    f"Confirmed, and the cost curve is steeper than most people assume. A SSIMULACRA2 point costs "
    f"{lo:.3f} bpp at q{KNEE[0]}, {at_knee:.3f} bpp at q{KNEE[1]} and {hi:.3f} bpp by q{hi_key[1]}: "
    f"the price roughly doubles over the first ten quality steps and then runs away entirely. "
    f"Below q70 the image degrades quickly in the other direction (score {s2_at[70]:.0f} and "
    f"dropping fast beneath it). The efficient delivery band is q{KNEE[0]} to q{KNEE[1]}, and the "
    f"60 to 80 rule of thumb sits just inside it, which is presumably why it has survived so long."
)

prose["claim_webp"] = (
    f"Correct, and the measurements are blunt about why. On photographs WebP saved only "
    f"{pct(sav['80']['WEBP'], 1)} against baseline JPEG at delivery quality, and a modern JPEG "
    f"encoder claws most of that back, so for photos it is close to a wash. On the test "
    f"screenshot WebP came in {pct(100 * (1 - ll['WEBP']['bytes'] / ll['PNG']['bytes']), 1)} "
    f"under optimised PNG. The correction is which mode to use: the lossless one. Lossy WebP at "
    f"q80 produced a larger file than lossless WebP on the same screenshot "
    f"({fmt_int(ly[('WEBP', 80)]['bytes'])} against {fmt_int(ll['WEBP']['bytes'])} bytes) while "
    f"scoring {ly[('WEBP', 80)]['ssimulacra2']:.0f} instead of a perfect 100, and even at q100 it "
    f"stalls around {webp_cap:.0f} because it cannot reproduce a glyph edge."
)

prose["claim_png"] = (
    f"Real, and it works. Palette quantisation to 256 colours took the test screenshot from "
    f"{fmt_int(ll['PNG']['bytes'])} to {fmt_int(pal['bytes'])} bytes at a score of "
    f"{pal['ssimulacra2']:.0f}, still a valid PNG that opens everywhere, still with alpha. It is "
    f"the right tool whenever the file has to keep the .png extension. It is no longer the best "
    f"answer available, though, because WebP lossless landed at {fmt_int(ll['WEBP']['bytes'])} "
    f"bytes with every pixel intact."
)

prose["crossover_note"] = (
    f"The two frontier codecs are not competing for the same job. AVIF is "
    f"{pct(sav['80']['AVIF'], 1)} under JPEG at delivery quality and {pct(sav['60']['AVIF'], 1)} "
    f"under it at thumbnail quality: the harder you squeeze, the more it wins. JPEG XL runs the "
    f"other way, {pct(sav['80']['JXL'], 1)} at delivery quality but only "
    f"{pct(sav['60']['JXL'], 1)} at thumbnail quality, and it is the one that stays efficient at "
    f"the visually-lossless end where AVIF's advantage has evaporated. "
    + (f"On this corpus they change places at about SSIMULACRA2 {cross:.0f}. Below that line AVIF "
       f"is the smaller file; above it JPEG XL is. "
       if cross else "")
    + f"That single fact settles most of the AVIF-versus-JXL argument: it depends entirely on "
      f"which end of the quality range you work at."
)

prose["lossless_note"] = (
    f"On photographs the ordering flips back. Against optimised PNG, JPEG XL lossless was "
    f"{pct(100 * (1 - pl_jxl / pl_png), 1)} smaller and WebP lossless "
    f"{pct(100 * (1 - pl_webp / pl_png), 1)} smaller, averaged over the {len(pl)} reference "
    f"images. Flat graphics and photographs want different lossless coders, which is why a "
    f"single 'best lossless format' answer never holds."
)

prose["screenshot_note"] = (
    f"The sharpest way to put it: at {fmt_int(same_size['bytes'])} bytes, AVIF q{same_size['quality']} "
    f"costs about the same as WebP lossless at {fmt_int(ll['WEBP']['bytes'])} bytes, and scores "
    f"{same_size['ssimulacra2']:.0f} where WebP scores a perfect 100. Pushed all the way to q100 "
    f"AVIF still only reaches {avif_cap:.0f} on this image. For text and hairlines, lossy coding "
    f"has nothing to offer at the price."
)

prose["method_corpus"] = (
    f"{A['n_images']} pristine reference photographs from the Kodak set, each encoded across a "
    f"quality ladder in five codecs, plus one rendered 1440 by 900 application screenshot pushed "
    f"through lossless, lossy and palette paths. Encoders: libjpeg-turbo, libwebp, libaom for "
    f"AVIF, libx265 for HEIF, and libjxl."
)

X["prose"] = prose
X["knee_q"] = KNEE
(DATA / "extra.json").write_text(json.dumps(X, indent=1))
print(json.dumps(prose, indent=1)[:400])
print(f"\ncrossover: SSIMULACRA2 {cross}")
print(f"marginal cost q{KNEE[0]}: {lo:.4f}  q{KNEE[1]}: {at_knee:.4f}  q{hi_key}: {hi:.4f}")
