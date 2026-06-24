#!/usr/bin/env python3
"""Enable Superset file uploads for the local PostgreSQL database connection."""

from __future__ import annotations

import json
import os

from superset.app import create_app


app = create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database

    database_name = os.environ.get("SUPERSET_DATABASE_LABEL", "Caritas Local PostgreSQL")
    database = (
        db.session.query(Database)
        .filter(Database.database_name == database_name)
        .one_or_none()
    )
    if database is None:
        raise SystemExit(f"Superset database connection not found: {database_name}")

    extra = database.get_extra() or {}
    extra.setdefault("metadata_params", {})
    extra.setdefault("engine_params", {})
    extra.setdefault("metadata_cache_timeout", {})
    extra.setdefault("schemas_allowed_for_file_upload", [])

    database.allow_file_upload = True
    database.extra = json.dumps(extra, indent=4)
    db.session.commit()
    print(f"Enabled file uploads for Superset database: {database_name}")
