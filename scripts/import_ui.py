#!/usr/bin/env python3
"""Small local web UI for reviewing import column types before loading data."""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from flask import Flask, jsonify, request, render_template_string
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from scripts.import_staging import (
    TRANSFORM_OPTIONS_BY_TYPE,
    bootstrap,
    delete_existing_import,
    detect_column_types,
    insert_frame,
    load_frames,
    normalize_frame,
    table_name_for,
    validate_column,
    staging_schema_conflicts,
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
  button:disabled { cursor: wait; opacity: .55; }
  .validation { min-width: 210px; }
  .valid { color: #17633b; }
  .invalid { color: #9f2424; }
  .invalid-row { background: #fff8f8; }
  .examples { margin: 8px 0; padding-left: 18px; }
  .examples li { margin-bottom: 5px; overflow-wrap: anywhere; }
  .validation-summary { margin: 14px 0; }
  .error[hidden] { display: none; }
  details { margin-top: 8px; }
  summary { cursor: pointer; }
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
  <p class="hint">File: <strong>{{ filename }}</strong>. Choose the type and conversion for each column. Every data row is checked.</p>

  {% if skipped %}
    <div class="panel">
      <strong>Skipped sheets</strong>
      <ul class="messages">{% for message in skipped %}<li>{{ message }}</li>{% endfor %}</ul>
    </div>
  {% endif %}

  <form id="review-form" action="/import" method="post">
    <input type="hidden" name="token" value="{{ token }}">
    <div class="panel">
      <label>
        <input type="checkbox" name="replace_existing" value="yes" {% if replace_existing %}checked{% endif %}>
        Replace existing staging tables for this file/sheet before importing
      </label>
      <p class="hint">Uncheck to append rows. Appending keeps existing column types; replacing recreates the table with your selected types.</p>
      <p class="hint">Replacing also removes database views that depend on this table. Recreate those views afterwards.</p>
    </div>
    <div id="review-errors" class="error" role="alert" {% if not errors %}hidden{% endif %}>
      <ul class="messages">{% for message in errors %}<li>{{ message }}</li>{% endfor %}</ul>
    </div>
    <p id="validation-summary" class="validation-summary" role="status" aria-live="polite">{{ summary }}</p>

    {% for sheet in sheets %}
      <h2>{{ sheet.label }} &rarr; staging.{{ sheet.table_name }}</h2>
      <p class="hint">{{ sheet.row_count }} data rows. Source row numbers count records including the header. A quoted CSV value spanning several lines counts as one record.</p>
      <table>
        <thead>
          <tr><th>Column</th><th>Suggested</th><th>Use type</th><th>Transform</th><th>Validation</th></tr>
        </thead>
        <tbody>
          {% for column in sheet.columns %}
            <tr data-sheet="{{ sheet.index }}" data-column="{{ column.name }}" {% if column.validation.invalid_count or column.validation.errors %}class="invalid-row"{% endif %}>
              <td><strong>{{ column.original_name }}</strong><div class="hint">{{ column.name }}</div></td>
              <td>{{ column.suggested_label }}</td>
              <td>
                <select aria-label="Type for {{ column.original_name }}" class="type-select" name="type__{{ sheet.index }}__{{ column.name }}">
                  {% for value, label in type_options %}
                    <option value="{{ value }}" {% if value == column.selected_type %}selected{% endif %}>{{ label }}</option>
                  {% endfor %}
                </select>
              </td>
              <td>
                <select aria-label="Transform for {{ column.original_name }}" class="transform-select" name="transform__{{ sheet.index }}__{{ column.name }}">
                  {% for value, label in transform_options_by_type.get(column.selected_type, []) %}
                    <option value="{{ value }}" {% if value == column.selected_transform %}selected{% endif %}>{{ label }}</option>
                  {% endfor %}
                </select>
              </td>
              <td class="validation">
                <div class="counts {% if column.validation.invalid_count or column.validation.errors %}invalid{% else %}valid{% endif %}">{{ column.validation.valid_count }} valid, {{ column.validation.empty_count }} empty, {{ column.validation.invalid_count }} invalid</div>
                {% if column.validation.errors %}<ul class="examples invalid">{% for error in column.validation.errors %}<li>{{ error }}</li>{% endfor %}</ul>{% endif %}
                {% if column.validation.invalid_examples %}
                  <details open><summary>Values to fix (up to {{ sample_limit }})</summary><ul class="examples invalid">
                    {% for example in column.validation.invalid_examples %}<li>Row {{ example.source_row_number }}: <code>{{ example.value }}</code>. {{ example.error }}</li>{% endfor %}
                  </ul></details>
                {% endif %}
                {% if column.validation.valid_examples %}
                  <details><summary>Valid conversions (up to {{ sample_limit }})</summary><ul class="examples">
                    {% for example in column.validation.valid_examples %}<li>Row {{ example.source_row_number }}: <code>{{ example.value }}</code> &rarr; <code>{{ example.converted }}</code></li>{% endfor %}
                  </ul></details>
                {% endif %}
              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% endfor %}

    <div class="toolbar">
      <button id="import-button" type="submit" {% if not valid %}disabled{% endif %}>Import data</button>
      <button class="secondary" type="submit" formaction="/review">Check changes</button>
      <a class="button secondary" href="/">Choose another file</a>
    </div>
    <p class="hint">Empty cells stay empty. Invalid values must be fixed in the source file or converted with a suitable type and transform.</p>
    <noscript><p class="hint">After changing a choice, use Check changes to update the validation.</p></noscript>
  </form>
</main>
<script>
(() => {
  const optionsByType = {{ transform_options_by_type | tojson }};
  const form = document.getElementById('review-form');
  const importButton = document.getElementById('import-button');
  const summary = document.getElementById('validation-summary');
  const errors = document.getElementById('review-errors');
  let timer;
  let controller;
  let revision = 0;

  function showErrors(messages) {
    errors.replaceChildren();
    errors.hidden = !messages.length;
    const list = document.createElement('ul');
    list.className = 'messages';
    messages.forEach(message => {
      const item = document.createElement('li');
      item.textContent = message;
      list.append(item);
    });
    errors.append(list);
  }

  function showExamples(cell, examples, invalid) {
    if (!examples.length) return;
    const details = document.createElement('details');
    details.open = invalid;
    const label = document.createElement('summary');
    label.textContent = (invalid ? 'Values to fix' : 'Valid conversions') + ' (up to {{ sample_limit }})';
    details.append(label);
    const list = document.createElement('ul');
    list.className = 'examples' + (invalid ? ' invalid' : '');
    examples.forEach(example => {
      const item = document.createElement('li');
      item.append(document.createTextNode('Row ' + example.source_row_number + ': '));
      const value = document.createElement('code');
      value.textContent = example.value;
      item.append(value);
      if (invalid) {
        item.append(document.createTextNode('. ' + example.error));
      } else {
        item.append(document.createTextNode(' → '));
        const converted = document.createElement('code');
        converted.textContent = example.converted;
        item.append(converted);
      }
      list.append(item);
    });
    details.append(list);
    cell.append(details);
  }

  function renderValidation(data) {
    showErrors(data.errors || []);
    summary.textContent = data.summary;
    for (const sheet of data.sheets || []) {
      for (const column of sheet.columns) {
        const row = form.querySelector('[data-sheet="' + sheet.index + '"][data-column="' + column.name + '"]');
        if (!row) continue;
        const cell = row.querySelector('.validation');
        const report = column.validation;
        const invalid = report.invalid_count > 0 || report.errors.length > 0;
        row.classList.toggle('invalid-row', invalid);
        cell.replaceChildren();
        const counts = document.createElement('div');
        counts.className = 'counts ' + (invalid ? 'invalid' : 'valid');
        counts.textContent = report.valid_count + ' valid, ' + report.empty_count + ' empty, ' + report.invalid_count + ' invalid';
        cell.append(counts);
        if (report.errors.length) {
          const list = document.createElement('ul');
          list.className = 'examples invalid';
          report.errors.forEach(message => {
            const item = document.createElement('li');
            item.textContent = message;
            list.append(item);
          });
          cell.append(list);
        }
        showExamples(cell, report.invalid_examples, true);
        showExamples(cell, report.valid_examples, false);
      }
    }
    importButton.disabled = !data.valid;
  }

  async function validate(currentRevision) {
    controller = new AbortController();
    try {
      const response = await fetch('/validate', {method: 'POST', body: new FormData(form), signal: controller.signal});
      const data = await response.json();
      if (revision !== currentRevision) return;
      if (!response.ok) throw new Error((data.errors || ['Could not check this file.']).join(' '));
      renderValidation(data);
    } catch (error) {
      if (error.name === 'AbortError' || revision !== currentRevision) return;
      showErrors([error.message || 'Could not check this file. Use Check changes to retry.']);
      summary.textContent = 'Validation failed. Import is paused until the file can be checked.';
      importButton.disabled = true;
    }
  }

  form.addEventListener('change', event => {
    if (event.target.matches('.type-select')) {
      const transform = event.target.closest('tr').querySelector('.transform-select');
      const previous = transform.value;
      const options = optionsByType[event.target.value] || [];
      transform.replaceChildren();
      options.forEach(([value, label]) => transform.add(new Option(label, value)));
      transform.value = options.some(([value]) => value === previous) ? previous : 'none';
    }
    revision += 1;
    if (controller) controller.abort();
    clearTimeout(timer);
    importButton.disabled = true;
    summary.textContent = 'Checking all rows…';
    const currentRevision = revision;
    timer = setTimeout(() => validate(currentRevision), 180);
  });
})();
</script>
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
    if not re.fullmatch(r"[0-9a-f]{32}", token):
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


def label_for_type(column_type: str) -> str:
    return dict(TYPE_OPTIONS).get(column_type, column_type)


def _build_review(path: Path, token: str, selections=None, check_schema=True):
    frames = load_frames(path)
    multiple_sheets = len(frames) > 1
    source_path = Path(original_upload_name(path))
    selections = selections if selections is not None else {"replace_existing": "yes"}
    replace_existing = selections.get("replace_existing") == "yes"
    sheets = []
    prepared = []
    skipped = []
    errors = []
    valid_count = empty_count = invalid_count = 0
    tables = set()

    for index, (sheet_name, frame) in enumerate(frames):
        label = sheet_name or source_path.name
        if frame.empty and len(frame.columns) == 0:
            skipped.append(f"Skipped empty sheet: {label}")
            continue

        normalized, original_columns = normalize_frame(frame)
        suggested_types = detect_column_types(normalized)
        table_name = table_name_for(source_path, sheet_name, multiple_sheets)
        if table_name in tables:
            errors.append(f"More than one sheet maps to staging.{table_name}. Rename the sheets so they have different table names.")
        tables.add(table_name)
        columns = []
        column_types = {}
        column_transforms = {}

        for name, original_name in zip(normalized.columns, original_columns):
            suggested_type = suggested_types[name]
            selected_type = selections.get(f"type__{index}__{name}", suggested_type)
            selected_transform = selections.get(f"transform__{index}__{name}", "none")
            column_types[name] = selected_type
            column_transforms[name] = selected_transform
            report = validate_column(normalized[name], name, selected_type, selected_transform, sample_limit=SAMPLE_LIMIT)
            # Configuration errors are distinct from invalid cell values.
            report.setdefault("errors", [])
            valid_count += report["valid_count"]
            empty_count += report["empty_count"]
            invalid_count += report["invalid_count"]
            columns.append({
                "name": name,
                "original_name": original_name,
                "suggested_type": suggested_type,
                "suggested_label": label_for_type(suggested_type),
                "selected_type": selected_type,
                "selected_transform": selected_transform,
                "validation": report,
            })

        sheets.append({"index": index, "label": label, "table_name": table_name, "row_count": len(normalized), "columns": columns})
        prepared.append({"sheet_name": sheet_name, "table_name": table_name, "frame": normalized, "original_columns": original_columns, "column_types": column_types, "column_transforms": column_transforms})

    if not sheets:
        raise ValueError("No non-empty sheets were found.")

    configuration_errors = any(column["validation"]["errors"] for sheet in sheets for column in sheet["columns"])
    if check_schema and not replace_existing and not configuration_errors:
        try:
            with psycopg2.connect("") as conn:
                for item in prepared:
                    errors.extend(staging_schema_conflicts(conn, item["table_name"], item["column_types"]))
        except psycopg2.Error:
            errors.append("Could not check the existing table definitions. Check that PostgreSQL is running, then use Check changes.")

    valid = invalid_count == 0 and not configuration_errors and not errors
    if valid:
        summary = f"All rows checked: {valid_count} valid values and {empty_count} empty cells. Ready to import."
    else:
        summary = f"All rows checked: {valid_count} valid values, {empty_count} empty cells and {invalid_count} invalid values. Resolve the errors before importing."
    return {
        "filename": original_upload_name(path), "token": token,
        "sheets": sheets, "skipped": skipped, "errors": errors,
        "replace_existing": replace_existing,
        "valid": valid, "summary": summary,
        "type_options": TYPE_OPTIONS,
        "transform_options_by_type": TRANSFORM_OPTIONS_BY_TYPE,
        "sample_limit": SAMPLE_LIMIT,
    }, prepared


def preview_context(path: Path, token: str, selections=None) -> dict[str, object]:
    return _build_review(path, token, selections)[0]


def _validation_payload(context):
    return {key: context[key] for key in ("valid", "summary", "sheets", "errors")}


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


@app.post("/validate")
def validate_reviewed_file():
    token = request.form.get("token", "")
    path = uploaded_path_for_token(token)
    if path is None:
        return jsonify(valid=False, errors=["The uploaded file is no longer available. Upload it again."]), 400
    try:
        context = preview_context(path, token, request.form)
        return jsonify(_validation_payload(context))
    except Exception as exc:
        return jsonify(valid=False, errors=[str(exc)]), 400


@app.post("/review")
def review_changes():
    token = request.form.get("token", "")
    path = uploaded_path_for_token(token)
    if path is None:
        return render_template_string(UPLOAD_TEMPLATE, error="The uploaded file is no longer available. Upload it again.", superset_url=superset_url()), 400
    try:
        context = preview_context(path, token, request.form)
    except Exception as exc:
        return render_template_string(UPLOAD_TEMPLATE, error=str(exc), superset_url=superset_url()), 400
    return render_template_string(PREVIEW_TEMPLATE, **context)


@app.post("/import")
def import_reviewed_file():
    token = request.form.get("token", "")
    path = uploaded_path_for_token(token)
    if path is None:
        return render_template_string(UPLOAD_TEMPLATE, error="The uploaded file is no longer available. Upload it again.", superset_url=superset_url()), 400

    context = None
    try:
        # Recheck every row on the server, including submissions without JavaScript.
        context, prepared = _build_review(path, token, request.form, check_schema=False)
        if not context["valid"]:
            return render_template_string(PREVIEW_TEMPLATE, **context), 400

        messages = []
        source_path = Path(original_upload_name(path))
        with psycopg2.connect("") as conn:
            if not context["replace_existing"]:
                conflicts = []
                for item in prepared:
                    conflicts.extend(staging_schema_conflicts(conn, item["table_name"], item["column_types"]))
                if conflicts:
                    raise ValueError(" ".join(conflicts))
            bootstrap(conn)
            for item in prepared:
                if context["replace_existing"]:
                    delete_existing_import(conn, item["table_name"])
                batch_id = insert_frame(conn, path=source_path, **item)
                messages.append(f"Imported {len(item['frame'])} rows into staging.{item['table_name']} (batch_id={batch_id})")
    except Exception as exc:
        if context is not None:
            context["errors"].append(str(exc))
            context["valid"] = False
            context["summary"] = "Import did not complete. Review the error, adjust your choices and try again."
            return render_template_string(PREVIEW_TEMPLATE, **context), 400
        return render_template_string(UPLOAD_TEMPLATE, error=str(exc), superset_url=superset_url()), 400

    return render_template_string(RESULT_TEMPLATE, error=None, messages=messages, superset_url=superset_url())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("IMPORT_UI_PORT", "8090")))
