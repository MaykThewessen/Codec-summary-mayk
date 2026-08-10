"""Sweep six video encoders across a CRF ladder at three resolutions.

One job = one (clip, resolution, codec, CRF) encode plus one metric pass.
Every job records:

  bytes        elementary-stream size, container overhead removed
  bpppf        bits per pixel per frame: bytes*8 / (w*h*frames)
  vmaf         Netflix VMAF, model vmaf_v0.6.1, mean over frames
  psnr_y, ssim recorded from the same libvmaf pass, for comparison
  cpu_s        encoder CPU seconds (single-threaded), the encode-cost axis

Encoders are pinned to a single thread so cpu_s is a clean measure of
computational cost, and four jobs run in parallel instead. CRF/CQ mode
throughout: fixed-bitrate mode would hide exactly the differences we want.

Six encoders, five formats. AV1 appears twice on purpose: libaom is the slow
reference encoder and SVT-AV1 is what production actually runs, and the whole
question of what AV1 costs turns on which one you mean.

ONE BINARY. Every encode, every downscale and every metric pass in this file
runs on /opt/ffmpeg-gpl/ffmpeg. An earlier version of this sweep used the
imageio-ffmpeg 7.0.2 static build, which had no libvvenc and no libsvtav1; that
file is kept as data/video/rd_video_ffmpeg702.jsonl for provenance and none of
its rows are mixed in here. Comparing codecs across two encoder builds would
make part of the answer a statement about which binary produced which codec.

Results append to data/video/rd_video.jsonl so the sweep is resumable.
"""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata" / "video"
DATA = ROOT / "data" / "video"
WORK = ROOT / ".work" / "video"
FFMPEG = "/opt/ffmpeg-gpl/ffmpeg"

RES = [("1080p", 1920, 1080), ("720p", 1280, 720), ("540p", 960, 540)]

# Ladders are per clip, not global. A probe pass showed the two clips sit about
# eight x264 CRF steps apart in difficulty: at CRF 34 the high-motion clip
# scores VMAF 60 and the flat-gradient clip 88. One shared ladder would have
# measured the easy clip only at the top of the range and the hard clip only at
# the bottom, and the comparison at each end would then be an artefact of the
# ladder rather than a finding. Each ladder is placed to span roughly VMAF 72 to
# 99 on its own clip at 1080p, which leaves headroom at 540p where the same
# setting scores two to three points lower against the downscaled reference.
# Fewer CRF steps buy the same VMAF range on VP9 and AV1 because their CRF
# scales are coarser, hence the wider spacing there. SVTAV1 and VVC ladders were
# placed by a full-clip calibration pass on this binary, not carried over.
LADDER = {
    "park_joy": {
        "H264": [21, 23, 25, 27, 29, 31, 33],
        "HEVC": [22, 24, 26, 28, 30, 32, 34],
        "VP9": [39, 42, 45, 47, 49, 52, 55, 35],
        "AV1": [34, 38, 42, 45, 48, 52, 56],
        "SVTAV1": [35, 39, 42, 45, 48, 51, 55],
        "VVC": [21, 23, 25, 27, 29, 30, 32],
    },
    "blue_sky": {
        "H264": [28, 30, 32, 34, 36, 38, 40],
        "HEVC": [29, 31, 33, 35, 37, 39, 41],
        "VP9": [49, 52, 55, 57, 59, 61, 63, 45, 41],
        "AV1": [46, 50, 53, 56, 58, 61, 63],
        "SVTAV1": [46, 50, 54, 57, 59, 61, 63, 62],
        # The trailing 43 is an extension pass: the first sweep left VVC's
        # flat-gradient ladder bottoming out at VMAF 80.8 at 540p, which would
        # have made the VMAF 80 comparison a statement about the ladder rather
        # than about VVC.
        "VVC": [27, 30, 33, 35, 37, 39, 41, 43],
    },
}
CODEC_ORDER = ["H264", "HEVC", "VP9", "AV1", "SVTAV1", "VVC"]
CLIPS_SWEPT = ["park_joy", "blue_sky"]
# Emit a coarse pass that already spans the whole range, then refine. An
# interrupted sweep then leaves a usable ladder rather than a ragged one.
# The trailing entries are the extension pass for VP9, whose first sweep topped
# out at VMAF 93 on the flat-gradient clip.
STAGES = [[0, 2, 4, 6], [1, 3, 5], [7, 8]]

