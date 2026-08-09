"""Sweeps every codec across its own level ladder on every corpus.

Level is the whole trade, so a single setting per codec would answer nothing:
each family is swept across the range a practitioner would actually consider,
and the resulting cloud of points is what the Pareto chart is drawn from.

Everything is measured one-shot on a single in-memory buffer, which isolates
the codec from file system and process startup cost. The CLI tools for zstd,
brotli, lz4 and 7-Zip are not installed in this container; the Python bindings
used here wrap the same reference C libraries at the same versions, so the
numbers are the codec's, not a wrapper's.

Subcommands:
  sweep [corpus...]   ratio and throughput for every codec, level and corpus
  memory              compressor peak RSS, plus the window each file declares
  containers          zip / 7z / tar.gz / tar.zst / tar.xz as archive formats
  scale               the same top settings on every corpus at once, 48 MB
  longrange           zstd --long against a corpus with 8 MB-distance repeats
"""

import bz2
import io
import json
import lzma
import resource
import statistics
import sys
import tarfile
import time
import zlib
from pathlib import Path

import brotli
import lz4.frame
import zstandard as zstd

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata" / "compression"
DATA = ROOT / "data" / "compression"
DATA.mkdir(parents=True, exist_ok=True)

CORPORA = ["web", "code", "logs", "timeseries", "compressed", "prose"]
BLOB_CAP = 8 * 1024 * 1024
ROUNDS = 3           # medians are taken over this many rounds
MIN_SECONDS = 0.10   # inner repeats until an operation is timed over this long

# --------------------------------------------------------------------------
# the ladders. Each entry is (family, level, encode, decode).
# --------------------------------------------------------------------------

def zstd_enc(level, long=False):
    if long:
        params = zstd.ZstdCompressionParameters.from_level(
            level, window_log=27, enable_ldm=1)
        c = zstd.ZstdCompressor(compression_params=params)
    else:
        c = zstd.ZstdCompressor(level=level)
    return c.compress


def zstd_dec():
    d = zstd.ZstdDecompressor(max_window_size=2 ** 27)
    return d.decompress


def build_configs():
    cfgs = []
    for lv in (1, 6, 9):
        cfgs.append(dict(family="gzip", level=lv,
                         enc=lambda b, lv=lv: zlib.compress(b, lv), dec=zlib.decompress))
    for lv in (1, 3, 6, 9, 12, 15, 19, 22):
        cfgs.append(dict(family="zstd", level=lv, enc=zstd_enc(lv), dec=zstd_dec()))
    for lv in (1, 5, 9, 11):
        cfgs.append(dict(family="brotli", level=lv,
                         enc=lambda b, lv=lv: brotli.compress(b, quality=lv, lgwin=24),
                         dec=brotli.decompress))
    for lv in (1, 6, 9):
        cfgs.append(dict(family="xz", level=lv,
                         enc=lambda b, lv=lv: lzma.compress(b, format=lzma.FORMAT_XZ, preset=lv),
                         dec=lzma.decompress))
    for lv in (1, 9, 12):
        cfgs.append(dict(family="lz4", level=lv,
                         enc=lambda b, lv=lv: lz4.frame.compress(b, compression_level=lv),
                         dec=lz4.frame.decompress))
    for lv in (1, 9):
        cfgs.append(dict(family="bzip2", level=lv,
                         enc=lambda b, lv=lv: bz2.compress(b, lv), dec=bz2.decompress))
    for c in cfgs:
        c["id"] = f"{c['family']}-{c['level']}"
        c["cobj"], c["dobj"] = STREAMS[c["family"]](c["level"])
    return cfgs


# --------------------------------------------------------------------------
# Streaming factories, used only by the memory probe. A one-shot call on a
# whole buffer lets several of these libraries alias the output buffer as their
# window, which measures the allocator rather than the codec. Streaming with
# the output thrown away is what `zstd -d file` actually does.
# --------------------------------------------------------------------------

class _Obj:
    """Uniform (feed, finish) wrapper over six different streaming APIs."""

    def __init__(self, feed, finish):
        self.feed, self.finish = feed, finish


