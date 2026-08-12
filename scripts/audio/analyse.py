"""Reduce the raw sweep to the numbers the page plots.

Everything here is a summary of measurements.json. No perceptual claim is
derived, because none can be: see the note at the top of measure_audio.py.

    python3 scripts/audio/analyse.py
"""

import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "audio"

LOSSY = ["OPUS", "AAC", "MP3", "VORBIS"]
FLAC_LEVELS = ["FLAC-0", "FLAC-5", "FLAC-8", "FLAC-12"]
PROBE = "probe_noise"


def med(xs):
    return round(st.median(xs), 2) if xs else None


def main():
    M = json.loads((DATA / "measurements.json").read_text())
    rows = [r for r in M["rows"] if not r.get("failed")]
    fails = [r for r in M["rows"] if r.get("failed")]
    clips = M["corpus"]["clips"]
    real = [c["name"] for c in clips if not c["synthetic"]]
    music = [c["name"] for c in clips if c["kind"] == "music"]
    speech = [c["name"] for c in clips if c["kind"] == "speech"]
    targets = M["targets"]

    def sel(codec, kind, setting, clips_wanted):
        return [r for r in rows if r["codec"] == codec and r["setting_kind"] == kind
                and r["setting"] == setting and r["clip"] in clips_wanted]

    # ---- achieved versus requested bitrate ---------------------------------
    achieved = {}
    for c in LOSSY:
        achieved[c] = {}
        for b in targets:
            rs = sel(c, "b", b, real)
            if not rs:
                continue
            k = [r["kbps"] for r in rs]
            achieved[c][b] = dict(
                median=med(k), lo=round(min(k), 2), hi=round(max(k), 2),
                ratio=round(st.median(k) / b, 3), n=len(k),
                per_clip={r["clip"]: r["kbps"] for r in rs})

    # ---- effective bandwidth ----------------------------------------------
    # Two readings on purpose. The probe is stationary and full band, so the
    # cutoff is unambiguous. Music is what people encode, and encoders make
    # signal dependent decisions, so the two do not have to agree.
    bandwidth = {}
    for c in LOSSY:
        bandwidth[c] = {}
        for b in targets:
            pr = sel(c, "b", b, [PROBE])
            mus = [r["bandwidth_hz"] for r in sel(c, "b", b, music)
                   if r["bandwidth_hz"] is not None]
            if not pr:
                continue
            bandwidth[c][b] = dict(
                probe=pr[0]["bandwidth_hz"],
                music_median=med(mus) if mus else None,
                music_n=len(mus), music_of=len(music))

    # ---- size for the fixed corpus ----------------------------------------
    wav_bytes = sum(c["bytes"] for c in clips if c["name"] in real)
    corpus_seconds = round(sum(c["seconds"] for c in clips if c["name"] in real), 2)
    size = {}
    for c in LOSSY:
        size[c] = {}
        for b in targets:
            rs = sel(c, "b", b, real)
            if len(rs) == len(real):
                size[c][b] = dict(bytes=sum(r["bytes"] for r in rs),
                                  vs_wav=round(sum(r["bytes"] for r in rs) / wav_bytes, 4))

    # ---- speed -------------------------------------------------------------
    speed = {}
    for c in LOSSY:
        rs = [r for r in rows if r["codec"] == c and r["setting_kind"] == "b"
              and r["clip"] in real]
        at128 = [r for r in rs if r["setting"] == 128]
        speed[c] = dict(
            encode_x=med([r["encode_x"] for r in at128]),
            decode_x=med([r["decode_x"] for r in at128]),
            encode_x_all=med([r["encode_x"] for r in rs]),
            decode_x_all=med([r["decode_x"] for r in rs]))

    # ---- lossless ----------------------------------------------------------
    lossless = {}
    for c in FLAC_LEVELS + ["ALAC"]:
        rs = [r for r in rows if r["codec"] == c and r["clip"] in real]
        if not rs:
            continue
        total = sum(r["bytes"] for r in rs)
        lossless[c] = dict(
            bytes=total, ratio=round(total / wav_bytes, 4),
            saving=round(100 * (1 - total / wav_bytes), 1),
            kbps=round(total * 8 / corpus_seconds / 1000, 1),
            bit_exact=all(r.get("bit_exact") for r in rs),
            n_exact=sum(1 for r in rs if r.get("bit_exact")), n=len(rs),
            encode_x=med([r["encode_x"] for r in rs]),
            decode_x=med([r["decode_x"] for r in rs]),
            per_clip={r["clip"]: dict(ratio=r["ratio"], exact=r.get("bit_exact"))
                      for r in rs})

    # ---- the native quality ladders people actually type -------------------
    native = {}
    for codec, kind in (("MP3", "V"), ("VORBIS", "q")):
        vals = sorted({r["setting"] for r in rows
                       if r["codec"] == codec and r["setting_kind"] == kind})
        native[codec] = dict(kind=kind, points=[])
        for v in vals:
            rs = sel(codec, kind, v, real)
            pr = sel(codec, kind, v, [PROBE])
            if not rs:
                continue
            native[codec]["points"].append(dict(
                setting=v, kbps=med([r["kbps"] for r in rs]),
                lo=round(min(r["kbps"] for r in rs), 1),
                hi=round(max(r["kbps"] for r in rs), 1),
                bandwidth=pr[0]["bandwidth_hz"] if pr else None))

    # ---- the speech clip on its own ----------------------------------------
    speech_rows = {}
    for c in LOSSY:
        speech_rows[c] = {}
        for b in targets:
            rs = sel(c, "b", b, speech)
            if rs:
                speech_rows[c][b] = dict(kbps=rs[0]["kbps"],
                                         bandwidth=rs[0]["bandwidth_hz"])

    out = dict(
        corpus=dict(clips=clips, real=real, music=music, speech=speech,
                    wav_bytes=wav_bytes, seconds=corpus_seconds,
                    wav_kbps=round(wav_bytes * 8 / corpus_seconds / 1000, 1)),
        targets=targets, achieved=achieved, bandwidth=bandwidth, size=size,
        speed=speed, lossless=lossless, native=native, speech=speech_rows,
        failures=[dict(codec=r["codec"], setting=f"{r['setting_kind']}{r['setting']}",
                       clip=r["clip"]) for r in fails],
        drop_db=M["drop_db"], ref_floor_db=M["ref_floor_db"])
    (DATA / "analysis.json").write_text(json.dumps(out, indent=1))

    print(f"corpus: {len(real)} real clips, {corpus_seconds}s, "
          f"WAV {wav_bytes/1024:.0f} kB at {out['corpus']['wav_kbps']} kbps\n")
    print("achieved kbps (median over the real clips) against the request:")
    print("  req " + "".join(f"{c:>18}" for c in LOSSY))
    for b in targets:
        cells = ""
        for c in LOSSY:
            a = achieved[c].get(b)
            cells += f"{a['median']:>11.1f} ({a['ratio']:.2f})" if a else f"{'-':>18}"
        print(f"  {b:>3} {cells}")
    print("\neffective bandwidth in kHz, stationary full band probe:")
    print("  req " + "".join(f"{c:>10}" for c in LOSSY))
    for b in targets:
        cells = ""
        for c in LOSSY:
            if b not in bandwidth[c]:
                cells += f"{'refused':>10}"
                continue
            v = bandwidth[c][b]["probe"]
            cells += f"{v/1000:>10.1f}" if v else f"{'full':>10}"
        print(f"  {b:>3} {cells}")
    print("\nlossless:")
    for k, v in lossless.items():
        print(f"  {k:<8} {v['saving']:>5.1f}% off WAV  {v['kbps']:>6.0f} kbps  "
              f"bit exact {v['n_exact']}/{v['n']}  enc {v['encode_x']:>6.0f}x  "
              f"dec {v['decode_x']:>6.0f}x")
    print("\nnative ladders:")
    for c, d in native.items():
        pts = "  ".join(f"{d['kind']}{p['setting']}={p['kbps']:.0f}" for p in d["points"])
        print(f"  {c:<8} {pts}")
    if fails:
        print(f"\n{len(fails)} encodes the encoder refused:")
        for f in fails[:12]:
            print(f"  {f['codec']} {f['setting_kind']}{f['setting']} {f['clip']}")


if __name__ == "__main__":
    main()