# Rough single-thread cost per frame at 1080p, used only to schedule the long
# jobs first so the tail does not idle three of the four workers.
COST_HINT = {"H264": 0.11, "HEVC": 0.21, "VP9": 0.46, "AV1": 0.8,
             "SVTAV1": 0.22, "VVC": 5.0}
PIXELS = {"1080p": 1.0, "720p": 0.444, "540p": 0.25}


def enc_args(codec, crf, gop, fps):
    """Encoder arguments, output pixel format, ffmpeg muxer, file extension.

    Presets, and why these:

    H264/HEVC  -preset medium. Unchanged from the previous sweep so the page
               stays comparable to what it said before.
    VP9        -cpu-used 2, AV1 -cpu-used 6. Also unchanged.
    SVTAV1     -preset 6. SVT-AV1's own documentation calls 6 the VOD default,
               and on this corpus it costs about the same per frame as x265 at
               -preset medium, so it is a fair speed-analogue of the HEVC
               setting rather than a handicap or a favour.
    VVC        -preset medium, the middle of libvvenc's five presets and its
               default. Faster would have understated VVC.

    libvvenc accepts only yuv420p10le, so VVC alone codes 10-bit internally and
    is decoded back to 8-bit for scoring. That is worth a few percent to VVC and
    is noted on the page; it is forced by the encoder, not chosen here.
    """
    if codec == "H264":
        return (["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                 "-g", str(gop), "-keyint_min", str(gop)], "yuv420p", "h264", "264")
    if codec == "HEVC":
        return (["-c:v", "libx265", "-preset", "medium", "-crf", str(crf),
                 "-x265-params",
                 f"log-level=error:pools=none:frame-threads=1:keyint={gop}:min-keyint={gop}"],
                "yuv420p", "hevc", "265")
    if codec == "VP9":
        return (["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf), "-cpu-used", "2",
                 "-deadline", "good", "-row-mt", "0", "-g", str(gop)], "yuv420p", "ivf", "ivf")
    if codec == "AV1":
        return (["-c:v", "libaom-av1", "-b:v", "0", "-crf", str(crf), "-cpu-used", "6",
                 "-usage", "good", "-row-mt", "0", "-g", str(gop)], "yuv420p", "ivf", "ivf")
    if codec == "SVTAV1":
        # lp=1 holds SVT-AV1 to one logical process, matching the single thread
        # every other encoder here is held to.
        return (["-c:v", "libsvtav1", "-preset", "6", "-crf", str(crf),
                 "-g", str(gop), "-svtav1-params", "lp=1"], "yuv420p", "ivf", "ivf")
    if codec == "VVC":
        return (["-c:v", "libvvenc", "-preset", "medium", "-qp", str(crf),
                 "-g", str(gop), "-period", str(round(gop / fps))],
                "yuv420p10le", "vvc", "vvc")
    raise ValueError(codec)


def run_timed(cmd):
    """Wall and child CPU seconds for one subprocess."""
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, status, ru = os.wait4(p.pid, 0)
    err = p.stderr.read().decode(errors="replace")
    p.stderr.close()
    if status != 0:
        raise RuntimeError(" ".join(cmd[:12]) + "\n" + err[-2000:])
    return time.time() - t0, ru.ru_utime + ru.ru_stime


def job(spec):
    clip, res, codec, crf = spec["clip"], spec["res"], spec["codec"], spec["crf"]
    src = TESTDATA / f"{clip}_{res}.y4m"
    w, h = spec["w"], spec["h"]
    n, fps = spec["frames"], spec["fps"]
    gop = max(1, round(2 * fps))
    args, pixfmt, fmt, ext = enc_args(codec, crf, gop, fps)
    out = WORK / f"{clip}_{res}_{codec}_{crf}.{ext}"
    log = WORK / f"{clip}_{res}_{codec}_{crf}.json"

    wall, cpu = run_timed(
        [FFMPEG, "-y", "-v", "error", "-nostdin", "-i", str(src)] + args +
        ["-pix_fmt", pixfmt, "-threads", "1", "-f", fmt, str(out)])

    size = out.stat().st_size
    # IVF carries a 32-byte file header and a 12-byte header per frame. Annex-B
    # h264/hevc/vvc have no container at all, so strip IVF to compare like for
    # like.
    payload = size - (32 + 12 * n) if ext == "ivf" else size

    # format=yuv420p on the distorted side brings VVC's 10-bit decode back to
    # the 8-bit source depth; it is a no-op for the other five. -frames:v pins
    # the comparison to the source length so a decoder that emits a frame more
    # or less cannot silently score padding against real frames.
    _, mcpu = run_timed(
        [FFMPEG, "-v", "error", "-nostdin", "-r", str(fps), "-i", str(out),
         "-r", str(fps), "-i", str(src),
         "-lavfi",
         "[0:v]format=yuv420p,setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];"
         f"[d][r]libvmaf=feature='name=psnr|name=float_ssim':log_fmt=json:"
         f"log_path={log}:n_threads=1",
         "-frames:v", str(n), "-f", "null", "-"])
    doc = json.loads(log.read_text())
    m = doc["pooled_metrics"]
    scored = len(doc["frames"])
    out.unlink()
    log.unlink()
    if scored != n:
        raise RuntimeError(f"{clip} {res} {codec} {crf}: scored {scored} of {n} frames")

    return dict(clip=clip, res=res, w=w, h=h, frames=n, fps=fps, codec=codec, crf=crf,
                bytes=payload,
                kbps=round(payload * 8 / (n / fps) / 1000, 1),
                bpppf=round(payload * 8 / (w * h * n), 6),
                vmaf=round(m["vmaf"]["mean"], 3),
                psnr_y=round(m["psnr_y"]["mean"], 3),
                ssim=round(m["float_ssim"]["mean"], 5),
                enc_wall_s=round(wall, 2), enc_cpu_s=round(cpu, 2),
                metric_cpu_s=round(mcpu, 2))


def main(workers=4):
    WORK.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    clips = json.loads((DATA / "clips.json").read_text())
    outfile = DATA / "rd_video.jsonl"

    done = set()
    if outfile.exists():
        for line in outfile.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["clip"], r["res"], r["codec"], r["crf"]))

    byname = {c["name"]: c for c in clips}
    stages = []
    for idxs in STAGES:
        batch = []
        for res, w, h in RES:
            for codec in CODEC_ORDER:
                for i in idxs:
                    for name in CLIPS_SWEPT:
                        c = byname.get(name)
                        if c is None or i >= len(LADDER[name][codec]):
                            continue
                        crf = LADDER[name][codec][i]
                        if (name, res, codec, crf) in done:
                            continue
                        batch.append(dict(clip=name, res=res, w=w, h=h,
                                          frames=c["frames"], fps=c["fps"],
                                          codec=codec, crf=crf))
        # Longest job first inside a stage: a 20-minute VVC encode started last
        # would leave three workers idle waiting for it.
        batch.sort(key=lambda s: -COST_HINT[s["codec"]] * PIXELS[s["res"]] * s["frames"])
        stages.append(batch)

    total = sum(len(b) for b in stages)
    print(f"{total} jobs in {len(stages)} stages, {len(done)} already done, "
          f"{workers} workers", flush=True)
    t0 = time.time()
    i = 0
    with ProcessPoolExecutor(max_workers=workers) as ex, open(outfile, "a") as f:
        for batch in stages:
            futs = [ex.submit(job, s) for s in batch]
            for fut in as_completed(futs):
                r = fut.result()
                i += 1
                f.write(json.dumps(r) + "\n")
                f.flush()
                print(f"[{i}/{total}] {int(time.time() - t0):5d}s  {r['clip']:9s} "
                      f"{r['res']:6s} {r['codec']:7s} q{r['crf']:<3d} "
                      f"{r['bpppf']:.4f} bpppf  vmaf {r['vmaf']:6.2f}  "
                      f"enc {r['enc_cpu_s']:7.1f}s", flush=True)
    print(f"done in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
