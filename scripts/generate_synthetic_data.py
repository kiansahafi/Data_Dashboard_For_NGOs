#!/usr/bin/env python3
"""
Generate the synthetic counselling data of the Sample CSO/NGO, 2022–2025.

One single table: one row per counselling event, with all client
characteristics of the Caritas Datenstandard v1.0
(https://doi.org/10.5281/zenodo.22919492), including the reasons for
support, repeated on every event row of a client.

Fully synthetic: client profiles and event histories are simulated from
hand-set distributions for a fictional organisation. No real records were
used as model input; only the column layout of a typical export served as a
template.

Writes data/de/beratungsdaten_synthesized.csv (German labels of the standard)
and data/en/counselling_events.csv (same records, English labels).

Usage:
    python generate_synthetic_data.py --clients 5500 --seed 2026
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client_model as g  # noqa: E402
import translate  # noqa: E402

WINDOW_START = pd.Timestamp("2022-01-01")
WINDOW_END = pd.Timestamp("2025-12-31")
BDAYS = pd.bdate_range("2005-01-01", WINDOW_END)

# --------------------------------------------------------------------------
# Event types: (weight for follow-up events, median minutes, lognormal sigma,
#               cap, rounding step)
# --------------------------------------------------------------------------
EVENTS = {
    "Besprechung mit KlientIn":   (.40, 25, .60, 180, 5),
    "Telefon":                    (.16, 10, .60, 90, 5),
    "Berichterstattung":          (.10, 5, .80, 120, 5),
    "E-Mail":                     (.09, 5, .60, 60, 1),
    "Dokument":                   (.07, 3, .90, 60, 1),
    "Besprechung mit Dritten":    (.05, 15, .60, 150, 5),
    "Gesuch an Fonds/Stiftung":   (.03, 30, .40, 90, 5),
    "Antrag":                     (.02, 15, .70, 120, 5),
    "Informationsbeschaffung":    (.015, 10, .60, 60, 5),
    "Finanzsanierung":            (.00, 20, .50, 90, 5),   # only for debt cases
    "Besuch":                     (.005, 45, .50, 180, 15),
    "Konferenz":                  (.003, 90, .30, 180, 15),
}
ERSTGESPRAECH = ("Erstgespräch", 45, .40, 120, 5)

# --------------------------------------------------------------------------
# Detailed residence categories as an office might record them, and how they
# map to the standard (None = keine Angabe). Categories outside the standard
# go to "andere", as the standard prescribes.
# --------------------------------------------------------------------------
STATUS_DETAIL_TO_STANDARD = {
    "Schweizer/in": "Schweizer/in",
    "Niederlassungsbewilligung (C)": "Niederlassungsbewilligung (C)",
    "Aufenthaltsbewilligung (B)": "Aufenthaltsbewilligung (B)",
    "Aufenthaltsbewilligung (B) Studierende": "Aufenthaltsbewilligung (B)",
    "Kurzaufenthaltsbewilligung (L)": "Kurzaufenthaltsbewilligung (L)",
    "Vorläufig Aufgenommene (F)": "Vorläufig Aufgenommene (F)",
    "Asylsuchende (N)": "Asylsuchende (N)",
    "Schutzstatus (S)": "Schutzstatus (S)",
    "Ohne Bewilligung": "Ohne Bewilligung",
    "anerkannte/r Flüchtling (B/C/F)": "andere",
    "Tourist/in": "andere",
    "Asylsuchende mit Nichteintretensentscheid": "andere",
    "unbekannt": None,
}

WOHNFORM = ["Mieter/in", "Untermieter/in", "Wohneigentum", "gratis Unterkunft",
            "ohne feste Unterkunft", "Kollektivunterkunft", "betreutes Wohnen",
            "Pension/Hotel", "stationäre Einrichtung"]


def detail_status(rng, std_status, nat, reg):
    """Turn a standard status into the finer category an office records."""
    if std_status is None:
        return "unbekannt"
    grp = g.NATIONEN[nat][1]
    u = rng.random()
    if rng.random() < .05:
        return "unbekannt"
    if std_status == "Aufenthaltsbewilligung (B)" and u < .03:
        return "Aufenthaltsbewilligung (B) Studierende"
    if grp == "ASYL" and std_status in ("Aufenthaltsbewilligung (B)", "Niederlassungsbewilligung (C)") and u < .30:
        return "anerkannte/r Flüchtling (B/C/F)"
    if std_status == "Asylsuchende (N)" and u < .25:
        return "Asylsuchende mit Nichteintretensentscheid"
    if grp in ("LATAM", "EU", "DRITT") and std_status == "Ohne Bewilligung" and u < .35:
        return "Tourist/in"
    if nat == "Ukraine" and std_status == "Schutzstatus (S)" and reg < pd.Timestamp("2022-06-01") and u < .25:
        return "Tourist/in"   # recorded before S status was granted
    return std_status


def wohnform(rng, status, age, hh):
    p = np.array([.62, .05, .03, .09, .07, .02, .03, .02, .02])
    if status in ("Asylsuchende (N)", "Asylsuchende mit Nichteintretensentscheid"):
        p = np.array([.10, .03, 0, .12, .10, .60, .03, .02, 0])
    elif status in ("Vorläufig Aufgenommene (F)", "Schutzstatus (S)"):
        p = np.array([.45, .05, 0, .20, .02, .25, .02, .01, 0])
    elif status in ("Ohne Bewilligung", "Tourist/in"):
        p = np.array([.10, .25, 0, .40, .20, .01, 0, .04, 0])
    if age >= 75:
        p[WOHNFORM.index("betreutes Wohnen")] += .08
        p[WOHNFORM.index("stationäre Einrichtung")] += .05
        p[WOHNFORM.index("ohne feste Unterkunft")] = 0
    if hh in ("Familie mit Kindern", "Einelternfamilie"):
        p[WOHNFORM.index("ohne feste Unterkunft")] *= .2
        p[WOHNFORM.index("stationäre Einrichtung")] = 0
    return g.pick(rng, WOHNFORM, p)


def registration_date(rng):
    """65 % new clients in 2022–2025, 35 % long-standing clients (2008–2021)."""
    if rng.random() < .65:
        days = BDAYS[BDAYS >= WINDOW_START]
        w = np.array([g.YEAR_VOLUME[d.year] * g.MONTH_VOLUME[d.month - 1] for d in days])
    else:
        days = BDAYS[(BDAYS >= "2008-01-01") & (BDAYS < WINDOW_START)]
        w = 1 + (days.year.values - 2008) / 8          # more recent = more likely still active
    return pd.Timestamp(rng.choice(days.values, p=w / w.sum()))


def n_events(rng):
    k = 1 + rng.negative_binomial(0.55, 0.55 / (0.55 + 1.9))
    return int(min(k, 150))


def minutes(rng, spec):
    _, med, sigma, cap, step = spec
    m = rng.lognormal(np.log(med), sigma)
    return int(min(cap, max(step, round(m / step) * step)))


def event_dates(rng, reg, k):
    """Events cluster in episodes; long-standing clients re-enter in the window."""
    new = reg >= WINDOW_START
    if new:  # first contact (Erstgespräch) on the day of registration or shortly after
        start = reg if rng.random() < .85 else reg + pd.offsets.BDay(int(rng.integers(1, 10)))
    else:
        start = pd.Timestamp(rng.choice(
            pd.bdate_range(WINDOW_START, WINDOW_END - pd.Timedelta(days=30)).values))
    span = max(1, int(k * rng.exponential(22)))
    offs = np.sort(rng.integers(0, span + 1, size=k))
    offs -= offs[0]
    if k > 3 and rng.random() < .15:                      # second episode later on
        cut = rng.integers(1, k)
        offs[cut:] += int(rng.exponential(300)) + 60
    dates = [start + pd.offsets.BDay(int(o * 5 / 7)) for o in offs]
    return [d for d in dates if WINDOW_START <= d <= WINDOW_END], new


def followup_weights(c, year):
    names = list(EVENTS)
    w = np.array([EVENTS[n][0] for n in names])
    if c["grund_schulden"] == 1:
        w[names.index("Finanzsanierung")] = .05
        w[names.index("Besprechung mit Dritten")] += .03
    if c["grund_zu_geringes_einkommen"] == 1:
        w[names.index("Gesuch an Fonds/Stiftung")] += .03
    if c["grund_administrative_unterstuetzung"] == 1:
        w[names.index("Dokument")] += .03
        w[names.index("Antrag")] += .02
    if c["alter"] >= 75:
        w[names.index("Besuch")] += .04
    w[names.index("E-Mail")] *= 1 + .15 * (year - 2022)   # slow shift to e-mail
    return names, w / w.sum()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--clients", type=int, default=5500)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    de, en = a.out / "de", a.out / "en"
    de.mkdir(parents=True, exist_ok=True)
    en.mkdir(parents=True, exist_ok=True)

    stellen = list(g.STELLEN)
    ids = rng.choice(np.arange(100000, 1000000), size=a.clients, replace=False)
    rows = []
    for cid in ids:
        reg = registration_date(rng)
        stelle = stellen[rng.choice(len(stellen), p=[g.STELLEN[s][0] for s in stellen])]
        plz, ort, kt = g.STELLEN[stelle][1][rng.integers(len(g.STELLEN[stelle][1]))]
        age = g.sample_age(rng)
        while age + (WINDOW_END.year - reg.year) > 95:   # keep long-standing clients plausible
            age = g.sample_age(rng)
        hh = g.household(rng, age)
        if rng.random() < .05:
            sex = "divers"
        else:
            sex = g.pick(rng, g.GESCHLECHT, [.14, .86, 0] if hh == "Einelternfamilie" else [.5, .5, 0])
        kin, aus = g.children(rng, hh, sex, age)
        nat = g.nationality(rng, reg)
        std = g.residence(rng, nat, reg)
        det = detail_status(rng, std, nat, reg)
        c = dict(client_id=int(cid), reg=reg, stelle=stelle, plz=plz, ort=ort, kt=kt, alter=age,
                 geburtsjahr=(reg - pd.DateOffset(years=age)).year - int(rng.random() < .5),
                 sex=sex, hh=hh, kin=kin, aus=aus, zivil=g.civil_status(rng, hh, age), nat=nat,
                 det=det, std=STATUS_DETAIL_TO_STANDARD[det],
                 wohnform=wohnform(rng, det, age, hh))
        c["erwerb"] = g.employment(rng, age, c["std"], hh, sex)
        gr = g.reasons(rng, dict(erwerbssituation=c["erwerb"], aufenthaltsstatus=c["std"], alter=age,
                                 beratungsstelle=stelle, zivilstand=c["zivil"], wohnsituation=hh))
        c.update({f"grund_{k}": v for k, v in gr.items()})

        k = n_events(rng)
        dates, new = event_dates(rng, reg, k)
        for j, d in enumerate(dates):
            if new and j == 0 and d <= reg + pd.Timedelta(days=14):
                art, spec = ERSTGESPRAECH[0], ERSTGESPRAECH
            else:
                names, w = followup_weights(c, d.year)
                art = names[rng.choice(len(names), p=w)]
                spec = EVENTS[art]
            rows.append({**c, "datum": d, "seq": j, "art": art, "min": minutes(rng, spec)})

    df = (pd.DataFrame(rows)
            .sort_values(["datum", "client_id", "seq"], kind="mergesort")
            .reset_index(drop=True))

    out = pd.DataFrame({
        "Ereignis_ID": np.arange(1, len(df) + 1),
        "Datum_Leistung": df.datum.dt.date,
        "Ereignisart": df.art,
        "Ereignis_Anzahl_Minuten": df["min"].astype("Int64"),
        "Client_ID": df.client_id,
        "Datum_Registrierung_Client": df.reg.dt.date,
        "Beratungsstelle": df.stelle,
        "Client_Geburtsjahr": df.geburtsjahr.astype("Int64"),
        "Client_Geschlecht": df.sex,
        "Client_PLZ": df.plz,
        "Client_Wohnort": df.ort,
        "Client_Kanton": df.kt,
        "Wohnsituation": df.hh,
        "Wohnform": df.wohnform,
        "Kinder_im_Haushalt": df.kin.astype("Int64"),
        "Kinder_auswaerts": df.aus.astype("Int64"),
        "Zivilstand": df.zivil,
        "Nationalitaet": df.nat,
        "Aufenthaltsstatus": df["std"],
        "Aufenthaltsstatus_Detail": df.det,
        "Erwerbssituation": df.erwerb,
        **{f"Grund_{k}": df[f"grund_{k}"].astype("Int64") for k in g.GRUENDE},
    })

    # realistic gaps, set per client so they stay constant across a client's events
    clients = out.Client_ID.unique()
    def blank(cols, share):
        hit = set(rng.choice(clients, size=int(share * len(clients)), replace=False))
        out.loc[out.Client_ID.isin(hit), cols] = pd.NA
    blank(["Client_Geburtsjahr"], .015)
    blank(["Client_PLZ", "Client_Wohnort", "Client_Kanton"], .01)
    blank(["Wohnsituation"], .04)
    blank(["Wohnform"], .18)
    blank(["Kinder_im_Haushalt"], .05)
    blank(["Kinder_auswaerts"], .15)
    blank(["Zivilstand"], .06)
    blank(["Nationalitaet"], .03)
    blank(["Erwerbssituation"], .07)
    blank([c for c in out if c.startswith("Grund_")], .02)
    # rare gaps at event level
    out.loc[rng.random(len(out)) < .005, "Ereignisart"] = pd.NA
    out.loc[rng.random(len(out)) < .005, "Ereignis_Anzahl_Minuten"] = pd.NA

    out.to_csv(de / "beratungsdaten_synthesized.csv", index=False, encoding="utf-8")
    translate.to_english(out, translate.COLS_EVENTS).to_csv(
        en / "counselling_events.csv", index=False, encoding="utf-8")
    print(f"wrote {len(out)} events for {out.Client_ID.nunique()} clients to {de} and {en}")


if __name__ == "__main__":
    main()
