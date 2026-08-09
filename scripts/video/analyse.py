"""Turn the raw video sweep into the numbers the page plots.

The one derived quantity that makes everything comparable is bits per pixel per
frame (bpppf): bytes*8 / (width*height*frames). A 1080p30 stream at 5 Mbit/s and
a 4K60 stream at 15 Mbit/s look far apart in Mbit/s and are 0.080 and 0.030 in
bpppf: the 4K stream is the more heavily constrained of the two. Normalising
this way is what lets 540p, 720p and 1080p sit on one axis, and it is what lets
us test whether the codec ranking really moves with resolution.

As on the images page, codecs are compared at matched perceptual quality
(VMAF), never at matched CRF: CRF numbers are not comparable across encoders.

Six encoders, five formats: AV1 is present twice, as libaom and as SVT-AV1,
because they are the same bitstream format with very different cost. Every row
read here came from one ffmpeg build (/opt/ffmpeg-gpl/ffmpeg); nothing from the
earlier imageio-ffmpeg 7.0.2 sweep is mixed in.
"""

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "video"

CODECS = ["H264", "HEVC", "VP9", "AV1", "SVTAV1", "VVC"]
# Pairs worth a direct head-to-head rather than a difference of two savings.
# Positive means the first named is the smaller file at the same VMAF.
PAIRS = [("SVTAV1", "AV1"), ("VVC", "AV1"), ("VVC", "SVTAV1"), ("VVC", "HEVC")]
RES = ["1080p", "720p", "540p"]
TARGETS = [95, 93, 90, 85, 80]
COST_TARGET = 93  # encode cost is quoted at a realistic VOD operating point
# The shared quality grid the aggregate curves are built on.
VMAF_GRID = [98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74]


