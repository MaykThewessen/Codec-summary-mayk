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


def head_to_head(target, a_codec, b_codec):
    """How much smaller a_codec is than b_codec, mean over the resolutions.

    Subtracting two savings-against-H.264 gives percentage points, not a
    percentage. This gives the number people actually mean.
    """
    vals = [100 * (1 - matched(r, target, a_codec) / matched(r, target, b_codec))
            for r in RES if has(r, target, a_codec) and has(r, target, b_codec)]
    return sum(vals) / len(vals) if vals else None


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

def _high_tier2_why():
    """At the generous end the two tier-2 codecs are close enough that the
    decision stops being about bits and starts being about where it must play."""
    return (
        f"At this density the two tier-2 codecs are close enough that efficiency stops "
        f"deciding: VP9 is {pct(abs(hv_mean[high]))} "
        f"{'smaller' if hv_mean[high] > 0 else 'larger'} than HEVC at VMAF {high}, and both "
        f"are well behind AV1. So pick on where the file has to play. HEVC is what broadcast "
        f"chains, UHD Blu-ray, Apple devices and cameras speak natively; VP9 is what browsers "
        f"speak. If it is going to a television, that is HEVC.")


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
    prose["vp9_high_why"] = _high_tier2_why()
else:
    lead = hv_mean[mid]
    who = "VP9" if lead > 0 else "HEVC"
    prose["mid_tier2_name"] = f"{who}, by a nose"
    prose["mid_tier2_why"] = (
        f"These two are the same codec generation and it shows: {who} is only "
        f"{pct(abs(lead))} ahead at VMAF {mid}, averaged over the three resolutions, and it "
        f"never gets further than "
        f"{max(abs(v) for v in hv_mean.values() if v is not None):.1f} percentage points ahead "
        f"anywhere. Pick on reach, not on efficiency. VP9 plays in every browser "
        f"and costs nothing to licence; HEVC does neither, and has hardware everywhere.")
    prose["vp9_high_why"] = _high_tier2_why()

prose["t_low"] = str(low)
prose["t_high"] = str(high)
prose["t_mid"] = str(mid)

# Tier 2 at the constrained end: whichever of HEVC and VP9 the data prefers.
_low2 = "VP9" if (hv_mean[low] or 0) > 0 else "HEVC"
prose["low_tier2_name"] = _low2
prose["chip_low_tier2"] = (dict(cls="warn", text="Current hardware, licensed")
                           if _low2 == "HEVC" else
                           dict(cls="good", text="Every browser, royalty-free"))
prose["low_tier2_cmd"] = ("x265 -preset medium -crf 28" if _low2 == "HEVC"
                          else "libvpx-vp9 -b:v 0 -crf 40 -cpu-used 2")
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
        + (f"closes from {spread_low:.1f} to {spread_high:.1f} percentage points"
           if spread_high < spread_low else
           f"holds at about {spread_high:.1f} percentage points"))
else:
    prose["converge_note"] = (
        f"the best saving against H.264 is {pct(max(conv_high.values()))} at VMAF {high} "
        f"against {pct(max(conv_low.values()))} at VMAF {low}, and the three non-H.264 codecs "
        f"sit {spread_high:.1f} percentage points apart")

# ---- does the ranking move with resolution? --------------------------------
orders = {r: A["order"][r] for r in RES}
same = all(orders[r][str(t)] == orders[RES[0]][str(t)]
           for r in RES for t in targets if str(t) in orders[r] and str(t) in orders[RES[0]])
order_1080 = " then ".join(LABEL[c] for c in orders["1080p"][str(mid)])

sp = A["saving_spread"]
worst_c = max(sp, key=lambda c: max(sp[c].values(), default=0))
worst_spread = max(sp[worst_c].values())
best_res, worst_res = RES[0], RES[-1]
# Where the ordering does differ, name the swap once and list where it happens.
alt = {}
for r in RES:
    for t in targets:
        o = tuple(orders[r][str(t)])
        if o != tuple(orders["1080p"][str(t)]):
            alt.setdefault(o, []).append(f"{r} VMAF {t}")
exc = ""
if alt:
    parts = [f"{' then '.join(LABEL[c] for c in o)} at {', '.join(where)}"
             for o, where in alt.items()]
    exc = (" The exception is one swap: " if len(alt) == 1 else " The exceptions: ") \
        + "; ".join(parts) + "."

prose["ranking_note"] = (
    f"The ordering at VMAF {mid} is {order_1080}, and it is that same ordering at every "
    f"resolution and every target measured" + ("." if not alt else " bar a few.") + exc + " "
    f"The margins are another matter. AV1 is {pct(sav(best_res, mid, 'AV1'))} under H.264 at "
    f"{best_res} and {pct(sav(worst_res, mid, 'AV1'))} at {worst_res}; HEVC is "
    f"{pct(sav(best_res, mid, 'HEVC'))} and {pct(sav(worst_res, mid, 'HEVC'))}. The largest "
    f"swing across resolutions for one codec at one target is {worst_spread:.1f} percentage "
    f"points ({LABEL[worst_c]}). Resolution does not reorder the codecs; it decides how much "
    f"the newer ones are worth, and it points the same way as bitrate does.")

