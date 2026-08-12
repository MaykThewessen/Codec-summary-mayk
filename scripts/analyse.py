"""Turn the raw sweeps into the numbers the page actually plots.

Key derived quantity: bits-per-pixel at MATCHED perceptual quality. Quality
numbers are not comparable across codecs (JPEG q80 and AVIF q80 are unrelated),
so for each image we interpolate each codec's rate curve at fixed SSIMULACRA2
targets, then take the geometric mean across images.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
TESTDATA = ROOT / "testdata"
TARGETS = [90, 85, 80, 75, 70, 60]  # SSIMULACRA2: 90 visually lossless, 70 high, 50 medium
CODECS = ["JPEG", "WEBP", "HEIF", "AVIF", "JXL"]


def interp_bpp(points, target):
    """log(bpp) linearly interpolated against ssimulacra2. points: [(s2, bpp)]."""
    pts = sorted(points)
    if target < pts[0][0] or target > pts[-1][0]:
        return None
    for (s0, b0), (s1, b1) in zip(pts, pts[1:]):
        if s0 <= target <= s1:
            if s1 == s0:
                return b0
            t = (target - s0) / (s1 - s0)
            return math.exp(math.log(b0) + t * (math.log(b1) - math.log(b0)))
    return None


def geomean(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def main():
    rows = json.loads((DATA / "rd_photo.json").read_text())
    images = sorted({r["image"] for r in rows})

    # bpp at matched quality, per codec per target
    matched = {c: {} for c in CODECS}
    for c in CODECS:
        for t in TARGETS:
            vals = []
            for img in images:
                pts = [(r["ssimulacra2"], r["bpp"]) for r in rows
                       if r["codec"] == c and r["image"] == img]
                v = interp_bpp(pts, t)
                if v:
                    vals.append(v)
            if len(vals) >= max(3, len(images) // 2):
                matched[c][t] = dict(bpp=round(geomean(vals), 4), n=len(vals))

    # savings vs JPEG at each target
    savings = {}
    for t in TARGETS:
        if t not in matched["JPEG"]:
            continue
        base = matched["JPEG"][t]["bpp"]
        savings[t] = {c: round(100 * (1 - matched[c][t]["bpp"] / base), 1)
                      for c in CODECS if t in matched[c]}

    # mean curve per codec: median bpp and s2 at each quality setting
    curves = {}
    for c in CODECS:
        qs = sorted({r["quality"] for r in rows if r["codec"] == c})
        curves[c] = [
            dict(q=q,
                 bpp=round(geomean([r["bpp"] for r in rows
                                    if r["codec"] == c and r["quality"] == q]), 4),
                 s2=round(sum(r["ssimulacra2"] for r in rows
                              if r["codec"] == c and r["quality"] == q)
                          / len([r for r in rows if r["codec"] == c and r["quality"] == q]), 2))
            for q in qs]

    # Which quality slider setting lands on each perceptual target, per codec.
    # This is what you actually type into an encoder, so it is worth inverting.
    q_for = {}
    for c in CODECS:
        pts = sorted((p["s2"], p["q"]) for p in curves[c])
        q_for[c] = {}
        for t in TARGETS:
            if t < pts[0][0] or t > pts[-1][0]:
                continue
            for (s0, q0), (s1, q1) in zip(pts, pts[1:]):
                if s0 <= t <= s1:
                    f = 0 if s1 == s0 else (t - s0) / (s1 - s0)
                    q_for[c][t] = round(q0 + f * (q1 - q0))
                    break

    out = dict(images=images, n_images=len(images), targets=TARGETS,
               matched=matched, savings=savings, curves=curves,
               quality_for_target=q_for)
    (DATA / "analysis.json").write_text(json.dumps(out, indent=1))

    print(f"{len(images)} images\n")
    print("bpp at matched SSIMULACRA2 (geometric mean):")
    print("target  " + "".join(f"{c:>10}" for c in CODECS))
    for t in TARGETS:
        cells = "".join(f"{matched[c][t]['bpp']:>10.3f}" if t in matched[c] else f"{'-':>10}"
                        for c in CODECS)
        print(f"  s2={t}{cells}")
    print("\nsize saving vs libjpeg-turbo at the same perceptual quality (%):")
    print("target  " + "".join(f"{c:>10}" for c in CODECS))
    for t, s in savings.items():
        print(f"  s2={t}" + "".join(f"{s.get(c, float('nan')):>10.1f}" for c in CODECS))
    print("\nJPEG quality knee (geomean bpp, mean s2):")
    for p in curves["JPEG"]:
        print(f"  q{p['q']:<3} {p['bpp']:>7.3f} bpp   s2 {p['s2']:>6.2f}")


if __name__ == "__main__":
    main()
