# Back up your work or move the app

[Back to the introduction](../README.md)

A portable backup contains the app, its container images, the imported database, and Superset's saved work. Copy the whole backup folder to start the app on another computer. You don't need the original project folder or the original Excel files to restore the imported data.

## Make a backup

With the app running, open a terminal in the project folder and run:

```sh
./run.sh backup
```

The runner prints the path to a new folder under `exports/`, for example:

```text
exports/caritas-backup-20261123-153000-12345/
```

Keep the whole folder together. It includes:

- `run.sh`, the importer, Superset configuration, and these guides;
- the supplied public demo CSVs, their description and codebook, and optional SQL schemas;
- a PostgreSQL dump of your imported data;
- Superset metadata, including saved charts, dashboards, datasets, and users;
- the container images needed to run the app offline;
- saved settings, including database credentials and the Superset secret key;
- checksums used to check the backup before restoring it.

The importer and Superset pause briefly while the backup is made, then resume if they were running. Wait for the completion message before copying the folder. The image archive can be large, so allow enough disk space on both computers.

The backup includes credentials and the data itself. Store it somewhere you would trust with the source data. It is not encrypted.

## Start on a new computer

The destination needs Podman and a Bash terminal. Install Podman and initialise its machine before going offline; that setup may need its own downloads. Once Podman is ready, the backup has the app images needed for an offline restore. See [Podman's machine documentation](https://docs.podman.io/en/latest/markdown/podman-machine.1.html) for macOS and Windows setup.

The included images require the same CPU architecture as the source computer: for example, Apple Silicon backups contain ARM images, while many Windows and Linux PCs use x86-64. Moving between those architectures needs a separate image build or a separate backup from the matching architecture.

1. Copy the entire `caritas-backup-...` folder, including hidden files such as `.caritas-settings.env`, to a permanent location on the new computer. This folder becomes the app's working folder.
2. Start Podman. On macOS, run `podman machine init` once if needed, then `podman machine start`.
3. Open a terminal in the copied backup folder and run:

```sh
./run.sh restore
```

Restore checks the backup and the CPU architecture, loads the included images, restores both databases, and starts the app. It does not need an internet download. Use the URLs printed at the end, or run:

```sh
./run.sh status
```

Sign in with the Superset account from the original installation. Restoring preserves existing users and passwords. The default is `admin` / `admin` only if that was still the account you used.

Keep the copied folder in place after restoring: the containers use its importer code and Superset configuration. To stop or restart this installation later, run `./run.sh stop` or `./run.sh start` from that folder.

## If a local installation already exists

Restore refuses to use existing Caritas containers or data volumes. It will not overwrite another installation's work. A stopped installation still has containers and volumes, so stopping it alone does not make the destination empty.

Use a clean destination for a move. If you intentionally want to replace an installation, back it up first. Then run `./run.sh reset` from that installation and type its confirmation phrase. This deletes its stored data and Superset work. After that, restore from the backup folder you intend to keep.

## What is outside the backup

The package contains data already imported into PostgreSQL, plus the supplied public demo files and their optional SQL schemas. Other source files in `data/` and temporary files uploaded to the importer are not included. Copy those separately if you want to keep your original workbooks.

Local Power BI `.pbix` files, other external reports, and manually managed PostgreSQL login roles and access grants are separate. Keep report files separately and recreate optional reader accounts and their grants after restore. See [the Power BI guide](power-bi.md).

Older backups consisting only of a `caritas-postgres-....dump` file and a `caritas-superset-home-....tgz` file are not portable app packages. They need a matching project setup, container images, and the original Superset secret key for a manual restore. Make a new portable backup from a working installation before moving it.
