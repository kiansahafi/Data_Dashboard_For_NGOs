# Use the data in Power BI and Superset

[Back to the introduction](../README.md)

Power BI and Superset can use the same PostgreSQL tables. This project does not have a converter for Power BI reports and Superset dashboards. You can share the data and the calculation rules, then build the visuals in each tool.

## What can be shared?

| What you want to share | How to do it | What carries over |
| --- | --- | --- |
| Imported data | Connect both tools to this app's PostgreSQL database | The same typed rows and columns |
| Totals and indicators | Put reusable calculations in PostgreSQL views and use those views in both tools | The SQL calculation; each tool still needs its own chart settings |
| A one-off table of results | Export CSV from one tool and load it in the other | The exported rows, including any filters or aggregation applied to them |
| A picture of a chart | Export an image or take a screenshot | A static picture; filters and drill-down do not carry over |
| An editable dashboard or report | Rebuild it in the destination tool | Layouts, filters, DAX measures, and visual settings need to be recreated |
| Superset work on another Superset installation | Use the app backup, or Superset's own asset export/import | Superset definitions; asset exports alone do not copy PostgreSQL rows |

Superset's export/import formats describe its own assets. They are not a Power BI report format. That is why this project's transfer route uses PostgreSQL or CSV for data and a manual rebuild for editable visuals. [Superset export/import documentation](https://superset.apache.org/docs/configuration/importing-exporting-datasources/)

## Connect Power BI Desktop

Power BI Desktop is a Windows application. It does not run natively on macOS. For this local setup, the easiest arrangement is to run Power BI Desktop and the dashboard app on the same Windows computer. [Microsoft's installation requirements](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop)

Start the app and run:

```sh
./run.sh status
```

Use the PostgreSQL port shown there. With the defaults, the connection details are:

| Field | Value |
| --- | --- |
| Server | `127.0.0.1:5432` |
| Database | `caritas` |
| Username | `caritas`, or a separate account created below |
| Password | `caritas_local_password`, unless changed during setup |
| Tables | The `staging` tables or the reporting views you created |

These are PostgreSQL credentials, separate from the Superset `admin` login. Saved installation settings may override the defaults.

In Power BI Desktop, select **Get data > PostgreSQL database**, enter the server and database, and choose **Import** or **DirectQuery**. Choose database authentication and enter the PostgreSQL username and password. In Navigator, select the tables or views and load them. Current Power BI Desktop includes the PostgreSQL Npgsql provider, so a separate driver installation is normally unnecessary. If the connector reports an unencrypted connection, this app's default connection is local and has no PostgreSQL TLS configured. [Microsoft's PostgreSQL connector instructions](https://learn.microsoft.com/en-us/power-query/connectors/postgresql)

The `127.0.0.1` address refers to the computer running the client. A Windows virtual machine on a Mac, or a second PC, cannot reach the Mac's database through its own loopback address. The runner binds PostgreSQL to the host's loopback interface. Such a setup needs a separately configured connection; this guide does not change that binding.

### Choose Import or DirectQuery

| Mode | How it behaves in this app |
| --- | --- |
| Import | Power BI stores a copy of the selected data. Refresh it after importing new files into the app. You can view the already imported report while PostgreSQL is stopped. |
| DirectQuery | Power BI queries PostgreSQL as you use the report. The database must stay running. Source changes appear when the relevant visuals query again; there is no automatic synchronization of chart definitions. |

For a small local Excel workflow, start with Import. DirectQuery is useful if you need queries against the current database and can work within its modeling and performance limits. [Microsoft's comparison of the two modes](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-use-directquery)

This setup uses local Power BI Desktop, not Power BI Service. Publishing and scheduled refresh in Microsoft's service introduce cloud access and may need an on-premises gateway. They are outside this offline app's setup. [Microsoft's gateway and refresh guide](https://learn.microsoft.com/en-us/power-bi/connect-data/service-gateway-enterprise-manage-scheduled-refresh)

## Optional: create an account for reading data

The app does not create a Power BI account automatically. To give Power BI permission to read staging and analytics tables without permission to change them, open a PostgreSQL session from the terminal:

```sh
podman exec -it caritas_postgres psql -U caritas -d caritas
```

These names assume the default container, database, and owner. Use your installation's names if they differ. Run the following once:

```sql
CREATE ROLE powerbi_reader LOGIN;
\password powerbi_reader
GRANT CONNECT ON DATABASE caritas TO powerbi_reader;
GRANT USAGE ON SCHEMA staging, analytics TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA staging, analytics TO powerbi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE caritas IN SCHEMA staging, analytics
  GRANT SELECT ON TABLES TO powerbi_reader;
\q
```

The `\password` command prompts for a password. Use `powerbi_reader` and that password in Power BI. Existing tables get `SELECT` permission; the default privilege also covers future tables and views created by `caritas`, including tables recreated by the importer. If a different role creates your views, grant its future objects separately. These grants exclude the raw import tables. [PostgreSQL permissions](https://www.postgresql.org/docs/16/sql-grant.html), [default privileges](https://www.postgresql.org/docs/16/sql-alterdefaultprivileges.html)

The portable backup omits PostgreSQL login roles and access grants. After restoring onto a new installation, recreate this optional account and its grants before reconnecting Power BI. PostgreSQL documents roles as global objects, outside a single database dump. [PostgreSQL backup scope](https://www.postgresql.org/docs/16/app-pgdump.html)

## Move a table of results

From Superset 4.1.1, open a chart in Explore and use its menu's **Download > Export to .CSV** option. In Power BI Desktop, load it with **Get data > Text/CSV**. Superset also offers **Download as image** if you only need a picture. These options are present in [Superset 4.1.1's chart menu](https://github.com/apache/superset/blob/4.1.1/superset-frontend/src/explore/components/useExploreAdditionalActionsMenu/index.jsx).

In the other direction, use a Power BI visual's **Export data** option to save CSV, then upload that file through this app's importer. Power BI Desktop exports summarized visual data to CSV and limits CSV exports to 30,000 rows. Active filters apply, so the file may represent only part of the source. For a complete dataset, use its original source rather than a visual export. [Microsoft's export instructions and limits](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-export-data?tabs=powerbi-desktop)

Treat a CSV export as a new dataset. For example, a file with one row per canton and a `case_count` column already contains totals: use `SUM(case_count)`, not `COUNT(*)`, when rebuilding its chart. Check dates, postal codes, and decimal separators in the import preview.

## Keep figures consistent

Start with the same table or PostgreSQL view, the same filters, and the same definition of a row. A service table can contain several rows for one case; counting its rows gives service records, while counting distinct case IDs gives cases. See [the worked example](analytics-example.md).

Superset virtual datasets are SQL stored in Superset metadata. Power BI does not see them as PostgreSQL views. To reuse one, copy its SQL into Power BI's native SQL option or create a database view and connect both tools to it. DAX measures and Power Query transformations stay in Power BI unless you rewrite their logic in shared SQL.

The importer's **Replace existing staging tables** option drops dependent PostgreSQL views along with the table. Recreate your reporting views after replacing their source table, or append compatible rows when that fits your workflow.

After importing new data, refresh Power BI's imported model and rerun or refresh Superset's charts. Compare an agreed total in both tools before sharing a report.
