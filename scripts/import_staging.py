#!/usr/bin/env python3
"""Import CSV/XLS/XLSX files into flexible PostgreSQL staging tables."""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import Json, execute_values
from psycopg2 import sql

SUPPORTED_EXTENSIONS = {".csv", ".xls", ".xlsx"}
DATE_LIKE_RE = re.compile(
    r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})"
    r"(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?$"
)
DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S.%f",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y.%m.%d %H:%M:%S.%f",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d",
    "%d-%m-%Y %H:%M:%S.%f",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%d.%m.%Y %H:%M:%S.%f",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%d/%m/%Y %H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)
NUMBER_LIKE_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)*$")
INTEGER_WITH_LEADING_ZERO_RE = re.compile(r"^[+-]?0\d+$")
LEADING_NUMBER_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)")
POSTGRES_TYPES = {"text", "date", "timestamp", "integer", "bigint", "numeric"}
STAGING_TRANSFORMS = {"none", "leading_number"}


def sanitize_identifier(value: object, fallback: str) -> str:
    text = str(value).strip().lower() if value is not None else ""
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = fallback
    if text[0].isdigit():
        text = f"c_{text}"
    return text[:55]


def unique_identifiers(values: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, value in enumerate(values, start=1):
        base = sanitize_identifier(value, f"column_{index}")
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


def table_name_for(path: Path, sheet_name: str | None, multiple_sheets: bool) -> str:
    base = sanitize_identifier(path.stem, "import")
    if multiple_sheets and sheet_name:
        suffix = sanitize_identifier(sheet_name, "sheet")
        return f"{base}_{suffix}"[:63]
    return base[:63]


def clean_cell_value(value: object) -> object | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def cell_text(value: object) -> str | None:
    value = clean_cell_value(value)
    if value is None:
        return None
    return str(value).strip()


def is_postal_code_column(column_name: str) -> bool:
    normalized = sanitize_identifier(column_name, "column")
    parts = set(normalized.split("_"))
    return (
        "postleitzahl" in normalized
        or "postcode" in normalized
        or "postal" in parts
        or "plz" in parts
        or "zip" in parts
    )


def parse_datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value

    text = cell_text(value)
    if text is None:
        return None

    text = text.replace("T", " ")
    if not DATE_LIKE_RE.match(text):
        return None

    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def parse_decimal_value(value: object) -> Decimal | None:
    text = cell_text(value)
    if text is None:
        return None

    text = text.replace("\u00a0", " ").replace("'", "").replace(" ", "")
    if not NUMBER_LIKE_RE.match(text):
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def infer_column_type(column_name: str, values: pd.Series) -> str:
    non_empty_values = [
        value for value in values if clean_cell_value(value) is not None
    ]
    if not non_empty_values or is_postal_code_column(column_name):
        return "text"

    parsed_dates = [parse_datetime_value(value) for value in non_empty_values]
    if all(value is not None for value in parsed_dates):
        if any(value.time() != time.min for value in parsed_dates if value is not None):
            return "timestamp"
        return "date"

    if any(
        INTEGER_WITH_LEADING_ZERO_RE.match(text)
        for text in (cell_text(value) for value in non_empty_values)
        if text is not None
    ):
        return "text"

    number_texts = [cell_text(value) for value in non_empty_values]
    parsed_numbers = [parse_decimal_value(value) for value in non_empty_values]
    if all(value is not None for value in parsed_numbers):
        has_decimal_marker = any(
            text is not None and ("." in text or "," in text) for text in number_texts
        )
        if not has_decimal_marker and all(
            value == value.to_integral_value()
            for value in parsed_numbers
            if value is not None
        ):
            integers = [int(value) for value in parsed_numbers if value is not None]
            if all(-(2**31) <= value <= 2**31 - 1 for value in integers):
                return "integer"
            return "bigint"
        return "numeric"

    return "text"


def detect_column_types(frame: pd.DataFrame) -> dict[str, str]:
    return {
        column: infer_column_type(column, frame[column]) for column in frame.columns
    }


def convert_staging_value(
    column_name: str, value: object, column_type: str
) -> object | None:
    value = clean_cell_value(value)
    if value is None:
        return None

    if column_type == "text":
        return value
    if column_type in {"date", "timestamp"}:
        parsed = parse_datetime_value(value)
        if parsed is None:
            raise ValueError(f"{column_name}: expected {column_type}, got {value!r}")
        return parsed.date() if column_type == "date" else parsed
    if column_type in {"integer", "bigint"}:
        parsed = parse_decimal_value(value)
        if parsed is None or parsed != parsed.to_integral_value():
            raise ValueError(f"{column_name}: expected integer, got {value!r}")
        return int(parsed)
    if column_type == "numeric":
        parsed = parse_decimal_value(value)
        if parsed is None:
            raise ValueError(f"{column_name}: expected number, got {value!r}")
        return parsed

    raise ValueError(
        f"Unsupported detected PostgreSQL type for {column_name}: {column_type}"
    )


def apply_staging_transform(
    column_name: str, value: object, transform: str
) -> object | None:
    value = clean_cell_value(value)
    if value is None or transform == "none":
        return value

    if transform == "leading_number":
        text = cell_text(value)
        match = LEADING_NUMBER_RE.match(text or "")
        return match.group(1) if match else None

    raise ValueError(f"Unsupported transform for {column_name}: {transform}")


def load_frames(path: Path) -> list[tuple[str | None, pd.DataFrame]]:
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type '{extension}'. Supported: {supported}")

    if extension == ".csv":
        return [(None, pd.read_csv(path, dtype=str, keep_default_na=False))]

    sheets = pd.read_excel(path, sheet_name=None, dtype=str, keep_default_na=False)
    return list(sheets.items())


def bootstrap(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
        cur.execute("CREATE SCHEMA IF NOT EXISTS staging")
        cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw.import_batches (
              batch_id uuid PRIMARY KEY,
              source_file text NOT NULL,
              sheet_name text,
              staging_table text NOT NULL,
              row_count integer NOT NULL,
              original_columns jsonb NOT NULL,
              loaded_at timestamptz NOT NULL DEFAULT now()
            )
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw.import_rows (
              id bigserial PRIMARY KEY,
              batch_id uuid NOT NULL REFERENCES raw.import_batches(batch_id) ON DELETE CASCADE,
              source_file text NOT NULL,
              sheet_name text,
              source_row_number integer NOT NULL,
              row_data jsonb NOT NULL,
              loaded_at timestamptz NOT NULL DEFAULT now()
            )
            """)
        cur.execute("""
            CREATE OR REPLACE VIEW analytics.import_batches AS
            SELECT
              batch_id,
              source_file,
              sheet_name,
              staging_table,
              row_count,
              original_columns,
              loaded_at
            FROM raw.import_batches
            """)


def ensure_staging_table(conn, table_name: str, column_types: dict[str, str]) -> None:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS staging.{table} (
                  import_row_id bigserial PRIMARY KEY,
                  batch_id uuid NOT NULL,
                  source_file text NOT NULL,
                  sheet_name text,
                  source_row_number integer NOT NULL,
                  loaded_at timestamptz NOT NULL DEFAULT now()
                )
                """).format(table=sql.Identifier(table_name)))

        for column, column_type in column_types.items():
            if column_type not in POSTGRES_TYPES:
                raise ValueError(
                    f"Unsupported PostgreSQL type for {column}: {column_type}"
                )
            cur.execute(
                sql.SQL(
                    "ALTER TABLE staging.{table} ADD COLUMN IF NOT EXISTS {column} {column_type}"
                ).format(
                    table=sql.Identifier(table_name),
                    column=sql.Identifier(column),
                    column_type=sql.SQL(column_type),
                )
            )