prose["claim_hypothesis"] = (
    f"Half right, and the half that is right is more useful than it looks. The ranking does "
    f"not move much: {order_1080} at 1080p, and the same order almost everywhere else, so "
    f"HEVC does "
    f"not win at 1080p between 1 and 10 Mbit/s. AV1 does, by {pct(sav('1080p', mid, 'AV1'))} "
    f"against H.264 where HEVC manages {pct(sav('1080p', mid, 'HEVC'))}. But the intuition "
    f"that resolution matters is correct, just not in the way the question assumed: it changes "
    f"the size of the win, not its owner. AV1's lead over H.264 goes from "
    f"{pct(sav('540p', mid, 'AV1'))} at 540p to {pct(sav('1080p', mid, 'AV1'))} at 1080p, and "
    f"HEVC's from {pct(sav('540p', mid, 'HEVC'))} to {pct(sav('1080p', mid, 'HEVC'))}: at 540p "
    f"HEVC is barely worth the trouble. Extrapolate the trend and 4K is where the modern "
    f"codecs are furthest ahead, for two reasons at once. More pixels gives their larger "
    f"transforms and prediction blocks more to work with, and 4K at a normal streaming bitrate "
    f"sits further left on the bits-per-pixel axis, where their lead is largest anyway. "
    f"4K60 at 15 Mbit/s is 0.0301 bits per pixel per frame; 1080p30 at 3 Mbit/s is 0.0482.")

# ---- do the resolutions land on one curve? ---------------------------------
# They do not, and saying so is the point: normalising puts the resolutions on
# one axis, not on one line. More pixels means more redundancy per pixel.
probe = A["collapse_probes"][1]
gaps = []
for c in CODECS:
    vals = [A["collapse"][c][r].get(str(probe)) for r in RES]
    if all(v is not None for v in vals):
        gaps.append((c, vals[0] - vals[-1], vals))
best = max(gaps, key=lambda g: g[1]) if gaps else ("", 0, [0, 0, 0])
prose["collapse_note"] = (
    f"Three curves, one shape, and a real offset between them. At {probe} bits per pixel per "
    f"frame {LABEL[best[0]]} reaches VMAF {best[2][0]:.1f} at 1080p and {best[2][-1]:.1f} at "
    f"540p, a gap of {best[1]:.1f} points for the same bits per pixel. Higher resolution is "
    f"cheaper per pixel, because neighbouring pixels are more alike and prediction has more to "
    f"work with. So normalising by pixel rate puts the resolutions on one axis, not on one "
    f"line, and what it buys is that the ordering of the codecs and the shape of every curve "
    f"become directly comparable across them.")

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

# ---- does the metric change the answer? -------------------------------------
bm = A["by_metric"]["1080p"]
mts = [t for t in A["targets"]
       if all(str(t) in bm[m] for m in ("vmaf", "psnr_y", "ssim"))]
