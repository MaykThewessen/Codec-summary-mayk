"""Round-trip a deliberately awkward table through every format and diff it.

Speed is the argument people have; correctness is the one that costs them a
week. This builds one small frame carrying every property a Dutch grid
timeseries actually has (tz-aware UTC and a market-local zone, nullable
integers, a bool with a gap, an ordered categorical, a named DatetimeIndex,
float32 that must stay 32-bit) and reports precisely what came back changed.

    python3 scripts/data_formats/measure_fidelity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from formats import BY_KEY, FORMATS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "testdata" / "data_formats" / "work"
DATA = ROOT / "data" / "data_formats"

N = 240

PROPS = [
    ("dtype", "Dtypes"),
    ("tz", "Timezone"),
    ("null", "Nulls"),
    ("categorical", "Categoricals"),
    ("index", "Index"),
    ("order", "Column order"),
]


def torture() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-03-30 22:00", periods=N, freq="h", tz="UTC",
                        name="utc_ts")
    df = pd.DataFrame({
        # the market-local view: crosses the CEST transition inside this range
        "local_ts": idx.tz_convert("Europe/Amsterdam"),
        "zone": pd.Categorical(rng.choice(["NL", "BE", "DE_LU"], N),
                               categories=["NL", "BE", "DE_LU"], ordered=True),
        "price_eur_mwh": np.round(rng.normal(80, 30, N), 2),
        "load_mw_f32": rng.normal(14_000, 900, N).astype(np.float32),
        "unit_id": pd.array(rng.integers(1, 500, N), dtype="Int32"),
        "curtailed": pd.array(rng.random(N) > 0.5, dtype="boolean"),
        "note": pd.array(rng.choice(["ok", "estimated", "revised"], N),
                         dtype="string"),
    }, index=idx)
    # holes in four different dtypes
    df.loc[df.index[3:7], "price_eur_mwh"] = np.nan
    df.loc[df.index[10:14], "unit_id"] = pd.NA
    df.loc[df.index[20:24], "curtailed"] = pd.NA
    df.loc[df.index[30:34], "note"] = pd.NA
    return df


def describe(df: pd.DataFrame) -> dict:
    return {
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "order": list(df.columns),
        "index_name": df.index.name,
        "index_dtype": str(df.index.dtype),
        "nulls": {c: int(df[c].isna().sum()) for c in df.columns},
    }


def compare(before: pd.DataFrame, after: pd.DataFrame, index_note: str = "") -> dict:
    """Grade each property good / partial / lost, with a concrete note."""
    b, a = describe(before), describe(after)
    res: dict[str, dict] = {}
    lost: list[str] = []

    # --- index -------------------------------------------------------------
    if index_note:
        res["index"] = dict(v="lost", why=index_note)
    elif a["index_name"] == b["index_name"] and "datetime" in a["index_dtype"]:
        res["index"] = dict(v="good", why="restored with its name and its dtype")
    elif b["index_name"] in a["order"]:
        res["index"] = dict(v="partial",
                            why="came back as an ordinary column: you have to know "
                                "to set it again, and to re-localize it first")
    else:
        res["index"] = dict(v="lost",
                            why=f"gone, replaced by a {a['index_dtype']} range")

    # --- column order ------------------------------------------------------
    common = [c for c in b["order"] if c in a["order"]]
    res["order"] = (dict(v="good", why="unchanged")
                    if [c for c in a["order"] if c in common] == common
                    else dict(v="lost", why="columns came back reordered"))

    # --- dtypes ------------------------------------------------------------
    changed = {c: (b["dtypes"][c], a["dtypes"].get(c, "missing"))
               for c in b["order"]
               if a["dtypes"].get(c, "missing") != b["dtypes"][c]}
    if not changed:
        res["dtype"] = dict(v="good", why="every column returned its own dtype")
    else:
        worst = ", ".join(f"{c}: {x} to {y}" for c, (x, y) in list(changed.items())[:3])
        res["dtype"] = dict(v="lost" if len(changed) > 2 else "partial",
                            why=f"{len(changed)} of {len(b['order'])} changed ({worst})")

    # --- timezone ----------------------------------------------------------
    # Three grades, and the middle one matters: an instant that survives with a
    # different zone attached is not the same column, it just prints the same.
    tz_cols = {c: b["dtypes"][c] for c in b["order"] if ", " in b["dtypes"][c]
               and b["dtypes"][c].startswith("datetime64")}
    tz_cols[b["index_name"]] = b["index_dtype"]
    got = {c: (a["dtypes"].get(c) or (a["index_dtype"] if c == a["index_name"] else "gone"))
           for c in tz_cols}
    same = [c for c in tz_cols if got[c] == tz_cols[c]]
    aware = [c for c in tz_cols if isinstance(got[c], str) and ", " in got[c]
             and got[c].startswith("datetime64")]
    if len(same) == len(tz_cols):
        res["tz"] = dict(v="good", why="every zone came back exactly as written")
    elif aware:
        moved = [c for c in tz_cols if c not in same]
        unparsed = [c for c in moved if not str(got[c]).startswith("datetime64")]
        extra = (" The Europe/Amsterdam column crosses the CEST transition, so its offsets are "
                 "mixed, and pandas will not parse a mixed-offset column back into one datetime "
                 "column at all: it stays a string unless you handle it yourself."
                 if unparsed else
                 " The zone name is nowhere in the file, so UTC is the best a reader can do.")
        res["tz"] = dict(
            v="partial",
            why="the instant survives but the zone does not: " +
                ", ".join(f"{c} {tz_cols[c]} to {got[c]}" for c in moved[:2]) + "." + extra)
    else:
        res["tz"] = dict(
            v="lost",
            why="aware timestamps came back as " +
                ", ".join(sorted({str(got[c]) for c in tz_cols})) +
                ": nothing in the file records which zone it was")

    # --- nulls -------------------------------------------------------------
    nb = {c: v for c, v in b["nulls"].items()}
    na = {c: a["nulls"].get(c, -1) for c in nb}
    if na == nb:
        gaps_typed = all("Int" in a["dtypes"].get(c, "") or "bool" in a["dtypes"].get(c, "")
                         or True for c in nb)
        int_null = a["dtypes"].get("unit_id", "")
        bool_null = a["dtypes"].get("curtailed", "")
        if int_null.startswith("Int") and bool_null == "boolean":
            res["null"] = dict(v="good", why="count and dtype both preserved")
        else:
            res["null"] = dict(
                v="partial",
                why=f"gaps kept, but the nullable integer became {int_null} "
                    f"and the nullable bool {bool_null}")
        del gaps_typed
    else:
        diff = [c for c in nb if na[c] != nb[c]]
        res["null"] = dict(v="lost",
                           why=f"null count changed in {', '.join(diff[:3])}")

    # --- categorical -------------------------------------------------------
    zone_after = a["dtypes"].get("zone", "missing")
    if zone_after.startswith("category"):
        cat_ok = isinstance(after["zone"].dtype, pd.CategoricalDtype) and \
            after["zone"].dtype.ordered == before["zone"].dtype.ordered
        res["categorical"] = (dict(v="good", why="dictionary and ordering both kept")
                              if cat_ok else
                              dict(v="partial", why="category kept, ordered flag lost"))
    else:
        res["categorical"] = dict(v="lost",
                                  why=f"returned as {zone_after}: the dictionary and "
                                      f"the ordering are gone")

    for k, v in res.items():
        if v["v"] != "good":
            lost.append(k)
    return dict(props=res, n_lost=len(lost))


INDEX_NOTE: dict[str, str] = {
    "json": "records orient has no place to put an index, so it is reset to a "
            "column before writing",
    "duckdb": "a table has no index in the pandas sense: registering the frame "
              "drops it, so it is reset to a column first",
}


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    df = torture()
    out = []
    for fmt in FORMATS:
        src = BY_KEY[fmt.alias_of] if fmt.alias_of else fmt
        p = WORK / f"fidelity_{src.key}{src.ext}"
        rec = dict(fmt=fmt.key, label=fmt.label, family=fmt.family)
        index_note = ""
        try:
            if fmt.alias_of:
                # the file already exists from its owner; only the reader differs
                index_note = INDEX_NOTE.get(fmt.alias_of, "")
            else:
                # ask the format to keep the index using its own idiomatic call.
                # Where the writer refuses, fall back to reset_index and record
                # that the caller had to do it: that is the loss.
                try:
                    fmt.write(df, p, index=True)
                except Exception as exc:  # noqa: BLE001
                    index_note = (f"the writer refuses a non-default index "
                                  f"({type(exc).__name__}), so it has to be reset "
                                  f"to a column before writing")
                    fmt.write(df.reset_index(), p, index=False)
                if fmt.key in ("json", "duckdb"):
                    index_note = INDEX_NOTE[fmt.key]
                    fmt.write(df.reset_index(), p, index=False)
            INDEX_NOTE.setdefault(fmt.key, index_note)
            back = fmt.read(p, ts_cols=["utc_ts", "local_ts"])
            rec.update(compare(df, back, index_note), ok=True)
            print(f"{fmt.key:<16} lost {rec['n_lost']}/6  " +
                  " ".join(f"{k}:{v['v'][0]}" for k, v in rec["props"].items()))
        except Exception as exc:  # noqa: BLE001
            rec.update(ok=False, reason=f"{type(exc).__name__}: {exc}")
            print(f"{fmt.key:<16} FAILED {exc}")
        out.append(rec)

    payload = dict(props=[dict(key=k, label=v) for k, v in PROPS],
                   source=describe(df), rows=N, results=out)
    (DATA / "fidelity.json").write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {DATA / 'fidelity.json'}")


if __name__ == "__main__":
    main()
