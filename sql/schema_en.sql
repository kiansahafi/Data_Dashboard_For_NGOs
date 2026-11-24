-- Schema for the synthetic demo data of the Sample CSO/NGO, ENGLISH version.
-- German version (labels of the Caritas Datenstandard v1.0): sql/schema_de.sql
--
--   psql -d dashboard -f sql/schema_en.sql
--   \copy demo_en.counselling_events FROM 'data/en/counselling_events.csv' WITH (FORMAT csv, HEADER true, NULL '')
--
-- One table, one row per counselling event. Client characteristics repeat on
-- every event row; the view v_clients turns them back into one row per client.
-- Column names are lower-case so Superset SQL needs no double quotes;
-- \copy loads by position, so the CSV header can stay as it is.

CREATE SCHEMA IF NOT EXISTS demo_en;

DROP TABLE IF EXISTS demo_en.counselling_events CASCADE;

CREATE TABLE demo_en.counselling_events (
    event_id                           integer PRIMARY KEY,
    service_date                        date NOT NULL,
    event_type                           text,
    event_minutes               smallint,
    client_id                             integer NOT NULL,
    client_registration_date            date NOT NULL,   -- characteristic 1: first entry
    office                       text NOT NULL,   -- extension
    client_birth_year                    smallint,        -- characteristic 2: age (year of birth)
    client_sex                     text,            -- characteristic 3
    client_postcode                            text,            -- characteristic 4: place of residence
    client_place_of_residence                        text,            -- characteristic 4: place of residence
    client_canton                         char(2),         -- derived from postcode
    household_type                         text,            -- characteristic 5
    housing_type                              text,            -- extension: housing type
    children_in_household                    smallint,        -- characteristic 6a
    children_elsewhere                      smallint,        -- characteristic 6b
    civil_status                            text,            -- characteristic 7
    nationality                         text,            -- characteristic 8
    residence_status                     text,            -- characteristic 9
    residence_status_detail              text,            -- extension: as recorded by the office
    employment_status                      text,            -- characteristic 10
    -- characteristic 11: reasons for support (multiple response, 1 = named)
    reason_insufficient_income           smallint,
    reason_debt                        smallint,
    reason_unemployment                smallint,
    reason_administrative_support   smallint,
    reason_health_problems        smallint,
    reason_housing_situation                   smallint,
    reason_family_or_relationship_problems  smallint,
    reason_legal_problems             smallint,
    reason_other                          smallint
);

CREATE INDEX ON demo_en.counselling_events (client_id);
CREATE INDEX ON demo_en.counselling_events (service_date);

-- Event level: derived time and age fields
CREATE OR REPLACE VIEW demo_en.v_counselling_events AS
SELECT
    b.*,
    EXTRACT(YEAR FROM b.service_date)::int                       AS service_year,
    date_trunc('month', b.service_date)::date                    AS service_month,
    EXTRACT(YEAR FROM b.service_date)::int - b.client_birth_year AS age_at_service,
    (b.client_registration_date >= DATE '2022-01-01')            AS new_client_in_period,
    'CH-' || b.client_canton                                       AS canton_iso
FROM demo_en.counselling_events b;

-- Client level: one row per client (replaces a separate case file)
CREATE OR REPLACE VIEW demo_en.v_clients AS
WITH agg AS (
    SELECT client_id,
           count(*)                     AS n_events,
           sum(event_minutes) AS minutes_total,
           min(service_date)          AS first_service,
           max(service_date)          AS last_service
    FROM demo_en.counselling_events
    GROUP BY client_id
)
SELECT DISTINCT ON (b.client_id)
    b.client_id, b.client_registration_date, b.office, b.client_birth_year,
    b.client_sex, b.client_postcode, b.client_place_of_residence, b.client_canton,
    b.household_type, b.housing_type, b.children_in_household, b.children_elsewhere,
    b.civil_status, b.nationality, b.residence_status, b.residence_status_detail,
    b.employment_status,
    b.reason_insufficient_income, b.reason_debt, b.reason_unemployment,
    b.reason_administrative_support, b.reason_health_problems,
    b.reason_housing_situation, b.reason_family_or_relationship_problems,
    b.reason_legal_problems, b.reason_other,
    EXTRACT(YEAR FROM b.client_registration_date)::int - b.client_birth_year AS age_at_first_entry,
    CASE
        WHEN b.client_birth_year IS NULL THEN NULL
        WHEN EXTRACT(YEAR FROM b.client_registration_date) - b.client_birth_year < 25 THEN '18–24'
        WHEN EXTRACT(YEAR FROM b.client_registration_date) - b.client_birth_year < 35 THEN '25–34'
        WHEN EXTRACT(YEAR FROM b.client_registration_date) - b.client_birth_year < 45 THEN '35–44'
        WHEN EXTRACT(YEAR FROM b.client_registration_date) - b.client_birth_year < 55 THEN '45–54'
        WHEN EXTRACT(YEAR FROM b.client_registration_date) - b.client_birth_year < 65 THEN '55–64'
        ELSE '65+'
    END                                                            AS age_group,
    'CH-' || b.client_canton                                       AS canton_iso,
    a.n_events, a.minutes_total, a.first_service, a.last_service
FROM demo_en.counselling_events b
JOIN agg a USING (client_id)
ORDER BY b.client_id, b.service_date, b.event_id;

-- Reasons for support in long format (one row per client and reason), handy for bar charts
CREATE OR REPLACE VIEW demo_en.v_reasons_for_support AS
SELECT c.client_id, c.office, c.client_registration_date, r.reason_for_support
FROM demo_en.v_clients c
CROSS JOIN LATERAL (VALUES
    ('insufficient income',                  c.reason_insufficient_income),
    ('debt',                               c.reason_debt),
    ('unemployment',                       c.reason_unemployment),
    ('administrative support',           c.reason_administrative_support),
    ('health problems',               c.reason_health_problems),
    ('housing situation',                          c.reason_housing_situation),
    ('family or relationship problems', c.reason_family_or_relationship_problems),
    ('legal problems',                    c.reason_legal_problems),
    ('other',                                 c.reason_other)
) AS r(reason_for_support, named)
WHERE r.named = 1;
