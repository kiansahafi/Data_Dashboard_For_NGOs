#!/usr/bin/env python3
"""Small local web UI for reviewing import column types before loading data."""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from flask import Flask, request, render_template_string
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from scripts.import_staging import (
    POSTGRES_TYPES,
    STAGING_TRANSFORMS,
    bootstrap,
    clean_cell_value,
    delete_existing_import,
    detect_column_types,
    insert_frame,
    load_frames,
    normalize_frame,
    table_name_for,
)


UPLOAD_DIR = Path(os.environ.get("IMPORT_UPLOAD_DIR", "/tmp/caritas-import-ui"))
UPLOAD_MAX_AGE_SECONDS = 24 * 60 * 60
SAMPLE_LIMIT = 5

TYPE_OPTIONS = [
    ("text", "Text / postal code"),
    ("integer", "Integer number"),
    ("bigint", "Large integer"),
    ("numeric", "Decimal number"),
    ("date", "Date"),
    ("timestamp", "Date and time"),
]
TRANSFORM_OPTIONS = [
    ("none", "Keep value"),
    ("leading_number", "Extract leading number"),
]

app = Flask(__name__)


BASE_STYLE = """
<style>
  :root { color-scheme: light; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f7f8fa;
    color: #1f2933;
  }
  main { max-width: 1120px; margin: 0 auto; padding: 32px 20px 48px; }
  h1 { margin: 0 0 6px; font-size: 28px; font-weight: 650; }
  h2 { margin: 28px 0 12px; font-size: 19px; }
  p { line-height: 1.45; }
  a { color: #165d9c; }
  .panel {
    background: #fff;
    border: 1px solid #d8dee6;
    border-radius: 8px;
    padding: 18px;
    margin-top: 18px;
  }
  .toolbar {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
    margin-top: 16px;
  }
  button, .button {
    border: 0;
    border-radius: 6px;
    background: #1b6aa9;
    color: #fff;
    font-weight: 600;
    padding: 10px 14px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
  }
  button.secondary, .button.secondary { background: #4b5563; }
  input[type=file] { display: block; margin-top: 12px; }
  label { font-weight: 600; }
  .hint { color: #5e6b78; font-size: 14px; }
  .error {
    border: 1px solid #d64545;
    background: #fff5f5;
    color: #8a1f1f;
    border-radius: 8px;
    padding: 14px;
    margin-top: 18px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    background: #fff;
    border: 1px solid #d8dee6;
    border-radius: 8px;
    overflow: hidden;
  }
  th, td {
    border-bottom: 1px solid #e7ebf0;
    padding: 9px 10px;
    text-align: left;
    vertical-align: top;
    font-size: 14px;
  }
  th { background: #eef2f6; font-size: 13px; color: #3d4852; }
  tr:last-child td { border-bottom: 0; }
  select {
    width: 100%;
    min-width: 150px;
    border: 1px solid #c8d1dc;
    border-radius: 6px;
    padding: 7px;
    background: #fff;
  }
  .sample { color: #334155; }
  .sample code {
    display: inline-block;
    margin: 0 6px 5px 0;
    background: #f1f5f9;
    border-radius: 4px;
    padding: 2px 5px;
    font-size: 12px;
  }
  .messages li { margin: 6px 0; }
  @media (max-width: 760px) {
    main { padding: 20px 12px 36px; }
    table { display: block; overflow-x: auto; white-space: nowrap; }
  }
</style>
"""

UPLOAD_TEMPLATE = (
    BASE_STYLE
    + """
<main>
  <h1>Import Data</h1>
  <p class="hint">Upload a CSV or Excel file, review suggested column types, then import it into PostgreSQL staging tables.</p>

  {% if error %}
    <div class="error">{{ error }}</div>
  {% endif %}

  <form class="panel" action="/preview" method="post" enctype="multipart/form-data">
    <label for="file">Data file</label>
    <input id="file" name="file" type="file" accept=".csv,.xls,.xlsx" required>
    <div class="toolbar">
      <button type="submit">Review import</button>
      <a class="button secondary" href="{{ superset_url }}">Open Superset</a>
    </div>
  </form>
</main>
"""
)

