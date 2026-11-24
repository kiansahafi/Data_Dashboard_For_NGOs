# Run the dashboard

[Back to the introduction](../README.md)

## Before you start

You need [Podman](https://podman.io/docs/installation), a browser, and a copy of this project. The commands below use a Bash terminal. On Windows, use a Bash environment with access to your Podman installation; `run.sh` is not a PowerShell script.

If you're starting from a portable backup, follow [the restore guide](backup-restore.md) instead. It includes the app and its container images, so you can restore without downloading them again.

## First start

Open a terminal in the project folder. On macOS, create a Podman machine if you don't have one yet, then start it:

```sh
podman machine init
podman machine start
```

You only need `podman machine init` once. If the machine is already running, go straight to:

```sh
./run.sh start
```

The first start downloads and builds the required images. Later starts use the local copies.

When setup finishes, open:

| What you want to do | Usual address |
| --- | --- |
| Import a file | [Data importer](http://127.0.0.1:8090) |
| Build or view charts | [Superset](http://127.0.0.1:8088) |

Sign in to Superset with username `admin` and password `admin`, unless you chose different details before setup.

If an address doesn't work, run:

```sh
./run.sh status
```

The runner chooses another port if a default port is busy. `status` shows the addresses it actually uses. All app ports bind to `127.0.0.1` on this computer.

## Import your data

For a first try, use the supplied [English or German synthetic demo files](../data/README.md). The [demo-data guide](demo-data.md) includes loading instructions and optional SQL views. These files are not loaded automatically when the app starts.

1. Open the data importer and choose a `.csv`, `.xls`, or `.xlsx` file.
2. Select **Review import**. For each column, check the suggested type and sample values. Keep postal codes and identifiers as text if their leading zeros matter.
3. Change a type or transform where needed. The importer checks every row and shows counts for valid, empty, and invalid values, with examples and source row numbers. Look at the converted examples to check that the result means what you intended.
4. Resolve invalid values before importing. You can choose a suitable type or transform, or correct the source file and upload it again. Blank cells are allowed and become empty database values.
5. Check the replacement setting, then select **Import data** once validation passes.

The transform menu follows the selected data type:

| Type | Available transforms |
| --- | --- |
| Text / postal code | Keep value, trim spaces, lowercase, uppercase, extract leading number |
| Integer, large integer, decimal | Keep value, extract leading number, explicit decimal comma or decimal point parsing |
| Date, date and time | Keep value, day-month-year, month-day-year, year-month-day, Excel serial date |

For ambiguous dates such as `03/04/2026`, choose the intended date order. The Excel serial transform uses Excel's 1900 date system. It rejects serial 60 because that value stands for the nonexistent 29 February 1900. Numeric transforms support examples such as `1.234,56` for decimal comma and `1,234.56` for decimal point.

A transform changes the value stored in the staging table. The original cell value stays in the raw import record. **Extract leading number** reports an error for a non-empty cell without a leading number, so those values aren't silently lost.

The web importer selects **Replace existing staging tables** by default. This replaces the table for the same file or sheet and removes its previous raw import records. Clear it only if you want to append more rows. Append mode keeps the existing table's column types, so the importer reports a type conflict before loading if your choices don't match. Appending the same file twice creates duplicate data.

Replacing a table also drops PostgreSQL views that depend on it. Recreate those views afterwards if you use them for reports.

Empty Excel sheets are skipped. Each non-empty sheet gets its own staging table when a workbook has several sheets. Table and column names use lowercase letters, numbers, and underscores; the preview shows the names that Superset will see.

### Import from the terminal

Put the file inside the project folder, for example in `data/`, and run:

```sh
./run.sh import data/example.xlsx
```

This uses automatic type detection and appends a new batch. Use the web importer if you want to review types, choose transforms, or replace an existing table.

## Make your first chart

1. Open Superset and sign in.
2. Open **Datasets** and add a dataset.
3. Choose **Caritas Local PostgreSQL**, the `staging` schema, and the table shown in the import result.
4. Open the dataset, choose a chart type, and select the columns and calculation you want.
5. Save the chart. You can add it to a dashboard when saving or create a dashboard from the **Dashboards** page.

For a step-by-step SQL example, see [case and service analysis](analytics-example.md).

## Stop and start again

```sh
./run.sh stop
./run.sh start
```

Stopping keeps your data, charts, and dashboards. Make a [backup](backup-restore.md) before moving the app or making changes you may want to undo.

`./run.sh reset` deletes the app's containers and persistent data volumes after you type the requested confirmation phrase. Use it only when you want to remove that local installation's stored work.

## Settings and troubleshooting

You can choose different ports before the first start:

```sh
POSTGRES_PORT=15432 SUPERSET_PORT=18088 IMPORT_UI_PORT=18090 ./run.sh start
```

If you choose a port explicitly and it's busy, the runner stops and asks you to choose another. Port choices are saved in `.caritas-local.env`.

For an installation used by other people, set your own password and Superset secret before the first start:

```sh
SUPERSET_ADMIN_PASSWORD='choose-a-password' \
SUPERSET_SECRET_KEY='choose-a-long-random-secret' \
./run.sh start
```

Keep the secret key with the installation. Superset uses it to encrypt saved database credentials. Changing the password variable after the admin account already exists does not reset that account's password; change it through Superset's user management.

If Podman isn't running, start its machine and try again. If an import fails, check the column errors in the importer before retrying. If an imported column changed type, refresh the dataset's column metadata in Superset before using that column in a chart.

## Where the data goes

PostgreSQL stores the imported data in these schemas:

| Table or schema | Contents |
| --- | --- |
| `raw.import_batches` | The file, sheet, and row count for each import |
| `raw.import_rows` | Original cell values as JSON, with their source row numbers |
| `staging.<table_name>` | The typed and transformed values used for analysis |
| `analytics.import_batches` | A view of the import history |

Superset keeps chart and dashboard definitions in its own metadata database. Both PostgreSQL data and Superset metadata live in Podman volumes, outside the source files. See [backup and restore](backup-restore.md) for how to copy the complete app.