def _zlib(level):
    def c():
        o = zlib.compressobj(level)
        return _Obj(o.compress, o.flush)

    def d():
        o = zlib.decompressobj()
        return _Obj(o.decompress, lambda: o.flush())
    return c, d


def _zstd_s(level):
    def c():
        o = zstd.ZstdCompressor(level=level).compressobj()
        return _Obj(o.compress, o.flush)

    def d():
        o = zstd.ZstdDecompressor(max_window_size=2 ** 27).decompressobj()
        return _Obj(o.decompress, lambda: b"")
    return c, d


def _brotli_s(level):
    def c():
        o = brotli.Compressor(quality=level, lgwin=24)
        return _Obj(o.process, o.finish)

    def d():
        o = brotli.Decompressor()
        return _Obj(o.process, lambda: b"")
    return c, d


def _lzma_s(level):
    def c():
        o = lzma.LZMACompressor(format=lzma.FORMAT_XZ, preset=level)
        return _Obj(o.compress, o.flush)

    def d():
        o = lzma.LZMADecompressor()
        return _Obj(o.decompress, lambda: b"")
    return c, d


def _lz4_s(level):
    def c():
        o = lz4.frame.LZ4FrameCompressor(compression_level=level)
        started = []

        def feed(b):
            head = o.begin() if not started else b""
            started.append(1)
            return head + o.compress(b)
        return _Obj(feed, o.flush)

    def d():
        o = lz4.frame.LZ4FrameDecompressor()
        return _Obj(o.decompress, lambda: b"")
    return c, d


def _bz2_s(level):
    def c():
        o = bz2.BZ2Compressor(level)
        return _Obj(o.compress, o.flush)

    def d():
        o = bz2.BZ2Decompressor()
        return _Obj(o.decompress, lambda: b"")
    return c, d


STREAMS = {"gzip": _zlib, "zstd": _zstd_s, "brotli": _brotli_s,
           "xz": _lzma_s, "lz4": _lz4_s, "bzip2": _bz2_s}


# --------------------------------------------------------------------------
def blob(corpus):
    """One buffer per corpus: every file concatenated in name order, capped."""
    d = TESTDATA / corpus
    out = bytearray()
    for p in sorted(d.iterdir()):
        out += p.read_bytes()
        if len(out) >= BLOB_CAP:
            break
    return bytes(out[:BLOB_CAP])


def timed(fn, arg):
    """Median-friendly single sample: inner-repeat short operations."""
    t0 = time.perf_counter()
    out = fn(arg)
    dt = time.perf_counter() - t0
    if dt < MIN_SECONDS:
        n = min(50, max(1, int(MIN_SECONDS / max(dt, 1e-6))))
        t0 = time.perf_counter()
        for _ in range(n):
            out = fn(arg)
        dt = (time.perf_counter() - t0) / n
    return dt, out


def sweep(corpora):
    cfgs = build_configs()
    rows = {}
    for corpus in corpora:
        raw = blob(corpus)
        mb = len(raw) / 1e6
        print(f"\n{corpus}: {len(raw)} bytes")
        # Rounds are outer, so a noisy neighbour process shows up as spread
        # across every codec rather than as a penalty on whichever one ran then.
        for rnd in range(ROUNDS):
            for c in cfgs:
                key = (corpus, c["id"])
                r = rows.setdefault(key, dict(corpus=corpus, codec=c["family"],
                                              level=c["level"], id=c["id"],
                                              in_bytes=len(raw), ct=[], dt=[]))
                ct, packed = timed(c["enc"], raw)
                dt, back = timed(c["dec"], packed)
                assert back == raw, f"round trip failed: {c['id']} on {corpus}"
                r["out_bytes"] = len(packed)
                r["ct"].append(ct)
                r["dt"].append(dt)
            print(f"  round {rnd + 1}/{ROUNDS} done")
        for c in cfgs:
            r = rows[(corpus, c["id"])]
            r["c_mb_s"] = round(mb / statistics.median(r["ct"]), 2)
            r["d_mb_s"] = round(mb / statistics.median(r["dt"]), 2)
            r["ratio"] = round(r["in_bytes"] / r["out_bytes"], 4)
            r["c_spread"] = round((max(r["ct"]) - min(r["ct"])) / statistics.median(r["ct"]), 3)
            r["d_spread"] = round((max(r["dt"]) - min(r["dt"])) / statistics.median(r["dt"]), 3)
        for c in cfgs:
            r = rows[(corpus, c["id"])]
            print(f"  {r['id']:<10} x{r['ratio']:>6.2f}  c {r['c_mb_s']:>8.1f} MB/s"
                  f"  d {r['d_mb_s']:>8.1f} MB/s")

    out = sorted(rows.values(), key=lambda r: (r["corpus"], r["codec"], r["level"]))
    for r in out:
        r.pop("ct"), r.pop("dt")
    path = DATA / "sweep.json"
    prev = json.loads(path.read_text()) if path.exists() else []
    keep = [r for r in prev if r["corpus"] not in corpora]
    path.write_text(json.dumps(sorted(keep + out, key=lambda r: (r["corpus"], r["codec"], r["level"])), indent=1))
    print(f"\nwrote {path} ({len(keep + out)} rows, {ROUNDS} rounds, median reported)")


