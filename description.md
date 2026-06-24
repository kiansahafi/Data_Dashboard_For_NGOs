I'd love to get a simple version running again — but just local on my laptop this time, no server, nothing fancy. Mostly for my own analytics. I attached above the doc with all the details on what it'd involve.

The task in one paragraph
Rebuild the Caritas+ Dashboard prototype as a fully local, offline application running on a single computer — no internet, no exposed server, no cloud. The system uses Apache Superset for visualisation on top of a PostgreSQL database, packaged in Docker (or Podman), and is ready to ingest the kind of simple Caritas Excel files described in the documentation (regional consultation data and Caritas-Markt data) and reproduce the dashboard's core indicators.
Because the solution is local and offline, the entire network-facing security layer from the original prototype — reverse proxy, BFH firewall, TLS/HTTPS, public IP exposure, internet-facing IAM/Active Directory, SSH hardening — falls away. This simplifies the build considerably and removes most of the original prototype's risk surface. The remaining work concentrates on the data pipeline, the dashboards, and the optional capability modules.

-

> the the dashboard charts i would then create (inside the superset UI)

---

potential extension components could be (second steps):

A — Simple Excel import function(!!!)(long term)
Upgrade the base's manual/scripted ingest into a reusable import function: upload an Excel file → validate → load into PostgreSQL, with basic column mapping and sanity checks. "Simple" excludes heavy metadata harmonisation and multilingual standardisation (see assumptions).

C.1 — Statistical Disclosure Control (sdcMicro-style) (!)(long term)
k-anonymity, global recoding (e.g. age → age bands), aggregation thresholds, small-cell suppression. Done well means: defining quasi-identifiers, setting defensible k-thresholds and recoding rules, measuring information loss, baking it into the ingest pipeline so the dashboard only ever sees safe aggregates, and documenting the rules.

D — Local PowerBI link (!) (long term)
Connect a local PowerBI Desktop instance to the same local PostgreSQL database, so analysts can build their own reports alongside Superset. Includes a read-only database role for PowerBI, the PostgreSQL/Npgsql connector configured against the local Postgres (localhost:5432), a chosen connection mode (Import vs DirectQuery), a couple of starter report templates, and reconnection documentation.

E — Portable / transferable package (!!!) (long term)
Turn the running solution into a clean, reproducible package: bundled images (docker save/load for offline transfer via USB), a database dump, exported Superset assets (datasets, charts, dashboards), and a one-shot install/restore script.

F — Install on the 3 other PC (!!!) (long term)
The hands-on labour of taking the package from E onto three additional machines and making each run: transfer images offline, restore the database and Superset assets, verify, hand over.

G — Maps with deck.gl (offline base map) (!) (long term) (interactive would be cool)
Choropleth maps at the Gemeinde level, the documented pain point of the original prototype — built in the fully offline variant. Requires the PostGIS extension, Swiss municipality geometries joined on BFS-Nummer (not postal code), a Python aggregation step producing a per-Gemeinde GeoJSON with the analytical values baked in, the deck.gl chart configured in Superset, and a self-hosted Swiss tile source (e.g. tileserver-gl) so a real base map renders without internet.

H - add switzeralnd governmental data's automatically (!) (long term)
(e.g. the unemployment ratios) to get them automatically and add them to the database when the app is instantiated.

\_\_

**Background & Goals:**
[Von Daten zu Taten: Ein Datentool für die Caritas Schweiz](https://arbor.bfh.ch/entities/publication/64b3ef31-d631-457e-8f8c-f0959cb21f6e)

**Documentation:**
[Caritas Dashboard: Prototype Insights, Dokumentation und Reporting](https://arbor.bfh.ch/entities/publication/e2b9b3be-0485-4eb1-b474-dc1c27a00624)

**Application/Usage:**
[Evidence-based policy engagement of social welfare non-governmental organisations: a case study on the democratic relevance of Caritas Switzerland’s data ecosystem in: European Social Work Research - Ahead of print](https://bristoluniversitypressdigital.com/view/journals/eswr/aop/article-10.1332-27551768Y2026D000000079/article-10.1332-27551768Y2026D000000079.xml)

Issues:

1. the numbers are being parsed as a texts
2. automatic type detection of data (date, postleitzahl, numbers, texts, )
3.

time horizons:

1. 1st of July: make it functional and correct the detected issues in the current version
   - make it open source on codeberge and issues part would be important
2. End of the Year: user friendly and useful as possible