PREVIEW_TEMPLATE = (
    BASE_STYLE
    + """
<main>
  <h1>Review Import</h1>
  <p class="hint">File: <strong>{{ filename }}</strong>. Suggested types can be changed before import.</p>

  {% if skipped %}
    <div class="panel">
      <strong>Skipped sheets</strong>
      <ul class="messages">
        {% for message in skipped %}<li>{{ message }}</li>{% endfor %}
      </ul>
    </div>
  {% endif %}

  <form action="/import" method="post">
    <input type="hidden" name="token" value="{{ token }}">
    <div class="panel">
      <label>
        <input type="checkbox" name="replace_existing" value="yes" checked>
        Replace existing staging tables for this file/sheet before importing
      </label>
      <p class="hint">Uncheck this if you intentionally want to append another batch.</p>
    </div>

    {% for sheet in sheets %}
      <h2>{{ sheet.label }} -> staging.{{ sheet.table_name }}</h2>
      <table>
        <thead>
          <tr>
            <th>Column</th>
            <th>Sample values</th>
            <th>Suggested</th>
            <th>Use type</th>
            <th>Transform</th>
          </tr>
        </thead>
        <tbody>
          {% for column in sheet.columns %}
            <tr>
              <td>
                <strong>{{ column.original_name }}</strong>
                <div class="hint">{{ column.name }}</div>
              </td>
              <td class="sample">
                {% for value in column.sample_values %}
                  <code>{{ value }}</code>
                {% else %}
                  <span class="hint">No non-empty sample</span>
                {% endfor %}
              </td>
              <td>{{ column.suggested_label }}</td>
              <td>
                <select name="type__{{ sheet.index }}__{{ column.name }}">
                  {% for value, label in type_options %}
                    <option value="{{ value }}" {% if value == column.suggested_type %}selected{% endif %}>{{ label }}</option>
                  {% endfor %}
                </select>
              </td>
              <td>
                <select name="transform__{{ sheet.index }}__{{ column.name }}">
                  {% for value, label in transform_options %}
                    <option value="{{ value }}">{{ label }}</option>
                  {% endfor %}
                </select>
              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% endfor %}

    <div class="toolbar">
      <button type="submit">Import data</button>
      <a class="button secondary" href="/">Choose another file</a>
    </div>
    <p class="hint">Use "Extract leading number" with a numeric type for values such as <code>03 Familie</code>. Without a leading number, the imported staging value becomes empty.</p>
  </form>
</main>
"""
)

RESULT_TEMPLATE = (
    BASE_STYLE
    + """
<main>
  <h1>Import Result</h1>
  {% if error %}
    <div class="error">{{ error }}</div>
  {% else %}
    <div class="panel">
      <ul class="messages">
        {% for message in messages %}<li>{{ message }}</li>{% endfor %}
      </ul>
    </div>
  {% endif %}
  <div class="toolbar">
    <a class="button" href="/">Import another file</a>
    <a class="button secondary" href="{{ superset_url }}">Open Superset</a>
  </div>
</main>
"""
)


def superset_url() -> str:
    return os.environ.get("SUPERSET_URL", "http://127.0.0.1:8088")


def cleanup_uploads() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - UPLOAD_MAX_AGE_SECONDS
    for path in UPLOAD_DIR.glob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def uploaded_path_for_token(token: str) -> Path | None:
    if not token or "/" in token:
        return None
    matches = sorted(UPLOAD_DIR.glob(f"{token}__*"))
    return matches[0] if matches else None


def original_upload_name(path: Path) -> str:
    return path.name.split("__", 1)[-1]


def save_upload(file: FileStorage) -> tuple[str, Path]:
    filename = secure_filename(file.filename or "")
    if not filename:
        raise ValueError("Choose a file to import.")
    extension = Path(filename).suffix.lower()
    if extension not in {".csv", ".xls", ".xlsx"}:
        raise ValueError("Supported file types are CSV, XLS, and XLSX.")

    cleanup_uploads()
    token = uuid.uuid4().hex
    path = UPLOAD_DIR / f"{token}__{filename}"
    file.save(path)
    return token, path


def sample_values(series) -> list[str]:
    values = []
    for value in series:
        value = clean_cell_value(value)
        if value is None:
            continue
        values.append(str(value))
        if len(values) == SAMPLE_LIMIT:
            break
    return values


def label_for_type(column_type: str) -> str:
    return dict(TYPE_OPTIONS).get(column_type, column_type)


