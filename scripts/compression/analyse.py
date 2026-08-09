"""Derives the quantities the page plots from the raw sweep.

The central object is the Pareto frontier of compression ratio against
decompression throughput, computed per corpus: a codec and level is on the
frontier when nothing else is both smaller and faster to read. Everything a
region on the map claims has to be defensible against that frontier.
"""

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "compression"

FAMILIES = ["gzip", "zstd", "brotli", "xz", "lz4", "bzip2"]
CORPORA = ["web", "code", "logs", "timeseries", "compressed", "prose"]
# One representative level per family for the cross-corpus comparison: the
# setting a practitioner would reach for when size is what they care about.
REPRESENTATIVE = {"gzip": 6, "zstd": 19, "brotli": 11, "xz": 9, "lz4": 12, "bzip2": 9}
BASELINE = ("gzip", 6)


def frontier(points, xkey, ykey):
    """Indices of non-dominated points, maximising both keys."""
    out = []
    for p in points:
        if not any(q is not p and q[xkey] >= p[xkey] and q[ykey] >= p[ykey]
                   and (q[xkey] > p[xkey] or q[ykey] > p[ykey]) for q in points):
            out.append(p["id"])
    return sorted(out, key=lambda i: next(p[xkey] for p in points if p["id"] == i))


def main():
    rows = json.loads((DATA / "sweep.json").read_text())
    by_corpus = {c: [r for r in rows if r["corpus"] == c] for c in CORPORA}
    by_corpus = {c: v for c, v in by_corpus.items() if v}

    out = {
        "corpora": list(by_corpus),
        "families": FAMILIES,
        "representative": REPRESENTATIVE,
        "rows": rows,
        "sizes": {c: v[0]["in_bytes"] for c, v in by_corpus.items()},
    }

    # ---- Pareto frontiers, both directions -------------------------------
    out["pareto_decomp"] = {c: frontier(v, "d_mb_s", "ratio") for c, v in by_corpus.items()}
    out["pareto_comp"] = {c: frontier(v, "c_mb_s", "ratio") for c, v in by_corpus.items()}

    # ---- how much of the plane zstd owns ---------------------------------
    zstd_share = {}
    for c, v in by_corpus.items():
        f = out["pareto_decomp"][c]
        zstd_share[c] = dict(
            n=len(f),
            zstd=sum(1 for i in f if i.startswith("zstd-")),
            members=f)
    out["frontier_share"] = zstd_share

    # ---- claim: zstd decompression speed is roughly level-independent ----
    const = {}
    for c, v in by_corpus.items():
        z = sorted((r for r in v if r["codec"] == "zstd"), key=lambda r: r["level"])
        d = [r["d_mb_s"] for r in z]
        const[c] = dict(levels=[r["level"] for r in z], d=d,
                        lo=min(d), hi=max(d), med=round(statistics.median(d), 1),
                        spread_pct=round(100 * (max(d) - min(d)) / statistics.median(d), 1),
                        c_lo=min(r["c_mb_s"] for r in z), c_hi=max(r["c_mb_s"] for r in z),
                        c_ratio=round(max(r["c_mb_s"] for r in z) / min(r["c_mb_s"] for r in z), 1))
        # the same statistic for the codecs it is being compared against
        for fam in ("xz", "brotli", "gzip"):
            g = [r["d_mb_s"] for r in v if r["codec"] == fam]
            const[c][fam + "_spread_pct"] = round(
                100 * (max(g) - min(g)) / statistics.median(g), 1)
    out["level_independence"] = const

    # ---- ratio by corpus at the representative level ---------------------
    grid = {}
    for c, v in by_corpus.items():
        grid[c] = {}
        for fam in FAMILIES:
            r = next((x for x in v if x["codec"] == fam and x["level"] == REPRESENTATIVE[fam]), None)
            if r:
                grid[c][fam] = dict(ratio=r["ratio"], out_bytes=r["out_bytes"],
                                    saved=round(100 * (1 - 1 / r["ratio"]), 1),
                                    d_mb_s=r["d_mb_s"], c_mb_s=r["c_mb_s"], id=r["id"])
    out["by_corpus"] = grid

    # ---- best achievable per corpus, and the gzip baseline ---------------
    best = {}
    for c, v in by_corpus.items():
        b = max(v, key=lambda r: r["ratio"])
        base = next(r for r in v if r["codec"] == BASELINE[0] and r["level"] == BASELINE[1])
        best[c] = dict(id=b["id"], ratio=b["ratio"], out_bytes=b["out_bytes"],
                       base_id=base["id"], base_ratio=base["ratio"],
                       gain_over_gzip=round(100 * (1 - b["out_bytes"] / base["out_bytes"]), 1))
    out["best"] = best

    # ---- diminishing returns inside the zstd ladder ----------------------
    knees = {}
    for c, v in by_corpus.items():
        z = sorted((r for r in v if r["codec"] == "zstd"), key=lambda r: r["level"])
        steps = []
        for a, b in zip(z, z[1:]):
            steps.append(dict(frm=a["level"], to=b["level"],
                              size_pct=round(100 * (1 - b["out_bytes"] / a["out_bytes"]), 2),
                              speed_pct=round(100 * (1 - b["c_mb_s"] / a["c_mb_s"]), 1)))
        knees[c] = steps
    out["zstd_steps"] = knees

    # ---- HTTP case: what the web corpus actually says ---------------------
    web = by_corpus.get("web")
    if web:
        g6 = next(r for r in web if r["id"] == "gzip-6")
        out["http"] = {
            r["id"]: dict(ratio=r["ratio"], out_bytes=r["out_bytes"], c_mb_s=r["c_mb_s"],
                          d_mb_s=r["d_mb_s"],
                          vs_gzip6=round(100 * (1 - r["out_bytes"] / g6["out_bytes"]), 1))
            for r in web
        }

    # ---- noise: worst observed spread across rounds ----------------------
    out["noise"] = dict(
        rounds=3,
        c_spread_med=round(statistics.median(r["c_spread"] for r in rows), 3),
        d_spread_med=round(statistics.median(r["d_spread"] for r in rows), 3),
        c_spread_p90=round(sorted(r["c_spread"] for r in rows)[int(0.9 * len(rows))], 3),
        d_spread_p90=round(sorted(r["d_spread"] for r in rows)[int(0.9 * len(rows))], 3),
    )

    for name in ("memory", "containers", "longrange", "scale"):
        p = DATA / f"{name}.json"
        if p.exists():
            out[name] = json.loads(p.read_text())

    (DATA / "analysis.json").write_text(json.dumps(out, indent=1))
    print(f"corpora: {list(by_corpus)}")
    for c in by_corpus:
        f = out["frontier_share"][c]
        print(f"\n{c}: frontier {f['n']} points, {f['zstd']} of them zstd")
        print("  " + ", ".join(f["members"]))
        li = out["level_independence"][c]
        print(f"  zstd decomp {li['lo']:.0f}-{li['hi']:.0f} MB/s "
              f"(spread {li['spread_pct']}% of median), compress speed varies {li['c_ratio']}x")
        b = out["best"][c]
        print(f"  best ratio {b['id']} x{b['ratio']} vs gzip-6 x{b['base_ratio']} "
              f"({b['gain_over_gzip']}% fewer bytes)")
    print("\nwrote", DATA / "analysis.json")


if __name__ == "__main__":
    main()
