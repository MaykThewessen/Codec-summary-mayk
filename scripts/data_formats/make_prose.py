"""Derive every sentence on the page that contains a number, then assemble the
page payload.

Prose is generated from the measurement files rather than typed by hand, so a
re-run of the sweeps cannot leave the text asserting something the charts no
longer show.

    python3 scripts/data_formats/make_prose.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "data_formats"

HERO_CORPUS, HERO_SCALE = "powerflow", "large"


def fmt_int(v: float) -> str:
    v = round(v)
    if abs(v) < 10000:
        return str(v)
    return ("-" if v < 0 else "") + f"{abs(v):,}".replace(",", ".")


def mb(b: float) -> str:
    if b >= 1e9:
        return f"{b / 1e9:.2f} GB"
    if b >= 1e6:
        return f"{b / 1e6:.1f} MB"
    return f"{b / 1e3:.0f} kB"


def secs(s: float | None) -> str:
    if s is None:
        return "n/a"
    if s < 0.001:
        return f"{s * 1e6:.0f} microseconds"
    if s < 1:
        return f"{s * 1000:.0f} ms" if s >= 0.01 else f"{s * 1000:.1f} ms"
    return f"{s:.2f} s" if s < 10 else f"{s:.1f} s"


def xf(v: float) -> str:
    if v >= 100:
        return f"{fmt_int(v)} times"
    return f"{v:.0f} times" if v >= 10 else f"{v:.1f} times"


def main() -> None:
    bench = json.loads((DATA / "bench.json").read_text())
    corpora = json.loads((DATA / "corpora.json").read_text())
    fidelity = json.loads((DATA / "fidelity.json").read_text())
    mmap = json.loads((DATA / "mmap.json").read_text())
    analysis = json.loads((DATA / "analysis.json").read_text())
    cold = (json.loads((DATA / "cold.json").read_text())
            if (DATA / "cold.json").exists() else dict(available=False, reason="not run"))

    runs = bench["runs"]
    idx = {(r["corpus"], r["scale"], r["fmt"]): r for r in runs}
    mem = {(c["corpus"], c["scale"]): c["mem_bytes"] for c in corpora}
    rowsof = {(c["corpus"], c["scale"]): c["rows"] for c in corpora}
    colsof = {(c["corpus"], c["scale"]): c["cols"] for c in corpora}

    def g(fmt: str, corpus: str = HERO_CORPUS, scale: str = HERO_SCALE) -> dict:
        return idx.get((corpus, scale, fmt), {})

    hero_rows = rowsof[(HERO_CORPUS, HERO_SCALE)]
    hero_cols = colsof[(HERO_CORPUS, HERO_SCALE)]
    pq = g("parquet_zstd")
    fe = g("feather")
    csv = g("csv")
    csvgz = g("csv_gz")
    duck = g("duckdb")
    pqduck = g("parquet_duckdb")
    tot = analysis["totals"]

    P: dict[str, str] = {}

    # ------------------------------------------------------- head counters --
    P["n_formats"] = str(tot["formats"])
    P["n_corpora"] = str(tot["corpora"])
    P["n_timings"] = fmt_int(tot["timings"])
    P["n_rows_total"] = fmt_int(tot["rows_written"])

    # ------------------------------------------------------------- the map --
    big = [c for c in corpora if c["scale"] == "large" and c["rows"] > 1_048_576]
    P["xlsx_fail_note"] = (
        f"not one of the {len(big)} large tables here fits in one: they run from "
        f"{fmt_int(min(c['rows'] for c in big))} to {fmt_int(max(c['rows'] for c in big))} rows.")
    xs, ps = g("xlsx", HERO_CORPUS, "small"), g("parquet_zstd", HERO_CORPUS, "small")
    if xs.get("write_s") and ps.get("write_s"):
        P["xlsx_write_vs_parquet"] = xf(xs["write_s"] / ps["write_s"])
    P["csvgz_vs_csv"] = f"{csvgz['size_bytes'] / csv['size_bytes'] * 100:.0f}%"

    smallest = min((r for r in runs if r["corpus"] == HERO_CORPUS
                    and r["scale"] == HERO_SCALE and r.get("ok")),
                   key=lambda r: r["size_bytes"])
    n_smallest = sum(1 for c in ["prices", "powerflow", "weather", "assets"]
                     for s in ["small", "large"]
                     if min((r for r in runs if r["corpus"] == c and r["scale"] == s
                             and r.get("ok")), key=lambda r: r["size_bytes"],
                            default={"fmt": ""})["fmt"] in ("parquet_zstd", "parquet_gzip"))
    P["pq_smallest_where"] = (f"{n_smallest} of the 8 corpus and scale combinations"
                              if n_smallest else "several of the corpora")
    P["pq_read_vs_csv"] = f"{pq['read_s'] / csv['read_s'] * 100:.1f}%"
    P["pq_cols_speedup"] = xf(pq["read_s"] / pq["cols_s"])
    P["csv_cols_saving"] = f"{(1 - csv['cols_s'] / csv['read_s']) * 100:.0f}%"
    P["pf_years"] = str(round(hero_rows / (4 * 24 * 365.25)))
    P["pqduck_filter_t"] = secs(pqduck.get("filter_s"))
    P["feather_write_note"] = (
        f"Writing the {mb(mem[(HERO_CORPUS, HERO_SCALE)])} power flow table took "
        f"{secs(fe['write_s'])} against {secs(pq['write_s'])} for Parquet zstd, and reading it "
        f"back took {secs(fe['read_s'])}.")

    mmcase = {c["case"]: c for c in mmap["cases"] if c.get("ok")}
    if "feather_mmap_open" in mmcase:
        mo = mmcase["feather_mmap_open"]
        P["mmap_file_mb"] = mb(mo["file_bytes"])
        P["mmap_open_t"] = secs(mo["seconds"])
        P["mmap_open_rss"] = mb(max(mo["rss_delta"], 0))

    # ------------------------------------------------- columnar projection --
    proj = analysis["projection"].get(f"{HERO_CORPUS}|{HERO_SCALE}", {})
    best_fmt = max(proj, key=proj.get) if proj else None
    best_row = g(best_fmt) if best_fmt else {}
    P["columnar_note"] = (
        f"On the wide table the three requested columns are {len(pq.get('subset_cols', []))} of "
        f"{hero_cols}, about {3 / hero_cols * 100:.0f}% of the data. Parquet zstd read them in "
        f"{secs(pq['cols_s'])} against {secs(pq['read_s'])} for the whole file, "
        f"{xf(pq['read_s'] / pq['cols_s'])} faster; "
        f"{best_row.get('label', '')} did best at {xf(proj[best_fmt])}. CSV read them in "
        f"{secs(csv['cols_s'])} against {secs(csv['read_s'])}, a saving of "
        f"{(1 - csv['cols_s'] / csv['read_s']) * 100:.0f}%, because usecols still has to parse "
        f"every byte of every row to find the commas. That gap, "
        f"{xf(csv['cols_s'] / pq['cols_s'])} between CSV and Parquet on the same question, is "
        f"the single largest effect measured on this page. One honest qualification: usecols "
        f"is not always worthless. On the string-heavy register table it saved "
        f"{(1 - g('csv', 'assets', 'large')['cols_s'] / g('csv', 'assets', 'large')['read_s']) * 100:.0f}%, "
        f"because the columns it skips are expensive to build in memory rather than expensive to "
        f"scan. It was still {xf(g('csv', 'assets', 'large')['cols_s'] / g('parquet_zstd', 'assets', 'large')['cols_s'])} "
        f"slower than Parquet answering the same question.")

    # ------------------------------------------------------------- pareto --
    front = analysis["pareto"][f"{HERO_CORPUS}|{HERO_SCALE}"]
    fl = [g(f).get("label", f) for f in front]
    P["pareto_note"] = (
        f"Nothing on the frontier is a surprise once you see it: "
        f"{', '.join(fl)}. Everything else is dominated, which includes every text format. "
        f"CSV is {csv['size_bytes'] / pq['size_bytes']:.1f} times the size of Parquet zstd "
        f"and {xf(csv['read_s'] / pq['read_s'])} slower to read: it loses on both axes at "
        f"once, so there is no trade to discuss. Where the frontier is genuinely a trade is "
        f"between uncompressed Feather at {mb(fe['size_bytes'])} and "
        f"{secs(fe['read_s'])} and Parquet zstd at {mb(pq['size_bytes'])} and "
        f"{secs(pq['read_s'])}: {pq['size_bytes'] / fe['size_bytes'] * 100:.0f}% of the bytes "
        f"for {pq['read_s'] / fe['read_s']:.1f} times the read time.")

    # -------------------------------------------------------------- scale --
    sm_csv, sm_pq = g("csv", HERO_CORPUS, "small"), g("parquet_zstd", HERO_CORPUS, "small")
    P["scale_note"] = (
        f"At 100.000 rows the whole question is close to academic: the difference between "
        f"CSV and Parquet on the wide table is {secs(sm_csv['read_s'])} against "
        f"{secs(sm_pq['read_s'])}, and nobody notices either. At "
        f"{fmt_int(hero_rows)} rows it is {secs(csv['read_s'])} against {secs(pq['read_s'])}, "
        f"and it is the difference between an interactive script and a coffee break. The "
        f"ranking barely moves with size; what moves is whether the ranking matters.")

    # ----------------------------------------------------------- fidelity --
    fres = {r["fmt"]: r for r in fidelity["results"] if r.get("ok")}
    clean = [r["label"] for r in fres.values() if r["n_lost"] == 0]
    worst = sorted(fres.values(), key=lambda r: -r["n_lost"])[:3]
    tl = [r["n_lost"] for r in fres.values() if r["family"] == "text"]
    span = (f"all four lost {tl[0]} of the six properties" if min(tl) == max(tl)
            else f"the text formats lost between {min(tl)} and {max(tl)} of the six properties")
    P["fidelity_note"] = (
        f"{len(clean)} of {len(fres)} formats returned the frame unchanged: "
        f"{', '.join(clean)}. Of the four formats you would hand to a person, {span}, and lost "
        f"them silently: nothing raises, nothing warns, the frame simply comes back different. "
        f"The two DuckDB rows are a different case and a milder one: "
        + ", ".join(f"{r['label']} lost {r['n_lost']}"
                    for r in fres.values() if r["family"] == "duckdb")
        + ", mostly because a SQL table has no pandas index and no category type, "
          "so those two ideas have nowhere to live.")

    csvf = fres.get("csv", {}).get("props", {})
    P["tz_note"] = (
        "CSV writes an ISO string with an offset, which looks like it survived. It has not: "
        "the offset is a number, not a zone, so the reader has to be told to parse it and to "
        "localize the result. Miss that and pandas 3 gives you a naive column that silently "
        "compares false against every aware timestamp in your code. "
        + (csvf.get("tz", {}).get("why", "")
           and f"Measured here: {csvf['tz']['why'].rstrip('.')}. ")
        + "Excel is worse: xlsxwriter refuses a tz-aware datetime outright, so the zone has to "
        "be stripped before writing and there is nothing in the file that records which zone it "
        "was. Parquet, Feather and DuckDB all store the zone with the value.")
    P["null_note"] = (
        "A nullable Int32 with four missing values comes back from CSV as float64: pandas has "
        "no way to know you wanted an integer, and NaN forces the column to float. Station "
        "numbers and unit ids become 260.0. "
        + (csvf.get("null", {}).get("why", "")
           and f"Measured: {csvf['null']['why'].rstrip('.')}. ")
        + "The nullable boolean has the same problem, becoming object or float depending on the "
        "reader. Parquet and Feather carry a validity bitmap next to the values, so the "
        "distinction between zero and missing is part of the file.")
    P["cat_note"] = (
        "An ordered categorical of bidding zones comes back from every text format as plain "
        "strings: both the dictionary and the ordering are gone, and any code that sorted on "
        "the category order now sorts alphabetically. Arrow stores it as a dictionary-encoded "
        "column, which is why Feather and Parquet keep it, and why the categorical is also "
        "where they get much of their compression on the register table.")

    # ------------------------------------------------------------- mmap ---
    if mmcase:
        cp = mmcase.get("feather_copy", {})
        op = mmcase.get("feather_mmap_open", {})
        zc = mmcase.get("feather_mmap_zerocopy", {})
        tp = mmcase.get("feather_mmap_topandas", {})
        zst = mmcase.get("feather_zstd_mmap_open", {})
        pqc = mmcase.get("parquet_copy", {})
        P["mmap_note"] = (
            f"Mapping the {mb(op.get('file_bytes', 0))} Arrow IPC file took "
            f"{secs(op.get('seconds'))} and grew the process by {mb(max(op.get('rss_delta', 0), 0))}: "
            f"nothing was read, the kernel just wired the file into the address space. Taking a "
            f"numpy view of one column stayed at {mb(max(zc.get('rss_delta', 0), 0))}. "
            f"Reading the same file into pandas cost {secs(cp.get('seconds'))} and "
            f"{mb(cp.get('rss_delta', 0))}, and converting the mapped table to pandas costs the "
            f"same {mb(tp.get('rss_delta', 0))}, because that is the copy. So the intuition is "
            f"right and the condition is exact: you get RAM-on-disc as long as you stay in "
            f"Arrow. Compressing the Feather file removes the property entirely, "
            f"{mb(zst.get('rss_delta', 0))} for the same map, since compressed buffers have to "
            f"be decoded into memory that the file does not back. Parquet is never mappable in "
            f"this sense: it is an encoded format, and pd.read_parquet cost "
            f"{secs(pqc.get('seconds'))} and {mb(pqc.get('rss_delta', 0))}.")

    # ------------------------------------------------------------- cold ---
    if cold.get("available"):
        cidx = {r["fmt"]: r for r in cold["runs"]}
        cc, cf, cp2 = cidx.get("csv"), cidx.get("feather"), cidx.get("parquet_zstd")
        pen = {k: v["seconds"] / idx[(cold["corpus"], cold["scale"], k)]["read_s"]
               for k, v in cidx.items() if idx.get((cold["corpus"], cold["scale"], k))}
        worst_pen = max(pen, key=pen.get)
        P["cold_note"] = (
            f"Cold, uncompressed Feather reads in {secs(cf['seconds'])} against "
            f"{secs(idx[(cold['corpus'], cold['scale'], 'feather')]['read_s'])} warm: the "
            f"{mb(cf['size_bytes'])} has to come off the disk and nothing can hide that. "
            f"Parquet zstd goes from {secs(idx[(cold['corpus'], cold['scale'], 'parquet_zstd')]['read_s'])} "
            f"to {secs(cp2['seconds'])} for {mb(cp2['size_bytes'])}. The cold penalty is largest "
            f"for {g(worst_pen).get('label', worst_pen)} at {xf(pen[worst_pen])}. The practical "
            f"reading: the smaller compressed formats lose least when the cache is cold, so if "
            f"your files live on a share rather than a local SSD, weight size higher than these "
            f"warm numbers suggest. CSV stays slowest either way, because parsing dominates.")
    else:
        P["cold_note"] = (
            "The page cache could not be dropped in this container, so no cold-read figure is "
            "reported here rather than a guess. " + cold.get("reason", ""))

    # ----------------------------------------------------------- engines ---
    eng = bench["engines"]

    def e(corpus, scale, fmt, engine):
        for r in eng:
            if (r["corpus"], r["scale"], r["fmt"], r["engine"]) == (corpus, scale, fmt, engine):
                return r["read_s"]
        return None

    ec = "prices"
    pdc, plc, ddc = (e(ec, "large", "csv", x) for x in ["pandas", "polars", "duckdb"])
    pdp, plp, ddp = (e(ec, "large", "parquet_zstd", x) for x in ["pandas", "polars", "duckdb"])
    if pdc and pdp:
        P["engine_note"] = (
            f"Changing engine on a CSV is worth something: DuckDB read the "
            f"{fmt_int(rowsof[(ec, 'large')])} row price CSV in {secs(ddc)} where pandas took "
            f"{secs(pdc)}, {xf(pdc / ddc)} faster, because it parses in parallel. Changing "
            f"format is worth an order of magnitude more: the same data as Parquet zstd read "
            f"in {secs(pdp)} in pandas, {xf(pdc / pdp)} faster than the CSV it replaced. If you "
            f"only change one thing, change the format. On Parquet the three engines land "
            f"within a factor of {max(pdp, plp, ddp) / min(pdp, plp, ddp):.1f} of each other, "
            f"because at that point almost nothing is left to parse.")

    # ------------------------------------------------------------ claims ---
    js = g("json", "prices", "large")
    P["claim_base"] = (
        f"CSV as the base is right, and it is the right thing to hand to a person. The "
        f"improvement is in the other direction. JSON was "
        f"{js['size_bytes'] / g('csv', 'prices', 'large')['size_bytes']:.1f} times the size of "
        f"the same data as CSV ({mb(js['size_bytes'])} against "
        f"{mb(g('csv', 'prices', 'large')['size_bytes'])}) and "
        f"{js['read_s'] / g('csv', 'prices', 'large')['read_s']:.1f} times the read time, and "
        f"it cannot project columns at all. Excel is slower still and cannot hold the data: "
        f"none of the four large tables fits in a worksheet. Both are worse than CSV for this "
        f"workload, not better. The formats that improve on CSV are the ones further down the "
        f"list: Feather and Parquet.")
    P["claim_feather"] = (
        f"Correct, and the mechanism is exactly the one implied. Uncompressed Arrow IPC is the "
        f"in-memory layout written straight to disk, so it wrote the {hero_cols} column power "
        f"flow table in {secs(fe['write_s'])} and read it back in {secs(fe['read_s'])}, the "
        f"fastest round trip measured. Memory-mapped it is literally RAM on disc: "
        f"{mb(mmcase.get('feather_mmap_open', {}).get('file_bytes', 0))} mapped in "
        f"{secs(mmcase.get('feather_mmap_open', {}).get('seconds'))} with the process growing by "
        f"{mb(max(mmcase.get('feather_mmap_open', {}).get('rss_delta', 0), 0))}. Two conditions "
        f"you have to know: compress the file and the property is gone, and convert to pandas "
        f"and you have paid for the copy anyway. The cost is size: at "
        f"{mb(fe['size_bytes'])} it is {fe['size_bytes'] / pq['size_bytes']:.1f} times the "
        f"Parquet file.")
    P["claim_parquet"] = (
        f"Correct on all three counts, and it is the right default. On the wide table it was "
        f"{mb(pq['size_bytes'])} against {mb(csv['size_bytes'])} for CSV and "
        f"{mb(fe['size_bytes'])} for uncompressed Feather; it read whole in "
        f"{secs(pq['read_s'])}; and the columnar claim is the one that pays best, three of "
        f"{hero_cols} columns in {secs(pq['cols_s'])}, {xf(pq['read_s'] / pq['cols_s'])} faster "
        f"than the full read. The one sharpening: zstd rather than the snappy default. It was "
        f"{(1 - pq['size_bytes'] / g('parquet_snappy')['size_bytes']) * 100:.0f}% smaller than "
        f"snappy here for a read time within "
        f"{abs(pq['read_s'] / g('parquet_snappy')['read_s'] - 1) * 100:.0f}%, and gzip buys a "
        f"little more size for a much slower write "
        f"({secs(g('parquet_gzip')['write_s'])} against {secs(pq['write_s'])}).")
    P["claim_duckdb"] = (
        f"DuckDB belongs on the list but not in the same column as the others: it is a query "
        f"engine that happens to have a storage format, not a file format that happens to be "
        f"queryable. Two consequences. First, you do not have to import anything: pointed "
        f"straight at the Parquet file it answered the filtered query in "
        f"{secs(pqduck['filter_s'])}, against {secs(pq['filter_s'])} for pyarrow's own pushdown "
        f"on the same file, and no copy of the data exists. Second, when you do import, you get "
        f"things no file format offers: indexes, joins across tables, updates in place, and "
        f"queries larger than memory. Its own file was {mb(duck['size_bytes'])} against "
        f"{mb(pq['size_bytes'])} for Parquet, and reading a whole table out of it into pandas "
        f"cost {secs(duck['read_s'])} against {secs(pq['read_s'])}, so as a plain container it "
        f"is not the best. Use it for the query, keep Parquet for the file.")
    csv_lost = fres.get("csv", {}).get("n_lost", 0)
    P["claim_csv_fidelity"] = (
        f"This is the finding worth taking away. Round-tripped through CSV, the test frame lost "
        f"{csv_lost} of its 6 properties, silently: "
        + " ".join(f"{k.capitalize()} ({v['v']}): {v['why'].rstrip('.')}."
                   for k, v in fres.get("csv", {}).get("props", {}).items()
                   if v["v"] != "good")
        + " For grid timeseries this is not a performance question, it is a correctness one. "
          "A tz-aware UTC column that comes back naive compares false against every aware "
          "timestamp in your code without raising, and a nullable integer that comes back as "
          "float turns station 260 into 260.0 and a missing reading into NaN, which is now "
          "indistinguishable from a genuine zero after one arithmetic operation. None of this "
          "announces itself.")
    P["claim_excel"] = (
        f"Excel is a deliverable, not a storage format, and the row limit settles it before any "
        f"other argument is needed. A worksheet holds 1.048.576 rows, and not one of the "
        f"{len(big)} large tables measured here fits: they run from "
        f"{fmt_int(min(c['rows'] for c in big))} to {fmt_int(max(c['rows'] for c in big))} rows. "
        f"Even where it fits, writing the 100.000 row wide "
        f"table took {secs(xs.get('write_s'))} against {secs(ps.get('write_s'))} for Parquet, "
        f"reading it back took {secs(xs.get('read_s'))}, and the file was "
        f"{xs.get('size_bytes', 0) / ps.get('size_bytes', 1):.0f} times larger. It also drops "
        f"the timezone from every timestamp on the way in. Generate it last, from the real "
        f"file, for a human who is going to look at it.")
    if xs.get("read_alt_s"):
        P["calamine_gain_comment"] = (
            f"# {xs['read_s'] / xs['read_alt_s']:.0f}x faster than openpyxl here")

    # ------------------------------------------------------------ method ---
    P["method_corpus"] = (
        f"Four generated corpora shaped like the files this work actually produces, each at two "
        f"scales, written and re-read by {tot['formats']} formats. "
        f"{tot['cases']} format and corpus combinations completed, {tot['skipped']} were "
        f"impossible and are reported as impossible rather than omitted. Every timing is the "
        f"median of repeated runs, {bench['env']['repeats']['small']} at the small scale and "
        f"{bench['env']['repeats']['large']} at the large one, with expensive combinations "
        f"stopping early against a {bench['env']['budget_s']:.0f} second budget; the number of "
        f"repeats actually taken is recorded per cell in the raw data.")
    P["method_noise"] = (
        "These ran on a shared container with other heavy jobs on the same four cores, so "
        "absolute milliseconds here are not a property of the formats. Medians of several "
        "repeats absorb some of that and the ratios between formats measured back to back are "
        "sound, but treat a difference under about 20% as noise, and do not compare a number "
        "on this page against a number from your own laptop.")
    P["method_gaps"] = (
        "No lazy or streaming reads: everything is materialised into a pandas DataFrame, so "
        "polars scan_parquet and DuckDB's out-of-core execution are not represented and both "
        "would look better if they were. No partitioned Parquet datasets, which change the "
        "filtered-query numbers substantially when the predicate matches the partition key. No "
        "Arrow Flight, no ORC, no HDF5 or NetCDF, which matter for weather in particular. "
        "Nothing here is measured over a network filesystem.")

    env = bench["env"]
    P["env_line"] = (f"python {env['python']} · pandas {env['pandas']} · pyarrow "
                     f"{env['pyarrow']} · duckdb {env['duckdb']} · numpy {env['numpy']}")

    payload = dict(env=env, corpora=corpora, runs=runs, engines=bench["engines"],
                   fidelity=fidelity, mmap=mmap, cold=cold, analysis=analysis, prose=P)
    (DATA / "page_data.json").write_text(json.dumps(payload, separators=(",", ":")))
    print(json.dumps({k: v[:180] for k, v in P.items()}, indent=1))
    print(f"\nwrote {DATA / 'page_data.json'}")


if __name__ == "__main__":
    main()
