"""Fetch the audio test corpus: six lossless clips under permissive licences.

Real material, not synthesis. Every source is a FLAC upload on Wikimedia
Commons under CC0, CC BY, CC BY-SA or public domain, so the corpus can be
re-fetched by anyone and the licence is checkable. Each source is trimmed to a
fixed 30 second window and normalised to 48 kHz / 16-bit / stereo WAV, which is
the reference every encoder sees.

Two synthetic probes are added on purpose: a full-band sweep and a pink-noise
plus tone bed. They are not music, they exist so the bandwidth measurement has
a signal with known energy at every frequency, which real recordings do not.
They are excluded from the size and bitrate statistics and used only for the
bandwidth ceiling check.

    python3 scripts/audio/make_corpus.py
"""

import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "testdata" / "audio"
DATA = ROOT / "data" / "audio"
FFMPEG = None

SR = 48000
CLIP_S = 30

# title on Commons, local name, start offset in seconds, licence, what it is for
SOURCES = [
    dict(name="music_synthwave",
         file="Alexi_Action_-_I_Am_Robot_(dark_synthwave).flac",
         start=45, licence="CC BY 3.0", credit="Alexi Action, I Am Robot",
         kind="music", note="dense electronic, loud, broadband"),
    dict(name="music_ambient",
         file="HOME_-_Resting_State_-_33.flac",
         start=40, licence="CC BY 3.0", credit="HOME, Resting State 33",
         kind="music", note="quiet sustained synth, low crest factor"),
    dict(name="music_orchestral",
         file="Raspberrymusic_-_Aliens_(trailer_music;_cinematic_epic_electronic_classical_music).flac",
         start=60, licence="CC BY 3.0", credit="raspberrymusic, Aliens",
         kind="music", note="cinematic orchestral, wide dynamics"),
    dict(name="piano_solo",
         file="Schubert_-_Piano_Sonata_No._13_in_A_major,_D664_-_III._Allegro_(Paul_Pitman).flac",
         start=30, licence="Public domain", credit="Schubert D664 III, Paul Pitman",
         kind="music", note="solo piano, hard tonal transients"),
    dict(name="percussion",
         file="Jhanjo.flac",
         start=0.5, licence="CC BY-SA 4.0", credit="jhanjh cymbals",
         kind="music", note="metal cymbals: broadband attacks, long HF decay"),
    dict(name="speech_en",
         file="Angela_Byron_-_voice_-en.flac",
         start=5, licence="CC BY-SA 4.0", credit="Angela Byron, spoken English",
         kind="speech", note="single voice, close mic: the podcast case"),
]

BASE = "https://upload.wikimedia.org/wikipedia/commons/"


def ffmpeg():
    global FFMPEG
    if FFMPEG is None:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return FFMPEG


UA = {"User-Agent": "codec-tradeoff-map/1.0 (audio corpus fetch; see repository)"}


def get(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or i == tries - 1:
                raise
            time.sleep(4 * (i + 1))
    raise RuntimeError("unreachable")


def commons_urls():
    """Ask the API where the files live rather than reconstructing the hash path."""
    titles = "|".join("File:" + s["file"].replace("_", " ") for s in SOURCES)
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&prop=imageinfo&iiprop=url|size|extmetadata&titles=" + urllib.parse.quote(titles))
    pages = json.loads(get(api))["query"]["pages"].values()
    by_title = {}
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        by_title[p["title"].replace("File:", "").replace(" ", "_")] = (ii.get("url"), lic)
    return by_title


def fetch(src, raw_dir, url):
    dest = raw_dir / (src["name"] + ".flac")
    if dest.exists() and dest.stat().st_size > 100000:
        return dest
    print(f"  fetching {src['name']} ...", flush=True)
    dest.write_bytes(get(url))
    time.sleep(1.0)
    return dest


def duration(path):
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def to_wav(src_path, out_path, start, seconds):
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-ss", str(start), "-i", str(src_path),
                    "-t", str(seconds), "-map", "0:a:0", "-ac", "2", "-ar", str(SR),
                    "-sample_fmt", "s16", "-af", "afade=t=in:d=0.05,afade=t=out:st=%.2f:d=0.05"
                    % (seconds - 0.05), str(out_path)], check=True)