def preview_context(path: Path, token: str) -> dict[str, object]:
    frames = load_frames(path)
    multiple_sheets = len(frames) > 1
    source_path = Path(original_upload_name(path))
    sheets = []
    skipped = []

    for index, (sheet_name, frame) in enumerate(frames):
        label = sheet_name or source_path.name
        if frame.empty and len(frame.columns) == 0:
            skipped.append(f"Skipped empty sheet: {label}")
            continue

        normalized, original_columns = normalize_frame(frame)
        suggested_types = detect_column_types(normalized)
        table_name = table_name_for(source_path, sheet_name, multiple_sheets)
        columns = []

        for name, original_name in zip(normalized.columns, original_columns):
            suggested_type = suggested_types[name]
            columns.append(
                {
                    "name": name,
                    "original_name": original_name,
                    "sample_values": sample_values(normalized[name]),
                    "suggested_type": suggested_type,
                    "suggested_label": label_for_type(suggested_type),
                }
            )

        sheets.append(
            {
                "index": index,
                "label": label,
                "table_name": table_name,
                "columns": columns,
            }
        )

    if not sheets:
        raise ValueError("No non-empty sheets were found.")

    return {
        "filename": original_upload_name(path),
        "token": token,
        "sheets": sheets,
        "skipped": skipped,
        "type_options": TYPE_OPTIONS,
        "transform_options": TRANSFORM_OPTIONS,
    }


@app.get("/")
def upload_form():
    return render_template_string(
        UPLOAD_TEMPLATE,
        error=None,
        superset_url=superset_url(),
    )


@app.post("/preview")
def preview_import():
    try:
        file = request.files.get("file")
        if file is None:
            raise ValueError("Choose a file to import.")
        token, path = save_upload(file)
        context = preview_context(path, token)
    except Exception as exc:
        return render_template_string(
            UPLOAD_TEMPLATE,
            error=str(exc),
            superset_url=superset_url(),
        ), 400

    return render_template_string(PREVIEW_TEMPLATE, **context)


@app.post("/import")
def import_reviewed_file():
    token = request.form.get("token", "")
    path = uploaded_path_for_token(token)
    if path is None:
        return render_template_string(
            RESULT_TEMPLATE,
            error="The uploaded file is no longer available. Upload it again.",
            messages=[],
            superset_url=superset_url(),
        ), 400

    try:
        frames = load_frames(path)
        multiple_sheets = len(frames) > 1
        replace_existing = request.form.get("replace_existing") == "yes"
        messages = []

        with psycopg2.connect("") as conn:
            bootstrap(conn)
            source_path = Path(original_upload_name(path))
            for index, (sheet_name, frame) in enumerate(frames):
                if frame.empty and len(frame.columns) == 0:
                    continue

                normalized, original_columns = normalize_frame(frame)
                table_name = table_name_for(source_path, sheet_name, multiple_sheets)
                detected_types = detect_column_types(normalized)
                column_types = {}
                column_transforms = {}

                for column in normalized.columns:
                    selected_type = request.form.get(
                        f"type__{index}__{column}", detected_types[column]
                    )
                    selected_transform = request.form.get(
                        f"transform__{index}__{column}", "none"
                    )
                    if selected_type not in POSTGRES_TYPES:
                        raise ValueError(f"Unsupported type for {column}: {selected_type}")
                    if selected_transform not in STAGING_TRANSFORMS:
                        raise ValueError(
                            f"Unsupported transform for {column}: {selected_transform}"
                        )
                    column_types[column] = selected_type
                    column_transforms[column] = selected_transform

                if replace_existing:
                    delete_existing_import(conn, table_name)

                batch_id = insert_frame(
                    conn,
                    path=source_path,
                    sheet_name=sheet_name,
                    table_name=table_name,
                    frame=normalized,
                    original_columns=original_columns,
                    column_types=column_types,
                    column_transforms=column_transforms,
                )
                messages.append(
                    f"Imported {len(normalized)} rows into staging.{table_name} "
                    f"(batch_id={batch_id})"
                )

        if not messages:
            raise ValueError("No non-empty sheets were found.")
    except Exception as exc:
        return render_template_string(
            RESULT_TEMPLATE,
            error=str(exc),
            messages=[],
            superset_url=superset_url(),
        ), 400

    return render_template_string(
        RESULT_TEMPLATE,
        error=None,
        messages=messages,
        superset_url=superset_url(),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("IMPORT_UI_PORT", "8090")))