# --------------------------------------------------------------------------
MEM_CHUNK = 256 * 1024


def window_of(family, level, packed):
    """The match window the compressed file asks its reader to hold.

    Parsed out of the file where the format writes it down (zstd frame header,
    xz block header), and the format constant otherwise. This is reported
    instead of a measured decompressor RSS: see the note in memory().
    """
    if family == "zstd":
        return zstd.get_frame_parameters(packed[:64]).window_size
    if family == "xz":
        # stream header is 12 bytes, then a block header whose last filter is
        # LZMA2 with a single properties byte encoding the dictionary size.
        i = 12
        hsize = (packed[i] + 1) * 4
        blk = packed[i:i + hsize]
        j = 2
        flags = blk[1]
        for present in (flags & 0x40, flags & 0x80):
            if present:
                while blk[j] & 0x80:
                    j += 1
                j += 1
        for _ in range((flags & 0x03) + 1):
            fid = 0
            shift = 0
            while blk[j] & 0x80:
                fid |= (blk[j] & 0x7F) << shift
                shift += 7
                j += 1
            fid |= blk[j] << shift
            j += 1
            plen = blk[j]
            j += 1
            if fid == 0x21 and plen == 1:
                b = blk[j]
                return (2 | (b & 1)) << (b // 2 + 11)
            j += plen
        return None
    if family == "brotli":
        return (1 << 24) - 16          # lgwin 24, the value this sweep used
    if family == "gzip":
        return 32 * 1024               # DEFLATE, fixed by the format
    if family == "lz4":
        return 64 * 1024               # LZ4 block format, fixed
    if family == "bzip2":
        return level * 100 * 1000      # block size; the decoder needs a few times this
    return None


def mem_child(mode, src, cid, dest):
    """Runs in a fresh interpreter, one direction, streaming, output discarded.

    ru_maxrss is a high-water mark that never falls, so the two directions need
    separate processes or the smaller hides behind the larger. Input is read a
    chunk at a time and output is counted rather than kept, which leaves the
    codec's own window and tables as the only thing that can move the number.
    """
    cfg = next(c for c in build_configs() if c["id"] == cid)
    obj = (cfg["cobj"] if mode == "c" else cfg["dobj"])()
    fh = open(src, "rb")
    out = open(dest, "wb") if dest != "-" else None
    # ru_maxrss is a high-water mark, and importing the six bindings pushes it
    # well above the steady state. Linux allows resetting it, which leaves the
    # delta below equal to the codec's own allocation and nothing else.
    try:
        Path("/proc/self/clear_refs").write_text("5")
    except OSError:
        pass
    base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    n = 0
    while True:
        chunk = fh.read(MEM_CHUNK)
        if not chunk:
            break
        piece = obj.feed(chunk)
        n += len(piece)
        if out:
            out.write(piece)
        del piece
    piece = obj.finish()
    n += len(piece)
    if out:
        out.write(piece)
        out.close()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    fh.close()
    print(json.dumps(dict(kb=max(0, peak - base), out_bytes=n)))


def memory():
    """Compressor peak RSS, measured. Decompressor window, read off the file.

    A measured decompressor RSS is not reported, and that is deliberate: the
    bindings here allocate their window lazily and satisfy it out of heap the
    interpreter had already faulted in, so the peak-RSS delta came out at zero
    for every codec including ones with an 8 MB window. Rather than publish a
    column of zeroes, the window each compressed file declares is parsed out of
    its own header. That is the number that constrains a reader anyway: whatever
    opens the file has to be able to hold it.
    """
    import subprocess
    import tempfile
    rows = []
    tmp = Path(tempfile.mkdtemp())
    raw_path = tmp / "raw.bin"
    raw_path.write_bytes(blob("code"))
    packed = tmp / "packed.bin"
    for c in build_configs():
        p = subprocess.run(
            [sys.executable, __file__, "--mem-child", "c", str(raw_path), c["id"], str(packed)],
            capture_output=True, text=True)
        if p.returncode != 0:
            print("  fail", c["id"], p.stderr[-400:])
            continue
        v = json.loads(p.stdout.strip().splitlines()[-1])
        win = window_of(c["family"], c["level"], packed.read_bytes()[:64])
        r = dict(corpus="code", id=c["id"], codec=c["family"], level=c["level"],
                 c_kb=v["kb"], window_bytes=win, out_bytes=v["out_bytes"])
        rows.append(r)
        print(f"  {c['id']:<10} compressor peak {r['c_kb']/1024:>8.1f} MB   "
              f"window {win/1024/1024:>7.2f} MB")
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    (DATA / "memory.json").write_text(json.dumps(rows, indent=1))
    print("wrote", DATA / "memory.json")


# --------------------------------------------------------------------------
def containers():
    """Archive formats, which is a different question from codec formats.

    zip stores each member compressed on its own; tar.* and 7z compress the
    whole stream, so cross-file redundancy is available to the matcher. On a
    directory of many similar small files that difference is larger than the
    difference between the codecs inside.
    """
    import py7zr
    src = TESTDATA / "code"
    files = sorted(src.iterdir())
    total = sum(p.stat().st_size for p in files)
    rows = []

    def tar_bytes():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for p in files:
                tf.add(p, arcname=p.name)
        return buf.getvalue()

    tar = tar_bytes()

    def rec(name, note, fn, solid):
        t0 = time.perf_counter()
        n = fn()
        dt = time.perf_counter() - t0
        rows.append(dict(name=name, note=note, bytes=n, solid=solid,
                         ratio=round(total / n, 4), seconds=round(dt, 3),
                         c_mb_s=round(total / 1e6 / dt, 1)))
        print(f"  {name:<22} {n:>10} B   x{total / n:>6.2f}   {dt:>6.2f} s")

    import zipfile

    def zip_deflate():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in files:
                z.write(p, arcname=p.name)
        return len(buf.getvalue())

    def zip_bzip2():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_BZIP2, compresslevel=9) as z:
            for p in files:
                z.write(p, arcname=p.name)
        return len(buf.getvalue())

    def sevenz():
        buf = io.BytesIO()
        with py7zr.SevenZipFile(buf, "w") as z:
            for p in files:
                z.write(p, arcname=p.name)
        return len(buf.getvalue())

    rec("zip (deflate 6)", "per-file, no cross-file matching", zip_deflate, False)
    rec("zip (bzip2 9)", "per-file, no cross-file matching", zip_bzip2, False)
    rec("tar.gz (gzip 6)", "solid stream, deflate 32 kB window", lambda: len(zlib.compress(tar, 6)), True)
    rec("tar.bz2 (bzip2 9)", "solid stream, 900 kB blocks", lambda: len(bz2.compress(tar, 9)), True)
    rec("tar.zst (zstd 19)", "solid stream, 8 MB window", lambda: len(zstd.ZstdCompressor(level=19).compress(tar)), True)
    rec("tar.xz (xz 9)", "solid stream, 64 MB dictionary", lambda: len(lzma.compress(tar, format=lzma.FORMAT_XZ, preset=9)), True)
    rec("7z (LZMA2)", "solid by default, same coder as xz", sevenz, True)

    (DATA / "containers.json").write_text(json.dumps(
        dict(files=len(files), bytes=total, tar_bytes=len(tar), rows=rows), indent=1))
    print("wrote", DATA / "containers.json")


