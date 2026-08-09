"""Sweep four video codecs across a CRF ladder at three resolutions.

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

Presets are the ones a practitioner would plausibly use for VOD but not the
slowest available, which biases against HEVC and AV1 (see caveats on the page).
Results append to data/video/rd_video.jsonl so the sweep is resumable.
"""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata" / "video"
DATA = ROOT / "data" / "video"
WORK = ROOT / ".work" / "video"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

RES = [("1080p", 1920, 1080), ("720p", 1280, 720), ("540p", 960, 540)]

# Ladders calibrated on a probe pass so every codec spans roughly VMAF 70 to 97
# on the hardest clip. A ladder that stops short would decide the comparison at
# that end rather than measure it.
# Ladders are per clip, not global. A probe pass showed the two clips sit about
# eight x264 CRF steps apart in difficulty: at CRF 34 the high-motion clip
# scores VMAF 60 and the flat-gradient clip 88. One shared ladder would have
# measured the easy clip only at the top of the range and the hard clip only at
# the bottom, and the comparison at each end would then be an artefact of the
# ladder rather than a finding. Each ladder is placed to span roughly VMAF 78 to
# 98 on its own clip. Fewer CRF steps buy the same VMAF range on VP9 and AV1
# because their CRF scales are coarser, hence the wider spacing there.
LADDER = {
    "park_joy": {
        "H264": [21, 23, 25, 27, 29, 31, 33],
        "HEVC": [22, 24, 26, 28, 30, 32, 34],
        "VP9": [39, 42, 45, 47, 49, 52, 55],
        "AV1": [34, 38, 42, 45, 48, 52, 56],
    },
    "in_to_tree": {
        "H264": [21, 23, 25, 27, 29, 31, 33],
        "HEVC": [22, 24, 26, 28, 30, 32, 34],
        "VP9": [39, 42, 45, 47, 49, 52, 55],
        "AV1": [34, 38, 42, 45, 48, 52, 56],
    },
    "blue_sky": {
        "H264": [28, 30, 32, 34, 36, 38, 40],
        "HEVC": [29, 31, 33, 35, 37, 39, 41],
        "VP9": [49, 52, 55, 57, 59, 61, 63],
        "AV1": [46, 50, 53, 56, 58, 61, 63],
    },
}
CODEC_ORDER = ["H264", "HEVC", "VP9", "AV1"]
# Emit a coarse pass that already spans the whole range, then refine. An
# interrupted sweep then leaves a usable ladder rather than a ragged one.
STAGES = [[0, 2, 4, 6], [1, 3, 5]]
CLIP_WAVES = [["park_joy", "blue_sky"], ["in_to_tree"]]


def enc_args(codec, crf, gop):
    if codec == "H264":
        return (["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                 "-g", str(gop), "-keyint_min", str(gop)], "h264", "264")
    if codec == "HEVC":
        return (["-c:v", "libx265", "-preset", "medium", "-crf", str(crf),
                 "-x265-params",
                 f"log-level=error:pools=none:frame-threads=1:keyint={gop}:min-keyint={gop}"],
                "hevc", "265")
    if codec == "VP9":
        return (["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf), "-cpu-used", "2",
                 "-deadline", "good", "-row-mt", "0", "-g", str(gop)], "ivf", "ivf")
    if codec == "AV1":
        return (["-c:v", "libaom-av1", "-b:v", "0", "-crf", str(crf), "-cpu-used", "6",
                 "-usage", "good", "-row-mt", "0", "-g", str(gop)], "ivf", "ivf")
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
    args, fmt, ext = enc_args(codec, crf, gop)
    out = WORK / f"{clip}_{res}_{codec}_{crf}.{ext}"
    log = WORK / f"{clip}_{res}_{codec}_{crf}.json"

    wall, cpu = run_timed(
        [FFMPEG, "-y", "-v", "error", "-nostdin", "-i", str(src)] + args +
        ["-pix_fmt", "yuv420p", "-threads", "1", "-f", fmt, str(out)])

    size = out.stat().st_size
    # IVF carries a 32-byte file header and a 12-byte header per frame. Annex-B
    # h264/hevc have no container at all, so strip IVF to compare like for like.
    payload = size - (32 + 12 * n) if ext == "ivf" else size

    _, mcpu = run_timed(
        [FFMPEG, "-v", "error", "-nostdin", "-r", str(fps), "-i", str(out),
         "-r", str(fps), "-i", str(src),
         "-lavfi",
         "[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];"
         f"[d][r]libvmaf=feature='name=psnr|name=float_ssim':log_fmt=json:"
         f"log_path={log}:n_threads=1",
         "-f", "null", "-"])
    m = json.loads(log.read_text())["pooled_metrics"]
    out.unlink()
    log.unlink()

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
    jobs = []
    for names in CLIP_WAVES:
        for idxs in STAGES:
            for res, w, h in RES:
                for codec in CODEC_ORDER:
                    for i in idxs:
                        for name in names:
                            c = byname.get(name)
                            if c is None:
                                continue
                            crf = LADDER[name][codec][i]
                            if (name, res, codec, crf) in done:
                                continue
                            jobs.append(dict(clip=name, res=res, w=w, h=h,
                                             frames=c["frames"], fps=c["fps"],
                                             codec=codec, crf=crf))

    print(f"{len(jobs)} jobs, {len(done)} already done, {workers} workers", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex, open(outfile, "a") as f:
        for i, r in enumerate(ex.map(job, jobs), 1):
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(f"[{i}/{len(jobs)}] {int(time.time() - t0):5d}s  {r['clip']:11s} "
                  f"{r['res']:6s} {r['codec']:5s} crf{r['crf']:<3d} "
                  f"{r['bpppf']:.4f} bpppf  vmaf {r['vmaf']:6.2f}  "
                  f"enc {r['enc_cpu_s']:7.1f}s", flush=True)
    print(f"done in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
