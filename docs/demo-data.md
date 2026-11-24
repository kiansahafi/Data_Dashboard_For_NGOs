# Try the synthetic demo data

The demo describes a fictional organisation with five counselling offices. It has 15,043 events from 2022 to 2025, involving 5,498 clients. Each event row repeats the client's characteristics, so use `COUNT(DISTINCT client_id)` when counting people.

Choose either language. The files contain the same records and missing values, with translated column names and category labels:

| Language | File |
| --- | --- |
| English | [counselling_events.csv](../data/en/counselling_events.csv) |
| German | [beratungsdaten_synthesized.csv](../data/de/beratungsdaten_synthesized.csv) |

These are simulated data for trying the software. Their patterns are invented and do not describe a real organisation or its clients. The [codebook](../data/codebook.csv) explains all 30 columns; [Synthetic data](synthetic-data.md) describes how they were made.

## Load a file through the importer

1. [Start the app](getting-started.md), then open the import URL shown by `./run.sh status` (normally [127.0.0.1:8090](http://127.0.0.1:8090)).
2. Choose one of the CSV files above and select **Review import**.
3. Keep the suggested types and **Keep value** transforms. Dates are already written as `YYYY-MM-DD`. Postcodes should stay as text. Empty cells mean "not recorded" and stay empty.
4. Check the validation results, then select **Import data**.
5. Open Superset and select **SQL > SQL Lab**. Choose **Caritas Local PostgreSQL**, then the `staging` schema.

For the English file, try:

```sql
SELECT
  COUNT(*) AS events,
  COUNT(DISTINCT client_id) AS clients
FROM staging.counselling_events;
```

For the German file, use `staging.beratungsdaten_synthesized` instead. A single import should give **15,043 events and 5,498 clients**. Replacing the existing table loads a fresh copy; appending the same file adds duplicate events.

The importer creates the staging table and keeps the original values in `raw`. It does not create the optional demo views described below. Starting the app does not load the files or create charts automatically.

## Create a first chart

In SQL Lab, run:

```sql
SELECT
  EXTRACT(YEAR FROM service_date)::integer AS year,
  COUNT(*) AS events,
  COUNT(DISTINCT client_id) AS clients
FROM staging.counselling_events
GROUP BY 1
ORDER BY 1;
```

Save the result as a dataset, then create a bar chart with `year` on the horizontal axis and `SUM(events)` as the metric. Add the chart to a new dashboard. Use `SUM(clients)` only for a chart grouped by year; adding those yearly client counts together counts clients who appear in several years more than once.

For German data, substitute `datum_leistung` for `service_date` and `staging.beratungsdaten_synthesized` for the table name.

## Optional: load the prepared schemas and views

The SQL files create separate `demo_en` and `demo_de` schemas, including client-level views and reasons for support in a format suited to bar charts. This is an alternative to the importer for the demo data. It does not use or alter the `staging` tables.

Run these commands from the project folder after starting the app. They use the runner's default PostgreSQL container name (`caritas_postgres`), database (`caritas`) and user (`caritas`). If you changed those settings, use your configured names instead.

Each schema file **drops and recreates its demo event table and dependent views**. Running it again replaces that language's demo data. Keep your own work in another schema.

English:

```sh
podman exec -i caritas_postgres psql -v ON_ERROR_STOP=1 -U caritas -d caritas < sql/schema_en.sql
podman exec -i caritas_postgres psql -v ON_ERROR_STOP=1 -U caritas -d caritas \
  -c "COPY demo_en.counselling_events FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')" \
  < data/en/counselling_events.csv
```

German:

```sh
podman exec -i caritas_postgres psql -v ON_ERROR_STOP=1 -U caritas -d caritas < sql/schema_de.sql
podman exec -i caritas_postgres psql -v ON_ERROR_STOP=1 -U caritas -d caritas \
  -c "COPY demo_de.beratungsdaten FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')" \
  < data/de/beratungsdaten_synthesized.csv
```

The CSV is passed through standard input; it does not need to be copied into the container. The schema loads columns in CSV order, so keep the supplied header and column order.

In Superset, select `demo_en` or `demo_de` as the schema and save any of these views as a dataset:

| English view | German view | Use |
| --- | --- | --- |
| `demo_en.v_counselling_events` | `demo_de.v_beratungsdaten` | One row per event, with year, month, age at service and ISO canton code |
| `demo_en.v_clients` | `demo_de.v_clients` | One row per client, with age group, event count and total minutes |
| `demo_en.v_reasons_for_support` | `demo_de.v_unterstuetzungsgruende` | One row per client and recorded reason |

For example, `SELECT COUNT(*) FROM demo_en.v_clients;` should return **5,498**. The reasons view has **12,438** rows; a client may have several reasons, so reason totals can exceed the number of clients. These views use all events in the supplied file. Their client ages and age groups refer to the year of registration, while event ages refer to the year of service.

## Optional: generate another version

The supplied CSV files are ready to use. To generate a different version, the helper needs Python 3.10 or later, NumPy and pandas. The app's import image already includes both Python packages.

After `./run.sh build`, this writes a new pair of CSV files under `exports/demo-preview/` and leaves the supplied demo files untouched:

```sh
mkdir -p exports/demo-preview
podman run --rm \
  -v "$PWD:/work:ro" \
  -v "$PWD/exports/demo-preview:/output" \
  -w /work \
  localhost/caritas-ingest:py3.12-ui-local \
  python scripts/generate_synthetic_data.py --clients 5500 --seed 2026 --out /output
```

Use your configured `INGEST_IMAGE` name if you changed it. The output directories are `en/` and `de/`. The `--clients` argument is the number of simulated profiles; some may have no events inside the observation window, so the exported number of clients can be smaller. Changing the seed or client count changes the result. Matching a seed across environments also requires matching the NumPy and pandas versions.

The generator uses [client_model.py](../scripts/client_model.py) for profiles and [translate.py](../scripts/translate.py) for English labels. It stops if it encounters a German category without a translation.
