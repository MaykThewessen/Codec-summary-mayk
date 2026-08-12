"""Time write, full read, column projection and filtered query for every format.

Four operations, four corpora, two scales, thirteen formats. Each timing is the
median of several repeats; the number of repeats actually taken is recorded per
cell, because expensive combinations stop early against a wall-clock budget.

The machine is a shared container with other work running on it, so absolute
milliseconds are not portable. Ratios between formats measured back to back are.

    python3 scripts/data_formats/measure_bench.py [corpus ...]
"""

from __future__ import annotations

import gc
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parent))
from formats import (BY_KEY, FORMATS, JSON_MAX_CELLS, SUBSET, TS_COLS,  # noqa: E402
                     XLSX_MAX_ROWS, predicates)
import formats as F  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata" / "data_formats"
WORK = TESTDATA / "work"
DATA = ROOT / "data" / "data_formats"

REPEATS = {"small": 7, "large": 4}
BUDGET_S = 40.0      # stop repeating an operation once it has cost this much
MIN_REPEATS = 2
CORPORA = ["prices", "powerflow", "weather", "assets"]
SCALES = ["small", "large"]


def timed(fn, repeats: int) -> tuple[float | None, list[float], int]:
    """Median of up to `repeats` calls, stopping early on the time budget."""
    ts: list[float] = []
    for _ in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        res = fn()
        dt = time.perf_counter() - t0
        n_rows = len(res) if res is not None and hasattr(res, "__len__") else 0
        del res
        ts.append(dt)
        if sum(ts) > BUDGET_S and len(ts) >= MIN_REPEATS:
            break
    return round(statistics.median(ts), 5), [round(t, 5) for t in ts], n_rows


def skip_reason(fmt, rows: int, cells: int) -> str | None:
    if fmt.key == "xlsx" and rows > XLSX_MAX_ROWS:
        return (f"{rows} rows will not fit: a worksheet holds at most "
                f"{XLSX_MAX_ROWS}")
    if fmt.key in ("json", "xlsx") and cells > JSON_MAX_CELLS:
        return (f"skipped: {cells} cells would take longer to encode than the "
                f"rest of the harness and adds nothing the small scale does not show")
    return None


def run_one(corpus: str, scale: str, df: pd.DataFrame) -> list[dict]:
    rows, ncols = len(df), len(df.columns)
    cells = rows * ncols
    pred = predicates(corpus)
    subset = SUBSET[corpus]
    ts_cols = TS_COLS[corpus]
    kw = dict(ts_cols=ts_cols)
    reps = REPEATS[scale]
    out = []

    for fmt in FORMATS:
        rec = dict(corpus=corpus, scale=scale, rows=rows, cols=ncols,
                   fmt=fmt.key, label=fmt.label, family=fmt.family,
                   pushdown=fmt.pushdown, note=fmt.note,
                   subset_cols=subset, pred=pred["desc"])
        reason = skip_reason(fmt, rows, cells)
        if reason:
            rec.update(ok=False, reason=reason)
            out.append(rec)
            print(f"  {fmt.key:<16} skipped: {reason[:60]}")
            continue

        src = BY_KEY[fmt.alias_of] if fmt.alias_of else fmt
        path = WORK / f"{corpus}_{scale}_{src.key}{src.ext}"
        try:
            if fmt.alias_of:
                rec["write_s"] = None
                rec["write_n"] = 0
                rec["shares_file_with"] = fmt.alias_of
            else:
                w, wt, _ = timed(lambda: fmt.write(df, path), min(reps, 4))
                rec["write_s"], rec["write_n"] = w, len(wt)
            rec["size_bytes"] = path.stat().st_size

            # one untimed warm-up so the timing measures decode, not first-touch
            fmt.read(path, **kw)
            r, rt, n = timed(lambda: fmt.read(path, **kw), reps)
            rec["read_s"], rec["read_n"], rec["read_rows"] = r, len(rt), n

            if fmt.read_cols:
                c, ct, _ = timed(lambda: fmt.read_cols(path, cols=subset, **kw), reps)
                rec["cols_s"], rec["cols_n"] = c, len(ct)
            else:
                rec["cols_s"], rec["cols_note"] = None, "no column projection possible"

            fq, ft, fn = timed(lambda: fmt.read_filter(path, pred=pred, **kw), reps)
            rec["filter_s"], rec["filter_n"], rec["filter_rows"] = fq, len(ft), fn

            if fmt.key == "xlsx":
                a, at, _ = timed(lambda: F._xlsx_read_calamine(path), reps)
                rec["read_alt_s"], rec["read_alt_engine"] = a, "calamine"
            rec["ok"] = True
            print(f"  {fmt.key:<16} {rec['size_bytes'] / 1e6:>8.2f} MB  "
                  f"w {str(rec['write_s']):>8}  r {rec['read_s']:>8.4f}  "
                  f"cols {str(rec['cols_s']):>8}  filt {rec['filter_s']:>8.4f}")
        except Exception as exc:  # noqa: BLE001
            rec.update(ok=False, reason=f"{type(exc).__name__}: {exc}")
            print(f"  {fmt.key:<16} FAILED {exc}")
        out.append(rec)
    return out


