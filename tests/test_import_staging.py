"""Regression tests for the conversions shared by preview and database import."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from scripts.import_staging import (
    TRANSFORM_OPTIONS_BY_TYPE,
    apply_staging_transform,
    convert_staging_value,
    ensure_staging_table,
    infer_column_type,
    insert_frame,
    load_frames,
    normalize_frame,
    staging_schema_conflicts,
    unique_identifiers,
    validate_column,
)


@pytest.mark.parametrize("value,kind,transform,expected", [
    ("03 Familie", "integer", "leading_number", 3),
    ("03 Familie", "text", "leading_number", "03"),
    ("  Hello  ", "text", "trim", "Hello"),
    ("ÄBC", "text", "lower", "äbc"),
    ("äbc", "text", "upper", "ÄBC"),
    ("1.234,56", "numeric", "decimal_comma", Decimal("1234.56")),
    ("1,234.56", "numeric", "decimal_point", Decimal("1234.56")),
    ("0.00000001", "numeric", "decimal_point", Decimal("0.00000001")),
    ("0,00000001", "numeric", "decimal_comma", Decimal("0.00000001")),
    ("1e-08", "numeric", "none", Decimal("1e-08")),
    ("1e-08", "numeric", "decimal_point", Decimal("1e-08")),
    ("1e-08", "numeric", "decimal_comma", Decimal("1e-08")),
    ("1,25E-8", "numeric", "decimal_comma", Decimal("1.25E-8")),
    ("1.25E-8", "numeric", "decimal_point", Decimal("1.25E-8")),
    ("1.25e+3 ratio", "integer", "leading_number", 1250),
    ("1,234", "integer", "decimal_point", 1234),
    ("1'234", "integer", "none", 1234),
    ("1’234,50", "numeric", "none", Decimal("1234.50")),
    ("12/31/2025", "date", "date_mdy", "2025-12-31"),
    ("31.12.2025", "date", "date_dmy", "2025-12-31"),
    ("2025/12/31", "date", "date_iso", "2025-12-31"),
    ("01/02/2025", "date", "date_mdy", "2025-01-02"),
    ("01/02/2025", "date", "date_dmy", "2025-02-01"),
    ("2025-12-31T14:23:30", "timestamp", "date_iso", "2025-12-31 14:23:30"),
    ("1", "date", "excel_serial", "1900-01-01"),
    ("59", "date", "excel_serial", "1900-02-28"),
    ("61.5", "timestamp", "excel_serial", "1900-03-01 12:00:00"),
])
def test_selected_transform_and_type(value, kind, transform, expected):
    converted = convert_staging_value("value", apply_staging_transform("value", value, transform), kind)
    assert str(converted) == str(expected)
    checked = validate_column([value], "value", kind, transform)
    assert checked["valid_count"] == 1
    assert checked["invalid_count"] == 0
    assert checked["valid_examples"][0]["converted"] == str(expected)


@pytest.mark.parametrize("value,kind,transform", [
    ("Familie", "integer", "leading_number"),
    ("2147483648", "integer", "none"),
    ("-2147483649", "integer", "none"),
    ("9223372036854775808", "bigint", "none"),
    ("-9223372036854775809", "bigint", "none"),
    ("12.5", "integer", "none"),
    ("31/12/2025", "date", "date_mdy"),
    ("2025-02-29", "date", "date_iso"),
    ("60", "date", "excel_serial"),
    ("2958466", "date", "excel_serial"),
    ("12,34.56", "numeric", "decimal_point"),
    ("12.34,56", "numeric", "decimal_comma"),
    ("1,25e-08", "numeric", "decimal_point"),
    ("1.25e-08", "numeric", "decimal_comma"),
    ("1e", "numeric", "none"),
    ("1e+", "numeric", "none"),
    ("Infinity", "numeric", "none"),
    ("NaN", "numeric", "none"),
])
def test_invalid_nonempty_values_are_never_silently_lost(value, kind, transform):
    checked = validate_column([value], "value", kind, transform)
    assert checked["invalid_count"] == 1
    assert checked["empty_count"] == 0
    assert checked["invalid_examples"][0]["source_row_number"] == 2
    assert checked["invalid_examples"][0]["error"]


def test_checks_all_rows_and_counts_blanks_separately():
    values = ["42"] * 20 + ["bad", None, "", "  ", "7"]
    checked = validate_column(values, "age", "integer", sample_limit=2)
    assert checked["valid_count"] == 21
    assert checked["invalid_count"] == 1
    assert checked["empty_count"] == 3
    assert len(checked["valid_examples"]) == 2
    assert checked["invalid_examples"][0]["source_row_number"] == 22


def test_transform_type_compatibility_even_for_empty_column():
    checked = validate_column([], "date", "date", "leading_number")
    assert checked["errors"]
    assert "cannot be used" in checked["errors"][0]
    assert "leading_number" not in dict(TRANSFORM_OPTIONS_BY_TYPE["date"])
    assert "date_mdy" in dict(TRANSFORM_OPTIONS_BY_TYPE["date"])
    assert validate_column([], "date", "unknown")["errors"]


def test_integer_boundaries_and_detection():
    assert convert_staging_value("n", str(2**31-1), "integer") == 2**31-1
    assert convert_staging_value("n", str(-(2**63)), "bigint") == -(2**63)
    assert infer_column_type("n", pd.Series([str(2**63)])) == "numeric"
    assert infer_column_type("PLZ", pd.Series(["0012"])) == "text"
    assert infer_column_type("code", pd.Series(["003"])) == "text"


def test_identifiers_do_not_collide_with_source_or_metadata_columns():
    names = unique_identifiers(["n", "n", "n_2", "source_file", "batch_id", "n!"])
    assert len(set(names)) == 6
    assert "source_file" not in names
    assert "batch_id" not in names


def test_append_rejects_type_change_before_altering_table():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("amount", "text"), ("time", "timestamp without time zone")]
    assert staging_schema_conflicts(conn, "sample", {"time": "timestamp"}) == []
    with pytest.raises(ValueError, match="existing type is text"):
        ensure_staging_table(conn, "sample", {"amount": "numeric"})
    assert all("ALTER TABLE" not in str(call) for call in cursor.execute.call_args_list)


def test_backend_refuses_tampered_type_transform_before_sql():
    conn = MagicMock()
    with pytest.raises(ValueError, match="cannot be used"):
        insert_frame(conn, Path("sample.csv"), None, "sample", pd.DataFrame({"a": ["1"]}),
                     ["a"], {"a": "date"}, {"a": "leading_number"})
    conn.cursor.assert_not_called()


def test_real_workbook_and_csv_are_loaded_without_losing_codes(tmp_path):
    frame = pd.DataFrame({"PLZ": ["0012", "3000"], "Datum": ["31.12.2025", "bad"],
                          "source_file": ["a", "b"]})
    for suffix in (".csv", ".xlsx"):
        path = tmp_path / ("sample" + suffix)
        if suffix == ".csv":
            frame.to_csv(path, index=False)
        else:
            frame.to_excel(path, index=False)
        loaded = load_frames(path)[0][1]
        normalized, originals = normalize_frame(loaded)
        assert normalized["plz"].tolist() == ["0012", "3000"]
        assert "source_file_2" in normalized.columns
        assert originals == list(frame.columns)
        checked = validate_column(normalized["datum"], "datum", "date", "date_dmy")
        assert checked["valid_count"] == checked["invalid_count"] == 1


def test_native_excel_date_can_be_selected_as_text_or_date():
    value = datetime(2025, 12, 31)
    assert convert_staging_value("date", value, "text") == "2025-12-31 00:00:00"
    assert str(convert_staging_value("date", value, "date")) == "2025-12-31"


def test_native_decimals_keep_precision_and_reject_nonfinite_numbers():
    value = Decimal("1E-8")
    assert convert_staging_value("ratio", value, "numeric") == value
    for value in (Decimal("Infinity"), Decimal("-Infinity")):
        checked = validate_column([value], "ratio", "numeric")
        assert checked["invalid_count"] == 1


def test_excel_scientific_numbers_are_valid_for_numeric_types(tmp_path):
    path = tmp_path / "ratios.xlsx"
    values = [1e-8, 1.25e20, 1.25e-20]
    pd.DataFrame({"ratio": values}).to_excel(path, index=False)
    loaded = load_frames(path)[0][1]
    assert infer_column_type("ratio", loaded["ratio"]) == "numeric"
    for transform in ("none", "decimal_point"):
        report = validate_column(loaded["ratio"], "ratio", "numeric", transform)
        assert report["valid_count"] == 3
        assert report["invalid_count"] == 0
        assert [Decimal(example["converted"]) for example in report["valid_examples"]] == [Decimal(str(value)) for value in values]
    assert infer_column_type("large", pd.Series(["1e30"])) == "numeric"
