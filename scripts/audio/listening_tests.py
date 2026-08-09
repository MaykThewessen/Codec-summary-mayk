"""The published listening-test record, transcribed with its citations.

Nothing in this file was measured here. Every number is copied from a public
results page, and every entry carries the test, the year, the encoder version,
the sample and listener counts, and the URL. Confidence intervals are only
present where the source publishes something they can be derived from:

  2011 tests   the results page prints the full blocked-ANOVA table, so the
               half width is 1.96 * sqrt(MSE / n) on the published MSE and n
  2014 test    the results page draws the intervals as an inline SVG with a
               labelled axis, so they are read back off the chart geometry
  2005 to 2008 the intervals exist only as pixels in a bitmap plot. Means are
               transcribed, intervals are recorded as absent rather than guessed

    python3 scripts/audio/listening_tests.py
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "audio"

# family drives colour on the page. Anchors are deliberately not a family.
OPUS, AAC, HEAAC, VORBIS, MP3, WMA, ANCHOR = (
    "opus", "aac", "he-aac", "vorbis", "mp3", "wma", "anchor")


def anova_ci(mse, n):
    """95% half width for a mean from a published blocked-ANOVA table."""
    return round(1.96 * math.sqrt(mse / n), 3)


# --------------------------------------------------------------------------
# 2014, the most recent public multiformat test with published intervals
# --------------------------------------------------------------------------
# Read back from the results page's inline SVG: the y axis is labelled 3.2 at
# y=364.5 and 0.2 rating units every 39 px, and each interval is drawn as a
# vertical path whose extent is given below in pixels.
K2014_AXIS = dict(y_at=364.5, value_at=3.2, px_per_02=39.0)
K2014_BARS = {  # codec: (top px, bottom px)
    "Opus": (68.0477, 96.4815),
    "AAC": (114.2715, 150.2031),
    "Vorbis": (143.4576, 183.2681),
    "MP3": (145.6422, 180.1227),
}
# the five tracks the test labels "Voice", transcribed from the per-track table
K2014_VOICE = {
    "4-Sound-English-male": dict(Opus=4.97, AAC=4.82, Vorbis=3.77, MP3=4.47),
    "12-German-male-speech": dict(Opus=4.82, AAC=4.80, Vorbis=3.59, MP3=4.09),
    "15-Good-evening": dict(Opus=4.31, AAC=4.51, Vorbis=4.24, MP3=4.19),
    "24-Greensleeves-Korean-male-speech": dict(Opus=5.00, AAC=4.32, Vorbis=4.23, MP3=4.40),
    "25-This-is-the-end": dict(Opus=4.89, AAC=4.41, Vorbis=4.20, MP3=4.56),
}


def k2014_ci():
    per_unit = K2014_AXIS["px_per_02"] / 0.2
    return {k: round((b - t) / 2 / per_unit, 3) for k, (t, b) in K2014_BARS.items()}


def build():
    ci14 = k2014_ci()
    ci11 = anova_ci(0.53, 531)   # 64 kbps 2011: MSE 0.53, 531 results
    ci11a = anova_ci(0.37, 280)  # 96 kbps AAC 2011: MSE 0.37, 280 results

    tests = []

    tests.append(dict(
        id="ha2005_128",
        title="Multiformat, 128 kbps",
        organiser="Sebastian Mares, HydrogenAudio",
        year=2006, when="Dec 2005 to Jan 2006",
        samples=18, listeners=None, results=None,
        target="128 kbps",
        url="https://listening-tests.hydrogenaudio.org/sebastian/mf-128-1/results.htm",
        verdict="Five way tie. Nothing separated the contenders at 128 kbps.",
        group="format",
        entries=[
            dict(label="Vorbis aoTuV 4.51b", family=VORBIS, mean=4.79),
            dict(label="AAC, iTunes 6.0.1.3", family=AAC, mean=4.74),
            dict(label="WMA Pro 9.1", family=WMA, mean=4.70),
            dict(label="AAC, Nero 3.1.0.2", family=AAC, mean=4.68,
                 note="excluded from the statistics after an encoder problem"),
            dict(label="MP3, LAME 3.97b2", family=MP3, mean=4.60),
            dict(label="Shine 0.1.4, low anchor", family=ANCHOR, mean=2.35),
        ]))

    tests.append(dict(
        id="ha2007_64",
        title="Multiformat, 64 kbps",
        organiser="Sebastian Mares, HydrogenAudio",
        year=2007, when="Jul 2007",
        samples=18, listeners=None, results=None,
        target="64 kbps",
        url="https://listening-tests.hydrogenaudio.org/sebastian/mf-64-1/results.htm",
        verdict="HE-AAC ahead of WMA Pro, which was tied with Vorbis. All far "
                "below plain AAC-LC given 96 kbps.",
        group="format",
        entries=[
            dict(label="AAC-LC 96 kbps, high anchor", family=ANCHOR, mean=4.59),
            dict(label="HE-AAC, Nero (Jul 2007)", family=HEAAC, mean=3.74),
            dict(label="WMA Pro 10", family=WMA, mean=3.52),
            dict(label="Vorbis aoTuV 5b", family=VORBIS, mean=3.32),
            dict(label="AAC-LC 48 kbps, low anchor", family=ANCHOR, mean=1.55),
        ]))

    tests.append(dict(
        id="ha2011_64",
        title="Multiformat, 64 kbps",
        organiser="IgorC, HydrogenAudio",
        year=2011, when="Mar to Apr 2011",
        samples=30, listeners=None, results=531,
        target="64 kbps",
        url="https://listening-tests.hydrogenaudio.org/igorc/results.html",
        verdict="Opus beat both HE-AAC encoders and Vorbis, every comparison at "
                "p<0.001 except Nero HE-AAC against Vorbis.",
        group="format",
        entries=[
            dict(label="Opus (CELT 0.11.2)", family=OPUS, mean=3.999, ci=ci11),
            dict(label="HE-AAC, Apple QuickTime 7.6.9", family=HEAAC, mean=3.817, ci=ci11),
            dict(label="HE-AAC, Nero 1.5.4", family=HEAAC, mean=3.547, ci=ci11),
            dict(label="Vorbis aoTuV 6.02b", family=VORBIS, mean=3.513, ci=ci11),
            dict(label="AAC-LC 48 kbps, low anchor", family=ANCHOR, mean=1.656, ci=ci11),
        ]))

    tests.append(dict(
        id="k2014_96",
        title="Multiformat, 96 kbps (MP3 given 128)",
        organiser="Kamedo2, public test",
        year=2014, when="Jul 2014",
        samples=40, listeners=38, results=339,
        target="96 kbps, MP3 at LAME -V5",
        url="https://listening-test.coresv.net/results.htm",
        verdict="Opus clear first, Apple AAC second, Vorbis and MP3 tied third "
                "even though the MP3 spent 29% more bitrate.",
        group="format",
        entries=[
            dict(label="Opus 1.1, --bitrate 96", family=OPUS, mean=4.65,
                 ci=ci14["Opus"], kbps=107),
            dict(label="AAC, qaac 2.41 --cvbr 96", family=AAC, mean=4.40,
                 ci=ci14["AAC"], kbps=104),
            dict(label="Vorbis aoTuV b6.03 -q2.2", family=VORBIS, mean=4.24,
                 ci=ci14["Vorbis"], kbps=106),
            dict(label="MP3, LAME 3.99.5 -V5", family=MP3, mean=4.24,
                 ci=ci14["MP3"], kbps=136),
            dict(label="FAAC 96 kbps, anchor", family=ANCHOR, mean=2.65, kbps=98),
            dict(label="FAAC -q30, low anchor", family=ANCHOR, mean=1.19, kbps=52),
        ]))

    tests.append(dict(
        id="ha2008_mp3",
        title="MP3 encoders, 128 kbps",
        organiser="Sebastian Mares, HydrogenAudio",
        year=2008, when="Oct 2008",
        samples=14, listeners=None, results=None,
        target="128 kbps, MP3 only",
        url="https://listening-tests.hydrogenaudio.org/sebastian/mp3-128-1/results.htm",
        verdict="Every modern encoder statistically tied. The 1994 encoder, at "
                "the same bitrate and in the same format, scored 1.56.",
        group="encoder",
        entries=[
            dict(label="Helix", family=MP3, mean=4.59),
            dict(label="LAME 3.98.2", family=MP3, mean=4.51),
            dict(label="Fraunhofer", family=MP3, mean=4.44),
            dict(label="LAME 3.97", family=MP3, mean=4.28),
            dict(label="iTunes", family=MP3, mean=4.26),
            dict(label="l3enc (1994), low anchor", family=ANCHOR, mean=1.56),
        ]))

    tests.append(dict(
        id="ha2011_aac96",
        title="AAC encoders, 96 kbps",
        organiser="IgorC, HydrogenAudio",
        year=2011, when="Jul 2011",
        samples=20, listeners=None, results=280,
        target="96 kbps, AAC only",
        url="https://listening-tests.hydrogenaudio.org/igorc/aac-96-a/results.html",
        verdict="Same format, same bitrate, 0.69 of a grade between the best and "
                "the worst encoder.",
        group="encoder",
        entries=[
            dict(label="Apple QuickTime CVBR", family=AAC, mean=4.391, ci=ci11a),
            dict(label="Apple QuickTime TVBR", family=AAC, mean=4.342, ci=ci11a),
            dict(label="Fraunhofer", family=AAC, mean=4.253, ci=ci11a),
            dict(label="Coding Technologies", family=AAC, mean=4.039, ci=ci11a),
            dict(label="Nero", family=AAC, mean=3.698, ci=ci11a),
            dict(label="low anchor", family=ANCHOR, mean=1.545, ci=ci11a),
        ]))

    # the speech subset of the 2014 test, averaged from its per-track table
    voice = {}
    for codec in ("Opus", "AAC", "Vorbis", "MP3"):
        vals = [t[codec] for t in K2014_VOICE.values()]
        voice[codec] = round(sum(vals) / len(vals), 3)

    out = dict(
        tests=tests,
        voice_2014=dict(n_tracks=len(K2014_VOICE), means=voice, per_track=K2014_VOICE,
                        source="k2014_96"),
        sources=[
            dict(key="ha2005_128", cite="Public multiformat listening test at 128 kbps, "
                 "Sebastian Mares, HydrogenAudio, December 2005 to January 2006, 18 samples",
                 url=tests[0]["url"]),
            dict(key="ha2007_64", cite="Public multiformat listening test at 64 kbps, "
                 "Sebastian Mares, HydrogenAudio, July 2007, 18 samples",
                 url=tests[1]["url"]),
            dict(key="ha2011_64", cite="Public multiformat listening test at 64 kbps, "
                 "IgorC, HydrogenAudio, March to April 2011, 30 samples, 531 results",
                 url=tests[2]["url"]),
            dict(key="k2014_96", cite="Public multiformat listening test, Kamedo2, "
                 "July 2014, 40 tracks, 38 listeners, 339 valid results",
                 url=tests[3]["url"]),
            dict(key="ha2008_mp3", cite="Public MP3 listening test at 128 kbps, "
                 "Sebastian Mares, HydrogenAudio, October 2008, 14 samples",
                 url=tests[4]["url"]),
            dict(key="ha2011_aac96", cite="Public AAC listening test at 96 kbps, "
                 "IgorC, HydrogenAudio, July 2011, 20 samples, 280 results",
                 url=tests[5]["url"]),
            dict(key="rfc6716", cite="RFC 6716, Definition of the Opus Audio Codec, "
                 "IETF, September 2012: the SILK, hybrid and CELT modes and their "
                 "bitrate ranges", url="https://datatracker.ietf.org/doc/html/rfc6716"),
            dict(key="opus_comparison", cite="Opus codec comparison page, listing the "
                 "HydrogenAudio, Google and Nokia tests",
                 url="https://opus-codec.org/comparison/"),
            dict(key="ha_lame", cite="HydrogenAudio Knowledgebase, LAME recommended "
                 "encoder settings", url="https://wiki.hydrogenaudio.org/index.php?title=LAME"),
            dict(key="spotify", cite="Spotify support, Audio quality: web player AAC "
                 "128 and 256 kbit/s, app tiers to 320 kbit/s, Premium lossless FLAC",
                 url="https://support.spotify.com/us/article/audio-quality/"),
            dict(key="dabplus", cite="ETSI TS 102 563, DAB+ audio coding: HE-AAC v2 "
                 "profile level 2", url="https://www.etsi.org/deliver/etsi_ts/102500_102599/"
                 "102563/02.01.01_60/ts_102563v020101p.pdf"),
        ])
    (DATA / "listening_tests.json").write_text(json.dumps(out, indent=1))

    print(f"{len(tests)} tests, {sum(len(t['entries']) for t in tests)} entries")
    print(f"derived 95% CI: 2011 tests +/-{ci11} and +/-{ci11a}, 2014 " +
          ", ".join(f"{k} +/-{v}" for k, v in ci14.items()))
    print("2014 voice subset means: " + ", ".join(f"{k} {v}" for k, v in voice.items()))


if __name__ == "__main__":
    build()
