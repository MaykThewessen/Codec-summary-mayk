"""Generate the four benchmark corpora, at two scales each.

The point of the page is Dutch grid work, so the corpora are shaped like the
files that job actually produces: day-ahead prices per bidding zone, power flow
solver output (wide, all float), KNMI-style weather (mixed dtypes and gaps),
and a connection register (high-cardinality strings). Generic random tables
would compress unrealistically well and would hide the string handling that
separates the formats.

Everything is written to testdata/data_formats/ as uncompressed Arrow IPC so
the benchmark can reload a corpus quickly without re-generating it.

    python3 scripts/data_formats/make_corpora.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata" / "data_formats"
DATA = ROOT / "data" / "data_formats"

SEED = 20260809

# Bidding zones as they appear in ENTSO-E / JAO exports.
ZONES_SMALL = ["NL", "BE", "DE_LU", "FR"]
ZONES_LARGE = ZONES_SMALL + ["DK1", "DK2", "NO2", "GB", "AT", "CH", "CZ", "PL"]

# 380 kV substations on the TenneT backbone: the corridors a power flow run reports on.
STATIONS_380 = [
    "MVL", "KIJ", "CST", "WTR", "BWK", "OZN", "DIE", "LLS", "ENS", "ZWO",
    "HGL", "DTC", "DOD", "GT", "KRI", "EEM", "MEE", "VVL", "BSL", "RLL",
]

# KNMI hoofdstations (station number, name).
KNMI = [
    (209, "IJmond"), (210, "Valkenburg"), (215, "Voorschoten"), (225, "IJmuiden"),
    (235, "De Kooy"), (240, "Schiphol"), (242, "Vlieland"), (248, "Wijdenes"),
    (249, "Berkhout"), (251, "Hoorn Terschelling"), (257, "Wijk aan Zee"),
    (260, "De Bilt"), (265, "Soesterberg"), (267, "Stavoren"), (269, "Lelystad"),
    (270, "Leeuwarden"), (273, "Marknesse"), (275, "Deelen"), (277, "Lauwersoog"),
    (278, "Heino"), (279, "Hoogeveen"), (280, "Eelde"), (283, "Hupsel"),
    (286, "Nieuw Beerta"), (290, "Twenthe"), (310, "Vlissingen"), (319, "Westdorpe"),
    (323, "Wilhelminadorp"), (330, "Hoek van Holland"), (340, "Woensdrecht"),
    (344, "Rotterdam"), (348, "Cabauw"), (350, "Gilze-Rijen"), (356, "Herwijnen"),
    (370, "Eindhoven"), (375, "Volkel"), (377, "Ell"), (380, "Maastricht"),
    (391, "Arcen"),
]

NETBEHEERDERS = ["Liander", "Enexis", "Stedin", "Westland Infra", "Rendo"]
CONTRACTS = ["GVKV", "KVKV", "MSA", "TSA", "GSA", "HSA", "kleinverbruik", "grootverbruik"]

GEMEENTE_STEM = [
    "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen",
    "Tilburg", "Almere", "Breda", "Nijmegen", "Apeldoorn", "Arnhem", "Haarlem",
    "Haarlemmermeer", "Amersfoort", "Zaanstad", "Den Bosch", "Zwolle", "Zoetermeer",
    "Leiden", "Leeuwarden", "Ede", "Maastricht", "Dordrecht", "Westland",
    "Alphen aan den Rijn", "Alkmaar", "Emmen", "Delft", "Venlo", "Deventer",
    "Sittard-Geleen", "Helmond", "Oss", "Amstelveen", "Hilversum", "Heerlen",
    "Hengelo", "Purmerend", "Roosendaal", "Schiedam", "Spijkenisse", "Vlaardingen",
    "Almelo", "Gouda", "Zaltbommel", "Terneuzen", "Katwijk", "Veenendaal", "Hoorn",
]


def _gemeenten(n: int, rng: np.random.Generator) -> list[str]:
    """342 gemeente-like names, so the category has realistic cardinality."""
    suffix = ["aan de Maas", "aan den IJssel", "aan Zee", "Noord", "Zuid",
              "West", "Oost", "Buiten", "Binnen", "Nieuw", "Oud", "Boven", "Beneden"]
    out = list(GEMEENTE_STEM)
    for s in suffix:
        for stem in GEMEENTE_STEM:
            if len(out) >= n:
                return out
            out.append(f"{stem} {s}")
    return out[:n]


def _seasonal(idx: pd.DatetimeIndex, rng: np.random.Generator, base: float,
              daily: float, weekly: float, yearly: float) -> np.ndarray:
    """Daily, weekly and annual cycles plus an AR(1) residual.

    Grid timeseries are not white noise: neighbouring hours are strongly
    correlated, which is exactly what the entropy coders exploit.
    """
    hod = idx.hour.to_numpy() + idx.minute.to_numpy() / 60.0
    dow = idx.dayofweek.to_numpy()
    doy = idx.dayofyear.to_numpy()
    sig = (base
           + daily * np.sin((hod - 4) / 24 * 2 * np.pi)
           + 0.4 * daily * np.sin((hod - 2) / 12 * 2 * np.pi)
           + weekly * (dow >= 5)
           + yearly * np.cos((doy - 15) / 365 * 2 * np.pi))
    # AR(1) residual, phi 0.92: hour-to-hour persistence. lfilter rather than a
    # Python loop, since the large corpora run to tens of millions of samples.
    eps = rng.normal(0.0, 1.0, size=len(idx))
    phi = 0.92
    resid = lfilter([np.sqrt(1 - phi ** 2)], [1.0, -phi], eps)
    return sig + resid


def make_prices(rng: np.random.Generator, zones: list[str], start: str, end: str,
                freq: str) -> pd.DataFrame:
    """Day-ahead prices, long format. Narrow, one timestamp column, tz-aware UTC."""
    idx = pd.date_range(start, end, freq=freq, tz="UTC", inclusive="left")
    frames = []
    for k, z in enumerate(zones):
        sig = _seasonal(idx, rng, base=78 + 6 * k, daily=26, weekly=-9, yearly=18)
        noise = rng.normal(0, 9, len(idx))
        price = sig + noise
        # solar surplus drives midday prices negative on sunny low-load days
        neg = rng.random(len(idx)) < 0.035
        price = np.where(neg, -rng.exponential(22, len(idx)), price)
        # scarcity spikes
        spike = rng.random(len(idx)) < 0.0022
        price = np.where(spike, price + rng.exponential(340, len(idx)), price)
        frames.append(pd.DataFrame({
            "timestamp": idx,
            "zone": pd.Categorical([z] * len(idx), categories=zones),
            # EPEX quotes EUR/MWh to two decimals; storing more is false precision
            "price_eur_mwh": np.round(price, 2),
        }))
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values(["timestamp", "zone"], ignore_index=True)


def make_powerflow(rng: np.random.Generator, n_rows: int) -> pd.DataFrame:
    """Power flow results: wide, all float, one row per snapshot.

    20 corridors x (active power, loading). The p_mw columns keep full solver
    precision, the loading columns are rounded to 2 decimals: both cases occur
    in practice and they compress very differently.
    """
    idx = pd.date_range("2020-01-01", periods=n_rows, freq="15min", tz="UTC")
    cols: dict[str, object] = {"snapshot": idx}
    for i in range(0, len(STATIONS_380), 2):
        a, b = STATIONS_380[i], STATIONS_380[(i + 1) % len(STATIONS_380)]
        base = rng.uniform(-900, 900)
        p = _seasonal(idx, rng, base=base, daily=380, weekly=-120, yearly=210)
        p = p + rng.normal(0, 55, n_rows)
        cols[f"p_mw_{a}_{b}_380"] = p
        rating = rng.uniform(1600, 2900)
        cols[f"loading_pct_{a}_{b}_380"] = np.round(np.abs(p) / rating * 100, 2)
    # second corridor family on the same substations, reversed pairing
    for i in range(1, len(STATIONS_380), 2):
        a, b = STATIONS_380[i], STATIONS_380[(i + 1) % len(STATIONS_380)]
        base = rng.uniform(-700, 700)
        p = _seasonal(idx, rng, base=base, daily=290, weekly=-80, yearly=160)
        p = p + rng.normal(0, 48, n_rows)
        cols[f"p_mw_{a}_{b}_220"] = p
        rating = rng.uniform(900, 1800)
        cols[f"loading_pct_{a}_{b}_220"] = np.round(np.abs(p) / rating * 100, 2)
    return pd.DataFrame(cols)


def make_weather(rng: np.random.Generator, n_rows: int) -> pd.DataFrame:
    """KNMI-shaped weather: mixed dtypes, a category, nullable ints, real gaps."""
    n_st = len(KNMI)
    n_time = n_rows // n_st + 1
    idx = pd.date_range("2015-01-01", periods=n_time, freq="h", tz="UTC")
    ts = np.tile(idx.to_numpy(), n_st)[:n_rows]
    st_num = np.repeat([k[0] for k in KNMI], n_time)[:n_rows]
    st_name = np.repeat([k[1] for k in KNMI], n_time)[:n_rows]
    full = pd.DatetimeIndex(ts, tz="UTC")

    temp = _seasonal(full, rng, base=10.4, daily=4.2, weekly=0.0, yearly=-7.6) * 1.0
    temp = np.round(temp + rng.normal(0, 1.4, n_rows), 1)
    wind = np.round(np.abs(rng.gamma(2.0, 2.4, n_rows)), 1)
    wdir = (rng.normal(230, 70, n_rows).astype(np.int64)) % 360
    hour = full.hour.to_numpy()
    doy = full.dayofyear.to_numpy()
    daylen = 0.5 + 0.42 * np.cos((doy - 172) / 365 * 2 * np.pi)
    solar = np.clip(np.sin((hour / 24 - 0.25 + daylen * 0) * 2 * np.pi), 0, None)
    ghi = np.round(solar * rng.uniform(120, 900, n_rows) * (1 - 0.55 * rng.random(n_rows)), 1)
    precip = np.round(np.where(rng.random(n_rows) < 0.14,
                               rng.exponential(1.1, n_rows), 0.0), 1)
    okta = rng.integers(0, 9, n_rows)
    code = rng.choice(["clear", "few", "scattered", "broken", "overcast", "fog",
                       "rain", "drizzle", "snow"], n_rows,
                      p=[0.14, 0.12, 0.13, 0.16, 0.22, 0.05, 0.11, 0.05, 0.02])
    flag = rng.choice(["valid", "valid", "valid", "estimated", "suspect"], n_rows)

    df = pd.DataFrame({
        "timestamp": full,
        "station_id": st_num.astype("int32"),
        "station_name": pd.Categorical(st_name),
        "temp_c": temp,
        "wind_speed_ms": wind,
        "wind_dir_deg": pd.array(wdir, dtype="Int16"),
        "ghi_w_m2": ghi,
        "precip_mm": precip,
        "cloud_okta": pd.array(okta, dtype="Int8"),
        "weather_code": pd.Categorical(code),
        "quality_flag": pd.array(flag, dtype="string"),
    })
    # sensor outages: real weather files have holes, and how a format stores a
    # hole is one of the things that separates them
    for col, frac in [("ghi_w_m2", 0.031), ("precip_mm", 0.018),
                      ("wind_dir_deg", 0.012), ("cloud_okta", 0.044),
                      ("quality_flag", 0.02)]:
        mask = rng.random(n_rows) < frac
        df.loc[mask, col] = None
    return df


def make_assets(rng: np.random.Generator, n_rows: int) -> pd.DataFrame:
    """Connection register: high-cardinality strings, where formats diverge most."""
    gem = _gemeenten(342, rng)
    ean = np.char.add("871687", np.char.zfill(
        rng.integers(0, 10 ** 12, n_rows).astype("U12"), 12))
    cid = np.array([f"{v:016x}" for v in rng.integers(0, 2 ** 63, n_rows)])
    words = ["aansluiting", "transformator", "veld", "kabel", "station", "verdeler",
             "trafo", "koppeling", "railsysteem", "beveiliging", "meetveld", "MS",
             "LS", "HS", "bay", "circuit", "streng", "net", "vak", "punt"]
    w = rng.choice(words, (n_rows, 4))
    desc = np.char.add(np.char.add(np.char.add(w[:, 0], " "), w[:, 1]),
                       np.char.add(np.char.add(" ", w[:, 2]), np.char.add(" ", w[:, 3])))
    return pd.DataFrame({
        "ean18": pd.array(ean, dtype="string"),
        "connection_id": pd.array(cid, dtype="string"),
        "gemeente": pd.Categorical(rng.choice(gem, n_rows), categories=gem),
        "netbeheerder": pd.Categorical(rng.choice(NETBEHEERDERS, n_rows),
                                       categories=NETBEHEERDERS),
        "contract_type": pd.array(rng.choice(CONTRACTS, n_rows), dtype="string"),
        "capacity_kw": np.round(rng.lognormal(3.2, 1.4, n_rows), 1),
        "description": pd.array(desc, dtype="string"),
        "last_reading_at": pd.date_range("2024-01-01", periods=n_rows,
                                         freq="7s", tz="UTC"),
    })


SPECS = {
    ("prices", "small"): lambda r: make_prices(r, ZONES_SMALL, "2022-01-01", "2025-01-01", "h"),
    ("prices", "large"): lambda r: make_prices(r, ZONES_LARGE, "2015-01-01", "2025-01-01", "15min"),
    ("powerflow", "small"): lambda r: make_powerflow(r, 100_000),
    ("powerflow", "large"): lambda r: make_powerflow(r, 1_200_000),
    ("weather", "small"): lambda r: make_weather(r, 100_000),
    ("weather", "large"): lambda r: make_weather(r, 3_000_000),
    ("assets", "small"): lambda r: make_assets(r, 100_000),
    ("assets", "large"): lambda r: make_assets(r, 2_000_000),
}

BLURB = {
    "prices": "Day-ahead prices per bidding zone, long format. Narrow, "
              "strongly autocorrelated, one tz-aware timestamp column.",
    "powerflow": "Power flow solver output: one row per snapshot, 40 float "
                 "columns across 20 corridors, half full precision and half rounded.",
    "weather": "KNMI-shaped observations: mixed dtypes, two categoricals, "
               "nullable integers and real sensor gaps.",
    "assets": "Connection register: EAN18 and connection id are unique per row, "
              "plus gemeente and netbeheerder categories and a free-text field.",
}


def main() -> None:
    TESTDATA.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    manifest = []
    for (corpus, scale), fn in SPECS.items():
        rng = np.random.default_rng(SEED + hash((corpus, scale)) % 10_000)
        df = fn(rng)
        path = TESTDATA / f"{corpus}_{scale}.arrow"
        df.to_feather(path, compression="uncompressed")
        mem = int(df.memory_usage(deep=True).sum())
        manifest.append(dict(corpus=corpus, scale=scale, rows=len(df),
                             cols=len(df.columns), mem_bytes=mem,
                             path=str(path.relative_to(ROOT)),
                             blurb=BLURB[corpus]))
        print(f"{corpus:<10} {scale:<6} {len(df):>9,} rows x {len(df.columns):>2} cols  "
              f"{mem / 1e6:>8.1f} MB in memory")
    (DATA / "corpora.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
