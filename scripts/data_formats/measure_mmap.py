"""Does "Feather is RAM saved to disc" actually hold? Measure it.

The claim is about memory mapping: an uncompressed Arrow IPC file has the same
byte layout on disk as Arrow has in memory, so the kernel can map it and nothing
is decoded or copied. That is true, and it has three conditions attached
(uncompressed, stay in Arrow, no nulls in the column) which decide whether you
get it or not.

Each case runs in a fresh subprocess so the resident set size is meaningful,
and reports wall time plus the RSS the process actually grew by.

    python3 scripts/data_formats/measure_mmap.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "testdata" / "data_formats" / "work"
DATA = ROOT / "data" / "data_formats"

CORPUS = "powerflow_large"
COL = "p_mw_MVL_KIJ_380"

CASES = [
    ("feather_copy", "feather",
     "Feather, read into pandas", "pd.read_feather(p)"),
    ("feather_mmap_open", "feather",
     "Feather mapped, table opened", "ipc.open_file(pa.memory_map(p)).read_all()"),
    ("feather_mmap_scan", "feather",
     "Feather mapped, mean of one column", "pc.mean(mapped[col])"),
    ("feather_mmap_zerocopy", "feather",
     "Feather mapped, numpy view of a column",
     "mapped[col].combine_chunks().to_numpy(zero_copy_only=True)"),
    ("feather_mmap_topandas", "feather",
     "Feather mapped, then to pandas", "mapped.to_pandas()"),
    ("feather_zstd_mmap_open", "feather_zstd",
     "Feather zstd mapped, table opened", "same call, compressed file"),
    ("parquet_copy", "parquet_zstd",
     "Parquet zstd, read into pandas", "pd.read_parquet(p)"),
    ("parquet_mmap_open", "parquet_zstd",
     "Parquet zstd, mapped source", "pq.read_table(pa.memory_map(p))"),
]

CHILD = r"""
import json, sys, time
import pyarrow as pa, pyarrow.compute as pc, pyarrow.ipc as ipc, pyarrow.parquet as pq
import pandas as pd

case, path, col = sys.argv[1], sys.argv[2], sys.argv[3]

def rss():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0

def hwm():
    for line in open("/proc/self/status"):
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) * 1024
    return 0

base = rss()
t0 = time.perf_counter()
keep = None
if case == "feather_copy":
    keep = pd.read_feather(path)
elif case == "feather_mmap_open" or case == "feather_zstd_mmap_open":
    keep = ipc.open_file(pa.memory_map(path)).read_all()
elif case == "feather_mmap_scan":
    t = ipc.open_file(pa.memory_map(path)).read_all()
    keep = pc.mean(t[col]).as_py()
elif case == "feather_mmap_zerocopy":
    t = ipc.open_file(pa.memory_map(path)).read_all()
    keep = t[col].combine_chunks().to_numpy(zero_copy_only=True)
elif case == "feather_mmap_topandas":
    t = ipc.open_file(pa.memory_map(path)).read_all()
    keep = t.to_pandas()
elif case == "parquet_copy":
    keep = pd.read_parquet(path)
elif case == "parquet_mmap_open":
    keep = pq.read_table(pa.memory_map(path))
dt = time.perf_counter() - t0
print(json.dumps(dict(case=case, seconds=round(dt, 5),
                      rss_delta=rss() - base, hwm=hwm(), base=base,
                      kind=type(keep).__name__)))
"""


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    child = WORK / "_mmap_child.py"
    child.write_text(CHILD)
    out = []
    for case, fmt, label, call in CASES:
        ext = ".parquet" if fmt.startswith("parquet") else ".arrow"
        path = WORK / f"{CORPUS}_{fmt}{ext}"
        rec = dict(case=case, fmt=fmt, label=label, call=call,
                   file_bytes=path.stat().st_size if path.exists() else None)
        if not path.exists():
            rec.update(ok=False, reason="file not built yet, run measure_bench first")
            out.append(rec)
            continue
        try:
            # run twice, keep the second: the first pays for the page cache
            for _ in range(2):
                res = subprocess.run([sys.executable, str(child), case, str(path), COL],
                                     capture_output=True, text=True, check=True)
            rec.update(json.loads(res.stdout.strip().splitlines()[-1]), ok=True)
            print(f"{case:<26} {rec['seconds']:>8.4f} s   RSS +{rec['rss_delta'] / 1e6:>8.1f} MB")
        except subprocess.CalledProcessError as exc:
            rec.update(ok=False, reason=exc.stderr.strip().splitlines()[-1][:200])
            print(f"{case:<26} FAILED {rec['reason']}")
        out.append(rec)
    (DATA / "mmap.json").write_text(json.dumps(dict(corpus=CORPUS, column=COL,
                                                    cases=out), indent=1))
    print(f"\nwrote {DATA / 'mmap.json'}")


if __name__ == "__main__":
    main()
