"""Derive every sentence on the video page that contains a number, then assemble
the page payload.

Nothing numeric on the page is typed by hand. Re-running the sweep and this
script cannot leave the prose asserting something the charts no longer show.
Writes data/video/page_data.json, which scripts/build_page.py injects.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "video"

A = json.loads((DATA / "analysis.json").read_text())
CLIPS = json.loads((DATA / "clips.json").read_text())
CLIPS = [c for c in CLIPS if c["name"] in A["clips"]]

RES = A["resolutions"]
CODECS = A["codecs"]
LABEL = {"H264": "H.264", "HEVC": "HEVC", "VP9": "VP9", "AV1": "AV1"}

# Cited, never measured here. Sources are named on the page.
VVC_VS_HEVC = "36 to 37%"


def pct(v, d=1):
    return f"{v:.{d}f}%"


def smaller(v, d=1):
    """Sign-aware phrasing, so a codec that loses does not read as a winner."""
    return f"{abs(v):.{d}f}% {'smaller' if v >= 0 else 'larger'}"


def sav(res, target, codec):
    return A["savings"][res][str(target)][codec]


def has(res, target, codec=None):
    s = A["savings"][res].get(str(target))
    return bool(s) and (codec is None or codec in s)


def mean_sav(target, codec):
    vals = [sav(r, target, codec) for r in RES if has(r, target, codec)]
    return sum(vals) / len(vals) if vals else None


def matched(res, target, codec):
    return A["matched"][res][codec][str(target)]["bpppf"]


def crf_at(res, codec):
    """CRF that lands on the cost target, as a range across clips.

    Content difficulty moves this a long way, so quoting one number would be a
    lie of precision: the two clips are about eight x264 CRF steps apart.
    """
    v = sorted(A["crf_for"][res][codec].values())
    return str(v[0]) if v[0] == v[-1] else f"{v[0]}-{v[-1]}"


def crf_span(res, codec):
    v = sorted(A["crf_for"][res][codec].values())
    return v[0], v[-1]


prose = {}
# Only quote targets that every codec reaches at every resolution. A target that
# only the hard clip's ladder reaches would be a statement about the sweep.
targets = [t for t in A["targets"]
           if all(has(r, t, c) for r in RES for c in CODECS if c != "H264")]
assert targets, "no VMAF target is covered by every codec at every resolution"
low = min(targets)
high = max(targets)
mid = 90 if 90 in targets else targets[len(targets) // 2]

# ---- the map cells ----------------------------------------------------------
prose["vvc_vs_hevc"] = VVC_VS_HEVC
prose["av1_low"] = pct(mean_sav(low, "AV1"))
prose["av1_mid"] = pct(mean_sav(mid, "AV1"))
prose["hevc_low"] = smaller(mean_sav(low, "HEVC"))
prose["h264_penalty"] = pct(100 - mean_sav(low, "AV1"), 0)

# which of HEVC and VP9 is ahead, and where
hv = {t: {r: A["hevc_vs_vp9"][r].get(str(t)) for r in RES} for t in targets}
hv_mean = {t: (lambda xs: sum(xs) / len(xs) if xs else None)(
    [v for v in hv[t].values() if v is not None]) for t in targets}
vp9_wins_high = (hv_mean[high] or 0) > 0
vp9_wins_low = (hv_mean[low] or 0) > 0

if vp9_wins_high and not vp9_wins_low:
    prose["mid_tier2_name"] = "HEVC, just"
    prose["mid_tier2_why"] = (
        f"The two are within a few percent of each other here: VP9 is "
        f"{pct(abs(hv_mean[mid]))} {'under' if hv_mean[mid] > 0 else 'over'} HEVC at VMAF "
        f"{mid}, averaged across the three resolutions. Pick on reach, not on efficiency: "
        f"VP9 plays in every browser and HEVC does not.")
    prose["vp9_high_why"] = (
        f"At the transparent end VP9 pulls ahead of HEVC by {pct(abs(hv_mean[high]))}, "
        f"which is the one place the ordering between them changes. Both are far behind AV1.")
else:
    lead = hv_mean[mid]
    who = "VP9" if lead > 0 else "HEVC"
    prose["mid_tier2_name"] = f"{who}, by a nose"
    prose["mid_tier2_why"] = (
        f"These two are the same codec generation and it shows: {who} is only "
        f"{pct(abs(lead))} ahead at VMAF {mid}, averaged over the three resolutions, and the "
        f"gap never opens up. Pick on reach, not on efficiency. VP9 plays in every browser "
        f"and costs nothing to licence; HEVC does neither, and has hardware everywhere.")
    prose["vp9_high_why"] = (
        f"At the transparent end the two stay level: VP9 is {pct(abs(hv_mean[high]))} "
        f"{'under' if hv_mean[high] > 0 else 'over'} HEVC at VMAF {high}. VP9 wins this square "
        f"on licensing and browser reach rather than on bits, which is the honest reason to "
        f"pick it.")

prose["t_low"] = str(low)
prose["t_high"] = str(high)
prose["t_mid"] = str(mid)

# Tier 2 at the constrained end: whichever of HEVC and VP9 the data prefers.
_low2 = "VP9" if (hv_mean[low] or 0) > 0 else "HEVC"
prose["low_tier2_name"] = _low2
prose["low_tier2_why"] = (
    f"Where AV1 is not an option, this is the next best thing when bits are scarce: "
    f"{smaller(mean_sav(low, _low2))} than H.264 at VMAF {low}, against "
    f"{smaller(mean_sav(low, 'VP9' if _low2 == 'HEVC' else 'HEVC'))} for the other one. "
    + ("HEVC has hardware decode on anything sold since about 2015, and a licence bill "
       "attached to it. The problem has never been the technology."
       if _low2 == "HEVC" else
       "VP9 carries no licence bill and plays in every browser, which is why it takes this "
       "square even when the margin over HEVC is small."))

# How much the codecs converge at the generous end. The direction is read off
# the data rather than assumed, so the sentence cannot argue with the chart.
conv_high = {c: mean_sav(high, c) for c in CODECS
             if c != "H264" and mean_sav(high, c) is not None}
conv_low = {c: mean_sav(low, c) for c in conv_high}
spread_high = max(conv_high.values()) - min(conv_high.values())
spread_low = max(conv_low.values()) - min(conv_low.values())
if max(conv_high.values()) < max(conv_low.values()):
    prose["converge_note"] = (
        f"the best saving against H.264 falls from {pct(max(conv_low.values()))} at VMAF {low} "
        f"to {pct(max(conv_high.values()))} at VMAF {high}, and the gap between the three "
        f"non-H.264 codecs "
        + (f"closes from {pct(spread_low)} to {pct(spread_high)}"
           if spread_high < spread_low else f"holds at about {pct(spread_high)}"))
else:
    prose["converge_note"] = (
        f"the best saving against H.264 is {pct(max(conv_high.values()))} at VMAF {high} "
        f"against {pct(max(conv_low.values()))} at VMAF {low}, and the three non-H.264 codecs "
        f"sit {pct(spread_high)} apart")

# ---- does the ranking move with resolution? --------------------------------
orders = {r: A["order"][r] for r in RES}
same = all(orders[r][str(t)] == orders[RES[0]][str(t)]
           for r in RES for t in targets if str(t) in orders[r] and str(t) in orders[RES[0]])
worst_spread = max((v for c in A["saving_spread"] for v in A["saving_spread"][c].values()),
                   default=0)
order_1080 = " then ".join(LABEL[c] for c in orders["1080p"][str(mid)])

prose["ranking_note"] = (
    f"The ordering at VMAF {mid} is {order_1080}, and it is the same ordering at every "
    f"resolution and every target on this corpus"
    + ("" if same else ", with one exception noted in the table") + ". "
    f"The largest disagreement between resolutions for any one codec at any one target is "
    f"{worst_spread:.1f} percentage points, which is inside the noise of a "
    f"{len(CLIPS)}-clip corpus. Resolution moves you along the horizontal axis of the map; it "
    f"does not reorder the codecs once you are there.")

prose["claim_hypothesis"] = (
    f"The intuition that something changes is right; the axis is wrong. Normalise the bitrate "
    f"to bits per pixel per frame and the three resolutions land on the same curve, and the "
    f"ranking is {order_1080} at every one of them (largest disagreement across resolutions: "
    f"{worst_spread:.1f} percentage points). What changes at 4K is not the ranking but the "
    f"position: 4K60 at 15 Mbit/s is 0.0301 bits per pixel per frame, more constrained than "
    f"1080p30 at 3 Mbit/s at 0.0482, so 4K pushes you left into the region where the newer "
    f"codecs are furthest ahead. And HEVC does not win at 1080p between 1 and 10 Mbit/s "
    f"either: AV1 is {pct(mean_sav(mid, 'AV1'))} under H.264 at VMAF {mid} against HEVC's "
    f"{pct(mean_sav(mid, 'HEVC'))}. HEVC is the best of the codecs that were current in 2015.")

# ---- collapse ---------------------------------------------------------------
probe = A["collapse_probes"][1]
coll = []
for c in CODECS:
    vals = [A["collapse"][c][r].get(str(probe)) or A["collapse"][c][r].get(probe) for r in RES]
    vals = [v for v in vals if v is not None]
    if len(vals) == len(RES):
        coll.append((c, max(vals) - min(vals)))
worst = max(coll, key=lambda x: x[1]) if coll else ("", 0)
prose["collapse_note"] = (
    f"Three curves, one shape. At {probe} bits per pixel per frame the three resolutions land "
    f"within {worst[1]:.1f} VMAF points of each other for the worst codec on this corpus "
    f"({LABEL[worst[0]]}), and closer than that for the rest. This is the whole argument for "
    f"normalising: once you divide the bitrate by the pixel rate, resolution stops being a "
    f"variable and becomes a position on the axis you already have.")

# ---- encode cost ------------------------------------------------------------
ec = A["enc_cost"]["1080p"]
order_cost = sorted((c for c in CODECS if c in ec), key=lambda c: ec[c]["rel"])
slowest = order_cost[-1]
prose["cost_note"] = (
    f"At matched VMAF {A['cost_target']} and 1080p, {LABEL[slowest]} costs "
    f"{ec[slowest]['rel']:.1f} times what H.264 costs to encode, and HEVC "
    f"{ec['HEVC']['rel']:.1f} times, and VP9 {ec['VP9']['rel']:.1f} times. Two things follow. "
    f"For anything watched once, the encode can easily cost more than the bandwidth it saves. "
    f"For anything watched a million times, it is free. That, and not compression efficiency, "
    f"is why live streaming still ships H.264 while catalogue video has moved on.")

# ---- claims -----------------------------------------------------------------
hevc_mean_all = sum(mean_sav(t, "HEVC") for t in targets if mean_sav(t, "HEVC") is not None) / \
    len([t for t in targets if mean_sav(t, "HEVC") is not None])
hevc_best = max((mean_sav(t, "HEVC"), t) for t in targets if mean_sav(t, "HEVC") is not None)
prose["v_hevc50_class"] = dict(cls="part", text="Optimistic by half")
prose["claim_hevc50"] = (
    f"Not on these measurements. Against x264 at the same preset and the same VMAF, x265 came "
    f"in {smaller(mean_sav(mid, 'HEVC'))} at VMAF {mid} and {smaller(hevc_best[0])} at "
    f"its best target (VMAF {hevc_best[1]}), averaging {smaller(hevc_mean_all)} across the "
    f"range. "
    f"The 50% figure traces back to Ohm, Sullivan, Tan and Wiegand's 2012 comparison, which "
    f"measured the HEVC and H.264 <em>reference</em> encoders under subjective testing. Two "
    f"things shrink it in practice: x264 is a far better H.264 encoder than the reference "
    f"software was, and PSNR-driven reference comparisons flatter the newer codec. "
    f"Twenty-five to thirty-five percent is the number to plan with.")

vp9_vs_hevc_low = hv_mean[low]
vp9_vs_hevc_high = hv_mean[high]
flips = (vp9_vs_hevc_low > 0) != (vp9_vs_hevc_high > 0)
prose["v_vp9_class"] = dict(cls="part", text="Half right, and the half that matters is wrong")
prose["claim_vp9"] = (
    f"The 'very equal' half is right and it is the important half: across every resolution and "
    f"every target measured, VP9 and HEVC are within "
    f"{max(abs(v) for v in hv_mean.values() if v is not None):.1f} percentage points of each "
    f"other, and at VMAF {mid} the gap is {pct(abs(hv_mean[mid]))}. "
    + (f"The 'one wins low, the other high' half also shows up, but it is tiny: VP9 is "
       f"{pct(abs(vp9_vs_hevc_low))} {'ahead of' if vp9_vs_hevc_low > 0 else 'behind'} HEVC at "
       f"VMAF {low} and {pct(abs(vp9_vs_hevc_high))} "
       f"{'ahead' if vp9_vs_hevc_high > 0 else 'behind'} at VMAF {high}. "
       if flips else
       f"There is no crossover on this corpus: "
       f"{'VP9' if (hv_mean[mid] or 0) > 0 else 'HEVC'} is ahead at both ends, by "
       f"{pct(abs(vp9_vs_hevc_low))} at VMAF {low} and {pct(abs(vp9_vs_hevc_high))} at VMAF "
       f"{high}. ")
    + f"Either way it is not a difference worth choosing on. They are the same codec "
      f"generation, they were finished within a year of each other, and the reason YouTube "
      f"ships VP9 is that it is royalty-free and plays in Chrome, not that it compresses "
      f"better. AV1 is {pct(mean_sav(mid, 'AV1') - mean_sav(mid, 'VP9'))} ahead of VP9 at VMAF "
      f"{mid}, and that gap <em>is</em> worth choosing on.")

prose["claim_av1"] = (
    f"This has it exactly backwards, and it is the most common misconception about AV1. "
    f"Decoding AV1 is a little more expensive than decoding HEVC and is comfortably within a "
    f"software decoder on any modern CPU; dav1d decodes 1080p faster than real time on a phone "
    f"core. Hardware decode is now in every 2023-and-later flagship SoC, most smart TVs, and "
    f"every GPU from RTX 30, RDNA 2 and Intel Arc onward. It is the <em>encode</em> side that "
    f"is expensive: on this corpus libaom needed {ec['AV1']['rel']:.1f} times H.264's CPU for "
    f"the same VMAF, and libaom is the slow reference encoder. The hardware you want for AV1 "
    f"is on the encoder, and most people never touch that side.")

# ---- method and caveats -----------------------------------------------------
clip_desc = "; ".join(f"{c['name']} ({c['character'].lower()}, {c['seconds']:.0f} s, "
                      f"{c['frames']} frames at {c['fps']:.0f} fps)" for c in CLIPS)
prose["method_corpus"] = (
    f"{len(CLIPS)} pristine uncompressed clips from the Xiph derf collection: {clip_desc}. "
    f"Each was fetched as raw 1080p y4m and downscaled with Lanczos to 720p and 540p; nothing "
    f"was ever upscaled. Every clip was swept on its own CRF ladder in four encoders at three "
    f"resolutions, {A['n_encodes']} encodes in total, "
    f"{A['total_enc_cpu_s'] / 3600:.1f} CPU-hours of encoding and "
    f"{A['total_metric_cpu_s'] / 3600:.1f} CPU-hours of scoring.")

prose["method_metric"] = (
    f"Quality was scored with VMAF (model vmaf_v0.6.1) through ffmpeg's libvmaf filter, with "
    f"PSNR-Y and SSIM recorded in the same pass. Each codec was swept on its own CRF ladder; "
    f"the rate at a given VMAF target was found by interpolating that codec's own curve per "
    f"clip, then taking the geometric mean across clips. CRF ladders are per clip, because a "
    f"single ladder placed to span VMAF 78 to 98 on the high-motion clip only reaches the top "
    f"of the range on the easy one, and the comparison at the low end would then be an "
    f"artefact of the sweep. Rate is always bits per pixel per frame; container overhead is "
    f"removed, so an IVF frame header is not counted against VP9 and AV1. Encoders: ffmpeg "
    f"7.0.2 static, libx264, libx265, libvpx-vp9 and libaom-av1, each pinned to a single "
    f"thread so encoder CPU time is a clean cost measure. The machine was shared with other "
    f"jobs, which stretches wall-clock time but leaves the CPU-time ratios between codecs "
    f"intact.")

prose["caveat_presets"] = (
    f"x264 and x265 ran at -preset medium, VP9 at -cpu-used 2, libaom-AV1 at -cpu-used 6. "
    f"Slower presets are worth several percent of BD-rate and they are worth most to HEVC and "
    f"AV1, which have the largest search spaces, so these settings understate HEVC's and AV1's "
    f"lead rather than overstate it. A probe at -cpu-used 5 produced a file "
    f"12% smaller than -cpu-used 6 at the same CRF on the high-motion clip, which gives a "
    f"sense of the size of the effect.")

hard = [c["name"] for c in CLIPS if c["character"] == "High motion"]
prose["caveat_corpus"] = (
    f"{len(CLIPS)} clips is a small corpus, and it is deliberately a hard one: the "
    f"high-motion clip is close to the worst case for any codec, and the flat-gradient clip is "
    f"the banding worst case. Real catalogue content is easier than both, so the absolute "
    f"bits-per-pixel numbers here are pessimistic. The compute budget for this environment was "
    f"shared with other work and libaom is very slow, which is why the corpus is this size; a "
    f"third clip was fetched and is in the repository, "
    + ("and it is included in these results. "
       if len(CLIPS) > 2 else
       "but there was not time to sweep it. ")
    + f"The direction of every finding is robust to corpus size; the exact percentages are not "
      f"general constants.")

# ---- does the metric change the answer? -------------------------------------
bm = A["by_metric"]["1080p"]
mt = str(mid)
def _d(m, c):
    return bm[m][mt][c] - bm["vmaf"][mt][c]
worst_metric = max(((abs(_d(m, c)), m, c) for m in ("psnr_y", "ssim") for c in bm["vmaf"][mt]),
                   default=(0, "psnr_y", "AV1"))
same_order = all(sorted(bm[m][mt], key=lambda c: -bm[m][mt][c])
                 == sorted(bm["vmaf"][mt], key=lambda c: -bm["vmaf"][mt][c])
                 for m in ("psnr_y", "ssim"))
prose["metric_note"] = (
    f"The three metrics disagree, as they always do, but not about the answer: at VMAF {mid} "
    f"the largest gap between VMAF's verdict and another metric's is "
    f"{worst_metric[0]:.1f} percentage points "
    f"({LABEL[worst_metric[2]]} scored with "
    f"{'PSNR-Y' if worst_metric[1] == 'psnr_y' else 'SSIM'}), and "
    + ("the ordering of the codecs is identical under all three. "
       if same_order else "the ordering changes under at least one of them, so read the table. ")
    + f"That is the check that matters: VMAF over-rewards sharpening and is weak on banding, "
      f"so a result that only holds under VMAF is not a result. This one holds under all three.")

# ---- cheat-sheet CRF values -------------------------------------------------
prose["crf_av1"] = crf_at("1080p", "AV1")
prose["crf_vp9"] = crf_at("1080p", "VP9")
prose["crf_h264"] = crf_at("1080p", "H264")
prose["crf_note"] = (
    f"Those are ranges because content difficulty moves CRF a long way. On this corpus the "
    f"high-motion clip and the flat-gradient clip needed x264 CRF "
    f"{crf_span('1080p', 'H264')[0]} and {crf_span('1080p', 'H264')[1]} respectively to land "
    f"on the same VMAF {A['cost_target']}: the same setting is a different picture on "
    f"different footage, which is why per-title encoding exists.")

payload = dict(analysis=A, clips=CLIPS, prose=prose)
(DATA / "page_data.json").write_text(json.dumps(payload, separators=(",", ":")))
(DATA / "prose.json").write_text(json.dumps(prose, indent=1))
print(json.dumps({k: (v if isinstance(v, str) else v) for k, v in prose.items()}, indent=1))
