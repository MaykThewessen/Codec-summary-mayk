"""Encode the corpus through every codec and measure what can honestly be measured.

Deliberately NOT measured here: perceptual quality. There is no PEAQ, no
ViSQOL and no listening panel in this environment, and a signal-difference
number dressed up as a quality score would be the single most misleading thing
this page could contain. The cited listening tests carry that half of the
argument; this file carries only properties that are true by construction:

  achieved bitrate     what the encoder actually emitted against what it was asked for
  bytes                file size on disk, container included
  encode / decode speed wall clock, single threaded, times realtime
  effective bandwidth  the frequency above which the codec discarded content,
                       found by comparing the decoded spectrum with the source
  bit exactness        for the lossless codecs, a raw PCM hash round trip

    python3 scripts/audio/measure_audio.py
"""

import hashlib
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata" / "audio"
DATA = ROOT / "data" / "audio"
WORK = TESTDATA / "work"

TARGETS = [32, 48, 64, 96, 128, 160, 192, 256, 320]

# codec key -> (ffmpeg encoder, container suffix, argument builder, ladder)
LOSSY = {
    "OPUS":   ("libopus", ".opus", lambda b: ["-b:a", f"{b}k", "-vbr", "on"], TARGETS),
    "AAC":    ("aac", ".m4a", lambda b: ["-b:a", f"{b}k"], TARGETS),
    "MP3":    ("libmp3lame", ".mp3", lambda b: ["-b:a", f"{b}k"], TARGETS),
    "VORBIS": ("libvorbis", ".ogg", lambda b: ["-b:a", f"{b}k"], TARGETS),
}

# the ladders practitioners actually use, which are quality handles, not bitrates
NATIVE = {
    "MP3": ("libmp3lame", ".mp3", "V", [0, 2, 4, 5, 7, 9],
            lambda v: ["-q:a", str(v)]),
    "VORBIS": ("libvorbis", ".ogg", "q", [0, 2, 4, 6, 8], lambda v: ["-q:a", str(v)]),
}

LOSSLESS = {
    "FLAC-0": ("flac", ".flac", ["-compression_level", "0"]),
    "FLAC-5": ("flac", ".flac", ["-compression_level", "5"]),
    "FLAC-8": ("flac", ".flac", ["-compression_level", "8"]),
    "FLAC-12": ("flac", ".flac", ["-compression_level", "12"]),
    "ALAC": ("alac", ".m4a", []),
}

FFMPEG = None


def ffmpeg():
    global FFMPEG
    if FFMPEG is None:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return FFMPEG


