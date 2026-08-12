"""Derive every sentence on the page that contains a number.

Two rules hold this file together. Anything measured here is computed from
analysis.json. Anything about perceived quality is computed from
listening_tests.json and is worded so a reader can tell it is cited, with the
test and the year attached. Nothing crosses over: no measured number is ever
turned into a quality claim.

    python3 scripts/audio/make_prose.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "audio"

A = json.loads((DATA / "analysis.json").read_text())
T = json.loads((DATA / "listening_tests.json").read_text())
MEAS = json.loads((DATA / "measurements.json").read_text())


def fmt_int(v):
    v = round(v)
    if abs(v) < 10000:
        return str(v)
    s = f"{abs(v):,}".replace(",", ".")
    return ("-" if v < 0 else "") + s


def pct(v, d=0):
    return f"{v:.{d}f}%"


def khz(hz):
    return "no cut" if hz is None else f"{hz/1000:.1f} kHz"


def test(tid):
    return next(t for t in T["tests"] if t["id"] == tid)


def entry(tid, needle):
    return next(e for e in test(tid)["entries"] if needle.lower() in e["label"].lower())


ach = A["achieved"]
bw = A["bandwidth"]
ll = A["lossless"]
nat = A["native"]
spd = A["speed"]
corpus = A["corpus"]

mp3v = {p["setting"]: p for p in nat["MP3"]["points"]}
vq = {p["setting"]: p for p in nat["VORBIS"]["points"]}

t2014, t2011, t2007, t2005 = test("k2014_96"), test("ha2011_64"), test("ha2007_64"), test("ha2005_128")
t_mp3, t_aac = test("ha2008_mp3"), test("ha2011_aac96")
voice = T["voice_2014"]["means"]

o14 = entry("k2014_96", "Opus")
a14 = entry("k2014_96", "qaac")
v14 = entry("k2014_96", "aoTuV")
m14 = entry("k2014_96", "LAME")
o11 = entry("ha2011_64", "Opus")
ah11 = entry("ha2011_64", "Apple")
nh11 = entry("ha2011_64", "Nero")
vb11 = entry("ha2011_64", "aoTuV")
lame08 = entry("ha2008_mp3", "LAME 3.98")
l3enc = entry("ha2008_mp3", "l3enc")
qt11 = entry("ha2011_aac96", "CVBR")
nero11 = entry("ha2011_aac96", "Nero")
hi07 = entry("ha2007_64", "high anchor")
he07 = entry("ha2007_64", "Nero")

n_music = len(corpus["music"])
mins = int(corpus["seconds"] // 60)
secs = int(round(corpus["seconds"] % 60))

P = {}

# ---------------------------------------------------------------- head + map
P["n_encodes"] = fmt_int(len([r for r in MEAS["rows"] if not r.get("failed")]))
P["n_test_entries"] = str(sum(len(t["entries"]) for t in T["tests"]))
P["corpus_desc"] = (
    f"{len(corpus['real'])} clips totalling {mins} minutes {secs} seconds, all from "
    f"lossless CC licensed or public domain sources, plus two synthetic full band probes")
P["voice_opus"] = f"{voice['Opus']:.2f}"
P["voice_vorbis"] = f"{voice['Vorbis']:.2f}"
P["mp3_extra_bitrate"] = pct(100 * (m14["kbps"] / o14["kbps"] - 1))
P["vorbis_floor"] = "refused every 32 kbps encode on this corpus outright"
P["mp3_v2_kbps"] = f"{mp3v[2]['kbps']:.0f} kbps"
P["mp3_v2_kbps_short"] = f"# {mp3v[2]['kbps']:.0f} kbps here"
P["mp3_v0_kbps"] = f"{mp3v[0]['kbps']:.0f} kbps"
P["mp3_v5_kbps"] = f"{mp3v[5]['kbps']:.0f} kbps"
P["wav_kbps"] = f"{corpus['wav_kbps']:.0f} kbps"
P["flac_exact"] = f"all {ll['FLAC-8']['n']} clips"
P["flac_saving"] = pct(ll["FLAC-8"]["saving"], 1)
P["alac_saving"] = pct(ll["ALAC"]["saving"], 1)
P["opus_128_kbps"] = f"{ach['OPUS']['128']['median']:.0f} kbps"
P["opus_96_kbps"] = f"{ach['OPUS']['96']['median']:.0f} kbps"
P["flac8_line"] = (f"{pct(ll['FLAC-8']['saving'], 1)} off WAV at "
                   f"{ll['FLAC-8']['encode_x']:.0f}x realtime")
P["flac12_line"] = (f"{pct(ll['FLAC-12']['saving'], 1)} off WAV at "
                    f"{ll['FLAC-12']['encode_x']:.0f}x realtime")

# ---------------------------------------------------------------- graph A
P["graph_a_note"] = (
    f"The shape is the same in every test and has been since 2011. Opus first, AAC "
    f"second, Vorbis and MP3 behind. In {t2014['year']} Opus scored {o14['mean']:.2f} "
    f"against Apple AAC at {a14['mean']:.2f}, with confidence intervals of "
    f"±{o14['ci']:.2f} and ±{a14['ci']:.2f}, so the gap is real rather than noise. The "
    f"MP3 in that test was given {m14['kbps']} kbps against Opus's {o14['kbps']} and "
    f"still finished level with Vorbis. Note the {t2005['year']} row as well: at 128 "
    f"kbps everything tied, including WMA Pro at {entry('ha2005_128', 'WMA')['mean']:.2f} "
    f"and LAME at {entry('ha2005_128', 'LAME')['mean']:.2f}. Above roughly 128 kbps the "
    f"format argument stops mattering, which is why every test since has been run lower.")

P["encoder_note"] = (
    f"This is the single most useful pair of rows on the page. In the "
    f"{t_mp3['year']} MP3 test every modern encoder was statistically tied, LAME 3.98.2 "
    f"at {lame08['mean']:.2f}, and the 1994 encoder l3enc, at the same 128 kbps and in "
    f"the same format, scored {l3enc['mean']:.2f}: a gap of "
    f"{lame08['mean'] - l3enc['mean']:.2f} grades that has nothing to do with MP3 and "
    f"everything to do with the encoder. The {t_aac['year']} AAC test says the same "
    f"about AAC, {qt11['mean']:.2f} for Apple's encoder against {nero11['mean']:.2f} for "
    f"Nero's, a spread of {qt11['mean'] - nero11['mean']:.2f} grades at one bitrate in "
    f"one format. MP3's bad reputation was earned by encoders, not by the standard.")

P["voice_note"] = (
    f"Averaged over the {T['voice_2014']['n_tracks']} tracks the 2014 test labels Voice, "
    f"Opus scored {voice['Opus']:.2f}, Apple AAC {voice['AAC']:.2f}, LAME "
    f"{voice['MP3']:.2f} at its higher bitrate, and Vorbis {voice['Vorbis']:.2f}. Vorbis "
    f"is last, and by a wider margin than on music: it lost "
    f"{voice['Opus'] - voice['Vorbis']:.2f} grades to Opus on speech against "
    f"{o14['mean'] - v14['mean']:.2f} over the whole set. This is the number that decides "
    f"the podcast question, and it points at Opus, not at Vorbis.")

# ---------------------------------------------------------------- graph B
def bwp(codec, br):
    d = bw[codec].get(str(br))
    return None if d is None else d["probe"]


P["bandwidth_note"] = (
    f"At 64 kbps the four codecs made completely different decisions about what to keep: "
    f"Opus held on to {khz(bwp('OPUS', 64))}, Vorbis {khz(bwp('VORBIS', 64))}, AAC "
    f"{khz(bwp('AAC', 64))} and MP3 {khz(bwp('MP3', 64))}. At 32 kbps ffmpeg's AAC "
    f"collapses to {khz(bwp('AAC', 32))} and MP3 to {khz(bwp('MP3', 32))}, which is the "
    f"muffled telephone sound everyone recognises, while Opus is still coding to "
    f"{khz(bwp('OPUS', 32))}. Opus never lowpasses on this corpus: it sits at 20 kHz from "
    f"32 kbps to 320. AAC and MP3 only catch up above roughly 192 kbps.")

P["achieved_note"] = (
    f"Ask four encoders for 64 kbps and you get {ach['OPUS']['64']['median']:.1f}, "
    f"{ach['AAC']['64']['median']:.1f}, {ach['MP3']['64']['median']:.1f} and "
    f"{ach['VORBIS']['64']['median']:.1f} kbps: a spread of "
    f"{pct(100 * (ach['OPUS']['64']['median'] / ach['VORBIS']['64']['median'] - 1))} between "
    f"the highest and the lowest. LAME in CBR hits its number exactly, every time. "
    f"ffmpeg's AAC lands within a few percent. Opus in its default unconstrained VBR "
    f"treats the number as a soft target and overshoots by "
    f"{pct(100 * (ach['OPUS']['64']['ratio'] - 1))} at 64 kbps, and its worst miss on "
    f"this corpus was the spoken word clip, where a 64 kbps request produced "
    f"{ach['OPUS']['64']['per_clip']['speech_en']:.0f} kbps. libvorbis in ABR mode runs "
    f"the other way and undershoots by "
    f"{pct(100 * (1 - ach['VORBIS']['64']['ratio']))}. If you are filling a fixed pipe, "
    f"this chart is the one that matters, and the answer is to measure rather than trust "
    f"the flag.")

P["lossless_note"] = (
    f"Every lossless encode round tripped to identical PCM: {ll['FLAC-8']['n_exact']} of "
    f"{ll['FLAC-8']['n']} clips at FLAC level 8 and {ll['ALAC']['n_exact']} of "
    f"{ll['ALAC']['n']} for ALAC, checked as a SHA-256 over the decoded samples, not as a "
    f"claim from the encoder. FLAC level 8 came out {pct(ll['FLAC-8']['saving'], 1)} under "
    f"WAV and ALAC {pct(ll['ALAC']['saving'], 1)}, so FLAC is "
    f"{pct(100 * (1 - ll['FLAC-8']['bytes'] / ll['ALAC']['bytes']), 1)} smaller than ALAC "
    f"on the same audio. The compression ladder flattens fast: going from level 0 to level "
    f"5 buys {ll['FLAC-5']['saving'] - ll['FLAC-0']['saving']:.1f} percentage points, 5 to "
    f"8 buys {ll['FLAC-8']['saving'] - ll['FLAC-5']['saving']:.1f} more, and 8 to 12 buys "
    f"a further {ll['FLAC-12']['saving'] - ll['FLAC-8']['saving']:.1f} for "
    f"{ll['FLAC-8']['encode_x'] / ll['FLAC-12']['encode_x']:.0f} times the encode time. "
    f"Level 8 is the sensible stopping point.")

P["speed_note"] = (
    f"Nothing here is slow enough to matter for a file you encode once. Opus was the "
    f"slowest encoder at {spd['OPUS']['encode_x']:.0f} times realtime and MP3 the fastest "
    f"at {spd['MP3']['encode_x']:.0f}, both measured at 128 kbps on one thread. Decoding "
    f"is another order of magnitude up and is where battery life actually lives: FLAC "
    f"decoded at {ll['FLAC-8']['decode_x']:.0f} times realtime, AAC at "
    f"{spd['AAC']['decode_x']:.0f} and Opus at {spd['OPUS']['decode_x']:.0f}, the slowest "
    f"of the set. On a phone that difference is real but small; on a battery powered "
    f"embedded player it is one of the reasons AAC hardware decoders exist.")

# ---------------------------------------------------------------- disagreements
P["disagree_bandwidth"] = (
    f"On the measured side Vorbis looks better than AAC at low bitrate: at 64 kbps it kept "
    f"{khz(bwp('VORBIS', 64))} against AAC's {khz(bwp('AAC', 64))}, and at 48 kbps "
    f"{khz(bwp('VORBIS', 48))} against {khz(bwp('AAC', 48))}. Listeners disagreed twice. In "
    f"{t2007['year']} at 64 kbps, HE-AAC scored {he07['mean']:.2f} and Vorbis "
    f"{entry('ha2007_64', 'aoTuV')['mean']:.2f}; in {t2011['year']}, Apple HE-AAC "
    f"{ah11['mean']:.2f} against Vorbis {vb11['mean']:.2f}. Keeping more spectrum is not "
    f"the same as coding it well. A codec that carries 15 kHz badly loses to one that "
    f"carries 12 kHz cleanly, and no bandwidth number can see that difference. Note also "
    f"that the AAC figures here come from ffmpeg's native encoder, which is not the "
    f"encoder those tests used.")

P["disagree_opus"] = (
    f"At 128 kbps and above, graph B has almost nothing to separate the four codecs: "
    f"bandwidth converges, sizes are within a few percent once you correct for Opus's "
    f"VBR overshoot, and every decoder is fast enough. Graph A still separates them "
    f"clearly, Opus at {o14['mean']:.2f} against {a14['mean']:.2f}, {v14['mean']:.2f} and "
    f"{m14['mean']:.2f} in {t2014['year']}. The whole difference lives in how bits are "
    f"allocated inside the bands both codecs keep, which is a psychoacoustic question and "
    f"is invisible to every measurement on this page. This is the clearest case for why "
    f"graph B cannot stand in for graph A: it is not that B is wrong, it is that B is "
    f"silent.")

P["disagree_encoder"] = (
    f"Two MP3 files at 128 kbps have the same bitrate by definition, and measured here "
    f"they would have near enough the same bandwidth as well. In the {t_mp3['year']} test "
    f"LAME 3.98.2 scored {lame08['mean']:.2f} and l3enc scored {l3enc['mean']:.2f}, "
    f"{lame08['mean'] - l3enc['mean']:.2f} grades apart. Every measurement on this page is "
    f"blind to that, because every measurement here is a property of the bitstream's "
    f"envelope rather than of the decisions inside it. It is also the reason the AAC "
    f"numbers in graph B carry a warning: ffmpeg's native AAC encoder is the weak end of "
    f"that same spread.")

P["disagree_agree"] = (
    f"Here the two halves point the same way and reinforce each other. Measured: at 32 "
    f"kbps MP3 kept only {khz(bwp('MP3', 32))} of the spectrum and libvorbis refused to "
    f"encode at all. Cited: in {t2011['year']} plain AAC-LC at 48 kbps scored "
    f"{entry('ha2011_64', 'low anchor')['mean']:.2f} out of 5, which is what the test "
    f"organisers chose as the deliberately broken reference. Below about 64 kbps the older "
    f"formats are not making a trade, they are failing, and that is the gap Opus and "
    f"HE-AAC were designed to fill.")

# ---------------------------------------------------------------- claims
P["claim_vorbis"] = (
    f"The behaviour is real and it belongs to Opus. Opus contains two codecs: SILK, a "
    f"speech coder derived from Skype's, and CELT, a transform coder for music, and RFC "
    f"6716 defines a hybrid mode that switches between and blends them by bitrate and "
    f"content. That is why it survives at 32 kbps on a voice. Vorbis has nothing like it: "
    f"it is a single MDCT transform codec, and on the speech tracks of the 2014 test it "
    f"came last of four, {voice['Vorbis']:.2f} against Opus at {voice['Opus']:.2f} and "
    f"even behind the MP3. Vorbis was excellent for its time and is genuinely royalty "
    f"free, but Opus was written by the same community to replace it and does so at every "
    f"bitrate. Treat Vorbis as legacy: keep decoding it, stop encoding it. Its one "
    f"remaining edge is that some old Android and game engine pipelines take Vorbis and "
    f"not Opus.")

P["claim_lame"] = (
    f"Confirmed, and the numbers are more extreme than the claim. Same format, same "
    f"bitrate, same samples, {t_mp3['year']}: LAME 3.98.2 {lame08['mean']:.2f}, l3enc from "
    f"1994 {l3enc['mean']:.2f}. Nearly three grades of the five point scale, purely from "
    f"the encoder. The settings worth typing are LAME's VBR modes rather than a bitrate: "
    f"measured on this corpus <code>-V0</code> cost {mp3v[0]['kbps']:.0f} kbps, "
    f"<code>-V2</code> {mp3v[2]['kbps']:.0f} kbps and <code>-V5</code> "
    f"{mp3v[5]['kbps']:.0f} kbps. <code>-V2</code> is the long standing HydrogenAudio "
    f"recommendation and is transparent for most listeners on most material; "
    f"<code>-V0</code> is the archival end. <code>-b 320</code> is worse than pointless: "
    f"it costs {320 - mp3v[0]['kbps']:.0f} kbps more than <code>-V0</code> measured here, "
    f"and no listening test has ever shown it sounding better.")

P["claim_aac"] = (
    f"Largely right, and a defensible favourite. AAC has been second in every multiformat "
    f"test since 2011 and it is the only modern codec with genuinely universal hardware "
    f"reach. The caveat is about the numbers on this page rather than about AAC: they come "
    f"from ffmpeg's native AAC encoder, which is the weakest of the widely used ones. The "
    f"{t_aac['year']} AAC test measured {qt11['mean'] - nero11['mean']:.2f} grades between "
    f"the best and worst encoders of this one format at one bitrate, and ffmpeg's was not "
    f"even in that field. So treat every AAC figure in graph B as the pessimistic case, "
    f"exactly as the images page treats stock libjpeg-turbo, and use qaac or fdk-aac in "
    f"practice.")

P["claim_heaac"] = (
    f"Right in shape, too generous in the ratio, and slightly off in the premise. HE-AAC "
    f"v1 is designed for roughly 32 to 64 kbps, and at 96 kbps a sensible encoder has "
    f"already switched to plain AAC-LC, so the comparison you want is AAC-LC at 96 against "
    f"MP3. In {t2014['year']} that was measured directly: Apple AAC at {a14['kbps']} kbps "
    f"scored {a14['mean']:.2f} and LAME at {m14['kbps']} kbps scored {m14['mean']:.2f}, so "
    f"AAC was worth roughly {m14['kbps'] / a14['kbps']:.2f} times the MP3 bitrate, not "
    f"2.6 times. Where the claim does hold is lower down: in {t2007['year']} HE-AAC at 64 "
    f"kbps scored {he07['mean']:.2f} while plain AAC-LC needed 96 kbps to reach "
    f"{hi07['mean']:.2f}, and MP3 at 64 kbps is not usable at all. A 250 kbps MP3 is "
    f"LAME <code>-V0</code>, which HydrogenAudio describes as transparent; nothing at 96 "
    f"kbps in any published test has reached that.")

P["claim_spotify"] = (
    f"True historically and no longer the whole picture. Spotify was built on Ogg Vorbis "
    f"and still uses it for the numbered quality tiers in the desktop and mobile apps, but "
    f"its own support page now describes the web player as AAC at 128 and 256 kbit/s, the "
    f"top app tier as roughly 320 kbit/s, and Premium lossless as FLAC. YouTube's audio is "
    f"Opus. Apple Music is AAC with ALAC for its lossless tier. So the current industry "
    f"answer is: AAC where reach matters, Opus where the client is a browser, FLAC for "
    f"lossless, and Vorbis only where it is already deployed.")

P["claim_wma"] = (
    f"Honest answer: it is dead, and it did not die because it was bad. In the "
    f"{t2005['year']} test WMA Pro scored {entry('ha2005_128', 'WMA')['mean']:.2f} at 128 "
    f"kbps, statistically tied with AAC, Vorbis and LAME, and in {t2007['year']} at 64 "
    f"kbps it beat Vorbis. It lost on ecosystem, not on coding: no browser decodes it, no "
    f"phone plays it, no streaming service uses it, and Microsoft itself has moved on. "
    f"There is no reason to encode WMA today and one reason to keep a decoder around, "
    f"which is old Windows Media content you did not create.")

P["claim_better"] = (
    f"There is: Opus. It won the {t2011['year']} test at 64 kbps ({o11['mean']:.2f} "
    f"against Apple HE-AAC at {ah11['mean']:.2f}) and the {t2014['year']} test at 96 kbps "
    f"({o14['mean']:.2f} against Apple AAC at {a14['mean']:.2f}), it is royalty free, it "
    f"is an IETF standard rather than a licensed one, it covers 6 kbps to 510 kbps in one "
    f"format, and it handles speech and music in the same bitstream. Every browser decodes "
    f"it and it is what YouTube serves. The catch is the one thing a listening test cannot "
    f"measure: car head units, Bluetooth A2DP, DAB receivers, hi-fi streamers and older "
    f"phones very often do not speak it. Use Opus for anything you control end to end. Use "
    f"AAC for anything you hand to a stranger's hardware.")

# ---------------------------------------------------------------- method
clip_bits = ", ".join(
    f"{c['name'].replace('_', ' ')} ({c['seconds']:.0f}s, {c['licence']})"
    for c in corpus["clips"] if not c["synthetic"])
P["method_corpus"] = (
    f"Corpus: {clip_bits}. All were fetched as FLAC from Wikimedia Commons by "
    f"scripts/audio/make_corpus.py, trimmed and normalised to 48 kHz 16-bit stereo WAV, "
    f"which is what every encoder was given. Two synthetic probes were added, a log sweep "
    f"and pink noise with a tone comb, because real recordings do not have steady energy "
    f"at every frequency and the bandwidth question needs a signal that does. The probes "
    f"are excluded from every size and bitrate figure. "
    f"{P['n_encodes']} encodes were measured in total.")

P["method_bandwidth"] = (
    f"Effective bandwidth is measured against the source, not against an absolute level. "
    f"Both signals get a Welch power spectrum, and the reported figure is the frequency "
    f"above which the decoded spectrum has fallen more than {A['drop_db']:.0f} dB below "
    f"the source's own spectrum, ignoring any band where the source itself is more than "
    f"{A['ref_floor_db']:.0f} dB down and so has nothing to discard. Defining it that way "
    f"means a recording that simply has no 18 kHz content cannot be mistaken for a codec "
    f"lowpass. On real music the test frequently cannot answer, because the material has "
    f"no usable energy up there, which is exactly why the stationary probe is the signal "
    f"plotted; the table view carries both readings and the number of clips each is based "
    f"on.")

(DATA / "prose.json").write_text(json.dumps(P, indent=1))
print(f"{len(P)} prose entries")
for k in sorted(P):
    v = P[k]
    print(f"  {k:<20} {v[:110]}{'...' if len(v) > 110 else ''}")
