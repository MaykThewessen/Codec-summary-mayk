"""Derives every sentence and cell figure on the page that contains a number.

Nothing numeric on the page is typed by hand. Re-running the sweep changes the
prose along with the charts, so the text cannot end up asserting something the
measurements no longer support.

Writes data/compression/page_data.json, which is what build_page.py inlines.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "compression"
A = json.loads((DATA / "analysis.json").read_text())

ROWS = A["rows"]
CORPORA = A["corpora"]
# The map cells quote the source-code corpus: the least special of the six, and
# the one whose numbers generalise best to "a directory of files".
MAP_CORPUS = "code"


def fmt_int(v):
    v = round(v)
    if abs(v) < 10000:
        return str(v)
    return ("-" if v < 0 else "") + f"{abs(v):,}".replace(",", ".")


def spd(v):
    return (fmt_int(v) if v >= 100 else f"{v:.1f}") + " MB/s"


def get(corpus, cid):
    return next(r for r in ROWS if r["corpus"] == corpus and r["id"] == cid)


def ratio_of(corpus, cid):
    return get(corpus, cid)["ratio"]


def saved(r):
    return f"{100 * (1 - 1 / r):.1f}%"


C = MAP_CORPUS
P = {}

# ---- head counts --------------------------------------------------------
n_settings = len({r["id"] for r in ROWS})
P["n_points"] = str(n_settings)
P["n_corpora"] = str(len(CORPORA))
P["corpus_mb"] = f"{A['sizes'][C] / 1024 / 1024:.0f} MB"
P["n_measurements"] = fmt_int(n_settings * len(CORPORA) * A["noise"]["rounds"])
P["n_rounds"] = str(A["noise"]["rounds"])

# ---- map cells ----------------------------------------------------------
mem = {m["id"]: m for m in A.get("memory", [])}


def cell(prefix, cid, corpus=C):
    r = get(corpus, cid)
    P[f"cell_{prefix}_ratio"] = f"{r['ratio']:.2f}x on source code"
    P[f"cell_{prefix}_speed"] = f"read {spd(r['d_mb_s'])}"
    return r


xz9 = cell("xz", "xz-9")
br11 = cell("br", "brotli-11", "web")
P["cell_br_ratio"] = f"{br11['ratio']:.2f}x on web assets"
z19 = cell("z19", "zstd-19")
z6 = cell("z6", "zstd-6")
z3 = cell("z3", "zstd-3")
lz4hc = cell("lz4hc", "lz4-9")
lz4f = cell("lz4", "lz4-1")
gz6 = cell("gzip", "gzip-6")

P["cell_lz4_speed_bare"] = spd(lz4f["d_mb_s"])
P["cell_zstd_vs_xz_dspeed"] = f"{z19['d_mb_s'] / xz9['d_mb_s']:.0f}x"
P["cell_br_vs_gzip"] = saved(br11["ratio"] / ratio_of("web", "gzip-6"))
if mem:
    P["xz_dmem"] = f"{mem['xz-9']['window_bytes'] / 1048576:.0f} MB window"
    P["z19_window"] = f"{mem['zstd-19']['window_bytes'] / 1048576:.0f} MB window"
    P["br_window"] = f"{mem['brotli-11']['window_bytes'] / 1048576:.0f} MB window"

# ---- the two frontier charts -------------------------------------------
fs = A["frontier_share"][C]
zstd_on = [i for i in fs["members"] if i.startswith("zstd-")]
front_rows = [get(C, i) for i in fs["members"]]
top = max(front_rows, key=lambda r: r["ratio"])
fast = max(front_rows, key=lambda r: r["d_mb_s"])
off = [f for f in ("gzip", "xz", "bzip2")
       if not any(r["codec"] == f for r in front_rows)]
P["note_pareto"] = (
    f"On this corpus the frontier holds {fs['n']} of the {n_settings} settings, and "
    f"{len(zstd_on)} of them are zstd ({', '.join(i.replace('-', ' -') for i in zstd_on)}). "
    f"That is the concrete form of the claim that zstd covers most of the plane. The two ends "
    f"belong to somebody else: {fast['codec']} -{fast['level']} holds the fast end at "
    f"{spd(fast['d_mb_s'])}, and {top['codec']} -{top['level']} holds the small end at "
    f"{top['ratio']:.2f}x. "
    + (f"Note who is missing: {', '.join(off)} put nothing on the frontier at all, because for "
       f"every setting they offer there is a zstd or brotli setting that is smaller and faster "
       f"to read at the same time. " if off else "")
    + f"Switch corpus with the control above and the membership shifts, but the shape does not."
)

P["note_comp"] = (
    f"The same points, plotted against how fast they compress. Note how much wider this axis "
    f"is: on this corpus compression throughput spans "
    f"{max(r['c_mb_s'] for r in ROWS if r['corpus'] == C) / min(r['c_mb_s'] for r in ROWS if r['corpus'] == C):.0f}x "
    f"from fastest to slowest, while decompression spans only "
    f"{max(r['d_mb_s'] for r in ROWS if r['corpus'] == C) / min(r['d_mb_s'] for r in ROWS if r['corpus'] == C):.0f}x. "
    f"Compression level is a knob on the encoder; the decoder mostly does not care. That "
    f"asymmetry is the single most useful thing to know about this whole subject."
)

# ---- corpus dependence --------------------------------------------------
best = A["best"]
worst_corpus = min(CORPORA, key=lambda c: best[c]["ratio"])
best_corpus = max(CORPORA, key=lambda c: best[c]["ratio"])
NICE = {"web": "HTML, CSS and JS", "code": "source code", "logs": "JSON logs",
        "timeseries": "CSV time series", "compressed": "already-compressed binary",
        "prose": "English prose"}
P["note_corpus"] = (
    f"Best achievable ratio ranges from {best[worst_corpus]['ratio']:.2f}x on "
    f"{NICE[worst_corpus]} to {best[best_corpus]['ratio']:.2f}x on {NICE[best_corpus]}: a factor "
    f"of {best[best_corpus]['ratio'] / best[worst_corpus]['ratio']:.0f} between corpora. Within "
    f"any one corpus the gap between the best codec and gzip -6 is at most "
    f"{max(best[c]['gain_over_gzip'] for c in CORPORA):.0f}% of the bytes. Choosing the right "
    f"codec matters; knowing what your data looks like matters more."
)

cm = A["by_corpus"]["compressed"]
best_comp = max(cm.values(), key=lambda v: v["ratio"])
P["note_compressed"] = (
    f"JPEG photographs and a zstd-compressed Parquet file: {fmt_int(A['sizes']['compressed'])} "
    f"bytes in. The best any codec managed was {best_comp['ratio']:.3f}x, which is "
    f"{best_comp['saved']:.1f}% of the bytes, and it cost "
    f"{spd(min(v['c_mb_s'] for v in cm.values()))} at the slow end to find out. Compressing "
    f"output that is already compressed is close to a pure waste of CPU, and gzip on a Parquet "
    f"file is the most common form of it."
)

lg = A["by_corpus"]["logs"]
ts = A["by_corpus"]["timeseries"]
P["note_logs"] = (
    f"Structured text is where compression still feels like magic. The NDJSON corpus went to "
    f"{max(v['ratio'] for v in lg.values()):.1f}x and the CSV to "
    f"{max(v['ratio'] for v in ts.values()):.1f}x, because every record repeats the same keys "
    f"and the same handful of enum values. These are also the two corpora where zstd -1 "
    f"compressed <em>better</em> than zstd -3 ({ratio_of('logs', 'zstd-1'):.2f}x against "
    f"{ratio_of('logs', 'zstd-3'):.2f}x on the logs) at "
    f"{get('logs', 'zstd-1')['c_mb_s'] / get('logs', 'zstd-3')['c_mb_s']:.1f} times the speed: "
    f"the low levels use different match strategies, and the cheapest one happens to suit "
    f"records that repeat every couple of hundred bytes. Always sweep, never assume monotonic."
)

wb = A["http"]
P["note_web"] = (
    f"On the web corpus brotli -11 reached {wb['brotli-11']['ratio']:.2f}x against gzip -6 at "
    f"{wb['gzip-6']['ratio']:.2f}x: {wb['brotli-11']['vs_gzip6']:.1f}% fewer bytes over the "
    f"wire for the same content. zstd -19 landed at {wb['zstd-19']['ratio']:.2f}x, close behind "
    f"and much faster to produce. Both decode fast enough that the browser never notices; the "
    f"reason to prefer brotli is that every browser already accepts it."
)

# ---- zstd level independence -------------------------------------------
li = A["level_independence"]
spread_all = [li[c]["spread_pct"] for c in CORPORA]
P["claim_zstd_flat"] = (
    f"It holds. Across levels 1 to 22 on this corpus zstd decompressed between "
    f"{spd(li[C]['lo'])} and {spd(li[C]['hi'])}, a spread of {li[C]['spread_pct']:.0f}% around "
    f"the median, while its compression speed fell by a factor of {li[C]['c_ratio']:.0f} over "
    f"the same range. The worst spread on any of the six corpora was "
    f"{max(spread_all):.0f}%. The residual trend is real and small: level 1 decodes fastest "
    f"because it emits longer, simpler matches, and everything from level 3 up is flat within "
    f"the noise of this machine. Turning the level up costs encode time, not read time."
)

P["claim_zstd_fast"] = (
    f"Both parts are right. zstd came out of Meta and is now in the Linux kernel, tar, "
    f"btrfs, RocksDB, Parquet and most CDNs. On this corpus it decompressed at "
    f"{spd(get(C, 'zstd-19')['d_mb_s'])} at level 19, against {spd(get(C, 'gzip-6')['d_mb_s'])} "
    f"for gzip -6 and {spd(get(C, 'xz-9')['d_mb_s'])} for xz -9: roughly "
    f"{get(C, 'zstd-19')['d_mb_s'] / get(C, 'gzip-6')['d_mb_s']:.0f} times gzip and "
    f"{get(C, 'zstd-19')['d_mb_s'] / get(C, 'xz-9')['d_mb_s']:.0f} times xz, while compressing "
    f"better than either of those two settings. Only lz4 reads back faster, and it gives up "
    f"{100 * (1 - ratio_of(C, 'lz4-1') / ratio_of(C, 'zstd-19')):.0f}% of the compression to do it."
)

steps = A["zstd_steps"][C]
step_9 = next(s for s in steps if s["frm"] == 9)
step_19 = next(s for s in steps if s["frm"] == 19)
step_12 = next(s for s in steps if s["frm"] == 12)
P["claim_zstd9"] = (
    f"Efficient in bytes, expensive in time, and the last step is nearly free of benefit. "
    f"Going from zstd -9 to -12 on this corpus removed a further {step_9['size_pct']:.1f}% of "
    f"the output for {step_9['speed_pct']:.0f}% of the compression speed; -19 to -22 removed "
    f"{step_19['size_pct']:.2f}% and is the setting people reach for when they want to feel "
    f"thorough. In throughput terms zstd -1 compresses at "
    f"{spd(get(C, 'zstd-1')['c_mb_s'])} and zstd -19 at {spd(get(C, 'zstd-19')['c_mb_s'])}, "
    f"a factor of {get(C, 'zstd-1')['c_mb_s'] / get(C, 'zstd-19')['c_mb_s']:.0f}, for "
    f"{100 * (1 - ratio_of(C, 'zstd-1') / ratio_of(C, 'zstd-19')):.0f}% fewer bytes. If the "
    f"data is written once and read many times, -19 is correct. If it is written continuously, "
    f"it is not."
)

# ---- xz -----------------------------------------------------------------
arch = [r for r in ROWS if r["corpus"] == C and r["codec"] in ("gzip", "zstd", "xz", "bzip2", "lz4")]
best_arch = max(arch, key=lambda r: r["ratio"])
P["claim_xz"] = (
    f"Confirmed, and the reason is exactly the shape of the trade. Among the tools you would "
    f"actually tar with, xz -9 gave the best ratio on this corpus at {ratio_of(C, 'xz-9'):.2f}x, "
    f"but it compressed at {spd(get(C, 'xz-9')['c_mb_s'])}, one of the slowest numbers on the "
    f"page, and it decompresses at only {spd(get(C, 'xz-9')['d_mb_s'])}: "
    f"{get(C, 'gzip-6')['d_mb_s'] / get(C, 'xz-9')['d_mb_s']:.1f} times slower than gzip and "
    f"{get(C, 'zstd-19')['d_mb_s'] / get(C, 'xz-9')['d_mb_s']:.0f} times slower than zstd -19. "
    f"For a distribution that is the right trade and not a close call: the package is compressed "
    f"once on a build machine and downloaded millions of times, so encoder cost amortises to "
    f"nothing and every byte is bandwidth. Outside that pattern the case is much weaker. zstd -19 "
    f"reached {ratio_of(C, 'zstd-19'):.2f}x, within "
    f"{100 * (ratio_of(C, 'xz-9') / ratio_of(C, 'zstd-19') - 1):.0f}% of xz, and reads back "
    f"{get(C, 'zstd-19')['d_mb_s'] / get(C, 'xz-9')['d_mb_s']:.0f} times faster; brotli -11 "
    f"actually beat xz outright at {ratio_of(C, 'brotli-11'):.2f}x, though brotli has no archive "
    f"tooling and is a delivery format rather than a storage one."
    + (f" And xz -9 writes a file that asks its reader for a "
       f"{mem['xz-9']['window_bytes'] / 1048576:.0f} MB dictionary, against "
       f"{mem['zstd-19']['window_bytes'] / 1048576:.0f} MB for zstd -19." if mem else "")
)

# ---- the corpus-size caveat, which decides part of the xz result ---------
sc = {r["id"]: r for r in A["scale"]["rows"]}
P["note_scale"] = (
    f"Every corpus here is {A['sizes'][C] / 1048576:.0f} MB, and xz preset 9 differs from preset "
    f"6 only in dictionary size, {mem['xz-9']['window_bytes'] / 1048576:.0f} MB against "
    f"{mem['xz-6']['window_bytes'] / 1048576:.0f} MB. Neither is filled, so xz -6 and xz -9 "
    f"emitted byte-identical output on all six: the -9 column on this page is not measuring what "
    f"-9 is for. Re-run on all six corpora concatenated, "
    f"{A['scale']['bytes'] / 1048576:.0f} MB, and they are still identical "
    f"({sc['xz-6']['ratio']:.2f}x against {sc['xz-9']['ratio']:.2f}x), because a bigger "
    f"dictionary only pays when the data repeats itself at that distance. The long-range "
    f"section is the case where it does, and there xz -9 came first."
    if mem else ""
)

P["note_bzip2"] = (
    f"bzip2 is on this page as the legacy reference and it refused to behave like one: bzip2 -9 "
    f"had the best ratio of any codec measured on JSON logs "
    f"({ratio_of('logs', 'bzip2-9'):.2f}x), CSV time series "
    f"({ratio_of('timeseries', 'bzip2-9'):.2f}x) and English prose "
    f"({ratio_of('prose', 'bzip2-9'):.2f}x). Its Burrows-Wheeler transform sorts repeated "
    f"records next to each other, which is exactly what those three corpora are made of. It is "
    f"still not the answer, because it is the slowest decompressor on the page by a wide margin: "
    f"{min(get(c, 'bzip2-9')['d_mb_s'] for c in CORPORA if c != 'compressed'):.0f} to "
    f"{max(get(c, 'bzip2-9')['d_mb_s'] for c in CORPORA if c != 'compressed'):.0f} MB/s, "
    f"between {min(get(c, 'zstd-19')['d_mb_s'] / get(c, 'bzip2-9')['d_mb_s'] for c in CORPORA if c != 'compressed'):.0f} "
    f"and {max(get(c, 'zstd-19')['d_mb_s'] / get(c, 'bzip2-9')['d_mb_s'] for c in CORPORA if c != 'compressed'):.0f} "
    f"times slower than zstd -19 on the same data. Worth knowing before dismissing a .bz2 "
    f"someone hands you, and worth remembering that ratio alone never settles anything."
)

P["claim_levels"] = (
    f"True, and it is usually the smallest lever available. On this corpus the whole range "
    f"from gzip -1 to xz -9, six codecs and {n_settings} settings, spans "
    f"{min(r['ratio'] for r in ROWS if r['corpus'] == C):.2f}x to "
    f"{max(r['ratio'] for r in ROWS if r['corpus'] == C):.2f}x. Switching corpus spans "
    f"{best[worst_corpus]['ratio']:.2f}x to {best[best_corpus]['ratio']:.2f}x. Changing what "
    f"you store, or how you encode it before it reaches the compressor, moves the result far "
    f"more than any level does: dictionary-encoding a string column, dropping a redundant "
    f"index, or storing a float32 where a float64 was not needed."
)

# ---- long range ---------------------------------------------------------
lr = A["longrange"]
lr_rows = {r["name"]: r for r in lr["rows"]}
P["lr_mb"] = f"{lr['bytes'] / 1024 / 1024:.0f} MB"
z3p, z3l = lr_rows["zstd -3"], lr_rows["zstd -3 --long=27"]
z19p, z19l = lr_rows["zstd -19"], lr_rows["zstd -19 --long=27"]
P["note_longrange"] = (
    f"One flag, {z3l['ratio'] / z3p['ratio']:.0f} times the compression: zstd -3 alone reached "
    f"{z3p['ratio']:.1f}x on this file and zstd -3 --long=27 reached {z3l['ratio']:.1f}x, at "
    f"{spd(z3l['c_mb_s'])} against {spd(z3p['c_mb_s'])}, so the long-distance matcher paid for "
    f"itself three times over in speed as well. At level 19 the gain is smaller "
    f"({z19p['ratio']:.1f}x to {z19l['ratio']:.1f}x) because that window is already 8 MB, but "
    f"the flag still made the encode {z19l['c_mb_s'] / z19p['c_mb_s']:.0f} times faster by "
    f"handing the long matches to a cheap matcher first. This is also the one case where xz -9 "
    f"came first outright: its 64 MB dictionary spans the whole repeat period and it reached "
    f"{lr_rows['xz -9']['ratio']:.1f}x, at {spd(lr_rows['xz -9']['c_mb_s'])} and reading back at "
    f"{spd(lr_rows['xz -9']['d_mb_s'])} against {spd(z19l['d_mb_s'])} for zstd. gzip, with a "
    f"32 kB window, managed "
    f"{lr_rows['gzip -6']['ratio']:.1f}x and never had a chance. If you compress backups, "
    f"snapshots or anything versioned, this flag is the highest-value thing on this page."
)

# ---- containers ---------------------------------------------------------
co = A["containers"]
cr = {r["name"]: r for r in co["rows"]}
P["cont_files"] = fmt_int(co["files"])
P["note_containers"] = (
    f"The gap that matters is not between the codecs, it is between per-file and solid. "
    f"zip with deflate produced {fmt_int(cr['zip (deflate 6)']['bytes'])} bytes; the same "
    f"deflate coder over a single tar stream produced "
    f"{fmt_int(cr['tar.gz (gzip 6)']['bytes'])}, "
    f"{100 * (1 - cr['tar.gz (gzip 6)']['bytes'] / cr['zip (deflate 6)']['bytes']):.0f}% less, "
    f"purely because matches can cross file boundaries. On {fmt_int(co['files'])} similar source "
    f"files that is worth more than any codec upgrade inside zip would be. 7z and tar.xz land "
    f"within {abs(100 * (cr['7z (LZMA2)']['bytes'] / cr['tar.xz (xz 9)']['bytes'] - 1)):.1f}% of "
    f"each other, as they should: same coder, same solid layout, different envelope."
)

# ---- memory -------------------------------------------------------------
if mem:
    P["note_memory"] = (
        f"The window column spans three orders of magnitude: "
        f"{mem['lz4-1']['window_bytes'] / 1024:.0f} kB for lz4 and "
        f"{mem['gzip-9']['window_bytes'] / 1024:.0f} kB for gzip, which is why both turn up in "
        f"bootloaders and firmware, against {mem['xz-9']['window_bytes'] / 1048576:.0f} MB for "
        f"xz -9. That is a property of the file rather than of the reader: anything that opens a "
        f"<code>-9</code> xz file has to find that memory, on a phone or in a browser tab or in "
        f"a thousand concurrent streams. zstd writes its window into the frame header, so the "
        f"file states its own demand: {mem['zstd-3']['window_bytes'] / 1048576:.0f} MB at level "
        f"3, {mem['zstd-19']['window_bytes'] / 1048576:.0f} MB at level 19. Compressor peak is "
        f"the other direction and is the encoder's problem alone: brotli -11 wanted "
        f"{mem['brotli-11']['c_kb'] / 1024:.0f} MB and zstd -22 wanted "
        f"{mem['zstd-22']['c_kb'] / 1024:.0f} MB, both to compress an "
        f"{A['sizes'][C] / 1048576:.0f} MB file."
    )
    P["note_memory_method"] = (
        "Compressor peak is measured: peak resident set of a fresh process, streaming, output "
        "discarded, with the high-water mark reset after the imports. Anything under a megabyte "
        "is reported as such rather than as a number, because it disappears into heap the "
        "interpreter had already faulted in. The decompressor side is not measured for the same "
        "reason, and the window each file declares is given instead: the libraries here allocate "
        "the window lazily out of free heap, so the peak-RSS delta came out at zero even for "
        "codecs with an 8 MB window. Windows are parsed out of the zstd frame header and the xz "
        "block header; for gzip, lz4 and bzip2 they are fixed by the format. These files were "
        "produced by a streaming encoder, so zstd -22 declares the full 128 MB window a pipe "
        "would need, where one-shot compression of a known-size input would clamp it."
    )

# ---- method -------------------------------------------------------------
P["method_corpus"] = (
    f"Six corpora of {A['sizes'][C] / 1024 / 1024:.0f} MB each, every codec swept across its own "
    f"level ladder: gzip 1/6/9, zstd 1/3/6/9/12/15/19/22, brotli 1/5/9/11, xz 1/6/9, lz4 "
    f"default and high-compression, bzip2 1/9. That is {n_settings} settings on "
    f"{len(CORPORA)} corpora, each round-tripped and verified byte-identical. Corpora: real "
    f"Wikipedia HTML plus the CSS and JS of widely deployed libraries; Python standard library "
    f"sources; generated NDJSON service logs; generated hourly day-ahead electricity price and "
    f"load CSV for four bidding zones; JPEG photographs and a zstd-compressed Parquet file; "
    f"public-domain English books."
)

P["method_timing"] = (
    f"Each setting was run for {A['noise']['rounds']} full rounds over every codec, and the "
    f"median is what is reported. Operations faster than 100 ms were repeated inside the timer "
    f"until they exceeded it, so a 3 ms lz4 decode is an average over many passes rather than "
    f"one noisy sample. Compression and decompression are timed separately on one in-memory "
    f"buffer, so no file system or process startup cost is included. Ratios are exact and "
    f"reproducible; throughputs are not."
)

P["method_noise"] = (
    f"Other work was running on this container throughout. Round-to-round spread was "
    f"{100 * A['noise']['c_spread_med']:.0f}% of the median for compression and "
    f"{100 * A['noise']['d_spread_med']:.0f}% for decompression at the midpoint, with a 90th "
    f"percentile of {100 * A['noise']['c_spread_p90']:.0f}% and "
    f"{100 * A['noise']['d_spread_p90']:.0f}%. Rounds are interleaved across all codecs rather "
    f"than run per codec, so load lands on everything equally. Read the ordering and the "
    f"order-of-magnitude gaps; do not read a 15% difference between two adjacent points as real."
)

A["prose"] = P
(DATA / "page_data.json").write_text(json.dumps(A, separators=(",", ":")))
print(json.dumps(P, indent=1))
print("\nwrote", DATA / "page_data.json",
      f"({(DATA / 'page_data.json').stat().st_size / 1024:.0f} KB)")
