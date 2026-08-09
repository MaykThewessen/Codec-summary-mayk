"""Fetch a few pristine uncompressed clips from the Xiph derf collection.

The full sequences are 0.6 to 1.5 GB each. A y4m file is a short ASCII header
followed by fixed-size frames, so an HTTP range request for the first N frames
gives a valid, complete y4m without pulling the whole thing.

Three clips with deliberately different character:
  park_joy    high motion, water and foliage, the hardest thing to code
  in_to_tree  slow push, very fine high-frequency detail, near-static camera
  blue_sky    large flat gradient sky plus hard thin branches, banding bait

720p and 540p are derived by downscaling here (never upscaling), which is
exactly what an encoding ladder does in production.
"""

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "testdata" / "video"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
BASE = "https://media.xiph.org/video/derf/y4m/"

CLIPS = [
    dict(name="park_joy", src="park_joy_1080p50.y4m", frames=150,
         character="High motion", note="Hand-held pan across a park, water spray and foliage. The hardest kind of content to code: motion in every direction and no flat area to hide in."),
    dict(name="in_to_tree", src="in_to_tree_1080p50.y4m", frames=150,
         character="Fine detail, slow", note="A slow push toward a tree line. Almost no global motion, but dense high-frequency leaf detail everywhere."),
    dict(name="blue_sky", src="blue_sky_1080p25.y4m", frames=75,
         character="Flat gradient", note="A rotating shot of bare branches against an open sky. Large smooth gradients next to hard thin edges: the classic banding trap."),
]

LADDER = [("1080p", 1920, 1080), ("720p", 1280, 720), ("540p", 960, 540)]


def head(url):
    req = urllib.request.Request(url, headers={"Range": "bytes=0-255"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def fetch_range(url, nbytes, dest):
    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{nbytes - 1}"})
    with urllib.request.urlopen(req, timeout=1800) as r, open(dest, "wb") as f:
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
    return got


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = []
    for clip in CLIPS:
        url = BASE + clip["src"]
        blob = head(url)
        hdr_end = blob.index(b"\n") + 1
        hdr = blob[:hdr_end].decode()
        fields = dict(w=0, h=0, fps=0.0)
        for tok in hdr.split()[1:]:
            if tok[0] == "W":
                fields["w"] = int(tok[1:])
            elif tok[0] == "H":
                fields["h"] = int(tok[1:])
            elif tok[0] == "F":
                num, den = tok[1:].split(":")
                fields["fps"] = int(num) / int(den)
        w, h = fields["w"], fields["h"]
        assert (w, h) == (1920, 1080), (clip["name"], w, h)
        # 4:2:0 8-bit plus the six-byte FRAME marker
        frame_bytes = w * h * 3 // 2 + 6
        assert blob[hdr_end:hdr_end + 6] == b"FRAME\n"
        want = hdr_end + clip["frames"] * frame_bytes

        dest = OUT / f"{clip['name']}_1080p.y4m"
        if not dest.exists() or dest.stat().st_size != want:
            print(f"fetch {clip['name']}: {want / 1e6:.0f} MB "
                  f"({clip['frames']} frames @ {fields['fps']:.0f} fps)", flush=True)
            got = fetch_range(url, want, dest)
            assert got == want, (got, want)
        else:
            print(f"have  {clip['name']}: {want / 1e6:.0f} MB", flush=True)

        for label, lw, lh in LADDER[1:]:
            small = OUT / f"{clip['name']}_{label}.y4m"
            if small.exists():
                continue
            print(f"scale {clip['name']} -> {label}", flush=True)
            subprocess.run(
                [FFMPEG, "-y", "-v", "error", "-i", str(dest),
                 "-vf", f"scale={lw}:{lh}:flags=lanczos", "-pix_fmt", "yuv420p",
                 "-f", "yuv4mpegpipe", str(small)], check=True)

        meta.append(dict(name=clip["name"], source=clip["src"], character=clip["character"],
                         note=clip["note"], frames=clip["frames"], fps=round(fields["fps"], 3),
                         seconds=round(clip["frames"] / fields["fps"], 2)))

    (ROOT / "data" / "video").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "video" / "clips.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    sys.exit(main())
