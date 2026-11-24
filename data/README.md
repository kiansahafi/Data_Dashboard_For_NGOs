# Synthetic demo data

**These data are entirely synthetic.** They describe a fictional organisation, the *Sample CSO/NGO*, with five counselling offices.

- The data were simulated from hand-set distributions. They were **not** derived from, fitted to or sampled from any real client records, so they carry no disclosure risk.
- The distributions are stylised to look like typical counselling data from a Swiss social welfare CSO. They are not estimates, and figures computed from them must not be cited as empirical findings.

The full rationale, including the data-protection reasoning and why no real data were used even as a basis for synthesis, is in [`docs/synthetic-data.md`](../docs/synthetic-data.md).

## One table, two languages

All data are in **one single CSV file**:
- one row per counselling event, 2022–2025: **15,043 events of 5,498 clients**
- each row also carries the client's characteristics and reasons for support

This mirrors an export from case-management software and keeps everything in one sheet. The client characteristics repeat on every event of a client and are identical on each of these rows.

| | English | German |
|---|---|---|
| **File** | [`en/counselling_events.csv`](en/counselling_events.csv) | [`de/beratungsdaten_synthesized.csv`](de/beratungsdaten_synthesized.csv) |
| **Labels** | English | labels of the data standard |
| **Database schema** | [`sql/schema_en.sql`](../sql/schema_en.sql) → schema `demo_en` | [`sql/schema_de.sql`](../sql/schema_de.sql) → schema `demo_de` |

Both files contain **identical records**: same IDs, same values and same missing cells, row by row. Only column names and labels differ.

The variables follow the **Caritas data standard for social counselling, version 1.0** (Caritas Schweiz & Sutter 2026, [doi:10.5281/zenodo.22919492](https://doi.org/10.5281/zenodo.22919492)), which is published in German and French. [`codebook.csv`](codebook.csv) lists every column with:
- its English and German name and a description
- whether it belongs to the standard
- its labels in English, German and French

All files are UTF-8 CSV with a header row. Dates are ISO (`YYYY-MM-DD`). **An empty cell means "not recorded"** (*keine Angabe*) and is loaded as `NULL`.

## Try the data

Upload either language version through the local data importer, review the columns, and import it into a staging table. The files contain the same records, so choose one language for an analysis rather than adding their totals together.

The demo files are not loaded automatically on startup. See [loading the demo data](../docs/demo-data.md) for the browser workflow and the optional SQL setup with analysis views.

## Columns

| Column (EN) | Column (DE) | Content |
|---|---|---|
| `event_id` | `Ereignis_ID` | running event number |
| `service_date` | `Datum_Leistung` | date of the event |
| `event_type` | `Ereignisart` | initial consultation, meeting with client, phone call, e-mail, report writing … (13 types) |
| `event_minutes` | `Ereignis_Anzahl_Minuten` | time spent, in minutes |
| `client_id` | `Client_ID` | random 6-digit client number |
| `client_registration_date` | `Datum_Registrierung_Client` | registration date (= *first entry* in the standard), kept separate from the event date |
| `office` | `Beratungsstelle` | one of five fictional offices |
| `client_birth_year` | `Client_Geburtsjahr` | year of birth |
| `client_sex` | `Client_Geschlecht` | female, male, gender-diverse |
| `client_postcode`, `client_place_of_residence`, `client_canton` | `Client_PLZ`, `Client_Wohnort`, `Client_Kanton` | place of residence: real Swiss postcodes, assigned at random |
| `household_type` | `Wohnsituation` | household type |
| `housing_type` | `Wohnform` | type of housing (tenant, free accommodation, no fixed abode, collective accommodation …); an extension, not part of the standard |
| `children_in_household`, `children_elsewhere` | `Kinder_im_Haushalt`, `Kinder_auswaerts` | number of dependent children |
| `civil_status`, `nationality`, `employment_status` | `Zivilstand`, `Nationalitaet`, `Erwerbssituation` | categories of the standard |
| `residence_status` | `Aufenthaltsstatus` | categories of the standard; anything outside them becomes *other* |
| `residence_status_detail` | `Aufenthaltsstatus_Detail` | the finer category an office would record, e.g. *recognised refugee*, *tourist*, *non-entry decision*, *unknown* |
| `reason_insufficient_income` … `reason_other` (9 columns) | `Grund_zu_geringes_einkommen` … `Grund_andere` | reasons for support, multiple response: 1 = named, 0 = not named |

Not part of the standard are:
- the event columns and `client_id`, which every export contains
- `office`, to demonstrate filtering by office
- `client_canton`, derived from the postcode, for map charts
- `housing_type` and `residence_status_detail`, described above

## Working at client level

Because client characteristics repeat across events, count clients with `COUNT(DISTINCT client_id)` rather than `COUNT(*)`. The optional SQL schema files provide three views after you load them. A web import creates staging tables without these views; the [demo-data guide](../docs/demo-data.md) explains both routes.

| View (EN / DE) | One row per | Use for |
|---|---|---|
| `v_counselling_events` / `v_beratungsdaten` | event | activity over time, event types, time spent; adds year, month, age at the event and an ISO canton code |
| `v_clients` | client | profiles, shares of clients, age groups; adds number of events, total minutes, first and last event |
| `v_reasons_for_support` / `v_unterstuetzungsgruende` | client × reason | bar charts of the reasons for support |

## How the events behave

- About 65 % of clients register in 2022–2025. Their first event is always an initial consultation, on the registration day or shortly after. The other 35 % are long-standing clients, registered 2008–2021, who come back during the period.
- Events come in episodes. Three in four clients have 1–3 events, a few have long case histories, and some come back months later.
- The event type depends on the client's profile:
  - debt cases get debt restructuring
  - low-income cases get more applications to funds and foundations
  - older clients get more home visits
  - e-mail slowly gains share over the years
- The pair `residence_status_detail` → `residence_status` shows the harmonisation step the standard asks for: local categories are mapped to the standard, and extra categories go to *other*.

## Built-in logic

The records are internally consistent, so that charts and filters behave as they would with real data:

- **Sex.** About 54 % of clients are women, 41 % men and 5 % gender-diverse. The standard currently lists only female and male; the third category is included so that dashboards are built for it from the start.
- **Residence status** matches nationality. Swiss nationals are always *Swiss citizen*, and *protection status (S)* only appears from March 2022.
- **Pensions.** Old-age (AHV) pensioners are 65 or older.
- **Children.**
  - Family households always have children in the household, and single-person households never do.
  - Single parents are mostly women. Children living elsewhere mostly belong to separated or divorced men living alone.
- **Reasons for support** depend on the profile. For example, unemployment is usually named for job seekers and health problems for disability (IV) pensioners. Every client with recorded reasons has at least one.
- **Volume.** New registrations rise from 2023, with a dip in summer and in December.
- **Missing values** of 1–17 % per characteristic are built in on purpose, so the dashboard can show how it handles incomplete records.

## Regenerate

```bash
python scripts/generate_synthetic_data.py --clients 5500 --seed 2026
```

The script writes both language versions. The same seed always gives the same data; change `--clients` or `--seed` for other variants.

- [`scripts/client_model.py`](../scripts/client_model.py) holds the client profiles.
- [`scripts/translate.py`](../scripts/translate.py) holds the English labels. It stops with an error if a German label has no English counterpart, so the two versions cannot drift apart.

## Licence

CC BY 4.0, the same as the data standard.