def run(args):
    t0 = time.perf_counter()
    p = subprocess.run([ffmpeg(), "-y", "-v", "error", "-threads", "1"] + args,
                       capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if p.returncode != 0:
        return None, dt, p.stderr.strip()[:200]
    return True, dt, ""


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    assert sw == 2, sw
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if ch == 2:
        x = x.reshape(-1, 2).mean(axis=1)
    return x, sr


def psd_db(x, sr, nfft=8192):
    """Welch power spectrum in dB. Long term average, so alignment does not matter."""
    hop = nfft // 2
    win = np.hanning(nfft)
    frames = max(1, (len(x) - nfft) // hop + 1)
    acc = np.zeros(nfft // 2 + 1)
    for i in range(frames):
        seg = x[i * hop: i * hop + nfft]
        if len(seg) < nfft:
            break
        acc += np.abs(np.fft.rfft(seg * win)) ** 2
    acc /= max(1, frames)
    freq = np.fft.rfftfreq(nfft, 1 / sr)
    return freq, 10 * np.log10(acc + 1e-20)


def smooth(v, k=9):
    ker = np.ones(k) / k
    return np.convolve(v, ker, mode="same")


DROP_DB = 20.0      # how far below the source a band must fall to count as discarded
REF_FLOOR_DB = 70.0  # ignore bands where the source itself has nothing to discard


def bandwidth_hz(ref_db, dec_db, freq):
    """Lowest frequency above which the codec has thrown the content away.

    Defined against the source, not against an absolute level, so a recording
    that simply has no 18 kHz content cannot be mistaken for a codec lowpass.
    Returns None when the source carries too little high frequency energy for
    the question to be answerable.
    """
    ref, dec = smooth(ref_db), smooth(dec_db)
    top = ref.max()
    usable = ref > (top - REF_FLOOR_DB)
    lo = np.searchsorted(freq, 2000.0)
    hi = np.searchsorted(freq, 23000.0)
    if not usable[lo:hi].any():
        return None
    # highest usable band the source actually has, and the last one the codec kept
    last_usable = lo + np.where(usable[lo:hi])[0][-1]
    kept = [i for i in range(lo, last_usable + 1)
            if usable[i] and (dec[i] - ref[i]) > -DROP_DB]
    if not kept:
        return float(freq[lo])
    edge = max(kept)
    if edge >= last_usable - 2:
        return None  # nothing discarded within the source's own band
    return float(freq[edge])


def raw_pcm_sha(path):
    p = subprocess.run([ffmpeg(), "-v", "error", "-i", str(path), "-f", "s16le",
                        "-ac", "2", "-ar", "48000", "-"], capture_output=True)
    return hashlib.sha256(p.stdout).hexdigest(), len(p.stdout)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    corpus = json.loads((DATA / "corpus.json").read_text())
    clips = corpus["clips"]

    refs = {}
    for c in clips:
        wav = TESTDATA / (c["name"] + ".wav")
        x, sr = read_wav(wav)
        f, db = psd_db(x, sr)
        refs[c["name"]] = dict(path=wav, freq=f, db=db, seconds=c["seconds"],
                               bytes=wav.stat().st_size)

    rows = []
    total = 0

    def measure(clip, codec, setting_kind, setting, enc, suffix, args):
        nonlocal total
        r = refs[clip["name"]]
        out = WORK / f"{clip['name']}__{codec}__{setting_kind}{setting}{suffix}"
        ok, enc_s, err = run(["-i", str(r["path"]), "-c:a", enc] + args + [str(out)])
        if not ok:
            rows.append(dict(clip=clip["name"], kind=clip["kind"], codec=codec,
                             setting_kind=setting_kind, setting=setting, failed=err))
            print(f"    ! {codec} {setting_kind}{setting} {clip['name']}: {err[:70]}")
            return
        dec = WORK / (out.stem + "__dec.wav")
        _, dec_s, _ = run(["-i", str(out), "-ac", "2", "-ar", "48000",
                           "-sample_fmt", "s16", str(dec)])
        x, sr = read_wav(dec)
        _, ddb = psd_db(x, sr)
        bw = bandwidth_hz(r["db"], ddb, r["freq"])
        size = out.stat().st_size
        row = dict(clip=clip["name"], kind=clip["kind"], codec=codec,
                   setting_kind=setting_kind, setting=setting,
                   seconds=r["seconds"], bytes=size,
                   kbps=round(size * 8 / r["seconds"] / 1000, 2),
                   encode_s=round(enc_s, 4), decode_s=round(dec_s, 4),
                   encode_x=round(r["seconds"] / enc_s, 1),
                   decode_x=round(r["seconds"] / dec_s, 1),
                   bandwidth_hz=None if bw is None else round(bw))
        if codec.startswith("FLAC") or codec == "ALAC":
            a, na = raw_pcm_sha(r["path"])
            b, nb = raw_pcm_sha(out)
            row["bit_exact"] = bool(a == b and na == nb)
            row["ratio"] = round(size / r["bytes"], 4)
        rows.append(row)
        dec.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        total += 1

    for clip in clips:
        print(f"  {clip['name']} ({clip['seconds']}s)", flush=True)
        for codec, (enc, suffix, argf, ladder) in LOSSY.items():
            for b in ladder:
                measure(clip, codec, "b", b, enc, suffix, argf(b))
        for codec, (enc, suffix, kind, ladder, argf) in NATIVE.items():
            for v in ladder:
                measure(clip, codec, kind, v, enc, suffix, argf(v))
        for codec, (enc, suffix, args) in LOSSLESS.items():
            measure(clip, codec, "c", 0, enc, suffix, args)

    out = dict(corpus=corpus, targets=TARGETS, rows=rows,
               ffmpeg="7.0.2 static (imageio-ffmpeg)",
               drop_db=DROP_DB, ref_floor_db=REF_FLOOR_DB)
    (DATA / "measurements.json").write_text(json.dumps(out, indent=1))
    fails = [r for r in rows if r.get("failed")]
    print(f"\n{total} encodes measured, {len(fails)} refused by the encoder")
    for r in fails:
        print(f"  {r['codec']} {r['setting_kind']}{r['setting']} {r['clip']}")


if __name__ == "__main__":
    sys.exit(main())
