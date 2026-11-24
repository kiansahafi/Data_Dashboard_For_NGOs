"""Exercise the actual runner against a stateful, isolated Podman substitute.

Run with: python3 -m unittest discover -s tests -p 'test_backup_restore.py'
No real containers or user data are accessed.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DEMO_FILES = (
    "data/README.md",
    "data/codebook.csv",
    "data/en/counselling_events.csv",
    "data/de/beratungsdaten_synthesized.csv",
    "sql/schema_en.sql",
    "sql/schema_de.sql",
)

FAKE_PODMAN = r'''
import io, json, os, pathlib, shutil, sys, tarfile

args = sys.argv[1:]
root = pathlib.Path(os.environ["TEST_PODMAN_ROOT"])
state_file = root / "state.json"
state = json.loads(state_file.read_text())
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(args) + "\n")

def save():
    state_file.write_text(json.dumps(state))

def fail(message="injected failure"):
    print(message, file=sys.stderr)
    sys.exit(1)

def option(flag):
    return args[args.index(flag) + 1]

if args[0] == "info":
    if "--format" in args:
        print(os.environ.get("TEST_ARCH", "arm64"))
elif args[:2] == ["container", "exists"]:
    sys.exit(0 if args[2] in state["containers"] else 1)
elif args[0] == "inspect":
    container = state["containers"].get(args[-1])
    if container is None:
        fail("no such container")
    template = option("--format") if "--format" in args else option("-f")
    if "State.Running" in template:
        print("true" if container["running"] else "false")
    elif "Config.Env" in template:
        assert r'printf "%s\x00"' in template, template
        sys.stdout.buffer.write(b"\0".join(v.encode() for v in container["env"]) + b"\0")
    elif "ImageName" in template:
        print(container["image"])
    else:
        fail("unsupported inspect")
elif args[0] in ("stop", "start"):
    state["containers"][args[1]]["running"] = args[0] == "start"
    save()
elif args[:2] == ["image", "exists"]:
    sys.exit(0 if args[2] in state["images"] else 1)
elif args[:2] == ["network", "exists"]:
    sys.exit(0 if args[2] in state["networks"] else 1)
elif args[:2] == ["network", "create"]:
    state["networks"].append(args[2])
    save()
elif args[:2] == ["volume", "exists"]:
    sys.exit(0 if args[2] in state["volumes"] else 1)
elif args[:2] == ["volume", "create"]:
    volume = root / args[2]
    volume.mkdir()
    state["volumes"][args[2]] = str(volume)
    save()
elif args[:2] == ["volume", "rm"]:
    shutil.rmtree(state["volumes"].pop(args[2]))
    save()
elif args[0] == "save":
    if os.environ.get("TEST_FAIL") == "save":
        fail()
    pathlib.Path(option("-o")).write_text(json.dumps(state["images"]))
elif args[0] == "load":
    state["images"] = json.loads(pathlib.Path(option("-i")).read_text())
    save()
elif args[0] == "exec":
    if "pg_dump" in args:
        if os.environ.get("TEST_FAIL") == "pg_dump":
            fail()
        sys.stdout.buffer.write(b"postgres-data-snapshot")
    elif "pg_restore" in args:
        if os.environ.get("TEST_FAIL") == "pg_restore":
            fail()
        state["restored_dump"] = sys.stdin.buffer.read().decode()
        save()
    elif "psql" in args:
        sys.stdin.read()
    elif "pg_isready" not in args:
        fail("unsupported exec")
elif args[0] == "rm":
    state["containers"].pop(args[-1])
    save()
elif args[0] == "run":
    if "--name" in args:
        name = option("--name")
        env = [args[i+1] for i, a in enumerate(args) if a == "-e"]
        image = next(v for v in args if v in state["images"])
        state["containers"][name] = {"running": True, "env": env, "image": image}
        save()
    elif "tar" in args:
        mounts = [args[i+1] for i, a in enumerate(args) if a == "-v"]
        volume = next(v.split(":")[0] for v in mounts if ":/volume" in v)
        backup = pathlib.Path(next(v.split(":")[0] for v in mounts if ":/backup" in v))
        volume_path = pathlib.Path(state["volumes"][volume])
        if "-czf" in args:
            with tarfile.open(backup / "superset-home.tgz", "w:gz") as archive:
                archive.add(volume_path / "superset.db", arcname="superset.db")
        else:
            with tarfile.open(backup / "superset-home.tgz") as archive:
                archive.extractall(volume_path)
    # Other one-off Superset setup commands succeed without changing users.
else:
    fail("unsupported command: " + repr(args))
'''


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="caritas-backup-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        for name in ("run.sh", "Containerfile.ingest", "Containerfile.superset"):
            shutil.copy2(ROOT / name, self.project / name)
        for name in ("scripts", "superset"):
            shutil.copytree(ROOT / name, self.project / name)
        self.runtime = self.base / "runtime"
        self.runtime.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        executable = self.bin / "podman"
        executable.write_text(f"#!{sys.executable}\n" + FAKE_PODMAN)
        executable.chmod(0o700)
        # Host-port probing is outside this test's scope and some sandboxes
        # prohibit binding even unused localhost sockets.
        probe = self.bin / "python3"
        probe.write_text("#!/bin/sh\nexit 0\n")
        probe.chmod(0o700)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", TEST_PODMAN_ROOT=str(self.runtime))
        for key in ("POSTGRES_PORT", "SUPERSET_PORT", "IMPORT_UI_PORT", "POSTGRES_PASSWORD", "SUPERSET_SECRET_KEY"):
            self.env.pop(key, None)
        self.password = "test db 'password' $dollar `literal`\nsecond line"
        self.secret = "test superset 'key' $dollar `literal`\nsecond line"
        self.images = ["docker.io/library/postgres:16.4-alpine", "localhost/caritas-superset:4.1.1-local", "localhost/caritas-ingest:py3.12-ui-local"]
        metadata = self.runtime / "caritas_superset_home"
        metadata.mkdir()
        (metadata / "superset.db").write_text("saved-users-charts-and-dashboards")
        pg_volume = self.runtime / "caritas_postgres_data"
        pg_volume.mkdir()
        self.write_state({
            "containers": {
                "caritas_postgres": {"running": True, "env": ["POSTGRES_DB=caritas", "POSTGRES_USER=caritas", f"POSTGRES_PASSWORD={self.password}"], "image": self.images[0]},
                "caritas_superset": {"running": True, "env": [f"SUPERSET_SECRET_KEY={self.secret}", "SUPERSET_DATABASE_LABEL=Caritas Local PostgreSQL"], "image": self.images[1]},
                "caritas_import_ui": {"running": True, "env": [], "image": self.images[2]},
            },
            "volumes": {"caritas_superset_home": str(metadata), "caritas_postgres_data": str(pg_volume)},
            "networks": ["caritas_local"], "images": self.images,
        })

    def write_state(self, state):
        (self.runtime / "state.json").write_text(json.dumps(state))

    def state(self):
        return json.loads((self.runtime / "state.json").read_text())

    def run_runner(self, command, project=None, **changes):
        return subprocess.run(["bash", str((project or self.project) / "run.sh"), command], env=dict(self.env, **changes), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def backup(self):
        result = self.run_runner("backup")
        self.assertEqual(result.returncode, 0, result.stdout)
        return next((self.project / "exports").glob("caritas-backup-*"))

    def fresh_runtime(self):
        state = self.state()
        for volume in state["volumes"].values():
            shutil.rmtree(volume)
        self.write_state({"containers": {}, "volumes": {}, "networks": [], "images": []})
        (self.runtime / "calls.jsonl").write_text("")

    def calls(self):
        return [json.loads(line) for line in (self.runtime / "calls.jsonl").read_text().splitlines()]

    def test_backup_alone_restores_data_metadata_credentials_and_images(self):
        for relative in PUBLIC_DEMO_FILES:
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"public example: {relative}\n")
        private_files = ("data/private-source.csv", "data/en/private-notes.csv", "sql/private-analysis.sql")
        for relative in private_files:
            (self.project / relative).write_text("private source: leave out of the app package\n")
        package = self.backup()
        checksums = (package / "backup/SHA256SUMS").read_text().splitlines()
        for relative in PUBLIC_DEMO_FILES:
            self.assertEqual((package / relative).read_bytes(), (self.project / relative).read_bytes())
            self.assertTrue(any(line.endswith(f"  {relative}") for line in checksums))
        for relative in private_files:
            self.assertFalse((package / relative).exists())
        self.assertEqual(package.stat().st_mode & 0o777, 0o700)
        self.assertEqual((package / ".caritas-settings.env").stat().st_mode & 0o777, 0o600)
        self.assertTrue(all(c["running"] for c in self.state()["containers"].values()))
        shutil.rmtree(self.project / "scripts")  # The source checkout is no longer needed.
        self.fresh_runtime()
        result = self.run_runner("restore", package)
        self.assertEqual(result.returncode, 0, result.stdout)
        state = self.state()
        self.assertEqual(state["restored_dump"], "postgres-data-snapshot")
        self.assertIn(f"POSTGRES_PASSWORD={self.password}", state["containers"]["caritas_postgres"]["env"])
        self.assertIn(f"SUPERSET_SECRET_KEY={self.secret}", state["containers"]["caritas_superset"]["env"])
        self.assertEqual((Path(state["volumes"]["caritas_superset_home"]) / "superset.db").read_text(), "saved-users-charts-and-dashboards")
        self.assertTrue((package / ".caritas-restored").exists())
        self.assertFalse(any(call[0] in ("pull", "build") for call in self.calls()))
        uri_call = next(call for call in self.calls() if "set-database-uri" in call)
        self.assertEqual(uri_call[uri_call.index("-u") + 1], f"postgresql+psycopg2://caritas:{quote(self.password, safe='')}@caritas_postgres:5432/caritas")
        self.assertFalse(any("create-admin" in call for call in self.calls()))
        stopped = self.run_runner("stop", package)
        self.assertEqual(stopped.returncode, 0, stopped.stdout)
        restarted = self.run_runner("start", package)
        self.assertEqual(restarted.returncode, 0, restarted.stdout)
        self.assertFalse(any("create-admin" in call for call in self.calls()))

    def test_failed_snapshot_resumes_both_interfaces_and_removes_partial_backup(self):
        result = self.run_runner("backup", TEST_FAIL="pg_dump")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(c["running"] for c in self.state()["containers"].values()))
        self.assertEqual(list((self.project / "exports").glob("caritas-backup-*")), [])

    def test_failed_image_export_does_not_publish_a_backup(self):
        result = self.run_runner("backup", TEST_FAIL="save")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list((self.project / "exports").glob("caritas-backup-*")), [])
        self.assertTrue(all(c["running"] for c in self.state()["containers"].values()))

    def test_restore_refuses_existing_installation_without_mutating_it(self):
        package = self.backup()
        before = self.state()
        (self.runtime / "calls.jsonl").write_text("")
        result = self.run_runner("restore", package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Restore refused", result.stdout)
        self.assertEqual(self.state(), before)
        self.assertFalse(any(c[0] in ("load", "rm", "run", "stop") for c in self.calls()))

    def test_restore_rejects_corrupt_dump_before_loading_images(self):
        package = self.backup()
        self.fresh_runtime()
        (package / "backup/postgres.dump").write_bytes(b"truncated")
        result = self.run_runner("restore", package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("damaged", result.stdout)
        self.assertFalse(any(c[0] == "load" for c in self.calls()))

    def test_restore_rejects_corrupt_optional_demo_schema_before_loading_images(self):
        schema = self.project / "sql/schema_en.sql"
        schema.parent.mkdir()
        schema.write_text("CREATE SCHEMA demo;\n")
        package = self.backup()
        self.fresh_runtime()
        (package / "sql/schema_en.sql").write_text("changed after backup\n")
        result = self.run_runner("restore", package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Backup file is damaged: sql/schema_en.sql", result.stdout)
        self.assertFalse(any(c[0] == "load" for c in self.calls()))

    def test_restore_refuses_detached_existing_volumes(self):
        package = self.backup()
        state = self.state()
        state["containers"] = {}
        self.write_state(state)
        (self.runtime / "calls.jsonl").write_text("")
        result = self.run_runner("restore", package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("volume caritas_postgres_data already exists", result.stdout)
        self.assertEqual(self.state(), state)
        self.assertFalse(any(c[0] == "load" for c in self.calls()))

    def test_restore_rejects_missing_checksum_and_wrong_architecture(self):
        package = self.backup()
        self.fresh_runtime()
        result = self.run_runner("restore", package, TEST_ARCH="amd64")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different CPU architecture", result.stdout)
        checksums = package / "backup/SHA256SUMS"
        checksums.write_text("\n".join(line for line in checksums.read_text().splitlines() if not line.endswith("backup/postgres.dump")) + "\n")
        result = self.run_runner("restore", package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum is missing", result.stdout)

    def test_failed_restore_removes_only_new_resources_and_can_be_retried(self):
        package = self.backup()
        self.fresh_runtime()
        result = self.run_runner("restore", package, TEST_FAIL="pg_restore")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state()["containers"], {})
        self.assertEqual(self.state()["volumes"], {})
        self.assertFalse((package / ".caritas-restored").exists())
        result = self.run_runner("restore", package)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_start_of_unrestored_backup_explains_restore_command(self):
        package = self.backup()
        result = self.run_runner("start", package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Restore it first with ./run.sh restore", result.stdout)


if __name__ == "__main__":
    unittest.main()
