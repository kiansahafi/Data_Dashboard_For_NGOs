# Local Caritas Dashboard

This is a fully local v1 scaffold for the Caritas data dashboard prototype. It runs PostgreSQL and Apache Superset with Podman and keeps all user operations behind one shell file.

## Requirements

- Podman installed.
- On macOS, a running Podman machine:

```sh
podman machine start
```

The first setup may download and build container images. After that, the stack runs locally without internet.

## Start

```sh
./run.sh start
```

Superset will be available at:

```text
http://127.0.0.1:8088
```

The local import UI will be available at:

```text
http://127.0.0.1:8090
```

If port `5432`, `8088`, or `8090` is already in use, `run.sh` automatically chooses a nearby free localhost port and stores it in `.caritas-local.env`. Check the actual URL with:

```sh
./run.sh status
```

Default local login:

```text
admin / admin
```

## Import Data

Open the local import UI:

```text
http://127.0.0.1:8090
```

Upload a CSV or Excel file, review the suggested column types, optionally change a column's type, and import it. Use the `Extract leading number` transform when a text-coded category such as `03 Familie` should be stored as a number or code in staging.

For scripted imports, put local files in `data/`, then run:

```sh
./run.sh import data/example.xlsx
```

Supported formats:

- `.csv`
- `.xls`
- `.xlsx`

Imports create flexible raw and staging tables:

- `raw.import_batches`
- `raw.import_rows`
- `staging.<file_or_sheet_name>`
- `analytics.import_batches`

Raw rows keep the imported cell values as JSON. Staging columns are automatically typed where possible
(`date`, `timestamp`, `integer`, `bigint`, `numeric`, or `text`), while postal-code columns such as
`Postleitzahl`/`PLZ` stay as text. Existing staging tables keep their current column definitions, so
reset and re-import old all-text tables if you want inferred types.

The registered Superset PostgreSQL database has file uploads enabled automatically, so Superset's own CSV/Excel upload menu is available without manually changing the database security settings.

Use the Superset UI to create datasets, charts, and dashboards from these tables.
Empty Excel worksheets are skipped. Re-importing the same workbook appends another batch, so do not rerun an import unless duplicate batches are intended.

## Superset Analytics Example

Open `http://127.0.0.1:8088` and sign in with `admin / admin`.

### Inspect the imported table

1. Open **SQL > SQL Lab**.
2. Select **Caritas Local PostgreSQL** as the database and `staging` as the schema.
3. Run:

```sql
SELECT *
FROM staging.ecase_basel_kd
LIMIT 100;
```

The `ecase_basel_kd` table has one row per service-related record, not one row per case. Use the two virtual datasets below to avoid mixing those grains.

### Create a case-level dataset

Run this query in SQL Lab:

```sql
SELECT DISTINCT ON (fallbearbeitungsnummer_kd)
  fallbearbeitungsnummer_kd AS case_id,
  aufnahmedatum_jahr_kd AS intake_year,
  geschlecht_kl AS gender,
  alter_kl AS age,
  kanton_kl AS canton,
  nation_kl AS nationality,
  haushaltsgr_sse_kl AS household_size,
  aufenthaltsstatus_kl AS residence_status
FROM staging.ecase_basel_kd
WHERE fallbearbeitungsnummer_kd IS NOT NULL
ORDER BY fallbearbeitungsnummer_kd, source_row_number;
```

After it runs, select **Save > Save dataset** and name it `ECase Basel - Cases`. It should contain 1,820 rows.

Suggested charts from this dataset:

- **Big Number**: metric `COUNT(*)`, title `Cases`.
- **Bar Chart**: X-axis `intake_year`, metric `COUNT(*)`, title `Cases by intake year`.
- **Pie Chart**: dimension `gender`, metric `COUNT(*)`, title `Cases by gender`.
- **Histogram**: numeric column `age`, title `Age distribution`.
- **Bar Chart**: dimension `residence_status`, metric `COUNT(*)`, row limit `10`.

### Create a service-level dataset

Run this query in SQL Lab:

```sql
SELECT
  import_row_id AS service_row_id,
  fallbearbeitungsnummer_kd AS case_id,
  leistung_von_jahr_le AS service_year,
  leistungsart_le AS service_type,
  bezeichnung_le AS service_name,
  gesch_ftsstelle_le AS office
FROM staging.ecase_basel_kd;
```

Save it as `ECase Basel - Services`. It should contain 7,118 rows.

Suggested charts from this dataset:

- **Big Number**: metric `COUNT(*)`, title `Service records`.
- **Bar Chart**: dimension `service_type`, metric `COUNT(*)`, row limit `10`, descending order.
- **Bar Chart**: X-axis `service_year`, metric `COUNT(*)`, title `Services by year`.
- **Bar Chart**: dimension `office`, metric `COUNT(*)`, title `Services by office`.

### Assemble the dashboard

1. Save each chart after configuring it in **Explore**.
2. Open **Dashboards**, create `ECase Basel Overview`, and add the saved charts.
3. In dashboard edit mode, add native filters for `intake_year`, `gender`, `service_year`, and `service_type`.
4. Keep tables and identifiers out of the dashboard. This source contains potentially identifying fields, so use aggregated charts for local analysis.

## Common Commands

```sh
./run.sh status
./run.sh stop
./run.sh backup
./run.sh reset
```

`reset` deletes local containers and persistent volumes only after an exact confirmation phrase.

## Configuration

You can override ports and credentials with environment variables:

```sh
POSTGRES_PORT=15432 SUPERSET_PORT=18088 IMPORT_UI_PORT=18090 ./run.sh start
SUPERSET_ADMIN_PASSWORD='new-password' ./run.sh start
```

Explicitly supplied ports are not auto-changed. If one is busy, the runner stops and asks you to choose another value.

For a shared machine, set a stronger `SUPERSET_SECRET_KEY` and admin password before the first start.
