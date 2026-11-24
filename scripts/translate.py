"""
English labels for the synthetic data.

The German labels are those of the data standard (Caritas Datenstandard
v1.0, published in German and French). Both language versions contain
exactly the same records.
"""
from __future__ import annotations

import pandas as pd

# --------------------------------------------------------------------------
# Column names (German -> English)
# --------------------------------------------------------------------------
REASON_COLS = {
    "zu_geringes_einkommen": "insufficient_income",
    "schulden": "debt",
    "erwerbslosigkeit": "unemployment",
    "administrative_unterstuetzung": "administrative_support",
    "gesundheitliche_probleme": "health_problems",
    "wohnsituation": "housing_situation",
    "probleme_familie_partnerschaft": "family_or_relationship_problems",
    "rechtliche_probleme": "legal_problems",
    "andere": "other",
}

COLS_EVENTS = {
    "Ereignis_ID": "event_id",
    "Datum_Leistung": "service_date",
    "Ereignisart": "event_type",
    "Ereignis_Anzahl_Minuten": "event_minutes",
    "Client_ID": "client_id",
    "Datum_Registrierung_Client": "client_registration_date",
    "Beratungsstelle": "office",
    "Client_Geburtsjahr": "client_birth_year",
    "Client_Geschlecht": "client_sex",
    "Client_PLZ": "client_postcode",
    "Client_Wohnort": "client_place_of_residence",
    "Client_Kanton": "client_canton",
    "Wohnsituation": "household_type",
    "Wohnform": "housing_type",
    "Kinder_im_Haushalt": "children_in_household",
    "Kinder_auswaerts": "children_elsewhere",
    "Zivilstand": "civil_status",
    "Nationalitaet": "nationality",
    "Aufenthaltsstatus": "residence_status",
    "Aufenthaltsstatus_Detail": "residence_status_detail",
    "Erwerbssituation": "employment_status",
    **{f"Grund_{k}": f"reason_{v}" for k, v in REASON_COLS.items()},
}

# --------------------------------------------------------------------------
# Value labels (German -> English)
# --------------------------------------------------------------------------
OFFICE = {
    "Beratungsstelle Zürich": "Office Zurich",
    "Beratungsstelle Bern": "Office Bern",
    "Beratungsstelle Basel": "Office Basel",
    "Beratungsstelle Lausanne": "Office Lausanne",
    "Beratungsstelle Luzern": "Office Lucerne",
}
SEX = {"männlich": "male", "weiblich": "female", "divers": "gender-diverse"}
HOUSEHOLD = {
    "Paar": "couple",
    "Familie mit Kindern": "family with children",
    "Einelternfamilie": "single-parent family",
    "Einpersonenhaushalt": "single-person household",
    "anderer Haushalt mit mehreren Personen": "other multi-person household",
}
CIVIL = {"ledig": "single", "verheiratet": "married", "getrennt": "separated",
         "geschieden": "divorced", "verwitwet": "widowed"}
RESIDENCE = {
    "Schweizer/in": "Swiss citizen",
    "Niederlassungsbewilligung (C)": "settlement permit (C)",
    "Aufenthaltsbewilligung (B)": "residence permit (B)",
    "Kurzaufenthaltsbewilligung (L)": "short-term residence permit (L)",
    "Vorläufig Aufgenommene (F)": "provisionally admitted (F)",
    "Asylsuchende (N)": "asylum seeker (N)",
    "Schutzstatus (S)": "protection status (S)",
    "Ohne Bewilligung": "no permit",
    "andere": "other",
}
RESIDENCE_DETAIL = {
    **RESIDENCE,
    "Aufenthaltsbewilligung (B) Studierende": "residence permit (B), student",
    "anerkannte/r Flüchtling (B/C/F)": "recognised refugee (B/C/F)",
    "Tourist/in": "tourist",
    "Asylsuchende mit Nichteintretensentscheid": "asylum seeker with non-entry decision",
    "unbekannt": "unknown",
}
EMPLOYMENT = {
    "erwerbstätig: angestellt": "employed",
    "erwerbstätig: selbstständig": "self-employed",
    "erwerbslos/auf Stellensuche": "unemployed / job-seeking",
    "IV-Rentner/in": "disability pensioner (IV)",
    "AHV-Rentner/in": "old-age pensioner (AHV)",
    "Hausfrau/Hausmann": "homemaker",
    "andere": "other",
}
REASON = {
    "zu geringes Einkommen": "insufficient income",
    "Schulden": "debt",
    "Erwerbslosigkeit": "unemployment",
    "administrative Unterstützung": "administrative support",
    "gesundheitliche Probleme": "health problems",
    "Wohnsituation": "housing situation",
    "Probleme in Familie oder Partnerschaft": "family or relationship problems",
    "rechtliche Probleme": "legal problems",
    "andere": "other",
}
EVENT = {
    "Erstgespräch": "initial consultation",
    "Besprechung mit KlientIn": "meeting with client",
    "Telefon": "phone call",
    "Berichterstattung": "report writing",
    "E-Mail": "e-mail",
    "Dokument": "document",
    "Besprechung mit Dritten": "meeting with third parties",
    "Gesuch an Fonds/Stiftung": "application to a fund or foundation",
    "Antrag": "benefit application",
    "Informationsbeschaffung": "information gathering",
    "Finanzsanierung": "debt restructuring",
    "Besuch": "home visit",
    "Konferenz": "case conference",
}
HOUSING = {
    "Mieter/in": "tenant",
    "Untermieter/in": "subtenant",
    "Wohneigentum": "owner-occupier",
    "gratis Unterkunft": "free accommodation",
    "ohne feste Unterkunft": "no fixed abode",
    "Kollektivunterkunft": "collective accommodation",
    "betreutes Wohnen": "supported housing",
    "Pension/Hotel": "boarding house / hotel",
    "stationäre Einrichtung": "residential institution",
}
NATIONALITY = {
    "Schweiz": "Switzerland", "Portugal": "Portugal", "Italien": "Italy",
    "Deutschland": "Germany", "Spanien": "Spain", "Frankreich": "France",
    "Kosovo": "Kosovo", "Türkei": "Türkiye", "Serbien": "Serbia",
    "Nordmazedonien": "North Macedonia", "Sri Lanka": "Sri Lanka",
    "Marokko": "Morocco", "Tunesien": "Tunisia", "Eritrea": "Eritrea",
    "Afghanistan": "Afghanistan", "Syrien": "Syria", "Somalia": "Somalia",
    "Irak": "Iraq", "Iran": "Iran", "Äthiopien": "Ethiopia", "Ukraine": "Ukraine",
    "Brasilien": "Brazil", "Bolivien": "Bolivia", "Kolumbien": "Colombia",
}

VALUES = {  # English column -> value map; place names stay in their official form
    "office": OFFICE, "client_sex": SEX, "household_type": HOUSEHOLD,
    "civil_status": CIVIL, "residence_status": RESIDENCE,
    "residence_status_detail": RESIDENCE_DETAIL, "employment_status": EMPLOYMENT,
    "event_type": EVENT, "housing_type": HOUSING,
    "nationality": NATIONALITY,
}


def to_english(df: pd.DataFrame, columns: dict) -> pd.DataFrame:
    """Rename columns and translate value labels; fail loudly on unknown labels."""
    out = df.rename(columns=columns)
    for col, mapping in VALUES.items():
        if col in out:
            unknown = set(out[col].dropna().unique()) - set(mapping)
            if unknown:
                raise ValueError(f"no English label for {col}: {sorted(unknown)}")
            out[col] = out[col].map(mapping, na_action="ignore")
    return out
