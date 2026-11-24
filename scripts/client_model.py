"""
Client-level building blocks for the synthetic data of the Sample CSO/NGO.

Value labels follow the Caritas Datenstandard v1.0
(https://doi.org/10.5281/zenodo.22919492). All distributions are hand-set;
no real records were used. The entry point is generate_synthetic_data.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Value labels exactly as defined in the standard (DE)
# --------------------------------------------------------------------------
GESCHLECHT = ["männlich", "weiblich", "divers"]
WOHNSITUATION = ["Paar", "Familie mit Kindern", "Einelternfamilie",
                 "Einpersonenhaushalt", "anderer Haushalt mit mehreren Personen"]
ZIVILSTAND = ["ledig", "verheiratet", "getrennt", "geschieden", "verwitwet"]
AUFENTHALT = ["Schweizer/in", "Niederlassungsbewilligung (C)",
              "Aufenthaltsbewilligung (B)", "Kurzaufenthaltsbewilligung (L)",
              "Vorläufig Aufgenommene (F)", "Asylsuchende (N)",
              "Schutzstatus (S)", "Ohne Bewilligung"]
ERWERB = ["erwerbstätig: angestellt", "erwerbstätig: selbstständig",
          "erwerbslos/auf Stellensuche", "IV-Rentner/in", "AHV-Rentner/in",
          "Hausfrau/Hausmann", "andere"]
GRUENDE = {  # column suffix -> label in the standard
    "zu_geringes_einkommen": "zu geringes Einkommen",
    "schulden": "Schulden",
    "erwerbslosigkeit": "Erwerbslosigkeit",
    "administrative_unterstuetzung": "administrative Unterstützung",
    "gesundheitliche_probleme": "gesundheitliche Probleme",
    "wohnsituation": "Wohnsituation",
    "probleme_familie_partnerschaft": "Probleme in Familie oder Partnerschaft",
    "rechtliche_probleme": "rechtliche Probleme",
    "andere": "andere",
}

# --------------------------------------------------------------------------
# Fictional organisation (Sample CSO/NGO): five counselling offices, each serving real
# Swiss postcodes (public reference data, no link to any real client)
# --------------------------------------------------------------------------
STELLEN = {
    "Beratungsstelle Zürich": (0.28, [("8004", "Zürich", "ZH"), ("8050", "Zürich", "ZH"),
                                      ("8400", "Winterthur", "ZH"), ("8600", "Dübendorf", "ZH"),
                                      ("8953", "Dietikon", "ZH")]),
    "Beratungsstelle Bern": (0.24, [("3011", "Bern", "BE"), ("3027", "Bern", "BE"),
                                    ("3008", "Bern", "BE"), ("3600", "Thun", "BE"),
                                    ("2502", "Biel/Bienne", "BE"), ("3400", "Burgdorf", "BE")]),
    "Beratungsstelle Basel": (0.18, [("4057", "Basel", "BS"), ("4058", "Basel", "BS"),
                                     ("4410", "Liestal", "BL"), ("4133", "Pratteln", "BL"),
                                     ("4600", "Olten", "SO")]),
    "Beratungsstelle Lausanne": (0.18, [("1004", "Lausanne", "VD"), ("1018", "Lausanne", "VD"),
                                        ("1020", "Renens VD", "VD"), ("1400", "Yverdon-les-Bains", "VD"),
                                        ("1800", "Vevey", "VD")]),
    "Beratungsstelle Luzern": (0.12, [("6003", "Luzern", "LU"), ("6020", "Emmenbrücke", "LU"),
                                      ("6300", "Zug", "ZG"), ("6430", "Schwyz", "SZ"),
                                      ("6460", "Altdorf UR", "UR")]),
}

# Nationality -> (weight, status profile)
NATIONEN = {
    "Schweiz": (0.45, "CH"), "Portugal": (0.05, "EU"), "Italien": (0.04, "EU"),
    "Deutschland": (0.02, "EU"), "Spanien": (0.02, "EU"), "Frankreich": (0.01, "EU"),
    "Kosovo": (0.04, "DRITT"), "Türkei": (0.03, "DRITT"), "Serbien": (0.02, "DRITT"),
    "Nordmazedonien": (0.015, "DRITT"), "Sri Lanka": (0.02, "DRITT"),
    "Marokko": (0.01, "DRITT"), "Tunesien": (0.01, "DRITT"),
    "Eritrea": (0.05, "ASYL"), "Afghanistan": (0.04, "ASYL"), "Syrien": (0.03, "ASYL"),
    "Somalia": (0.02, "ASYL"), "Irak": (0.015, "ASYL"), "Iran": (0.01, "ASYL"),
    "Äthiopien": (0.01, "ASYL"), "Ukraine": (0.04, "UA"),
    "Brasilien": (0.015, "LATAM"), "Bolivien": (0.01, "LATAM"), "Kolumbien": (0.01, "LATAM"),
}
STATUS_PROFILE = {  # probabilities over AUFENTHALT
    "CH":    [1, 0, 0, 0, 0, 0, 0, 0],
    "EU":    [0, .55, .38, .05, 0, 0, 0, .02],
    "DRITT": [0, .55, .30, 0, .05, .02, 0, .08],
    "ASYL":  [0, .12, .35, 0, .35, .15, 0, .03],
    "UA":    [0, .05, .05, 0, 0, 0, .90, 0],
    "LATAM": [0, .25, .25, .05, 0, 0, 0, .45],
}

YEAR_VOLUME = {2019: 1.00, 2020: 1.25, 2021: 1.15, 2022: 1.05,
               2023: 1.20, 2024: 1.25, 2025: 1.30}
MONTH_VOLUME = np.array([1.05, 1.05, 1.1, 1.0, 1.0, 0.95, 0.8, 0.8, 1.05, 1.1, 1.05, 0.85])
UKRAINE_FROM = pd.Timestamp("2022-03-01")

def pick(rng, labels, p):
    p = np.asarray(p, dtype=float)
    return labels[rng.choice(len(labels), p=p / p.sum())]


def sample_age(rng):
    bands = [(18, 24, .08), (25, 34, .22), (35, 44, .25), (45, 54, .20),
             (55, 64, .14), (65, 74, .07), (75, 92, .04)]
    lo, hi, _ = bands[rng.choice(len(bands), p=[b[2] for b in bands])]
    return int(rng.integers(lo, hi + 1))


def household(rng, age):
    if age >= 65:
        p = [.30, 0, 0, .60, .10]
    elif age <= 24:
        p = [.05, .10, .20, .35, .30]
    else:
        p = [.10, .24, .20, .36, .10]
    return pick(rng, WOHNSITUATION, p)


def children(rng, hh, sex, age):
    if hh in ("Familie mit Kindern", "Einelternfamilie"):
        k = int(rng.choice([1, 2, 3, 4, 5], p=[.40, .35, .17, .06, .02]))
        if age < 25 or age > 55:
            k = min(k, 2)
    elif hh == "anderer Haushalt mit mehreren Personen":
        k = int(rng.choice([0, 1, 2], p=[.70, .20, .10]))
    else:
        k = 0
    aus = 0
    if hh == "Einpersonenhaushalt" and 25 <= age <= 60:
        p_aus = [.72, .18, .10] if sex == "männlich" else [.96, .03, .01]
        aus = int(rng.choice([0, 1, 2], p=p_aus))
    elif hh != "Einpersonenhaushalt" and 25 <= age <= 60 and rng.random() < .03:
        aus = 1
    return k, aus


def civil_status(rng, hh, age):
    if age <= 24:
        return pick(rng, ZIVILSTAND, [.90, .08, .01, .01, 0])
    p = {
        "Paar": [.35, .65, 0, 0, 0],
        "Familie mit Kindern": [.13, .87, 0, 0, 0],
        "Einelternfamilie": [.30, 0, .25, .38, .07],
        "Einpersonenhaushalt": [.45, .03, .10, .30, .12] if age < 70 else [.15, .03, .05, .37, .40],
        "anderer Haushalt mit mehreren Personen": [.60, .15, .08, .12, .05],
    }[hh]
    return pick(rng, ZIVILSTAND, p)


def nationality(rng, date):
    names = list(NATIONEN)
    w = np.array([NATIONEN[c][0] for c in names])
    if date < UKRAINE_FROM:
        w[names.index("Ukraine")] = 0.003
    return names[rng.choice(len(names), p=w / w.sum())]


def residence(rng, nat, date):
    p = np.array(STATUS_PROFILE[NATIONEN[nat][1]], dtype=float)
    if date < UKRAINE_FROM:  # status S did not exist in practice before March 2022
        p[AUFENTHALT.index("Schutzstatus (S)")] = 0
        if nat == "Ukraine":
            p = np.array([0, .45, .45, .05, 0, 0, 0, .05])
    return pick(rng, AUFENTHALT, p)


def employment(rng, age, status, hh, sex):
    if age >= 65:
        return pick(rng, ERWERB, [.04, .01, 0, 0, .91, 0, .04])
    if status == "Asylsuchende (N)":
        return pick(rng, ERWERB, [.15, 0, .55, 0, 0, 0, .30])
    if status == "Schutzstatus (S)":
        return pick(rng, ERWERB, [.20, 0, .50, 0, 0, .05, .25])
    p = np.array([.34, .05, .32, .10, 0, .09, .10])
    if age <= 24:
        p = np.array([.30, .01, .30, .03, 0, .06, .30])  # 'andere' ~ in Ausbildung
    elif age >= 55:
        p = np.array([.28, .05, .35, .20, 0, .05, .07])
    if hh == "Einelternfamilie" and sex == "weiblich":
        p[ERWERB.index("Hausfrau/Hausmann")] += .08
    return pick(rng, ERWERB, p)


def reasons(rng, r):
    e, s, age = r["erwerbssituation"], r["aufenthaltsstatus"], r["alter"]
    p = {
        "zu_geringes_einkommen": .45 + (.20 if e and e.startswith("erwerbstätig") else 0)
                                 + (.10 if e == "AHV-Rentner/in" else 0),
        "schulden": .30 + (.05 if 30 <= age <= 55 else 0),
        "erwerbslosigkeit": .70 if e == "erwerbslos/auf Stellensuche" else .04,
        "administrative_unterstuetzung": .30 + (.25 if s not in (None, "Schweizer/in") else 0)
                                         + (.10 if age >= 65 else 0),
        "gesundheitliche_probleme": (.60 if e == "IV-Rentner/in" else .12) + (.10 if age >= 55 else 0),
        "wohnsituation": .20 + (.08 if r["beratungsstelle"] in
                                ("Beratungsstelle Zürich", "Beratungsstelle Lausanne") else 0),
        "probleme_familie_partnerschaft": .10 + (.15 if r["zivilstand"] in ("getrennt", "geschieden")
                                                 or r["wohnsituation"] == "Einelternfamilie" else 0),
        "rechtliche_probleme": .06 + (.15 if s in ("Ohne Bewilligung", "Asylsuchende (N)") else 0),
        "andere": .05,
    }
    hits = {k: int(rng.random() < min(v, .95)) for k, v in p.items()}
    if sum(hits.values()) == 0:  # at least one reason per client
        hits[max(p, key=p.get)] = 1
    return hits