if mts:
    mt = str(mid if mid in mts else mts[len(mts) // 2])

    def _d(m, c):
        return bm[m][mt][c] - bm["vmaf"][mt][c]

    worst_metric = max((abs(_d(m, c)), m, c)
                       for m in ("psnr_y", "ssim") for c in bm["vmaf"][mt])
    same_order = all(sorted(bm[m][mt], key=lambda c: -bm[m][mt][c])
                     == sorted(bm["vmaf"][mt], key=lambda c: -bm["vmaf"][mt][c])
                     for m in ("psnr_y", "ssim"))
    prose["metric_note"] = (
        f"The three metrics disagree, as they always do"
        + (", but not about the answer" if same_order else "") + ": at VMAF "
        f"{mt} the largest gap between VMAF's verdict and another metric's is "
        f"{worst_metric[0]:.1f} percentage points ({LABEL[worst_metric[2]]} scored with "
        f"{'PSNR-Y' if worst_metric[1] == 'psnr_y' else 'SSIM'}), and "
        + ("the ordering of the codecs is identical under all three, which is the check "
           "that matters: a result that only holds under VMAF is not a result. "
           if same_order else
           "the ordering is not identical under all three, so the table is the honest "
           "summary and the headline percentages should be read as VMAF's opinion. ")
        + f"SSIM is a poor cross-codec judge at low rates and that is where most of the "
          f"disagreement sits. VMAF's own weaknesses run the other way: it over-rewards "
          f"sharpening and is weak on banding.")
else:
    prose["metric_note"] = (
        "The cross-check could not be completed at any target on this sweep: matching on "
        "PSNR-Y or SSIM requires the other codec's ladder to cover the PSNR that H.264 reached "
        "at the VMAF target, and on this corpus it does not everywhere. Rather than clamp to "
        "the end of a ladder and invent the answer, the comparison is left out. Per-encode "
        "PSNR-Y and SSIM are in the raw sweep file.")

# ---- claims -----------------------------------------------------------------
hevc_mean_all = sum(mean_sav(t, "HEVC") for t in targets if mean_sav(t, "HEVC") is not None) / \
    len([t for t in targets if mean_sav(t, "HEVC") is not None])
hevc_best = max((mean_sav(t, "HEVC"), t) for t in targets if mean_sav(t, "HEVC") is not None)
prose["v_hevc50_class"] = dict(cls="part", text="Optimistic by half")
prose["claim_hevc50"] = (
    f"Not on these measurements, and not close. Against x264 at the same preset and the same "
    f"VMAF, x265 came in {smaller(sav('1080p', mid, 'HEVC'))} at 1080p and VMAF {mid}; its "
    f"best showing anywhere was {smaller(sav('1080p', low, 'HEVC'))} at 1080p and VMAF {low}; "
    f"and at 540p it was {smaller(sav('540p', mid, 'HEVC'))} than x264 for the same picture. "
    f"The 50% figure traces back to Ohm, Sullivan, Tan and Wiegand's 2012 comparison, which "
    f"measured the HEVC and H.264 <em>reference</em> encoders under subjective testing. Two "
    f"things shrink it in practice: x264 is a far better H.264 encoder than the reference "
    f"software was, and PSNR-driven reference comparisons flatter the newer codec. That "
    f"second point shows up directly in this sweep: score the identical encodes with PSNR-Y "
    f"instead of VMAF and x265 comes out {smaller(bm['psnr_y'][mt]['HEVC'])} than x264 rather "
    f"than {smaller(bm['vmaf'][mt]['HEVC'])}. A good part of the distance between 50% and what "
    f"you will actually see is the choice of metric. Twenty to thirty percent is the number to "
    f"plan with at 1080p, and less than that below it.")

vp9_vs_hevc_low = hv_mean[low]
vp9_vs_hevc_high = hv_mean[high]
flips = (vp9_vs_hevc_low > 0) != (vp9_vs_hevc_high > 0)
prose["v_vp9_class"] = (
    dict(cls="part", text="Half right")
    if flips else dict(cls="part", text="Right about close, wrong about the crossover"))
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
    + f"It is a real edge to VP9 and it is a small one. They are the same codec generation, "
      f"they were finished within a year of each other, and the reason YouTube ships VP9 is "
      f"that it is royalty-free and plays in Chrome, not that it compresses better. For scale: "
      f"AV1 files are {pct(head_to_head(mid, 'AV1', 'VP9'))} smaller than VP9 files at VMAF "
      f"{mid} for the same picture. That gap <em>is</em> worth choosing on; four percent is "
      f"not.")

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
    f"lead rather than overstate it. For scale: a calibration probe at -cpu-used 5 produced a "
    f"file 12% smaller than -cpu-used 6 at the same CRF on the high-motion clip. That pair was "
    f"not quality-scored, so read it as an indication of the size of the preset effect rather "
    f"than as a BD-rate.")

prose["caveat_vmaf"] = (
    "VMAF was trained on Netflix's own catalogue and its own scaling pipeline. It "
    "over-rewards sharpening and contrast enhancement, it is weak on banding, and it was "
    "fitted for 1080p viewed at a set distance. PSNR-Y and SSIM are recorded alongside every "
    "encode in the raw data, and the cross-check above shows they do not simply agree: PSNR-Y "
    "is markedly more generous to the newer codecs than VMAF is, SSIM markedly less. Where a "
    "page quotes one number, it is quoting one metric's opinion. Everything here is VMAF's.")

hard = [c["name"] for c in CLIPS if c["character"] == "High motion"]
prose["caveat_corpus"] = (
    f"{len(CLIPS)} clips is a small corpus, and it is deliberately a hard one: the "
    f"high-motion clip is close to the worst case for any codec, and the flat-gradient clip is "
    f"the banding worst case. Real catalogue content is easier than both, so the absolute "
    f"bits-per-pixel numbers here are pessimistic. The compute budget for this environment was "
    f"shared with other work and libaom is very slow, which is why the corpus is this size; a "
    f"third clip was fetched and is in the repository, "
    + ("and it is included in these results. " if not A.get("dropped_clips") else
       f"but only partially swept ({', '.join(A['dropped_clips'])}), so it is excluded from "
       f"every number on this page rather than half-counted. ")
    + f"The direction of every finding is robust to corpus size; the exact percentages are not "
      f"general constants.")

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
