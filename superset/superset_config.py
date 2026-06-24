import os


SECRET_KEY = os.environ.get(
    "SUPERSET_SECRET_KEY",
    "caritas-local-only-secret-key-change-me-before-sharing-2026",
)

SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SUPERSET_METADATA_URI",
    "sqlite:////app/superset_home/superset.db",
)

ENABLE_PROXY_FIX = False
WTF_CSRF_ENABLED = True

FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}
