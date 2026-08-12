"""Assembles the six test corpora under testdata/compression/.

Compression ratio is a property of the data far more than of the codec, so a
single blended corpus would be actively misleading. Six are built here, each
one a directory of ordinary files, and every measurement is reported per
corpus and never averaged across them.

Provenance, since half the argument about a benchmark is what went into it:

  web         Wikipedia article HTML (CC BY-SA 4.0) plus the CSS and JS of
              widely deployed MIT-licensed libraries, fetched from jsDelivr.
  code        Python standard library sources from this container (PSF licence).
  logs        Generated NDJSON application logs. Structure copied from real
              service logs: repeated keys, hex trace ids, bounded enums.
  timeseries  Generated hourly day-ahead electricity price and load CSV for
              four bidding zones, shaped like the ENTSO-E series this repo's
              other work uses: seasonal, weekly and daily cycles, solar-driven
              negative prices, occasional scarcity spikes.
  compressed  Already-compressed binary: Kodak reference photographs encoded to
              JPEG, plus a zstd-compressed Parquet file of the timeseries data.
  prose       Public-domain English books from Project Gutenberg.

The generated corpora are generated rather than downloaded because no
permissively redistributable real equivalent exists; their statistical shape is
what matters for compression and that is reproduced honestly.
"""

import hashlib
import io
import json
import random
import sys
import sysconfig
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "testdata" / "compression"
UA = {"User-Agent": "codec-summary-mayk/1.0 (compression corpus builder)"}

# Every corpus is capped at the same uncompressed size so ratios and
# throughputs are comparable across them.
TARGET = 8 * 1024 * 1024

WIKI_ARTICLES = [
    "Data_compression", "Electricity_market", "Netherlands", "Photosynthesis",
    "Amsterdam", "Wind_power", "Transformer_(deep_learning_architecture)",
    "Second_law_of_thermodynamics", "Rijksmuseum", "Nikola_Tesla",
    "History_of_the_Netherlands", "Solar_power",
]

WEB_ASSETS = [
    # name, url. All MIT or similar; these are the files real sites actually ship.
    ("bootstrap.css", "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.css"),
    ("bootstrap.bundle.js", "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.js"),
    ("jquery.js", "https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.js"),
    ("d3.js", "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.js"),
    ("lodash.js", "https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.js"),
    ("react-dom.development.js", "https://cdn.jsdelivr.net/npm/react-dom@18.3.1/umd/react-dom.development.js"),
    ("vue.js", "https://cdn.jsdelivr.net/npm/vue@3.5.13/dist/vue.global.js"),
    ("chart.js", "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js"),
]

GUTENBERG = [
    ("pride_and_prejudice.txt", "https://www.gutenberg.org/files/1342/1342-0.txt"),
    ("moby_dick.txt", "https://www.gutenberg.org/files/2701/2701-0.txt"),
    ("frankenstein.txt", "https://www.gutenberg.org/files/84/84-0.txt"),
    ("alice.txt", "https://www.gutenberg.org/files/11/11-0.txt"),
    ("sherlock.txt", "https://www.gutenberg.org/files/1661/1661-0.txt"),
    ("war_and_peace.txt", "https://www.gutenberg.org/files/2600/2600-0.txt"),
    ("origin_of_species.txt", "https://www.gutenberg.org/files/1228/1228-0.txt"),
    ("great_expectations.txt", "https://www.gutenberg.org/files/1400/1400-0.txt"),
    ("les_miserables.txt", "https://www.gutenberg.org/files/135/135-0.txt"),
]

KODAK = list(range(1, 25))
KODAK_URL = "https://r0k.us/graphics/kodak/kodak/kodim{:02d}.png"