# --------------------------------------------------------------------------
def longrange():
    """Redundancy at 8 MB distance: what the default window cannot see."""
    raw = (TESTDATA / "longrange" / "revisions.bin").read_bytes()
    mb = len(raw) / 1e6
    rows = []

    def rec(name, note, enc, dec):
        t0 = time.perf_counter()
        packed = enc(raw)
        ct = time.perf_counter() - t0
        t0 = time.perf_counter()
        back = dec(packed)
        dt = time.perf_counter() - t0
        assert back == raw
        rows.append(dict(name=name, note=note, bytes=len(packed),
                         ratio=round(len(raw) / len(packed), 3),
                         c_mb_s=round(mb / ct, 1), d_mb_s=round(mb / dt, 1)))
        print(f"  {name:<26} {len(packed):>10} B  x{len(raw)/len(packed):>7.2f}"
              f"  c {mb/ct:>7.1f}  d {mb/dt:>7.1f} MB/s")

    dec = zstd_dec()
    rec("zstd -3", "2 MB window: sees nothing across revisions", zstd_enc(3), dec)
    rec("zstd -3 --long=27", "128 MB window, long-distance matcher on", zstd_enc(3, True), dec)
    rec("zstd -19", "8 MB window, still short of the 8.4 MB period", zstd_enc(19), dec)
    rec("zstd -19 --long=27", "the combination that actually wins", zstd_enc(19, True), dec)
    rec("xz -9", "64 MB dictionary, gets there but slowly",
        lambda b: lzma.compress(b, format=lzma.FORMAT_XZ, preset=9), lzma.decompress)
    rec("gzip -6", "32 kB window: no chance", lambda b: zlib.compress(b, 6), zlib.decompress)

    (DATA / "longrange.json").write_text(json.dumps(
        dict(bytes=len(raw), revisions=8, rows=rows), indent=1))
    print("wrote", DATA / "longrange.json")


