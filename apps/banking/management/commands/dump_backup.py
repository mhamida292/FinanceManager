"""Dump the Postgres database to /backups/finance-YYYY-MM-DD-HHMM.sql.gz.

Intended to be invoked nightly by the host crontab:
    0 2 * * * cd /opt/finance && docker compose exec -T web python manage.py dump_backup

Retention: deletes backup files in /backups/ older than RETENTION_DAYS.
"""
import gzip
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

BACKUP_DIR = Path("/backups")
RETENTION_DAYS = 30


class Command(BaseCommand):
    help = "Dump Postgres to a gzipped SQL file in /backups/, then prune old ones."

    def handle(self, *args, **options):
        if not BACKUP_DIR.is_dir():
            self.stderr.write(self.style.ERROR(f"{BACKUP_DIR} does not exist — check the compose bind-mount."))
            return

        db = settings.DATABASES["default"]
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        target = BACKUP_DIR / f"finance-{timestamp}.sql.gz"

        env = {
            **os.environ,
            "PGPASSWORD": db["PASSWORD"],
        }
        cmd = [
            "pg_dump",
            "--host", db["HOST"],
            "--port", str(db["PORT"] or 5432),
            "--username", db["USER"],
            "--dbname", db["NAME"],
            "--format", "plain",
            "--no-owner",
            "--no-privileges",
        ]
        self.stdout.write(f"[backup] dumping to {target} ...")
        try:
            with gzip.open(target, "wb") as gz:
                proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                gz.write(proc.stdout)
        except subprocess.CalledProcessError as exc:
            target.unlink(missing_ok=True)
            self.stderr.write(self.style.ERROR(f"pg_dump failed: {exc.stderr.decode()[:500]}"))
            return

        size_mb = target.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(f"[backup] wrote {target.name} ({size_mb:.2f} MB)"))

        cutoff = time.time() - RETENTION_DAYS * 86400
        pruned = 0
        for f in BACKUP_DIR.glob("finance-*.sql.gz"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                pruned += 1
        if pruned:
            self.stdout.write(f"[backup] pruned {pruned} backup(s) older than {RETENTION_DAYS} days")
