from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflow_text() -> str:
    return _read(WORKFLOW)


def _workflow() -> dict:
    return yaml.safe_load(_workflow_text())


def _sh_parse_error(path: Path) -> str | None:
    sh = shutil.which("sh")
    if sh is None:
        return None
    completed = subprocess.run(
        [sh, "-n", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return None if completed.returncode == 0 else completed.stderr.strip()


def test_scripts_exist() -> None:
    assert (SCRIPTS / "backup.sh").is_file()
    assert (SCRIPTS / "restore.sh").is_file()
    assert (SCRIPTS / "backup.ps1").is_file()


def test_backup_script_contract() -> None:
    text = _read(SCRIPTS / "backup.sh")
    assert text.startswith(("#!/usr/bin/env sh", "#!/bin/sh"))
    assert re.search(r"^set -eu$", text, re.MULTILINE)
    assert "${DATABASE_URL" in text
    assert "pg_dump" in text
    assert "--format=custom" in text
    assert "--no-owner" in text
    assert "--no-privileges" in text
    assert "${BACKUP_DIR:-./backups}" in text
    assert "violencia-$(date -u +%Y%m%dT%H%M%SZ).dump" in text
    assert ".sha256" in text
    assert re.search(r"sha256sum|shasum -a 256", text)
    assert "backup written: ${dump_path}" in text
    assert re.search(r'if \[ -z "\$\{DATABASE_URL:-\}" \]', text)
    assert re.search(r"exit 1", text)


def test_restore_script_contract() -> None:
    text = _read(SCRIPTS / "restore.sh")
    assert text.startswith(("#!/usr/bin/env sh", "#!/bin/sh"))
    assert re.search(r"^set -eu$", text, re.MULTILINE)
    assert "${DATABASE_URL" in text
    assert "pg_restore" in text
    assert "--clean" in text
    assert "--if-exists" in text
    assert "--no-owner" in text
    assert "ALLOW_PROD_RESTORE" in text
    assert "*test*" in text
    assert "*restore*" in text
    assert re.search(r"refusing to restore", text, re.IGNORECASE)
    assert re.search(r"restore complete", text, re.IGNORECASE)


def test_backup_powershell_contract() -> None:
    text = _read(SCRIPTS / "backup.ps1")
    assert "DATABASE_URL" in text
    assert "pg_dump" in text
    assert "--format=custom" in text
    assert "--no-owner" in text
    assert "--no-privileges" in text
    assert "Get-FileHash" in text
    assert "SHA256" in text
    assert "violencia-" in text


def test_shell_scripts_are_parseable() -> None:
    if shutil.which("sh") is None:
        return
    for name in ("backup.sh", "restore.sh"):
        error = _sh_parse_error(SCRIPTS / name)
        assert error is None, f"{name}: {error}"


def test_ci_keeps_existing_jobs() -> None:
    jobs = _workflow()["jobs"]
    assert {"lint", "typecheck", "test", "integration"} <= set(jobs)


def test_ci_has_backup_restore_job() -> None:
    workflow = _workflow()
    assert "backup-restore" in workflow["jobs"]

    text = _workflow_text()
    assert "scripts/backup.sh" in text
    assert "scripts/restore.sh" in text
    assert "violencia_restore" in text
    assert "apply_migrations.py" in text
    assert "pg_dump" in text or "postgresql-client" in text

    job = workflow["jobs"]["backup-restore"]
    assert "services" in job
    assert "db" in job["services"]
    assert job["services"]["db"]["image"].startswith("pgvector/pgvector:pg17")
    job_text = yaml.safe_dump(job)
    assert "INSERT INTO norms" in job_text
    assert "SELECT" in job_text
    assert "ALLOW_PROD_RESTORE" not in job_text
