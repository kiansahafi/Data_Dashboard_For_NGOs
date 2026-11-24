# Count cases and services separately

[Back to the introduction](../README.md)

This example uses an ECase workbook imported as `staging.ecase_basel_kd`. Its rows describe service records, so a case can appear more than once. The queries below create separate datasets for questions about cases and questions about services.

Use this example only if your file has the same columns. Your row counts depend on the workbook and on whether you replaced or appended previous imports.

## Look at the imported table

Open Superset, then **SQL > SQL Lab**. Select **Caritas Local PostgreSQL** and the `staging` schema. Run:

```sql
SELECT *
FROM staging.ecase_basel_kd
LIMIT 100;
```

Check the actual column names and the meaning of a row before choosing calculations.

## Create a dataset for cases

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
ORDER BY fallbearbeitungsnummer_kd, source_row_number, import_row_id;
```

This keeps the first source row for each non-empty case ID. If repeated records disagree about a person's details, decide which record should take precedence before using those details in an analysis.

Select **Save > Save dataset** and name it `ECase Basel - Cases`. You can then make charts such as:

| Chart | Settings |
| --- | --- |
| Cases | Big Number, metric `COUNT(*)` |
| Cases by intake year | Bar chart, dimension `intake_year`, metric `COUNT(*)` |
| Cases by gender | Pie or bar chart, dimension `gender`, metric `COUNT(*)` |
| Age distribution | Histogram using the numeric `age` column |
| Cases by residence status | Bar chart, dimension `residence_status`, metric `COUNT(*)` |

## Create a dataset for services

Run:

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

Save it as `ECase Basel - Services`. Each row is a service record. Try:

| Chart | Settings |
| --- | --- |
| Service records | Big Number, metric `COUNT(*)` |
| Services by type | Bar chart, dimension `service_type`, metric `COUNT(*)` |
| Services by year | Bar chart, dimension `service_year`, metric `COUNT(*)` |
| Services by office | Bar chart, dimension `office`, metric `COUNT(*)` |

## Put the charts on a dashboard

Save the charts from Explore. Create an `ECase Basel Overview` dashboard and add them. Add filters for fields such as `intake_year`, `gender`, `service_year`, and `service_type`, and check which charts each filter applies to.

Keep identifying fields out of shared dashboard views and use aggregated charts for analysis. The raw workbook can contain personal information.

If you want Power BI to use these same datasets, create PostgreSQL views from the queries or copy the SQL into Power BI. Saving a virtual dataset in Superset does not create a database view. See [the Power BI guide](power-bi.md).
