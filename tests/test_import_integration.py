"""Real PostgreSQL regression tests; point CARITAS_TEST_DSN at a disposable DB."""

import io
import os
import re
import uuid

import psycopg2
import pytest

from scripts import import_ui


@pytest.fixture
def database(monkeypatch, tmp_path):
    dsn = os.environ.get("CARITAS_TEST_DSN")
    if not dsn:
        pytest.skip("Set CARITAS_TEST_DSN to run the disposable PostgreSQL integration tests.")
    real_connect = psycopg2.connect
    monkeypatch.setattr(import_ui.psycopg2, "connect", lambda _: real_connect(dsn))
    monkeypatch.setattr(import_ui, "UPLOAD_DIR", tmp_path)
    table = "test_import_" + uuid.uuid4().hex
    yield real_connect, dsn, table
    with real_connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS staging."{table}"')
            cur.execute("DELETE FROM raw.import_batches WHERE staging_table = %s", (f"staging.{table}",))


def upload(client, table, contents):
    response = client.post("/preview", data={"file": (io.BytesIO(contents), table + ".csv")})
    assert response.status_code == 200
    return re.search(r'name="token" value="([a-f0-9]+)"', response.get_data(as_text=True)).group(1)


def test_review_and_import_store_selected_types_and_preserve_raw_values(database):
    connect, dsn, table = database
    client = import_ui.app.test_client()
    token = upload(client, table, b"Amount,Date,PLZ,source_file\n03 Familie,12/31/2025,0012,manual\n04 Test,01/02/2026,3000,other\n")
    form = {"token": token, "replace_existing": "yes",
            "type__0__amount": "integer", "transform__0__amount": "leading_number",
            "type__0__date": "date", "transform__0__date": "date_mdy"}
    report = client.post("/validate", data=form).get_json()
    assert report["valid"], report
    response = client.post("/import", data=form)
    assert response.status_code == 200, response.get_data(as_text=True)
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT amount, date::text, plz, source_file_2 FROM staging."{table}" ORDER BY source_row_number')
            assert cur.fetchall() == [(3, "2025-12-31", "0012", "manual"), (4, "2026-01-02", "3000", "other")]
            cur.execute("SELECT row_data->>'amount' FROM raw.import_rows WHERE source_file = %s ORDER BY source_row_number", (table + ".csv",))
            assert [row[0] for row in cur.fetchall()] == ["03 Familie", "04 Test"]

    # Appending with a different selected type must report the conflict immediately.
    form.pop("replace_existing")
    form["type__0__amount"] = "text"
    report = client.post("/validate", data=form).get_json()
    assert not report["valid"]
    assert any("existing type is integer" in error for error in report["errors"])
    assert client.post("/import", data=form).status_code == 400

    # Matching schema appends, while replacement applies an intentional type change.
    form["type__0__amount"] = "integer"
    assert client.post("/import", data=form).status_code == 200
    form.update({"replace_existing": "yes", "type__0__amount": "text"})
    assert client.post("/import", data=form).status_code == 200
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT data_type FROM information_schema.columns WHERE table_schema = 'staging' AND table_name = %s AND column_name = 'amount'", (table,))
            assert cur.fetchone() == ("text",)
            cur.execute(f'SELECT count(*) FROM staging."{table}"')
            assert cur.fetchone() == (2,)


def test_bad_replacement_keeps_existing_rows_and_types(database):
    connect, dsn, table = database
    client = import_ui.app.test_client()
    token = upload(client, table, b"Amount\n42\ninvalid\n")
    form = {"token": token, "replace_existing": "yes"}
    assert client.post("/import", data=form).status_code == 200
    form["type__0__amount"] = "integer"
    response = client.post("/import", data=form)
    assert response.status_code == 400
    assert "Row 3" in response.get_data(as_text=True)
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT amount FROM staging."{table}" ORDER BY source_row_number')
            assert cur.fetchall() == [("42",), ("invalid",)]