def normalize_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    if frame.empty and len(frame.columns) == 0:
        raise ValueError("Sheet has no columns.")

    original_columns = [str(column) for column in frame.columns]
    normalized_columns = unique_identifiers(original_columns)
    frame = frame.copy()
    frame.columns = normalized_columns
    frame = frame.where(pd.notnull(frame), None)
    return frame, original_columns


def delete_existing_import(conn, table_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM raw.import_batches WHERE staging_table = %s",
            (f"staging.{table_name}",),
        )
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS staging.{table} CASCADE").format(
                table=sql.Identifier(table_name),
            )
        )


def insert_frame(
    conn,
    path: Path,
    sheet_name: str | None,
    table_name: str,
    frame: pd.DataFrame,
    original_columns: list[str],
    column_types: dict[str, str] | None = None,
    column_transforms: dict[str, str] | None = None,
) -> uuid.UUID:
    batch_id = uuid.uuid4()
    columns = list(frame.columns)
    detected_types = detect_column_types(frame)
    column_types = {**detected_types, **(column_types or {})}
    column_transforms = {
        column: (column_transforms or {}).get(column, "none") for column in columns
    }
    invalid_transforms = set(column_transforms.values()) - STAGING_TRANSFORMS
    if invalid_transforms:
        invalid = ", ".join(sorted(invalid_transforms))
        raise ValueError(f"Unsupported transform value: {invalid}")
    ensure_staging_table(conn, table_name, column_types)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.import_batches (
              batch_id,
              source_file,
              sheet_name,
              staging_table,
              row_count,
              original_columns
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(batch_id),
                path.name,
                sheet_name,
                f"staging.{table_name}",
                len(frame),
                Json(original_columns),
            ),
        )

        raw_rows = []
        staging_rows = []
        for row_number, row in enumerate(frame.to_dict(orient="records"), start=1):
            row_data = {key: clean_cell_value(value) for key, value in row.items()}
            raw_rows.append(
                (str(batch_id), path.name, sheet_name, row_number, Json(row_data))
            )
            try:
                staging_values = [
                    convert_staging_value(
                        column,
                        apply_staging_transform(
                            column,
                            row_data.get(column),
                            column_transforms[column],
                        ),
                        column_types[column],
                    )
                    for column in columns
                ]
            except ValueError as exc:
                raise ValueError(f"Could not convert row {row_number}: {exc}") from exc
            staging_rows.append(
                [str(batch_id), path.name, sheet_name, row_number] + staging_values
            )

        if raw_rows:
            execute_values(
                cur,
                """
                INSERT INTO raw.import_rows (
                  batch_id,
                  source_file,
                  sheet_name,
                  source_row_number,
                  row_data
                )
                VALUES %s
                """,
                raw_rows,
            )

            target_columns = [
                sql.Identifier("batch_id"),
                sql.Identifier("source_file"),
                sql.Identifier("sheet_name"),
                sql.Identifier("source_row_number"),
            ] + [sql.Identifier(column) for column in columns]

            insert_sql = sql.SQL(
                "INSERT INTO staging.{table} ({columns}) VALUES %s"
            ).format(
                table=sql.Identifier(table_name),
                columns=sql.SQL(", ").join(target_columns),
            )
            execute_values(cur, insert_sql, staging_rows)

    return batch_id


