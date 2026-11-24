-- Schema for the synthetic demo data of the Sample CSO/NGO, GERMAN version
-- (labels of the Caritas Datenstandard v1.0). English version: sql/schema_en.sql
--
--   psql -d dashboard -f sql/schema_de.sql
--   \copy demo_de.beratungsdaten FROM 'data/de/beratungsdaten_synthesized.csv' WITH (FORMAT csv, HEADER true, NULL '')
--
-- One table, one row per counselling event. Client characteristics repeat on
-- every event row; the view v_clients turns them back into one row per client.
-- Column names are lower-case so Superset SQL needs no double quotes;
-- \copy loads by position, so the CSV header can stay as it is.

CREATE SCHEMA IF NOT EXISTS demo_de;

DROP TABLE IF EXISTS demo_de.beratungsdaten CASCADE;

CREATE TABLE demo_de.beratungsdaten (
    ereignis_id                           integer PRIMARY KEY,
    datum_leistung                        date NOT NULL,
    ereignisart                           text,
    ereignis_anzahl_minuten               smallint,
    client_id                             integer NOT NULL,
    datum_registrierung_client            date NOT NULL,   -- characteristic 1: first entry
    beratungsstelle                       text NOT NULL,   -- extension
    client_geburtsjahr                    smallint,        -- characteristic 2: age (year of birth)
    client_geschlecht                     text,            -- characteristic 3
    client_plz                            text,            -- characteristic 4: place of residence
    client_wohnort                        text,            -- characteristic 4: place of residence
    client_kanton                         char(2),         -- derived from postcode
    wohnsituation                         text,            -- characteristic 5
    wohnform                              text,            -- extension: housing type
    kinder_im_haushalt                    smallint,        -- characteristic 6a
    kinder_auswaerts                      smallint,        -- characteristic 6b
    zivilstand                            text,            -- characteristic 7
    nationalitaet                         text,            -- characteristic 8
    aufenthaltsstatus                     text,            -- characteristic 9
    aufenthaltsstatus_detail              text,            -- extension: as recorded by the office
    erwerbssituation                      text,            -- characteristic 10
    -- characteristic 11: reasons for support (multiple response, 1 = named)
    grund_zu_geringes_einkommen           smallint,
    grund_schulden                        smallint,
    grund_erwerbslosigkeit                smallint,
    grund_administrative_unterstuetzung   smallint,
    grund_gesundheitliche_probleme        smallint,
    grund_wohnsituation                   smallint,
    grund_probleme_familie_partnerschaft  smallint,
    grund_rechtliche_probleme             smallint,
    grund_andere                          smallint
);

CREATE INDEX ON demo_de.beratungsdaten (client_id);
CREATE INDEX ON demo_de.beratungsdaten (datum_leistung);

-- Event level: derived time and age fields
CREATE OR REPLACE VIEW demo_de.v_beratungsdaten AS
SELECT
    b.*,
    EXTRACT(YEAR FROM b.datum_leistung)::int                       AS jahr_leistung,
    date_trunc('month', b.datum_leistung)::date                    AS monat_leistung,
    EXTRACT(YEAR FROM b.datum_leistung)::int - b.client_geburtsjahr AS alter_bei_leistung,
    (b.datum_registrierung_client >= DATE '2022-01-01')            AS neuklient_im_zeitraum,
    'CH-' || b.client_kanton                                       AS kanton_iso
FROM demo_de.beratungsdaten b;

-- Client level: one row per client (replaces a separate case file)
CREATE OR REPLACE VIEW demo_de.v_clients AS
WITH agg AS (
    SELECT client_id,
           count(*)                     AS anzahl_ereignisse,
           sum(ereignis_anzahl_minuten) AS minuten_total,
           min(datum_leistung)          AS erste_leistung,
           max(datum_leistung)          AS letzte_leistung
    FROM demo_de.beratungsdaten
    GROUP BY client_id
)
SELECT DISTINCT ON (b.client_id)
    b.client_id, b.datum_registrierung_client, b.beratungsstelle, b.client_geburtsjahr,
    b.client_geschlecht, b.client_plz, b.client_wohnort, b.client_kanton,
    b.wohnsituation, b.wohnform, b.kinder_im_haushalt, b.kinder_auswaerts,
    b.zivilstand, b.nationalitaet, b.aufenthaltsstatus, b.aufenthaltsstatus_detail,
    b.erwerbssituation,
    b.grund_zu_geringes_einkommen, b.grund_schulden, b.grund_erwerbslosigkeit,
    b.grund_administrative_unterstuetzung, b.grund_gesundheitliche_probleme,
    b.grund_wohnsituation, b.grund_probleme_familie_partnerschaft,
    b.grund_rechtliche_probleme, b.grund_andere,
    EXTRACT(YEAR FROM b.datum_registrierung_client)::int - b.client_geburtsjahr AS alter_bei_ersteintritt,
    CASE
        WHEN b.client_geburtsjahr IS NULL THEN NULL
        WHEN EXTRACT(YEAR FROM b.datum_registrierung_client) - b.client_geburtsjahr < 25 THEN '18–24'
        WHEN EXTRACT(YEAR FROM b.datum_registrierung_client) - b.client_geburtsjahr < 35 THEN '25–34'
        WHEN EXTRACT(YEAR FROM b.datum_registrierung_client) - b.client_geburtsjahr < 45 THEN '35–44'
        WHEN EXTRACT(YEAR FROM b.datum_registrierung_client) - b.client_geburtsjahr < 55 THEN '45–54'
        WHEN EXTRACT(YEAR FROM b.datum_registrierung_client) - b.client_geburtsjahr < 65 THEN '55–64'
        ELSE '65+'
    END                                                            AS altersgruppe,
    'CH-' || b.client_kanton                                       AS kanton_iso,
    a.anzahl_ereignisse, a.minuten_total, a.erste_leistung, a.letzte_leistung
FROM demo_de.beratungsdaten b
JOIN agg a USING (client_id)
ORDER BY b.client_id, b.datum_leistung, b.ereignis_id;

-- Reasons for support in long format (one row per client and reason), handy for bar charts
CREATE OR REPLACE VIEW demo_de.v_unterstuetzungsgruende AS
SELECT c.client_id, c.beratungsstelle, c.datum_registrierung_client, r.unterstuetzungsgrund
FROM demo_de.v_clients c
CROSS JOIN LATERAL (VALUES
    ('zu geringes Einkommen',                  c.grund_zu_geringes_einkommen),
    ('Schulden',                               c.grund_schulden),
    ('Erwerbslosigkeit',                       c.grund_erwerbslosigkeit),
    ('administrative Unterstützung',           c.grund_administrative_unterstuetzung),
    ('gesundheitliche Probleme',               c.grund_gesundheitliche_probleme),
    ('Wohnsituation',                          c.grund_wohnsituation),
    ('Probleme in Familie oder Partnerschaft', c.grund_probleme_familie_partnerschaft),
    ('rechtliche Probleme',                    c.grund_rechtliche_probleme),
    ('andere',                                 c.grund_andere)
) AS r(unterstuetzungsgrund, genannt)
WHERE r.genannt = 1;
