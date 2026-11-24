#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LOCAL_ENV_FILE="$PROJECT_DIR/.caritas-local.env"
SETTINGS_FILE="$PROJECT_DIR/.caritas-settings.env"

# A restored backup carries its database credentials and Superset encryption key.
# Generated settings only fill unset variables, so explicit overrides still work.
if [ -f "$SETTINGS_FILE" ]; then
  # shellcheck disable=SC1090
  . "$SETTINGS_FILE"
fi

USER_SET_POSTGRES_PORT="${POSTGRES_PORT+x}"
USER_POSTGRES_PORT="${POSTGRES_PORT-}"
USER_SET_SUPERSET_PORT="${SUPERSET_PORT+x}"
USER_SUPERSET_PORT="${SUPERSET_PORT-}"
USER_SET_IMPORT_UI_PORT="${IMPORT_UI_PORT+x}"
USER_IMPORT_UI_PORT="${IMPORT_UI_PORT-}"

if [ -f "$LOCAL_ENV_FILE" ]; then
  # Stores auto-selected localhost ports so later commands report the same URLs.
  # shellcheck disable=SC1090
  . "$LOCAL_ENV_FILE"
fi

if [ "$USER_SET_POSTGRES_PORT" = "x" ]; then
  POSTGRES_PORT="$USER_POSTGRES_PORT"
fi
if [ "$USER_SET_SUPERSET_PORT" = "x" ]; then
  SUPERSET_PORT="$USER_SUPERSET_PORT"
fi
if [ "$USER_SET_IMPORT_UI_PORT" = "x" ]; then
  IMPORT_UI_PORT="$USER_IMPORT_UI_PORT"
fi

PROJECT_NAME="${PROJECT_NAME:-caritas_dashboard}"
NETWORK_NAME="${NETWORK_NAME:-caritas_local}"

POSTGRES_IMAGE="${POSTGRES_IMAGE:-docker.io/library/postgres:16.4-alpine}"
SUPERSET_BASE_IMAGE="${SUPERSET_BASE_IMAGE:-docker.io/apache/superset:4.1.1}"
SUPERSET_IMAGE="${SUPERSET_IMAGE:-localhost/caritas-superset:4.1.1-local}"
INGEST_IMAGE="${INGEST_IMAGE:-localhost/caritas-ingest:py3.12-ui-local}"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-caritas_postgres}"
SUPERSET_CONTAINER="${SUPERSET_CONTAINER:-caritas_superset}"
IMPORT_UI_CONTAINER="${IMPORT_UI_CONTAINER:-caritas_import_ui}"
POSTGRES_VOLUME="${POSTGRES_VOLUME:-caritas_postgres_data}"
SUPERSET_VOLUME="${SUPERSET_VOLUME:-caritas_superset_home}"

POSTGRES_DB="${POSTGRES_DB:-caritas}"
POSTGRES_USER="${POSTGRES_USER:-caritas}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-caritas_local_password}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

SUPERSET_PORT="${SUPERSET_PORT:-8088}"
IMPORT_UI_PORT="${IMPORT_UI_PORT:-8090}"
SUPERSET_ADMIN_USER="${SUPERSET_ADMIN_USER:-admin}"
SUPERSET_ADMIN_PASSWORD="${SUPERSET_ADMIN_PASSWORD:-admin}"
SUPERSET_ADMIN_EMAIL="${SUPERSET_ADMIN_EMAIL:-admin@local.invalid}"
SUPERSET_SECRET_KEY="${SUPERSET_SECRET_KEY:-caritas-local-only-secret-key-change-me-before-sharing-2026}"
SUPERSET_DATABASE_LABEL="${SUPERSET_DATABASE_LABEL:-Caritas Local PostgreSQL}"