def scale():
    """A larger input, because 8 MB does not exercise the big dictionaries.

    At 8 MB, xz -6 and xz -9 emit byte-identical output: preset 9 differs from
    preset 6 only in dictionary size (64 MB against 8 MB) and the input never
    fills either. Reporting the main sweep without this would let the corpus
    size decide the ranking. Ratio only plus a single timing pass, on every
    corpus concatenated.
    """
    raw = b"".join(blob(c) for c in CORPORA)
    mb = len(raw) / 1e6
    print(f"{len(raw)} bytes ({mb:.1f} MB)")
    picks = [("gzip", 6), ("bzip2", 9), ("brotli", 11), ("zstd", 19), ("zstd", 22),
             ("xz", 6), ("xz", 9)]
    cfgs = {c["id"]: c for c in build_configs()}
    rows = []
    for fam, lv in picks:
        c = cfgs[f"{fam}-{lv}"]
        t0 = time.perf_counter()
        packed = c["enc"](raw)
        ct = time.perf_counter() - t0
        t0 = time.perf_counter()
        back = c["dec"](packed)
        dt = time.perf_counter() - t0
        assert back == raw
        rows.append(dict(id=c["id"], codec=fam, level=lv, in_bytes=len(raw),
                         out_bytes=len(packed), ratio=round(len(raw) / len(packed), 4),
                         c_mb_s=round(mb / ct, 2), d_mb_s=round(mb / dt, 2),
                         window_bytes=window_of(fam, lv, packed[:64])))
        r = rows[-1]
        print(f"  {r['id']:<10} x{r['ratio']:>6.2f}  c {r['c_mb_s']:>7.1f}  d {r['d_mb_s']:>7.1f}"
              f"  window {r['window_bytes']/1048576:.0f} MB")
    (DATA / "scale.json").write_text(json.dumps(dict(bytes=len(raw), rows=rows), indent=1))
    print("wrote", DATA / "scale.json")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--mem-child":
        mem_child(a[1], a[2], a[3], a[4])
    elif not a or a[0] == "sweep":
        sweep(a[1:] or CORPORA)
    elif a[0] == "memory":
        memory()
    elif a[0] == "containers":
        containers()
    elif a[0] == "longrange":
        longrange()
    elif a[0] == "scale":
        scale()
    else:
        raise SystemExit(__doc__)