def engine_comparison(corpus: str, scale: str) -> list[dict]:
    """The same file read by pandas, polars and duckdb.

    Format and engine are separate choices and get confused constantly. This
    isolates the engine on two files: the CSV everyone starts with and the
    parquet they should end with.
    """
    import polars as pl
    rows = []
    csv_p = WORK / f"{corpus}_{scale}_csv.csv"
    pq_p = WORK / f"{corpus}_{scale}_parquet_zstd.parquet"
    ts = TS_COLS[corpus]
    cases = [
        ("csv", "pandas", lambda: pd.read_csv(csv_p, parse_dates=ts)),
        ("csv", "polars", lambda: pl.read_csv(csv_p, try_parse_dates=True)),
        ("csv", "duckdb", lambda: duckdb.sql(f"SELECT * FROM read_csv('{csv_p}')").df()),
        ("parquet_zstd", "pandas", lambda: pd.read_parquet(pq_p)),
        ("parquet_zstd", "polars", lambda: pl.read_parquet(pq_p)),
        ("parquet_zstd", "duckdb",
         lambda: duckdb.sql(f"SELECT * FROM read_parquet('{pq_p}')").df()),
    ]
    for fmt, engine, fn in cases:
        if not (csv_p if fmt == "csv" else pq_p).exists():
            continue
        fn()
        t, tl, _ = timed(fn, REPEATS[scale])
        rows.append(dict(corpus=corpus, scale=scale, fmt=fmt, engine=engine,
                         read_s=t, n=len(tl)))
        print(f"  engine {fmt:<13} {engine:<8} {t:.4f} s")
    return rows


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or CORPORA
    runs, engines = [], []
    for corpus in wanted:
        for scale in SCALES:
            src = TESTDATA / f"{corpus}_{scale}.arrow"
            df = pd.read_feather(src)
            print(f"\n{corpus} / {scale}: {len(df)} rows x {len(df.columns)} cols")
            runs += run_one(corpus, scale, df)
            engines += engine_comparison(corpus, scale)
            del df
            gc.collect()

    env = dict(
        python=platform.python_version(),
        pandas=pd.__version__, pyarrow=pa.__version__, duckdb=duckdb.__version__,
        numpy=np.__version__, platform=platform.platform(),
        repeats=REPEATS, budget_s=BUDGET_S,
        cache="warm: every timed read follows an untimed read of the same file, "
              "so these are decode costs rather than disk costs",
    )
    payload = dict(env=env, runs=runs, engines=engines)
    out = DATA / "bench.json"
    prev = json.loads(out.read_text()) if out.exists() else None
    if prev and wanted != CORPORA:
        keep = [r for r in prev["runs"] if r["corpus"] not in wanted]
        keepe = [r for r in prev["engines"] if r["corpus"] not in wanted]
        payload["runs"] = keep + runs
        payload["engines"] = keepe + engines
    out.write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {out}  ({len(payload['runs'])} rows)")


if __name__ == "__main__":
    main()