urlencode_component() {
  local LC_ALL=C value="$1" character index
  for ((index=0; index<${#value}; index++)); do
    character="${value:index:1}"
    case "$character" in
      [a-zA-Z0-9.~_-]) printf '%s' "$character" ;;
      *) printf '%%%02X' "'$character" ;;
    esac
  done
}

ANALYTICS_SQLALCHEMY_URI="${ANALYTICS_SQLALCHEMY_URI:-postgresql+psycopg2://$(urlencode_component "$POSTGRES_USER"):$(urlencode_component "$POSTGRES_PASSWORD")@${POSTGRES_CONTAINER}:5432/$(urlencode_component "$POSTGRES_DB")}"

DATA_DIR="$PROJECT_DIR/data"
EXPORTS_DIR="$PROJECT_DIR/exports"
SUPERSET_CONFIG_DIR="$PROJECT_DIR/superset"

# Only these public examples travel with the app. Other source data stays out
# of the portable package; imported database rows are already in its dump.
PUBLIC_DEMO_FILES=(
  data/README.md
  data/codebook.csv
  data/en/counselling_events.csv
  data/de/beratungsdaten_synthesized.csv
  sql/schema_en.sql
  sql/schema_de.sql
)

log() {
  printf '[caritas] %s\n' "$*"
}

die() {
  printf '[caritas] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Local Caritas Dashboard runner

Usage:
  ./run.sh start                 Start PostgreSQL, Superset, and the import UI
  ./run.sh stop                  Stop containers without deleting data
  ./run.sh status                Show container status and local URLs
  ./run.sh import data/file.xlsx Import a CSV/XLS/XLSX file into staging tables
  ./run.sh backup                Create a complete, portable backup in exports/
  ./run.sh restore               Restore and start this portable backup on a fresh installation
  ./run.sh build                 Build local helper images
  ./run.sh reset                 Delete containers and persistent volumes after confirmation
  ./run.sh help                  Show this help

Superset:
  URL:      http://127.0.0.1:8088
  Username: admin
  Password: admin
  Restored backups keep their original Superset accounts.

Import UI:
  URL:      http://127.0.0.1:8090

Environment overrides:
  POSTGRES_PORT=15432 SUPERSET_PORT=18088 IMPORT_UI_PORT=18090 ./run.sh start
  SUPERSET_ADMIN_PASSWORD='new-password' ./run.sh start
USAGE
}

require_podman() {
  command -v podman >/dev/null 2>&1 || die "Podman is not installed or not on PATH."
  podman info >/dev/null 2>&1 || die "Podman is installed, but it is not running. On macOS, run: podman machine start"
}

ensure_dirs() {
  mkdir -p "$DATA_DIR" "$EXPORTS_DIR" "$SUPERSET_CONFIG_DIR"
}

valid_port() {
  case "$1" in
    ''|*[!0-9]*)
      return 1
      ;;
  esac
  [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

port_available() {
  local port="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
    return $?
  fi

  if command -v nc >/dev/null 2>&1; then
    ! nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    return $?
  fi

  return 0
}

find_available_port() {
  local preferred="$1"
  local fallback_start="$2"
  local fallback_end="$3"
  local port

  if valid_port "$preferred" && port_available "$preferred"; then
    printf '%s\n' "$preferred"
    return
  fi

  for port in $(seq "$fallback_start" "$fallback_end"); do
    if port_available "$port"; then
      printf '%s\n' "$port"
      return
    fi
  done

  return 1
}

save_local_env() {
  cat > "$LOCAL_ENV_FILE" <<EOF
POSTGRES_PORT=$POSTGRES_PORT
SUPERSET_PORT=$SUPERSET_PORT
IMPORT_UI_PORT=$IMPORT_UI_PORT
EOF
}

configure_host_ports() {
  local next_port

  valid_port "$POSTGRES_PORT" || die "Invalid POSTGRES_PORT: $POSTGRES_PORT"
  valid_port "$SUPERSET_PORT" || die "Invalid SUPERSET_PORT: $SUPERSET_PORT"
  valid_port "$IMPORT_UI_PORT" || die "Invalid IMPORT_UI_PORT: $IMPORT_UI_PORT"

  if ! container_exists "$POSTGRES_CONTAINER" && ! port_available "$POSTGRES_PORT"; then
    if [ "$USER_SET_POSTGRES_PORT" = "x" ]; then
      die "POSTGRES_PORT=$POSTGRES_PORT is already in use. Pick another with: POSTGRES_PORT=15432 ./run.sh start"
    fi
    next_port="$(find_available_port "$POSTGRES_PORT" 15432 15499)" || die "No available PostgreSQL host port found in 15432-15499."
    log "PostgreSQL host port $POSTGRES_PORT is in use; using $next_port instead."
    POSTGRES_PORT="$next_port"
  fi

  if ! container_exists "$SUPERSET_CONTAINER" && ! port_available "$SUPERSET_PORT"; then
    if [ "$USER_SET_SUPERSET_PORT" = "x" ]; then
      die "SUPERSET_PORT=$SUPERSET_PORT is already in use. Pick another with: SUPERSET_PORT=18088 ./run.sh start"
    fi
    next_port="$(find_available_port "$SUPERSET_PORT" 18088 18149)" || die "No available Superset host port found in 18088-18149."
    log "Superset host port $SUPERSET_PORT is in use; using $next_port instead."
    SUPERSET_PORT="$next_port"
  fi

  if ! container_exists "$IMPORT_UI_CONTAINER" && ! port_available "$IMPORT_UI_PORT"; then
    if [ "$USER_SET_IMPORT_UI_PORT" = "x" ]; then
      die "IMPORT_UI_PORT=$IMPORT_UI_PORT is already in use. Pick another with: IMPORT_UI_PORT=18090 ./run.sh start"
    fi
    next_port="$(find_available_port "$IMPORT_UI_PORT" 18090 18149)" || die "No available import UI host port found in 18090-18149."
    log "Import UI host port $IMPORT_UI_PORT is in use; using $next_port instead."
    IMPORT_UI_PORT="$next_port"
  fi

  save_local_env
}

ensure_network() {
  if ! podman network exists "$NETWORK_NAME" >/dev/null 2>&1; then
    log "Creating Podman network: $NETWORK_NAME"
    podman network create "$NETWORK_NAME" >/dev/null
  fi
}

ensure_volumes() {
  if ! podman volume exists "$POSTGRES_VOLUME" >/dev/null 2>&1; then
    log "Creating PostgreSQL volume: $POSTGRES_VOLUME"
    podman volume create "$POSTGRES_VOLUME" >/dev/null
  fi
  if ! podman volume exists "$SUPERSET_VOLUME" >/dev/null 2>&1; then
    log "Creating Superset volume: $SUPERSET_VOLUME"
    podman volume create "$SUPERSET_VOLUME" >/dev/null
  fi
}

ensure_postgres_image() {
  if ! podman image exists "$POSTGRES_IMAGE" >/dev/null 2>&1; then
    log "Pulling PostgreSQL image: $POSTGRES_IMAGE"
    podman pull "$POSTGRES_IMAGE"
  fi
}

build_images() {
  require_podman
  ensure_dirs

  if ! podman image exists "$SUPERSET_IMAGE" >/dev/null 2>&1; then
    log "Building local Superset image: $SUPERSET_IMAGE"
    podman build \
      --build-arg "SUPERSET_BASE_IMAGE=$SUPERSET_BASE_IMAGE" \
      -f "$PROJECT_DIR/Containerfile.superset" \
      -t "$SUPERSET_IMAGE" \
      "$PROJECT_DIR"
  else
    log "Superset image already exists: $SUPERSET_IMAGE"
  fi

  if ! podman image exists "$INGEST_IMAGE" >/dev/null 2>&1; then
    log "Building local import image: $INGEST_IMAGE"
    podman build \
      -f "$PROJECT_DIR/Containerfile.ingest" \
      -t "$INGEST_IMAGE" \
      "$PROJECT_DIR"
  else
    log "Import image already exists: $INGEST_IMAGE"
  fi
}

container_exists() {
  podman container exists "$1" >/dev/null 2>&1
}

container_running() {
  [ "$(podman inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

create_postgres_container() {
  log "Creating PostgreSQL container on 127.0.0.1:${POSTGRES_PORT}."
  podman run -d \
    --name "$POSTGRES_CONTAINER" \
    --network "$NETWORK_NAME" \
    -p "127.0.0.1:${POSTGRES_PORT}:5432" \
    -e "POSTGRES_DB=$POSTGRES_DB" \
    -e "POSTGRES_USER=$POSTGRES_USER" \
    -e "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
    -v "$POSTGRES_VOLUME:/var/lib/postgresql/data" \
    "$POSTGRES_IMAGE" >/dev/null
}

recover_postgres_port_conflict() {
  local next_port

  if [ "$USER_SET_POSTGRES_PORT" = "x" ]; then
    die "POSTGRES_PORT=$POSTGRES_PORT is already in use. Pick another with: POSTGRES_PORT=15432 ./run.sh start"
  fi

  next_port="$(find_available_port "$POSTGRES_PORT" 15432 15499)" || die "No available PostgreSQL host port found in 15432-15499."
  log "PostgreSQL host port $POSTGRES_PORT is in use; recreating container with $next_port."
  POSTGRES_PORT="$next_port"
  save_local_env
  podman rm "$POSTGRES_CONTAINER" >/dev/null
  create_postgres_container
}

start_postgres() {
  local start_output

  ensure_postgres_image

  if container_exists "$POSTGRES_CONTAINER"; then
    if container_running "$POSTGRES_CONTAINER"; then
      log "PostgreSQL is already running."
    else
      log "Starting PostgreSQL container."
      if ! start_output="$(podman start "$POSTGRES_CONTAINER" 2>&1)"; then
        if [[ "$start_output" == *"address already in use"* || "$start_output" == *"bind"* ]]; then
          recover_postgres_port_conflict
        else
          printf '%s\n' "$start_output" >&2
          die "Could not start PostgreSQL container."
        fi
      fi
    fi
  else
    create_postgres_container
  fi

  wait_for_postgres
  bootstrap_postgres
}

wait_for_postgres() {
  log "Waiting for PostgreSQL to accept connections."
  for _ in $(seq 1 60); do
    if podman exec "$POSTGRES_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  die "PostgreSQL did not become ready in time."
}

bootstrap_postgres() {
  log "Ensuring base database schemas exist."
  podman exec -i "$POSTGRES_CONTAINER" psql \
    -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" <<'SQL'
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS raw.import_batches (
  batch_id uuid PRIMARY KEY,
  source_file text NOT NULL,
  sheet_name text,
  staging_table text NOT NULL,
  row_count integer NOT NULL,
  original_columns jsonb NOT NULL,
  loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.import_rows (
  id bigserial PRIMARY KEY,
  batch_id uuid NOT NULL REFERENCES raw.import_batches(batch_id) ON DELETE CASCADE,
  source_file text NOT NULL,
  sheet_name text,
  source_row_number integer NOT NULL,
  row_data jsonb NOT NULL,
  loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW analytics.import_batches AS
SELECT
  batch_id,
  source_file,
  sheet_name,
  staging_table,
  row_count,
  original_columns,
  loaded_at
FROM raw.import_batches;
SQL
}

superset_env_args() {
  printf '%s\0' \
    -e "SUPERSET_SECRET_KEY=$SUPERSET_SECRET_KEY" \
    -e "POSTGRES_HOST=$POSTGRES_CONTAINER" \
    -e "POSTGRES_PORT=5432" \
    -e "POSTGRES_DB=$POSTGRES_DB" \
    -e "POSTGRES_USER=$POSTGRES_USER" \
    -e "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
    -e "SUPERSET_DATABASE_LABEL=$SUPERSET_DATABASE_LABEL"
}

run_superset_once() {
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(superset_env_args)

  podman run --rm \
    --network "$NETWORK_NAME" \
    "${args[@]}" \
    -v "$SUPERSET_VOLUME:/app/superset_home" \
    -v "$SUPERSET_CONFIG_DIR:/app/pythonpath:ro" \
    "$SUPERSET_IMAGE" \
    "$@"
}

setup_superset_metadata() {
  log "Running Superset metadata migrations."
  run_superset_once superset db upgrade

  if [ "${RESTORING_BACKUP:-0}" = "1" ] || [ -f "$PROJECT_DIR/.caritas-restored" ]; then
    log "Keeping the Superset user accounts restored from backup."
  elif run_superset_once superset fab create-admin \
    --username "$SUPERSET_ADMIN_USER" \
    --firstname Local \
    --lastname Admin \
    --email "$SUPERSET_ADMIN_EMAIL" \
    --password "$SUPERSET_ADMIN_PASSWORD"; then
    log "Created Superset admin user '$SUPERSET_ADMIN_USER'."
  else
    log "Superset admin user may already exist; continuing."
  fi

  log "Initializing Superset permissions."
  run_superset_once superset init

  log "Registering PostgreSQL database in Superset."
  if run_superset_once superset set-database-uri \
    -d "$SUPERSET_DATABASE_LABEL" \
    -u "$ANALYTICS_SQLALCHEMY_URI"; then
    log "Registered '$SUPERSET_DATABASE_LABEL'."
    log "Enabling Superset file uploads for '$SUPERSET_DATABASE_LABEL'."
    run_superset_once python /app/pythonpath/enable_file_upload.py
  else
    log "Could not auto-register the database. You can add it manually in Superset with:"
    log "$ANALYTICS_SQLALCHEMY_URI"
  fi
}

create_superset_container() {
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(superset_env_args)

  log "Creating Superset container on 127.0.0.1:${SUPERSET_PORT}."
  podman run -d \
    --name "$SUPERSET_CONTAINER" \
    --network "$NETWORK_NAME" \
    -p "127.0.0.1:${SUPERSET_PORT}:8088" \
    "${args[@]}" \
    -v "$SUPERSET_VOLUME:/app/superset_home" \
    -v "$SUPERSET_CONFIG_DIR:/app/pythonpath:ro" \
    "$SUPERSET_IMAGE" \
    superset run -h 0.0.0.0 -p 8088 >/dev/null
}

recover_superset_port_conflict() {
  local next_port

  if [ "$USER_SET_SUPERSET_PORT" = "x" ]; then
    die "SUPERSET_PORT=$SUPERSET_PORT is already in use. Pick another with: SUPERSET_PORT=18088 ./run.sh start"
  fi

  next_port="$(find_available_port "$SUPERSET_PORT" 18088 18149)" || die "No available Superset host port found in 18088-18149."
  log "Superset host port $SUPERSET_PORT is in use; recreating container with $next_port."
  SUPERSET_PORT="$next_port"
  save_local_env
  podman rm "$SUPERSET_CONTAINER" >/dev/null
  create_superset_container
}

start_superset() {
  local start_output

  if container_running "$SUPERSET_CONTAINER"; then
    log "Superset is already running."
    return
  fi

  setup_superset_metadata

  if container_exists "$SUPERSET_CONTAINER"; then
    log "Starting Superset container."
    if ! start_output="$(podman start "$SUPERSET_CONTAINER" 2>&1)"; then
      if [[ "$start_output" == *"address already in use"* || "$start_output" == *"bind"* ]]; then
        recover_superset_port_conflict
      else
        printf '%s\n' "$start_output" >&2
        die "Could not start Superset container."
      fi
    fi
  else
    create_superset_container
  fi
}

import_ui_env_args() {
  printf '%s\0' \
    -e "PGHOST=$POSTGRES_CONTAINER" \
    -e "PGPORT=5432" \
    -e "PGDATABASE=$POSTGRES_DB" \
    -e "PGUSER=$POSTGRES_USER" \
    -e "PGPASSWORD=$POSTGRES_PASSWORD" \
    -e "IMPORT_UI_PORT=8090" \
    -e "SUPERSET_URL=http://127.0.0.1:${SUPERSET_PORT}"
}

create_import_ui_container() {
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(import_ui_env_args)

  log "Creating import UI container on 127.0.0.1:${IMPORT_UI_PORT}."
  podman run -d \
    --name "$IMPORT_UI_CONTAINER" \
    --network "$NETWORK_NAME" \
    -p "127.0.0.1:${IMPORT_UI_PORT}:8090" \
    "${args[@]}" \
    -v "$PROJECT_DIR:/work:ro" \
    -w /work \
    "$INGEST_IMAGE" \
    python scripts/import_ui.py >/dev/null
}

recover_import_ui_port_conflict() {
  local next_port

  if [ "$USER_SET_IMPORT_UI_PORT" = "x" ]; then
    die "IMPORT_UI_PORT=$IMPORT_UI_PORT is already in use. Pick another with: IMPORT_UI_PORT=18090 ./run.sh start"
  fi

  next_port="$(find_available_port "$IMPORT_UI_PORT" 18090 18149)" || die "No available import UI host port found in 18090-18149."
  log "Import UI host port $IMPORT_UI_PORT is in use; recreating container with $next_port."
  IMPORT_UI_PORT="$next_port"
  save_local_env
  podman rm "$IMPORT_UI_CONTAINER" >/dev/null
  create_import_ui_container
}

start_import_ui() {
  local start_output

  if container_running "$IMPORT_UI_CONTAINER"; then
    log "Import UI is already running."
    return
  fi

  if container_exists "$IMPORT_UI_CONTAINER"; then
    log "Starting import UI container."
    if ! start_output="$(podman start "$IMPORT_UI_CONTAINER" 2>&1)"; then
      if [[ "$start_output" == *"address already in use"* || "$start_output" == *"bind"* ]]; then
        recover_import_ui_port_conflict
      else
        printf '%s\n' "$start_output" >&2
        die "Could not start import UI container."
      fi
    fi
  else
    create_import_ui_container
  fi
}

cmd_start() {
  if [ -f "$PROJECT_DIR/backup/format" ] && [ ! -f "$PROJECT_DIR/.caritas-restored" ]; then
    die "This is a portable backup. Restore it first with ./run.sh restore"
  fi
  require_podman
  ensure_dirs
  ensure_network
  ensure_volumes
  configure_host_ports
  build_images
  start_postgres
  start_superset
  start_import_ui

  log "Ready."
  log "Superset:   http://127.0.0.1:${SUPERSET_PORT}"
  log "Import UI:  http://127.0.0.1:${IMPORT_UI_PORT}"
  if [ -f "$PROJECT_DIR/.caritas-restored" ]; then
    log "Login:      Use your Superset account from the backup."
  else
    log "Login:      ${SUPERSET_ADMIN_USER} / ${SUPERSET_ADMIN_PASSWORD}"
  fi
  log "PostgreSQL: 127.0.0.1:${POSTGRES_PORT} database=${POSTGRES_DB} user=${POSTGRES_USER}"
}

cmd_stop() {
  require_podman
  for container in "$IMPORT_UI_CONTAINER" "$SUPERSET_CONTAINER" "$POSTGRES_CONTAINER"; do
    if container_running "$container"; then
      log "Stopping $container."
      podman stop "$container" >/dev/null
    else
      log "$container is not running."
    fi
  done
}

cmd_status() {
  require_podman
  log "Containers:"
  for container in "$POSTGRES_CONTAINER" "$SUPERSET_CONTAINER" "$IMPORT_UI_CONTAINER"; do
    if container_exists "$container"; then
      podman ps -a --filter "name=^${container}$" \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
      log "$container: not created"
    fi
  done
  printf '\n'
  log "Superset URL:   http://127.0.0.1:${SUPERSET_PORT}"
  log "Import UI URL:  http://127.0.0.1:${IMPORT_UI_PORT}"
  log "PostgreSQL URL: 127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"
}

container_path_for_project_file() {
  local input="$1"
  local dir base abs_dir abs_file
  dir="$(dirname "$input")"
  base="$(basename "$input")"
  abs_dir="$(cd "$dir" && pwd -P)"
  abs_file="$abs_dir/$base"

  case "$abs_file" in
    "$PROJECT_DIR"/*)
      printf '/work/%s\n' "${abs_file#"$PROJECT_DIR"/}"
      ;;
    *)
      die "Import files must be inside this project folder. Put them under: $DATA_DIR"
      ;;
  esac
}

cmd_import() {
  local input="${1:-}"
  [ -n "$input" ] || die "Missing import file. Usage: ./run.sh import data/file.xlsx"
  [ -f "$input" ] || die "Import file not found: $input"

  require_podman
  ensure_dirs
  ensure_network
  ensure_volumes
  configure_host_ports
  build_images
  start_postgres

  local container_file
  container_file="$(container_path_for_project_file "$input")"

  log "Importing $input into PostgreSQL staging tables."
  podman run --rm \
    --network "$NETWORK_NAME" \
    -e "PGHOST=$POSTGRES_CONTAINER" \
    -e "PGPORT=5432" \
    -e "PGDATABASE=$POSTGRES_DB" \
    -e "PGUSER=$POSTGRES_USER" \
    -e "PGPASSWORD=$POSTGRES_PASSWORD" \
    -v "$PROJECT_DIR:/work:ro" \
    -w /work \
    "$INGEST_IMAGE" \
    python scripts/import_staging.py "$container_file"
}

checksum_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d ' ' -f 1
  else
    die "Backups require sha256sum or shasum to check file integrity."
  fi
}

write_settings() {
  local output="$1" key value
  : > "$output"
  chmod 600 "$output"
  for key in NETWORK_NAME POSTGRES_IMAGE SUPERSET_IMAGE INGEST_IMAGE \
    POSTGRES_CONTAINER SUPERSET_CONTAINER IMPORT_UI_CONTAINER \
    POSTGRES_VOLUME SUPERSET_VOLUME POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \
    SUPERSET_SECRET_KEY SUPERSET_ADMIN_USER SUPERSET_ADMIN_PASSWORD \
    SUPERSET_ADMIN_EMAIL SUPERSET_DATABASE_LABEL; do
    value="${!key}"
    printf 'if [ -z "${%s+x}" ]; then %s=%q; fi\n' "$key" "$key" "$value" >> "$output"
  done
}

capture_backup_settings() {
  local scratch="$1" entry
  # Read the actual container credentials, including settings supplied only at
  # its original start. NUL separators preserve spaces and newlines in secrets.
  podman inspect --format '{{range .Config.Env}}{{printf "%s\x00" .}}{{end}}' \
    "$POSTGRES_CONTAINER" > "$scratch"
  while IFS= read -r -d '' entry; do
    case "$entry" in
      POSTGRES_DB=*) POSTGRES_DB="${entry#*=}" ;;
      POSTGRES_USER=*) POSTGRES_USER="${entry#*=}" ;;
      POSTGRES_PASSWORD=*) POSTGRES_PASSWORD="${entry#*=}" ;;
    esac
  done < "$scratch"
  podman inspect --format '{{range .Config.Env}}{{printf "%s\x00" .}}{{end}}' \
    "$SUPERSET_CONTAINER" > "$scratch"
  while IFS= read -r -d '' entry; do
    case "$entry" in
      SUPERSET_SECRET_KEY=*) SUPERSET_SECRET_KEY="${entry#*=}" ;;
      SUPERSET_DATABASE_LABEL=*) SUPERSET_DATABASE_LABEL="${entry#*=}" ;;
    esac
  done < "$scratch"
  rm "$scratch"
  POSTGRES_IMAGE="$(podman inspect --format '{{.ImageName}}' "$POSTGRES_CONTAINER")"
  SUPERSET_IMAGE="$(podman inspect --format '{{.ImageName}}' "$SUPERSET_CONTAINER")"
  if container_exists "$IMPORT_UI_CONTAINER"; then
    INGEST_IMAGE="$(podman inspect --format '{{.ImageName}}' "$IMPORT_UI_CONTAINER")"
  fi
}

cmd_backup() (
  # The subshell keeps cleanup traps local to this command.
  umask 077
  require_podman
  ensure_dirs
  container_running "$POSTGRES_CONTAINER" || die "PostgreSQL is not running. Start it first with ./run.sh start"
  container_exists "$SUPERSET_CONTAINER" || die "Superset has not been set up. Run ./run.sh start first."

  local stamp package partial relative digest success=0 container
  local paused=()
  stamp="$(date +%Y%m%d-%H%M%S)-$$"
  package="$EXPORTS_DIR/caritas-backup-$stamp"
  partial="$package.partial"
  mkdir -m 700 "$partial"
  backup_cleanup() {
    local result=$? item
    trap - EXIT
    for item in ${paused[@]+"${paused[@]}"}; do
      if ! podman start "$item" >/dev/null; then
        log "Could not restart $item after backup. Run ./run.sh start."
        result=1
      fi
    done
    if [ "$success" -ne 1 ]; then
      rm -rf "$partial"
      log "Backup failed; no complete backup was published."
    fi
    exit "$result"
  }
  trap backup_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  mkdir "$partial/backup" "$partial/scripts" "$partial/superset" "$partial/data" "$partial/exports"
  capture_backup_settings "$partial/backup/.container-env"
  write_settings "$partial/.caritas-settings.env"
  cp "$PROJECT_DIR/run.sh" "$PROJECT_DIR/Containerfile.ingest" "$PROJECT_DIR/Containerfile.superset" "$partial/"
  cp "$PROJECT_DIR/scripts/"*.py "$partial/scripts/"
  cp "$SUPERSET_CONFIG_DIR/"*.py "$partial/superset/"
  for relative in README.md docs; do
    if [ -e "$PROJECT_DIR/$relative" ]; then
      cp -R "$PROJECT_DIR/$relative" "$partial/"
    fi
  done
  for relative in "${PUBLIC_DEMO_FILES[@]}"; do
    if [ -f "$PROJECT_DIR/$relative" ]; then
      mkdir -p "$partial/$(dirname "$relative")"
      cp "$PROJECT_DIR/$relative" "$partial/$relative"
    fi
  done
  printf 'caritas-portable-backup-v1\n' > "$partial/backup/format"
  podman info --format '{{.Host.Arch}}' > "$partial/backup/architecture"

  # Stop writers while copying SQLite metadata and taking the PostgreSQL snapshot.
  for container in "$IMPORT_UI_CONTAINER" "$SUPERSET_CONTAINER"; do
    if container_running "$container"; then
      paused+=("$container")
      podman stop "$container" >/dev/null
    fi
  done
  log "Saving PostgreSQL data and Superset metadata."
  podman exec "$POSTGRES_CONTAINER" pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -Fc --no-owner --no-acl > "$partial/backup/postgres.dump"
  podman run --rm \
    -v "$SUPERSET_VOLUME:/volume:ro" \
    -v "$partial/backup:/backup" \
    "$POSTGRES_IMAGE" \
    tar -czf /backup/superset-home.tgz -C /volume .
  # Resume the UI before the larger image export.
  for container in ${paused[@]+"${paused[@]}"}; do
    podman start "$container" >/dev/null
  done
  paused=()
  log "Saving container images for offline installation. This may take a few minutes."
  podman save --multi-image-archive --format docker-archive \
    -o "$partial/backup/images.tar" "$POSTGRES_IMAGE" "$SUPERSET_IMAGE" "$INGEST_IMAGE"
  for relative in backup/postgres.dump backup/superset-home.tgz backup/images.tar; do
    [ -s "$partial/$relative" ] || die "Backup file is empty: $relative"
  done
  (
    cd "$partial"
    for relative in run.sh Containerfile.ingest Containerfile.superset \
      .caritas-settings.env scripts/*.py superset/*.py backup/format \
      backup/architecture backup/postgres.dump backup/superset-home.tgz backup/images.tar; do
      digest="$(checksum_file "$relative")"
      printf '%s  %s\n' "$digest" "$relative"
    done > backup/SHA256SUMS
    for relative in "${PUBLIC_DEMO_FILES[@]}"; do
      if [ -f "$relative" ]; then
        digest="$(checksum_file "$relative")"
        printf '%s  %s\n' "$digest" "$relative" >> backup/SHA256SUMS
      fi
    done
  )
  mv "$partial" "$package"
  success=1
  log "Backup complete: $package"
  log "To install on another computer, copy this entire folder, open it, and run ./run.sh restore"
  log "This folder includes your data, login information, and encryption key; keep it private."
)

cmd_restore() (
  local payload="$PROJECT_DIR/backup" relative expected actual architecture
  local restore_started=0 restore_complete=0 verified="|"
  require_podman
  [ "$#" -eq 0 ] || die "Open the portable backup folder and run ./run.sh restore without arguments."
  [ -f "$payload/format" ] || die "No portable backup found here. Open a caritas-backup-* folder and run ./run.sh restore."
  [ "$(cat "$payload/format")" = "caritas-portable-backup-v1" ] || die "Unsupported backup format."
  [ -s "$payload/SHA256SUMS" ] || die "Backup checksum list is missing."
  log "Checking backup files."
  while IFS=' ' read -r expected relative; do
    case "$relative" in
      run.sh|Containerfile.ingest|Containerfile.superset|.caritas-settings.env|scripts/*.py|superset/*.py|backup/*) ;;
      data/README.md|data/codebook.csv|data/en/counselling_events.csv|data/de/beratungsdaten_synthesized.csv|sql/schema_en.sql|sql/schema_de.sql) ;;
      *) die "Unexpected file in backup checksum list: $relative" ;;
    esac
    case "$relative" in *..*|/*) die "Invalid backup path: $relative" ;; esac
    [ -f "$PROJECT_DIR/$relative" ] && [ ! -L "$PROJECT_DIR/$relative" ] || die "Backup file is missing: $relative"
    actual="$(checksum_file "$PROJECT_DIR/$relative")"
    [ "$expected" = "$actual" ] || die "Backup file is damaged: $relative"
    verified="$verified$relative|"
  done < "$payload/SHA256SUMS"
  for relative in run.sh Containerfile.ingest Containerfile.superset \
    .caritas-settings.env scripts/import_staging.py scripts/import_ui.py \
    superset/superset_config.py superset/enable_file_upload.py \
    backup/format backup/architecture backup/postgres.dump \
    backup/superset-home.tgz backup/images.tar; do
    case "$verified" in
      *"|$relative|"*) ;;
      *) die "Backup checksum is missing for $relative" ;;
    esac
  done
  for relative in postgres.dump superset-home.tgz images.tar architecture; do
    [ -s "$payload/$relative" ] || die "Backup file is missing or empty: $relative"
  done
  architecture="$(podman info --format '{{.Host.Arch}}')"
  [ "$(cat "$payload/architecture")" = "$architecture" ] || die "This backup was made for a different CPU architecture. Restore it on the same architecture."
  for relative in "$POSTGRES_CONTAINER" "$SUPERSET_CONTAINER" "$IMPORT_UI_CONTAINER"; do
    ! container_exists "$relative" || die "Restore refused: container $relative already exists. Use a fresh installation; existing data has not been changed."
  done
  for relative in "$POSTGRES_VOLUME" "$SUPERSET_VOLUME"; do
    ! podman volume exists "$relative" >/dev/null 2>&1 || die "Restore refused: volume $relative already exists. Use a fresh installation; existing data has not been changed."
  done
  restore_cleanup() {
    local result=$? item
    trap - EXIT
    if [ "$restore_started" -eq 1 ] && [ "$restore_complete" -ne 1 ]; then
      log "Restore failed. Removing only the new containers and volumes created by this restore."
      for item in "$IMPORT_UI_CONTAINER" "$SUPERSET_CONTAINER" "$POSTGRES_CONTAINER"; do
        if container_exists "$item"; then podman rm -f "$item" >/dev/null || true; fi
      done
      for item in "$SUPERSET_VOLUME" "$POSTGRES_VOLUME"; do
        if podman volume exists "$item" >/dev/null 2>&1; then podman volume rm "$item" >/dev/null || true; fi
      done
      rm -f "$PROJECT_DIR/.caritas-restored"
    fi
    exit "$result"
  }
  trap restore_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  log "Loading bundled container images."
  podman load -i "$payload/images.tar"
  for relative in "$POSTGRES_IMAGE" "$SUPERSET_IMAGE" "$INGEST_IMAGE"; do
    podman image exists "$relative" >/dev/null 2>&1 || die "Required image is missing from backup: $relative"
  done
  ensure_dirs
  configure_host_ports
  ensure_network
  restore_started=1
  ensure_volumes
  log "Restoring Superset metadata."
  podman run --rm \
    -v "$SUPERSET_VOLUME:/volume" \
    -v "$payload:/backup:ro" \
    "$POSTGRES_IMAGE" \
    tar -xzf /backup/superset-home.tgz -C /volume
  start_postgres
  log "Restoring PostgreSQL data."
  podman exec -i "$POSTGRES_CONTAINER" pg_restore \
    --exit-on-error --clean --if-exists --no-owner --no-acl \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$payload/postgres.dump"
  RESTORING_BACKUP=1
  start_superset
  start_import_ui
  touch "$PROJECT_DIR/.caritas-restored"
  restore_complete=1
  log "Restore complete. Your Superset users, charts, and dashboards have been restored."
  log "Superset:  http://127.0.0.1:${SUPERSET_PORT}"
  log "Import UI: http://127.0.0.1:${IMPORT_UI_PORT}"
)

cmd_reset() {
  require_podman
  printf 'This deletes all local Caritas containers and persistent volumes.\n'
  printf 'Type "delete local caritas data" to continue: '
  local answer
  read -r answer
  [ "$answer" = "delete local caritas data" ] || die "Reset refused."

  for container in "$IMPORT_UI_CONTAINER" "$SUPERSET_CONTAINER" "$POSTGRES_CONTAINER"; do
    if container_exists "$container"; then
      log "Removing container: $container"
      podman rm -f "$container" >/dev/null
    fi
  done

  for volume in "$SUPERSET_VOLUME" "$POSTGRES_VOLUME"; do
    if podman volume exists "$volume" >/dev/null 2>&1; then
      log "Removing volume: $volume"
      podman volume rm "$volume" >/dev/null
    fi
  done

  if podman network exists "$NETWORK_NAME" >/dev/null 2>&1; then
    log "Removing network: $NETWORK_NAME"
    podman network rm "$NETWORK_NAME" >/dev/null
  fi

  log "Reset complete."
}

main() {
  local command="${1:-help}"
  case "$command" in
    start)
      cmd_start
      ;;
    stop)
      cmd_stop
      ;;
    status)
      cmd_status
      ;;
    import)
      shift
      cmd_import "$@"
      ;;
    backup)
      cmd_backup
      ;;
    restore)
      shift
      cmd_restore "$@"
      ;;
    build)
      build_images
      ;;
    reset)
      cmd_reset
      ;;
    help|--help|-h)
      usage
      ;;
    *)
      usage
      die "Unknown command: $command"
      ;;
  esac
}

main "$@"
