"""One cold-cache read per format, to show what the warm numbers hide.

Everything else on this page is measured with the file already in the page
cache, which is the normal case on a workstation that has just written it. A
cold read is the other normal case: the file came off a network share or the
machine has been doing something else. Then the file size stops being a storage
question and becomes the read time.

Requires root to drop the page cache; if it cannot, it says so and the page
reports the measurement as unavailable rather than guessing.

    python3 scripts/data_formats/measure_cold.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "testdata" / "data_formats" / "work"
DATA = ROOT / "data" / "data_formats"

CORPUS, SCALE = "powerflow", "large"
FMTS = [("csv", ".csv"), ("csv_gz", ".csv.gz"), ("feather", ".arrow"),
        ("feather_lz4", ".arrow"), ("feather_zstd", ".arrow"),
        ("parquet_none", ".parquet"), ("parquet_snappy", ".parquet"),
        ("parquet_zstd", ".parquet"), ("parquet_gzip", ".parquet"),
        ("duckdb", ".duckdb")]

CHILD = r"""
import json, sys, time
import pandas as pd, duckdb
fmt, path = sys.argv[1], sys.argv[2]
t0 = time.perf_counter()
if fmt.startswith("csv"):
    df = pd.read_csv(path, parse_dates=["snapshot"])
elif fmt.startswith("feather"):
    df = pd.read_feather(path)
elif fmt.startswith("parquet"):
    df = pd.read_parquet(path)
else:
    con = duckdb.connect(path); con.execute("SET TimeZone='UTC'")
    df = con.execute("SELECT * FROM t").df(); con.close()
print(json.dumps(dict(seconds=round(time.perf_counter() - t0, 4), rows=len(df))))
"""


def drop_caches() -> bool:
    try:
        subprocess.run(["sync"], check=True)
        Path("/proc/sys/vm/drop_caches").write_text("3\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    child = WORK / "_cold_child.py"
    child.write_text(CHILD)
    if not drop_caches():
        (DATA / "cold.json").write_text(json.dumps(
            dict(available=False,
                 reason="the page cache could not be dropped in this container, "
                        "so no cold-read figure is reported"), indent=1))
        print("cannot drop caches: reporting the measurement as unavailable")
        return
    out = []
    for fmt, ext in FMTS:
        p = WORK / f"{CORPUS}_{SCALE}_{fmt}{ext}"
        if not p.exists():
            continue
        drop_caches()
        res = subprocess.run([sys.executable, str(child), fmt, str(p)],
                             capture_output=True, text=True)
        if res.returncode:
            print(f"{fmt:<16} FAILED {res.stderr.strip().splitlines()[-1][:120]}")
            continue
        rec = json.loads(res.stdout.strip().splitlines()[-1])
        rec.update(fmt=fmt, size_bytes=p.stat().st_size)
        out.append(rec)
        print(f"{fmt:<16} {rec['seconds']:>8.3f} s cold   {rec['size_bytes'] / 1e6:>8.1f} MB")
    (DATA / "cold.json").write_text(json.dumps(
        dict(available=True, corpus=CORPUS, scale=SCALE,
             method="sync + drop_caches=3 before every read, one read each, "
                    "in a fresh process",
             runs=out), indent=1))
    print(f"\nwrote {DATA / 'cold.json'}")


if __name__ == "__main__":
    main()
