"""Importer review checks exercise real conversions without a running database."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import import_ui


class ImportReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.upload_patch = patch.object(import_ui, "UPLOAD_DIR", Path(self.directory.name))
        self.upload_patch.start()
        self.addCleanup(self.upload_patch.stop)
        self.client = import_ui.app.test_client()

    def upload(self, content, filename="example.csv"):
        response = self.client.post(
            "/preview", data={"file": (BytesIO(content.encode()), filename)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        path = next(Path(self.directory.name).iterdir())
        return path.name.split("__", 1)[0], response

    def form(self, token, **choices):
        return {"token": token, "replace_existing": "yes", **choices}

    def report(self, response, column=0, sheet=0):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["sheets"][sheet]["columns"][column]["validation"]

    def test_initial_preview_reports_valid_values_and_type_specific_transforms(self):
        token, response = self.upload("date,postcode\n2025-12-31,0300\n2026-01-01,0400\n")
        page = response.get_data(as_text=True)
        self.assertIn("2 valid, 0 empty, 0 invalid", page)
        self.assertIn("Valid conversions", page)
        self.assertIn("Year / month / day", page)
        self.assertIn('id="import-button" type="submit" >', page)
        self.assertIn("optionsByType[event.target.value]", page)
        self.assertEqual(len(token), 32)

    def test_changed_type_checks_entire_file_beyond_display_sample(self):
        token, _ = self.upload("value\n1\n2\n3\n4\n5\n6\nwrong\n")
        response = self.client.post("/validate", data=self.form(token, type__0__value="integer"))
        report = self.report(response)
        self.assertFalse(response.get_json()["valid"])
        self.assertEqual(report["valid_count"], 6)
        self.assertEqual(report["invalid_count"], 1)
        self.assertEqual(len(report["valid_examples"]), 5)
        self.assertEqual(report["invalid_examples"][0]["source_row_number"], 8)
        self.assertEqual(report["invalid_examples"][0]["value"], "wrong")

    def test_csv_blank_records_keep_validation_row_numbers(self):
        token, _ = self.upload("value\n1\n\nwrong\n")
        response = self.client.post("/validate", data=self.form(token, type__0__value="integer"))
        report = self.report(response)
        self.assertEqual(report["empty_count"], 1)
        self.assertEqual(report["invalid_examples"][0]["source_row_number"], 4)

    def test_selected_date_transform_changes_validation_and_conversion(self):
        token, _ = self.upload("date\n12/31/2025\n01/30/2026\n")
        form = self.form(token, type__0__date="date", transform__0__date="date_dmy")
        report = self.report(self.client.post("/validate", data=form))
        self.assertEqual(report["invalid_count"], 2)
        form["transform__0__date"] = "date_mdy"
        response = self.client.post("/validate", data=form)
        report = self.report(response)
        self.assertTrue(response.get_json()["valid"])
        self.assertEqual(report["valid_examples"][0]["converted"], "2025-12-31")

    def test_transform_failure_is_visible_and_does_not_silently_empty_cell(self):
        token, _ = self.upload("category\n03 Familie\nMissing\n")
        response = self.client.post("/validate", data=self.form(
            token, type__0__category="integer", transform__0__category="leading_number",
        ))
        report = self.report(response)
        self.assertEqual(report["valid_count"], 1)
        self.assertEqual(report["empty_count"], 0)
        self.assertEqual(report["invalid_count"], 1)
        self.assertEqual(report["valid_examples"][0]["converted"], "3")

    def test_invalid_type_transform_pair_is_rejected_on_server(self):
        token, _ = self.upload("date\n2025-12-31\n")
        response = self.client.post("/validate", data=self.form(
            token, type__0__date="date", transform__0__date="leading_number",
        ))
        report = self.report(response)
        self.assertFalse(response.get_json()["valid"])
        self.assertTrue(report["errors"])

    def test_invalid_import_preserves_choices_without_opening_database(self):
        token, _ = self.upload("value\nwrong\n")
        with patch.object(import_ui.psycopg2, "connect") as connect:
            response = self.client.post("/import", data=self.form(token, type__0__value="integer"))
        self.assertEqual(response.status_code, 400)
        connect.assert_not_called()
        page = response.get_data(as_text=True)
        self.assertIn('value="integer" selected', page)
        self.assertIn('value="' + token + '"', page)
        self.assertIn("wrong", page)
        self.assertIsNotNone(import_ui.uploaded_path_for_token(token))

    def test_valid_import_uses_selected_types_and_transforms(self):
        token, _ = self.upload("value\n03 Familie\n")
        with patch.object(import_ui.psycopg2, "connect"), \
             patch.object(import_ui, "bootstrap"), \
             patch.object(import_ui, "delete_existing_import") as delete, \
             patch.object(import_ui, "insert_frame", return_value="batch") as insert:
            response = self.client.post("/import", data=self.form(
                token, type__0__value="integer", transform__0__value="leading_number",
            ))
        self.assertEqual(response.status_code, 200)
        delete.assert_called_once()
        self.assertEqual(insert.call_args.kwargs["column_types"], {"value": "integer"})
        self.assertEqual(insert.call_args.kwargs["column_transforms"], {"value": "leading_number"})

    def test_append_schema_conflicts_reported_before_database_mutation(self):
        token, _ = self.upload("value\n1\n")
        form = {"token": token, "type__0__value": "integer"}
        with patch.object(import_ui.psycopg2, "connect"), \
             patch.object(import_ui, "staging_schema_conflicts", return_value=["Existing value is text. Choose Replace to change its type."]), \
             patch.object(import_ui, "bootstrap") as bootstrap, \
             patch.object(import_ui, "insert_frame") as insert:
            validation = self.client.post("/validate", data=form)
            response = self.client.post("/import", data=form)
        self.assertFalse(validation.get_json()["valid"])
        self.assertIn("Existing value is text", validation.get_json()["errors"][0])
        self.assertEqual(response.status_code, 400)
        bootstrap.assert_not_called()
        insert.assert_not_called()
        self.assertNotIn('value="yes" checked', response.get_data(as_text=True))

    def test_database_failure_preserves_review(self):
        token, _ = self.upload("value\n1\n")
        with patch.object(import_ui.psycopg2, "connect", side_effect=import_ui.psycopg2.OperationalError("database unavailable")):
            response = self.client.post("/import", data=self.form(token))
        self.assertEqual(response.status_code, 400)
        self.assertIn("database unavailable", response.get_data(as_text=True))
        self.assertIn("Review Import", response.get_data(as_text=True))
        self.assertIsNotNone(import_ui.uploaded_path_for_token(token))

    def test_review_without_javascript_updates_report_and_preserves_transform(self):
        token, _ = self.upload("value\n03 Familie\n")
        response = self.client.post("/review", data=self.form(
            token, type__0__value="integer", transform__0__value="leading_number",
        ))
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("1 valid, 0 empty, 0 invalid", page)
        self.assertIn('value="leading_number" selected', page)

    def test_duplicate_sheet_table_names_are_rejected_upfront(self):
        token, _ = self.upload("value\n1\n")
        with patch.object(import_ui, "load_frames", return_value=[
            ("A-B", pd.DataFrame({"value": ["1"]})),
            ("A B", pd.DataFrame({"value": ["2"]})),
        ]):
            response = self.client.post("/validate", data=self.form(token))
        self.assertFalse(response.get_json()["valid"])
        self.assertIn("More than one sheet", response.get_json()["errors"][0])

    def test_tokens_do_not_allow_glob_matching_or_path_traversal(self):
        self.upload("value\n1\n")
        for token in ("*", "../file", "?" * 32, ""):
            response = self.client.post("/validate", data={"token": token})
            self.assertEqual(response.status_code, 400)
            self.assertIsNone(import_ui.uploaded_path_for_token(token))


if __name__ == "__main__":
    unittest.main()