def geomean(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def interp_log(points, target):
    """value at target, log-linear in value, linear in the quality axis.

    points: [(quality, value)]. Returns None outside the measured range, which
    is the honest answer: extrapolating a rate curve invents the result.
    """
    pts = sorted(points)
    if target < pts[0][0] or target > pts[-1][0]:
        return None
    for (q0, v0), (q1, v1) in zip(pts, pts[1:]):
        if q0 <= target <= q1:
            if q1 == q0:
                return v0
            t = (target - q0) / (q1 - q0)
            return math.exp(math.log(v0) + t * (math.log(v1) - math.log(v0)))
    return None


def interp_lin(points, target):
    pts = sorted(points)
    if target < pts[0][0] or target > pts[-1][0]:
        return None
    for (q0, v0), (q1, v1) in zip(pts, pts[1:]):
        if q0 <= target <= q1:
            t = 0 if q1 == q0 else (target - q0) / (q1 - q0)
            return v0 + t * (v1 - v0)
    return None


def main():
    rows = [json.loads(l) for l in (DATA / "rd_video.jsonl").read_text().splitlines() if l.strip()]
    clips = sorted({r["clip"] for r in rows})
    by = defaultdict(list)
    for r in rows:
        by[(r["res"], r["codec"], r["clip"])].append(r)
    for v in by.values():
        v.sort(key=lambda r: r["crf"])

    # A clip only counts once it has been swept in every codec at every
    # resolution. A half-swept clip would quietly change which clips back which
    # number, which is exactly the kind of thing rule 3 warns about.
    clips = [cl for cl in clips
             if all(by[(res, c, cl)] for res in RES for c in CODECS)]
    if not clips:
        raise SystemExit("no clip has a complete sweep yet")
    dropped = sorted({r["clip"] for r in rows} - set(clips))
    # Everything downstream, including the encode counts and the CPU totals,
    # describes only the clips that were swept end to end.
    rows = [r for r in rows if r["clip"] in clips]

    # ---- span check: every codec must cover the whole target range ----------
    span = {}
    for res in RES:
        for c in CODECS:
            for clip in clips:
                v = by[(res, c, clip)]
                span[f"{res}/{c}/{clip}"] = [round(min(r["vmaf"] for r in v), 1),
                                             round(max(r["vmaf"] for r in v), 1)]

    # ---- aggregate curve per resolution and codec --------------------------
    # CRF ladders are per clip (the two clips sit about eight x264 CRF steps
    # apart in difficulty), so a curve cannot be built by averaging clips at a
    # shared CRF: there is no shared CRF. Aggregate on a shared VMAF grid
    # instead, which is the same matched-quality rule used everywhere else.
    curves = {res: {} for res in RES}
    for res in RES:
        for c in CODECS:
            pts = []
            for v in VMAF_GRID:
                bs, ps, ss, es = [], [], [], []
                for clip in clips:
                    pl = by[(res, c, clip)]
                    b = interp_log([(r["vmaf"], r["bpppf"]) for r in pl], v)
                    if b is None:
                        break
                    bs.append(b)
                    ps.append(interp_lin([(r["vmaf"], r["psnr_y"]) for r in pl], v))
                    ss.append(interp_lin([(r["vmaf"], r["ssim"]) for r in pl], v))
                    es.append(interp_log([(r["vmaf"], r["enc_cpu_s"] / r["frames"]) for r in pl], v))
                if len(bs) != len(clips):
                    continue
                pts.append(dict(vmaf=v,
                                bpppf=round(geomean(bs), 6),
                                psnr=round(sum(ps) / len(ps), 2),
                                ssim=round(sum(ss) / len(ss), 5),
                                enc_cpu_fs=round(geomean(es), 4)))
            curves[res][c] = sorted(pts, key=lambda p: p["bpppf"])

    # ---- what CRF actually lands on the operating point, per clip ----------
    crf_for = {res: {c: {} for c in CODECS} for res in RES}
    for res in RES:
        for c in CODECS:
            for clip in clips:
                pl = by[(res, c, clip)]
                v = interp_lin([(r["vmaf"], float(r["crf"])) for r in pl], COST_TARGET)
                if v is not None:
                    crf_for[res][c][clip] = round(v)

    # ---- bpppf at matched VMAF, per clip then geometric mean ----------------
    matched = {res: {c: {} for c in CODECS} for res in RES}
    cost = {res: {c: {} for c in CODECS} for res in RES}
    for res in RES:
        for c in CODECS:
            for t in TARGETS:
                bs, cs = [], []
                for clip in clips:
                    v = by[(res, c, clip)]
                    b = interp_log([(r["vmaf"], r["bpppf"]) for r in v], t)
                    e = interp_log([(r["vmaf"], r["enc_cpu_s"] / r["frames"]) for r in v], t)
                    if b:
                        bs.append(b)
                    if e:
                        cs.append(e)
                if len(bs) == len(clips):
                    matched[res][c][t] = dict(bpppf=round(geomean(bs), 6), n=len(bs))
                if len(cs) == len(clips):
                    cost[res][c][t] = round(geomean(cs), 4)

    # ---- the same comparison judged by three metrics ------------------------
    # VMAF has known biases, so the honest check is to re-run the matched-quality
    # comparison against PSNR-Y and SSIM. The anchor is the same operating point
    # in every case: whatever H.264 scored at the VMAF target on that clip.
    by_metric = {res: {m: {} for m in ("vmaf", "psnr_y", "ssim")} for res in RES}
    for res in RES:
        for t in TARGETS:
            for m in ("vmaf", "psnr_y", "ssim"):
                base, other = [], {c: [] for c in CODECS if c != "H264"}
                for clip in clips:
                    h = by[(res, "H264", clip)]
                    bh = interp_log([(r["vmaf"], r["bpppf"]) for r in h], t)
                    ref = interp_lin([(r["vmaf"], r[m]) for r in h], t)
                    if bh is None or ref is None:
                        base = []
                        break
                    vals = {}
                    for c in other:
                        v = interp_log([(r[m], r["bpppf"]) for r in by[(res, c, clip)]], ref)
                        if v is None:
                            vals = None
                            break
                        vals[c] = v
                    if vals is None:
                        base = []
                        break
                    base.append(bh)
                    for c in other:
                        other[c].append(vals[c])
                if len(base) == len(clips):
                    b = geomean(base)
                    by_metric[res][m][t] = {c: round(100 * (1 - geomean(other[c]) / b), 1)
                                            for c in other}

    # ---- saving against H.264 at the same VMAF ------------------------------
    savings = {res: {} for res in RES}
    for res in RES:
        for t in TARGETS:
            if t not in matched[res]["H264"]:
                continue
            base = matched[res]["H264"][t]["bpppf"]
            savings[res][t] = {c: round(100 * (1 - matched[res][c][t]["bpppf"] / base), 1)
                               for c in CODECS if t in matched[res][c]}

    # ---- encode cost relative to H.264 at a fixed quality -------------------
    enc_cost = {res: {} for res in RES}
    for res in RES:
        base = cost[res]["H264"].get(COST_TARGET)
        for c in CODECS:
            v = cost[res][c].get(COST_TARGET)
            if v and base:
                enc_cost[res][c] = dict(cpu_s_per_frame=round(v, 4),
                                        rel=round(v / base, 2))

    # ---- does the ranking move with resolution? ----------------------------
    # For each target, the ordering of codecs by bpppf at each resolution.
    order = {res: {t: sorted([c for c in CODECS if t in matched[res][c]],
                             key=lambda c: matched[res][c][t]["bpppf"])
                   for t in TARGETS} for res in RES}
    stable = all(order[r][t] == order[RES[0]][t] for r in RES for t in TARGETS
                 if t in savings[r] and t in savings[RES[0]])
    # spread of the saving for one codec across the three resolutions
    spread = {}
    for c in CODECS:
        if c == "H264":
            continue
        spread[c] = {t: round(max(savings[r][t][c] for r in RES if t in savings[r] and c in savings[r][t])
                              - min(savings[r][t][c] for r in RES if t in savings[r] and c in savings[r][t]), 1)
                     for t in TARGETS
                     if all(t in savings[r] and c in savings[r][t] for r in RES)}

    # ---- HEVC versus VP9: is either better at one end? ---------------------
    hevc_vp9 = {}
    for res in RES:
        d = {}
        for t in TARGETS:
            if t in matched[res]["HEVC"] and t in matched[res]["VP9"]:
                d[t] = round(100 * (1 - matched[res]["VP9"][t]["bpppf"]
                                    / matched[res]["HEVC"][t]["bpppf"]), 1)
        hevc_vp9[res] = d  # positive: VP9 smaller than HEVC

    # ---- direct head-to-heads that the page quotes -------------------------
    # Subtracting two savings-against-H.264 gives percentage points, not a
    # percentage. These are the real ratios.
    pairs = {}
    for a, b in PAIRS:
        d = {}
        for res in RES:
            dd = {}
            for t in TARGETS:
                if t in matched[res][a] and t in matched[res][b]:
                    dd[t] = round(100 * (1 - matched[res][a][t]["bpppf"]
                                         / matched[res][b][t]["bpppf"]), 1)
            d[res] = dd
        pairs[f"{a}_vs_{b}"] = d

    # ---- the two AV1 encoders side by side ---------------------------------
    # Same format, same decoder, different cost. This is the comparison that
    # decides whether AV1's encode price is a real objection or a libaom one.
    av1_enc = {}
    for res in RES:
        ca, cs = cost[res]["AV1"].get(COST_TARGET), cost[res]["SVTAV1"].get(COST_TARGET)
        av1_enc[res] = dict(
            aom_cpu_s_per_frame=round(ca, 4) if ca else None,
            svt_cpu_s_per_frame=round(cs, 4) if cs else None,
            speedup=round(ca / cs, 1) if ca and cs else None,
            bits=pairs["SVTAV1_vs_AV1"][res])

    # ---- do the three resolutions collapse onto one curve? -----------------
    # VMAF at a fixed bpppf, per resolution, per codec.
    probes = [0.02, 0.04, 0.08, 0.16]
    collapse = {c: {res: {p: (lambda v: round(v, 2) if v else None)(
        interp_lin([(x["bpppf"], x["vmaf"]) for x in curves[res][c]], p))
        for p in probes} for res in RES} for c in CODECS}

    # ---- per-resolution real-world bitrate anchors --------------------------
    anchors = [
        dict(label="1080p30 at 1 Mbit/s", bpppf=1e6 / (1920 * 1080 * 30)),
        dict(label="1080p30 at 3 Mbit/s", bpppf=3e6 / (1920 * 1080 * 30)),
        dict(label="1080p30 at 5 Mbit/s", bpppf=5e6 / (1920 * 1080 * 30)),
        dict(label="1080p30 at 10 Mbit/s", bpppf=10e6 / (1920 * 1080 * 30)),
        dict(label="4K60 at 15 Mbit/s", bpppf=15e6 / (3840 * 2160 * 60)),
        dict(label="4K60 at 25 Mbit/s", bpppf=25e6 / (3840 * 2160 * 60)),
        dict(label="720p30 at 2 Mbit/s", bpppf=2e6 / (1280 * 720 * 30)),
        dict(label="Blu-ray 1080p24 at 30 Mbit/s", bpppf=30e6 / (1920 * 1080 * 24)),
    ]
    for a in anchors:
        a["bpppf"] = round(a["bpppf"], 5)

    out = dict(clips=clips, resolutions=RES, codecs=CODECS, targets=TARGETS,
               cost_target=COST_TARGET, n_encodes=len(rows),
               curves=curves, matched=matched, savings=savings, crf_for=crf_for,
               by_metric=by_metric,
               enc_cost=enc_cost, cost_by_target=cost, order=order,
               ranking_stable=stable, saving_spread=spread,
               hevc_vs_vp9=hevc_vp9, pairs=pairs, av1_encoders=av1_enc,
               collapse=collapse, collapse_probes=probes,
               span=span, anchors=anchors, dropped_clips=dropped,
               total_enc_cpu_s=round(sum(r["enc_cpu_s"] for r in rows), 1),
               total_metric_cpu_s=round(sum(r["metric_cpu_s"] for r in rows), 1))
    (DATA / "analysis.json").write_text(json.dumps(out, indent=1))

    # ---- console summary ---------------------------------------------------
    print(f"{len(rows)} encodes, {len(clips)} clips: {', '.join(clips)}\n")
    for res in RES:
        print(f"--- {res}: bits per pixel per frame at matched VMAF")
        print("  target " + "".join(f"{c:>10}" for c in CODECS))
        for t in TARGETS:
            cells = "".join(f"{matched[res][c][t]['bpppf']:>10.4f}" if t in matched[res][c]
                            else f"{'-':>10}" for c in CODECS)
            print(f"  vmaf {t}{cells}")
        print("  saving vs H.264 (%)")
        for t in TARGETS:
            if t in savings[res]:
                print(f"  vmaf {t}" + "".join(f"{savings[res][t].get(c, float('nan')):>10.1f}"
                                              for c in CODECS))
        print()
    print("ranking identical across resolutions:", stable)
    print("order at each target, 1080p:", {t: order["1080p"][t] for t in TARGETS})
    print("saving spread across resolutions (pp):", spread)
    print("VP9 minus HEVC saving (positive = VP9 smaller):", hevc_vp9)
    for k, v in pairs.items():
        print(f"{k} (positive = first is smaller):", {r: v[r] for r in RES})
    print("AV1 encoders:", av1_enc)
    print("encode cost at VMAF", COST_TARGET, enc_cost)
    print("\nVMAF span per res/codec/clip:")
    for k, v in span.items():
        print(f"  {k:28s} {v[0]:6.1f} .. {v[1]:6.1f}")


if __name__ == "__main__":
    main()