def get(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - transient network, retry
            last = e
    raise RuntimeError(f"{url}: {last}")


def write(corpus, name, data):
    p = DEST / corpus / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return p.stat().st_size


# --------------------------------------------------------------------------- web
def build_web():
    total = 0
    for title in WIKI_ARTICLES:
        if total > TARGET * 0.62:
            break
        url = f"https://en.wikipedia.org/api/rest_v1/page/html/{title}"
        try:
            total += write("web", f"wiki_{title.lower()}.html", get(url))
        except RuntimeError as e:
            print("  skip", title, e)
    for name, url in WEB_ASSETS:
        if total > TARGET * 1.05:
            break
        try:
            total += write("web", name, get(url))
        except RuntimeError as e:
            print("  skip", name, e)
    return total


# -------------------------------------------------------------------------- code
def build_code():
    """Python standard library sources: real code, real comments, real docstrings."""
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    files = sorted(
        (p for p in stdlib.rglob("*.py")
         if "test" not in p.parts and "site-packages" not in p.parts
         and p.stat().st_size > 2000),
        key=lambda p: str(p))
    total = 0
    for p in files:
        if total >= TARGET:
            break
        rel = p.relative_to(stdlib).as_posix().replace("/", "__")
        total += write("code", rel, p.read_bytes())
    return total


# -------------------------------------------------------------------------- logs
SERVICES = ["ingest-api", "forecast-worker", "price-scraper", "grid-sync",
            "auth-gateway", "report-render", "tile-server"]
LEVELS = (["INFO"] * 80) + (["DEBUG"] * 12) + (["WARN"] * 6) + (["ERROR"] * 2)
PATHS = ["/v1/prices", "/v1/prices/{zone}", "/v1/forecast/day-ahead", "/healthz",
         "/v1/assets/{id}/timeseries", "/v1/report/{id}", "/metrics", "/v1/auth/token"]
MSGS = ["request completed", "cache miss, fetching upstream", "batch flushed to warehouse",
        "retrying after upstream 503", "schema validated", "connection pool resized",
        "slow query detected", "token refreshed", "partition written"]


def build_logs():
    rng = random.Random(20260809)
    total, part, buf = 0, 0, io.StringIO()
    ts = 1735689600.0
    while total < TARGET:
        ts += rng.expovariate(1 / 0.35)
        svc = rng.choice(SERVICES)
        lvl = rng.choice(LEVELS)
        rec = {
            "ts": f"2026-{1 + int(ts // 2678400) % 12:02d}-"
                  f"{1 + int(ts // 86400) % 28:02d}T"
                  f"{int(ts // 3600) % 24:02d}:{int(ts // 60) % 60:02d}:"
                  f"{int(ts) % 60:02d}.{int(ts * 1000) % 1000:03d}Z",
            "level": lvl,
            "service": svc,
            "trace_id": "%032x" % rng.getrandbits(128),
            "span_id": "%016x" % rng.getrandbits(64),
            "msg": rng.choice(MSGS),
            "http": {"method": rng.choice(["GET", "GET", "GET", "POST", "PUT"]),
                     "path": rng.choice(PATHS),
                     "status": rng.choice([200] * 20 + [204, 301, 400, 404, 500, 503]),
                     "duration_ms": round(rng.lognormvariate(3.0, 0.9), 2)},
            "host": f"ip-10-42-{rng.randrange(0, 8)}-{rng.randrange(1, 250)}",
            "zone": rng.choice(["NL", "BE", "DE-LU", "FR"]),
            "version": "2.14.3",
        }
        if lvl == "ERROR":
            rec["error"] = {"type": rng.choice(["UpstreamTimeout", "ValidationError",
                                                "ConnectionReset", "QuotaExceeded"]),
                            "retryable": rng.random() < 0.7}
        buf.write(json.dumps(rec, separators=(",", ":")) + "\n")
        if buf.tell() > 2_000_000:
            total += write("logs", f"app-{part:02d}.ndjson", buf.getvalue())
            buf, part = io.StringIO(), part + 1
    if buf.tell():
        total += write("logs", f"app-{part:02d}.ndjson", buf.getvalue())
    return total


# -------------------------------------------------------------------- timeseries
ZONES = ["NL", "BE", "DE-LU", "FR"]


def price_rows(rng, hours):
    """Hourly rows shaped like a day-ahead price series, one block per zone."""
    import math
    out = []
    for zi, zone in enumerate(ZONES):
        base = [78.0, 92.0, 71.0, 58.0][zi]
        for h in range(hours):
            day = h / 24.0
            season = 22 * math.cos(2 * math.pi * (day - 15) / 365.25)
            weekday = (int(day) + 3) % 7
            week = -11 if weekday >= 5 else 0
            hod = h % 24
            daily = 26 * math.sin(2 * math.pi * (hod - 9) / 24) + \
                14 * math.sin(2 * math.pi * (hod - 18) / 12)
            solar = max(0.0, 3800 * math.sin(math.pi * max(0, (hod - 6)) / 13)) \
                * (0.55 + 0.45 * math.cos(2 * math.pi * (day - 172) / 365.25))
            wind = max(0.0, rng.gauss(2600, 1500))
            load = 11000 + 2600 * math.sin(2 * math.pi * (hod - 10) / 24) + \
                (-1400 if weekday >= 5 else 0) + rng.gauss(0, 320)
            price = base + season + week + daily - 0.0085 * solar - 0.0061 * wind \
                + rng.gauss(0, 9)
            if rng.random() < 0.004:
                price += rng.uniform(140, 900)
            out.append((zone, h, price, load, wind, solar))
    return out


def build_timeseries():
    rng = random.Random(4242)
    hours = 8760 * 5
    rows = price_rows(rng, hours)
    hdr = "timestamp_utc,bidding_zone,day_ahead_price_eur_mwh,load_mw,wind_generation_mw,solar_generation_mw\n"
    total, part, buf = 0, 0, io.StringIO()
    buf.write(hdr)
    epoch = 1546300800  # 2019-01-01T00:00:00Z
    for zone, h, price, load, wind, solar in rows:
        t = epoch + h * 3600
        days = t // 86400
        y = 1970 + days // 365
        buf.write(f"{y}-{1 + (days // 30) % 12:02d}-{1 + days % 28:02d}T"
                  f"{(t // 3600) % 24:02d}:00:00Z,{zone},{price:.2f},"
                  f"{load:.1f},{wind:.1f},{solar:.1f}\n")
        if buf.tell() > 3_000_000:
            total += write("timeseries", f"day_ahead_{part:02d}.csv", buf.getvalue())
            buf, part = io.StringIO(), part + 1
            buf.write(hdr)
        if total >= TARGET:
            break
    if buf.tell() > len(hdr):
        total += write("timeseries", f"day_ahead_{part:02d}.csv", buf.getvalue())
    return total


# -------------------------------------------------------------------- compressed
def build_compressed():
    """Data that has already been through an entropy coder once."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from PIL import Image

    total = 0
    # Parquet, zstd-compressed: exactly the file the user's own pipelines emit.
    csvs = sorted((DEST / "timeseries").glob("*.csv"))
    if csvs:
        import csv as csvmod
        cols = {k: [] for k in ["timestamp_utc", "bidding_zone", "day_ahead_price_eur_mwh",
                                "load_mw", "wind_generation_mw", "solar_generation_mw"]}
        for p in csvs:
            with p.open() as fh:
                for row in csvmod.DictReader(fh):
                    for k in cols:
                        cols[k].append(row[k])
        tbl = pa.table({
            "timestamp_utc": pa.array(cols["timestamp_utc"]),
            "bidding_zone": pa.array(cols["bidding_zone"]).dictionary_encode(),
            "day_ahead_price_eur_mwh": pa.array([float(v) for v in cols["day_ahead_price_eur_mwh"]]),
            "load_mw": pa.array([float(v) for v in cols["load_mw"]]),
            "wind_generation_mw": pa.array([float(v) for v in cols["wind_generation_mw"]]),
            "solar_generation_mw": pa.array([float(v) for v in cols["solar_generation_mw"]]),
        })
        buf = io.BytesIO()
        pq.write_table(tbl, buf, compression="zstd", compression_level=9)
        total += write("compressed", "day_ahead_prices.zstd.parquet", buf.getvalue())

    # JPEGs: pristine reference photographs put through a normal camera-grade encode.
    photos = ROOT / "testdata" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    for n in KODAK:
        if total >= TARGET:
            break
        src = photos / f"kodim{n:02d}.png"
        if not src.exists():
            try:
                src.write_bytes(get(KODAK_URL.format(n)))
            except RuntimeError as e:
                print("  skip kodim", n, e)
                continue
        im = Image.open(src).convert("RGB")
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
        total += write("compressed", f"photo_{n:02d}.jpg", buf.getvalue())
    return total


# ------------------------------------------------------------------------- prose
def build_prose():
    total = 0
    for name, url in GUTENBERG:
        if total >= TARGET:
            break
        try:
            total += write("prose", name, get(url))
        except RuntimeError as e:
            print("  skip", name, e)
    return total


# ------------------------------------------------------------- long-range corpus
def build_longrange():
    """A corpus with redundancy far beyond a default compression window.

    Eight near-identical revisions of the code corpus, roughly 8 MB apart. This
    is what a versioned dataset, a monorepo tarball or a backup set looks like,
    and it is the case zstd's --long flag exists for.
    """
    src = sorted((DEST / "code").glob("*"))
    if not src:
        return 0
    blob = b"".join(p.read_bytes() for p in src)[:TARGET]
    rng = random.Random(7)
    out = bytearray()
    for rev in range(8):
        b = bytearray(blob)
        # ~200 small edits per revision: enough that it is not a literal repeat,
        # little enough that a long-range matcher still finds nearly everything.
        for _ in range(200):
            i = rng.randrange(0, len(b) - 64)
            b[i:i + 12] = b"# rev%03d   " % rev
        out += b
    return write("longrange", "revisions.bin", bytes(out))


BUILDERS = {
    "web": build_web,
    "code": build_code,
    "logs": build_logs,
    "timeseries": build_timeseries,
    "compressed": build_compressed,
    "prose": build_prose,
    "longrange": build_longrange,
}
# compressed depends on timeseries, longrange on code
ORDER = ["web", "code", "logs", "timeseries", "compressed", "prose", "longrange"]


def main(which=None):
    DEST.mkdir(parents=True, exist_ok=True)
    names = which or ORDER
    manifest = {}
    for name in names:
        d = DEST / name
        if d.exists() and any(d.iterdir()):
            n = sum(1 for _ in d.iterdir())
            size = sum(p.stat().st_size for p in d.iterdir())
            print(f"have  {name:11s} {n:3d} files  {size/1e6:.2f} MB")
        else:
            print(f"build {name} ...")
            BUILDERS[name]()
            size = sum(p.stat().st_size for p in d.iterdir())
            print(f"      {name:11s} {sum(1 for _ in d.iterdir()):3d} files  {size/1e6:.2f} MB")
        files = sorted(d.iterdir())
        manifest[name] = dict(
            files=[f.name for f in files],
            bytes=sum(f.stat().st_size for f in files),
            sha256=hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()[:16],
        )
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print("\nwrote", DEST / "manifest.json")


if __name__ == "__main__":
    main(sys.argv[1:] or None)