def write_wav(path, x):
    """x: float array (n, 2) in -1..1."""
    import wave
    d = np.clip(x, -1, 1)
    pcm = (d * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)


def synth_probes():
    """Two signals with known energy everywhere, for the bandwidth ceiling."""
    n = CLIP_S * SR
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)

    # 1. logarithmic sweep 20 Hz to 22 kHz, both channels, constant amplitude
    f0, f1 = 20.0, 22000.0
    k = np.log(f1 / f0)
    phase = 2 * np.pi * f0 * CLIP_S / k * (np.exp(k * t / CLIP_S) - 1)
    sweep = 0.5 * np.sin(phase)
    sweep = np.stack([sweep, sweep], axis=1)

    # 2. pink noise plus a tone comb, so every band carries steady energy
    white = rng.standard_normal((n, 2))
    spec = np.fft.rfft(white, axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    shape = np.ones_like(f)
    shape[1:] = 1 / np.sqrt(f[1:])
    pink = np.fft.irfft(spec * shape[:, None], n=n, axis=0)
    pink /= np.max(np.abs(pink)) / 0.4
    comb = sum(0.03 * np.sin(2 * np.pi * fr * t) for fr in
               (500, 1000, 2000, 4000, 8000, 12000, 15000, 17000, 19000, 21000))
    bed = pink + comb[:, None]
    bed /= max(1.0, np.max(np.abs(bed)) / 0.9)

    return [("probe_sweep", sweep, "log sweep 20 Hz to 22 kHz"),
            ("probe_noise", bed, "pink noise plus a tone comb to 21 kHz")]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    raw = OUT / "raw"
    raw.mkdir(exist_ok=True)

    urls = commons_urls()
    manifest = []
    for src in SOURCES:
        url, lic_api = urls.get(src["file"], (None, ""))
        if not url:
            raise SystemExit(f"Commons has no url for {src['file']}")
        got = fetch(src, raw, url)
        dur = duration(got) or CLIP_S + src["start"] + 1
        # Sources are not all long enough for a 30 s window. Take what is there
        # rather than loop it, and normalise every measurement per second.
        start = min(src["start"], max(0.0, dur - CLIP_S - 0.2))
        secs = round(min(CLIP_S, dur - start - 0.2), 2)
        wav = OUT / (src["name"] + ".wav")
        to_wav(got, wav, round(start, 2), secs)
        manifest.append(dict(name=src["name"], kind=src["kind"], synthetic=False,
                             licence=lic_api or src["licence"], credit=src["credit"],
                             note=src["note"], source_file=src["file"],
                             source_seconds=round(dur, 1), start=round(start, 2),
                             seconds=secs, bytes=wav.stat().st_size))
        print(f"  {src['name']:<18} {wav.stat().st_size/1024:8.0f} kB  "
              f"{secs:5.1f}s from {start:5.1f}s of {dur:6.1f}s  {lic_api}")

    for name, x, note in synth_probes():
        wav = OUT / (name + ".wav")
        write_wav(wav, x)
        manifest.append(dict(name=name, kind="probe", synthetic=True,
                             licence="generated here", credit="synthesised",
                             note=note, source_file="", seconds=float(CLIP_S),
                             bytes=wav.stat().st_size))
        print(f"  {name:<18} {wav.stat().st_size/1024:8.0f} kB  synthetic probe")

    (DATA / "corpus.json").write_text(json.dumps(
        dict(sample_rate=SR, seconds=CLIP_S, channels=2, bit_depth=16,
             clips=manifest), indent=1))
    total = sum(c["seconds"] for c in manifest)
    print(f"\n{len(manifest)} clips, {total:.1f}s total, {SR} Hz stereo 16-bit")


if __name__ == "__main__":
    main()