def import_file(path: Path) -> int:
    frames = load_frames(path)
    if not frames:
        raise ValueError("No sheets or rows were found.")

    imported = 0
    imported_messages: list[str] = []
    skipped_messages: list[str] = []
    with psycopg2.connect("") as conn:
        bootstrap(conn)
        multiple_sheets = len(frames) > 1
        for sheet_name, frame in frames:
            if frame.empty and len(frame.columns) == 0:
                label = sheet_name or path.name
                skipped_messages.append(f"Skipped empty sheet: {label}")
                continue

            normalized, original_columns = normalize_frame(frame)
            table_name = table_name_for(path, sheet_name, multiple_sheets)
            batch_id = insert_frame(
                conn,
                path=path,
                sheet_name=sheet_name,
                table_name=table_name,
                frame=normalized,
                original_columns=original_columns,
            )
            imported += len(normalized)
            imported_messages.append(
                f"Imported {len(normalized)} rows from "
                f"{path.name}{f' / {sheet_name}' if sheet_name else ''} "
                f"into staging.{table_name} (batch_id={batch_id})"
            )

        if not imported_messages:
            raise ValueError("No non-empty sheets were found.")

    for message in skipped_messages:
        print(message)
    for message in imported_messages:
        print(message)
    return imported


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import CSV/XLS/XLSX files into PostgreSQL staging tables."
    )
    parser.add_argument(
        "file", help="Path to the input file inside the import container."
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"Input file does not exist: {path}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"Input path is not a file: {path}", file=sys.stderr)
        return 2

    try:
        imported = import_file(path)
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(f"Import complete. Total rows imported: {imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
