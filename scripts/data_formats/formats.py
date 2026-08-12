"""The format registry: how each candidate is written, read, projected, filtered.

One module so the benchmark, the fidelity check and the cheat sheet on the page
all describe the same calls. Every reader returns a pandas DataFrame, so the
timings include whatever conversion that format needs to get there: that
conversion is part of the cost of using the format, not an artefact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

# xlsx cannot hold more rows than this. It is a hard limit of the sheet format,
# not a library restriction.
XLSX_MAX_ROWS = 1_048_576
# Above this many cells a JSON or xlsx run costs more than the whole rest of the
# harness and tells us nothing new, so it is skipped and reported as skipped.
JSON_MAX_CELLS = 15_000_000


def _duck(path: str | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(path) if path else duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    return con


class Fmt:
    """One storage format, plus the four operations we time on it."""

    def __init__(self, key: str, label: str, family: str, ext: str,
                 write: Callable, read: Callable,
                 read_cols: Callable | None, read_filter: Callable | None,
                 pushdown: bool, mmap: bool, note: str = "",
                 alias_of: str | None = None) -> None:
        self.key = key
        self.label = label
        self.family = family
        self.ext = ext
        self.write = write
        self.read = read
        self.read_cols = read_cols
        self.read_filter = read_filter
        self.pushdown = pushdown
        self.mmap = mmap
        self.note = note
        self.alias_of = alias_of


# ---------------------------------------------------------------- csv / json --
def _csv_write(df: pd.DataFrame, p: Path, index: bool = False, **_) -> None:
    df.to_csv(p, index=index)


def _csv_read(p: Path, ts_cols: list[str], **_) -> pd.DataFrame:
    # Without parse_dates the timestamps come back as strings, which is not the
    # same table. Parsing is the honest cost of a CSV read.
    return pd.read_csv(p, parse_dates=ts_cols)


def _csv_cols(p: Path, cols: list[str], ts_cols: list[str], **_) -> pd.DataFrame:
    return pd.read_csv(p, usecols=cols, parse_dates=[c for c in ts_cols if c in cols])


def _csv_filter(p: Path, pred, ts_cols: list[str], **_) -> pd.DataFrame:
    return pred["pandas"](pd.read_csv(p, parse_dates=ts_cols))


def _csvgz_write(df: pd.DataFrame, p: Path, index: bool = False, **_) -> None:
    # level 6, not gzip's default 9: 9 triples the write time for a few percent
    df.to_csv(p, index=index, compression={"method": "gzip", "compresslevel": 6})


def _json_write(df: pd.DataFrame, p: Path, **_) -> None:
    df.to_json(p, orient="records", date_format="iso")


def _json_read(p: Path, ts_cols: list[str] | None = None, **_) -> pd.DataFrame:
    df = pd.read_json(p, orient="records", convert_dates=False)
    # Same rule as CSV: a read that leaves the timestamps as strings has not
    # reproduced the table, so the parse counts against the format.
    for c in ts_cols or []:
        df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
    return df


def _json_filter(p: Path, pred, ts_cols=None, **_) -> pd.DataFrame:
    return pred["pandas"](_json_read(p, ts_cols=ts_cols))


# ---------------------------------------------------------------------- xlsx --
def _xlsx_write(df: pd.DataFrame, p: Path, index: bool = False, **_) -> None:
    # xlsxwriter has no tz-aware datetime support at all, so the column has to be
    # stripped of its zone before it will write. That is itself a finding.
    out = df.copy()
    for c in out.columns:
        if isinstance(out[c].dtype, pd.DatetimeTZDtype):
            out[c] = out[c].dt.tz_convert("UTC").dt.tz_localize(None)
    out.to_excel(p, index=index, engine="xlsxwriter")


def _xlsx_read(p: Path, **_) -> pd.DataFrame:
    return pd.read_excel(p, engine="openpyxl")


def _xlsx_read_calamine(p: Path, **_) -> pd.DataFrame:
    return pd.read_excel(p, engine="calamine")


def _xlsx_cols(p: Path, cols: list[str], **_) -> pd.DataFrame:
    return pd.read_excel(p, engine="openpyxl", usecols=cols)


def _xlsx_filter(p: Path, pred, **_) -> pd.DataFrame:
    return pred["pandas"](_xlsx_read(p))


# ------------------------------------------------------------------- feather --
def _feather_write(comp: str) -> Callable:
    def w(df: pd.DataFrame, p: Path, index: bool = False, **_) -> None:
        # to_feather refuses a non-default index outright: Arrow IPC has no
        # concept of one. The caller has to reset it, which is a real loss.
        df.to_feather(p, compression=comp)
    return w


def _feather_read(p: Path, **_) -> pd.DataFrame:
    return pd.read_feather(p)


def _feather_cols(p: Path, cols: list[str], **_) -> pd.DataFrame:
    return pd.read_feather(p, columns=cols)


def _feather_filter(p: Path, pred, **_) -> pd.DataFrame:
    # Arrow IPC has no predicate pushdown and no statistics: the whole file has
    # to be materialised before a single row can be discarded.
    t = pa.ipc.open_file(str(p)).read_all()
    return t.filter(pred["arrow"]).to_pandas()


# ------------------------------------------------------------------- parquet --
def _parquet_write(comp: str | None) -> Callable:
    def w(df: pd.DataFrame, p: Path, index: bool = False, **_) -> None:
        df.to_parquet(p, engine="pyarrow", compression=comp, index=index)
    return w


def _parquet_read(p: Path, **_) -> pd.DataFrame:
    return pd.read_parquet(p, engine="pyarrow")


def _parquet_cols(p: Path, cols: list[str], **_) -> pd.DataFrame:
    return pd.read_parquet(p, engine="pyarrow", columns=cols)


def _parquet_filter(p: Path, pred, **_) -> pd.DataFrame:
    # filters= is a real pushdown: row groups whose statistics cannot match are
    # never decompressed.
    return pq.read_table(p, filters=pred["arrow"]).to_pandas()


# -------------------------------------------------------------------- duckdb --
def _duckdb_write(df: pd.DataFrame, p: Path, **_) -> None:
    if Path(p).exists():
        Path(p).unlink()
    con = _duck(str(p))
    con.register("src", df)
    con.execute("CREATE TABLE t AS SELECT * FROM src")
    con.close()


def _duckdb_read(p: Path, **_) -> pd.DataFrame:
    con = _duck(str(p))
    out = con.execute("SELECT * FROM t").df()
    con.close()
    return out


def _duckdb_cols(p: Path, cols: list[str], **_) -> pd.DataFrame:
    con = _duck(str(p))
    out = con.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM t').df()
    con.close()
    return out


def _duckdb_filter(p: Path, pred, **_) -> pd.DataFrame:
    con = _duck(str(p))
    out = con.execute(f"SELECT * FROM t WHERE {pred['sql']}").df()
    con.close()
    return out


def _pqduck_read(p: Path, **_) -> pd.DataFrame:
    con = _duck()
    out = con.execute("SELECT * FROM read_parquet(?)", [str(p)]).df()
    con.close()
    return out


def _pqduck_cols(p: Path, cols: list[str], **_) -> pd.DataFrame:
    con = _duck()
    sel = ", ".join(chr(34) + c + chr(34) for c in cols)
    out = con.execute(f"SELECT {sel} FROM read_parquet(?)", [str(p)]).df()
    con.close()
    return out


def _pqduck_filter(p: Path, pred, **_) -> pd.DataFrame:
    con = _duck()
    out = con.execute(
        f"SELECT * FROM read_parquet('{p}') WHERE {pred['sql']}").df()
    con.close()
    return out


FORMATS: list[Fmt] = [
    Fmt("csv", "CSV", "text", ".csv", _csv_write, _csv_read, _csv_cols, _csv_filter,
        False, False, "usecols still parses every byte of every row"),
    Fmt("csv_gz", "CSV .gz", "text", ".csv.gz", _csvgz_write, _csv_read, _csv_cols,
        _csv_filter, False, False, "gzip level 6"),
    Fmt("json", "JSON", "text", ".json", _json_write, _json_read, None, _json_filter,
        False, False, "records orient, ISO dates, no column projection possible"),
    Fmt("xlsx", "Excel xlsx", "text", ".xlsx", _xlsx_write, _xlsx_read, _xlsx_cols,
        _xlsx_filter, False, False,
        f"hard limit of {XLSX_MAX_ROWS} rows per sheet; tz dropped on write"),
    Fmt("feather", "Feather (uncompressed)", "arrow", ".arrow", _feather_write("uncompressed"),
        _feather_read, _feather_cols, _feather_filter, False, True,
        "the only format here that can be memory-mapped without decoding"),
    Fmt("feather_lz4", "Feather lz4", "arrow", ".arrow", _feather_write("lz4"),
        _feather_read, _feather_cols, _feather_filter, False, False, ""),
    Fmt("feather_zstd", "Feather zstd", "arrow", ".arrow", _feather_write("zstd"),
        _feather_read, _feather_cols, _feather_filter, False, False, ""),
    Fmt("parquet_none", "Parquet (uncompressed)", "parquet", ".parquet",
        _parquet_write(None), _parquet_read, _parquet_cols, _parquet_filter,
        True, False, ""),
    Fmt("parquet_snappy", "Parquet snappy", "parquet", ".parquet",
        _parquet_write("snappy"), _parquet_read, _parquet_cols, _parquet_filter,
        True, False, "pyarrow default"),
    Fmt("parquet_zstd", "Parquet zstd", "parquet", ".parquet",
        _parquet_write("zstd"), _parquet_read, _parquet_cols, _parquet_filter,
        True, False, ""),
    Fmt("parquet_gzip", "Parquet gzip", "parquet", ".parquet",
        _parquet_write("gzip"), _parquet_read, _parquet_cols, _parquet_filter,
        True, False, ""),
    Fmt("duckdb", "DuckDB table", "duckdb", ".duckdb", _duckdb_write, _duckdb_read,
        _duckdb_cols, _duckdb_filter, True, False, "native storage, one file"),
    Fmt("parquet_duckdb", "Parquet read by DuckDB", "duckdb", ".parquet",
        None, _pqduck_read, _pqduck_cols, _pqduck_filter, True, False,
        "no import step: queries the parquet_zstd file in place",
        alias_of="parquet_zstd"),
]

BY_KEY = {f.key: f for f in FORMATS}


# ---------------------------------------------------------------- predicates --
def _utc(s: pd.Series) -> pd.Series:
    """Re-localize a timestamp column that lost its zone on the way to disk.

    CSV, JSON and xlsx all hand back either strings or naive datetimes, and in
    pandas 3 a naive-versus-aware comparison raises. Every predicate below runs
    through this, which is exactly the tax those formats impose on real code.
    """
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        return s
    return pd.to_datetime(s, utc=True, format="mixed")


def predicates(corpus: str) -> dict:
    """The interactive query per corpus, expressed once per engine.

    Every engine must express the same predicate, or the comparison is between
    questions rather than between formats.
    """
    f = ds.field
    if corpus == "prices":
        lo = pd.Timestamp("2023-01-01", tz="UTC")
        hi = pd.Timestamp("2024-01-01", tz="UTC")
        return dict(
            desc="zone NL, calendar year 2023",
            sql="zone = 'NL' AND timestamp >= TIMESTAMPTZ '2023-01-01 00:00:00+00' "
                "AND timestamp < TIMESTAMPTZ '2024-01-01 00:00:00+00'",
            arrow=(f("zone") == "NL") & (f("timestamp") >= lo) & (f("timestamp") < hi),
            pandas=lambda d: d[(d["zone"] == "NL") & (_utc(d["timestamp"]) >= lo)
                               & (_utc(d["timestamp"]) < hi)],
        )
    if corpus == "powerflow":
        lo = pd.Timestamp("2021-02-01", tz="UTC")
        hi = pd.Timestamp("2021-03-01", tz="UTC")
        return dict(
            desc="snapshots in February 2021",
            sql="snapshot >= TIMESTAMPTZ '2021-02-01 00:00:00+00' "
                "AND snapshot < TIMESTAMPTZ '2021-03-01 00:00:00+00'",
            arrow=(f("snapshot") >= lo) & (f("snapshot") < hi),
            pandas=lambda d: d[(_utc(d["snapshot"]) >= lo) & (_utc(d["snapshot"]) < hi)],
        )
    if corpus == "weather":
        return dict(
            desc="station 260 De Bilt, above 20 C",
            sql="station_id = 260 AND temp_c > 20",
            arrow=(f("station_id") == 260) & (f("temp_c") > 20),
            pandas=lambda d: d[(d["station_id"] == 260) & (d["temp_c"] > 20)],
        )
    return dict(
        desc="netbeheerder Liander, above 100 kW",
        sql="netbeheerder = 'Liander' AND capacity_kw > 100",
        arrow=(f("netbeheerder") == "Liander") & (f("capacity_kw") > 100),
        pandas=lambda d: d[(d["netbeheerder"] == "Liander") & (d["capacity_kw"] > 100)],
    )


SUBSET = {
    # three columns out of forty-one: the whole argument for columnar storage
    "powerflow": ["snapshot", "p_mw_MVL_KIJ_380", "loading_pct_MVL_KIJ_380"],
    "prices": ["timestamp", "price_eur_mwh"],
    "weather": ["timestamp", "station_id", "temp_c"],
    "assets": ["gemeente", "netbeheerder", "capacity_kw"],
}

TS_COLS = {
    "prices": ["timestamp"],
    "powerflow": ["snapshot"],
    "weather": ["timestamp"],
    "assets": ["last_reading_at"],
}
