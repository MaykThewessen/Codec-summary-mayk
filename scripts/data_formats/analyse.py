"""Derive the quantities the page argues from, and print them for inspection.

Nothing here re-times anything: it reads the measurement files and computes the
comparisons, so a re-run of the sweep changes the derived numbers automatically.

    python3 scripts/data_formats/analyse.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "data_formats"

CORPORA = ["powerflow", "prices", "weather", "assets"]
SCALES = ["small", "large"]


def load() -> dict:
    b = json.loads((DATA / "bench.json").read_text())
    return dict(
        env=b["env"], runs=b["runs"], engines=b["engines"],
        corpora=json.loads((DATA / "corpora.json").read_text()),
        fidelity=json.loads((DATA / "fidelity.json").read_text()),
        mmap=json.loads((DATA / "mmap.json").read_text()),
        cold=json.loads((DATA / "cold.json").read_text())
        if (DATA / "cold.json").exists() else dict(available=False, reason="not run"),
    )


def index(runs: list[dict]) -> dict:
    return {(r["corpus"], r["scale"], r["fmt"]): r for r in runs}


def pareto(runs: list[dict], corpus: str, scale: str) -> list[str]:
    """Formats nothing else beats on both file size and full read time."""
    rows = [r for r in runs if r["corpus"] == corpus and r["scale"] == scale
            and r.get("ok") and r.get("read_s") and r.get("size_bytes")]
    rows.sort(key=lambda r: r["size_bytes"])
    front, best = [], float("inf")
    for r in rows:
        if r["read_s"] < best:
            front.append(r["fmt"])
            best = r["read_s"]
    return front


def main() -> None:
    d = load()
    runs, idx = d["runs"], index(d["runs"])
    out: dict = dict(pareto={}, projection={}, compression={}, totals={})

    for c in CORPORA:
        for s in SCALES:
            key = f"{c}|{s}"
            out["pareto"][key] = pareto(runs, c, s)
            proj = {}
            for r in runs:
                if r["corpus"] == c and r["scale"] == s and r.get("ok") and r.get("cols_s"):
                    proj[r["fmt"]] = round(r["read_s"] / r["cols_s"], 2)
            out["projection"][key] = proj

    # file size as a share of the same table in memory
    mem = {(m["corpus"], m["scale"]): m["mem_bytes"] for m in d["corpora"]}
    for r in runs:
        if r.get("ok"):
            m = mem.get((r["corpus"], r["scale"]))
            if m:
                out["compression"].setdefault(f"{r['corpus']}|{r['scale']}", {})[r["fmt"]] = \
                    round(r["size_bytes"] / m, 4)

    timings = sum(
        (r.get("write_n") or 0) + (r.get("read_n") or 0) + (r.get("cols_n") or 0)
        + (r.get("filter_n") or 0) for r in runs if r.get("ok"))
    timings += len(d["engines"]) * 3
    out["totals"] = dict(
        formats=len({r["fmt"] for r in runs}),
        corpora=len({r["corpus"] for r in runs}),
        cases=len([r for r in runs if r.get("ok")]),
        skipped=len([r for r in runs if not r.get("ok")]),
        timings=timings,
        rows_written=sum(r["rows"] for r in runs if r.get("ok")),
    )
    (DATA / "analysis.json").write_text(json.dumps(out, indent=1))

    # ------------------------------------------------------------- report --
    print(f"{out['totals']['cases']} measured cases, "
          f"{out['totals']['skipped']} impossible, {timings} timed calls\n")
    for c in CORPORA:
        for s in SCALES:
            front = out["pareto"][f"{c}|{s}"]
            if front:
                print(f"pareto {c:<10} {s:<6} {', '.join(front)}")
    print("\nprojection gain (full read / three-column read), large scale:")
    for c in CORPORA:
        p = out["projection"].get(f"{c}|large", {})
        if not p:
            continue
        top = sorted(p.items(), key=lambda kv: -kv[1])[:4]
        print(f"  {c:<10} " + "  ".join(f"{k} {v}x" for k, v in top))
    print("\nfidelity: properties lost per format")
    for r in d["fidelity"]["results"]:
        if r.get("ok"):
            print(f"  {r['fmt']:<16} {r['n_lost']}/6  " +
                  " ".join(f"{k}={v['v']}" for k, v in r["props"].items()))
    print("\nsize as a share of the same frame in memory (powerflow large):")
    comp = out["compression"].get("powerflow|large", {})
    for k, v in sorted(comp.items(), key=lambda kv: kv[1]):
        print(f"  {k:<16} {v * 100:>7.1f}%")
    med = statistics.median([r["read_s"] for r in runs
                             if r.get("ok") and r["fmt"] == "parquet_zstd"])
    print(f"\nmedian parquet_zstd read across all cases: {med:.4f} s")


if __name__ == "__main__":
    main()
