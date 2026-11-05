from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"
DOCS06 = ROOT / "docs" / "06-geracao-citacoes-e-seguranca.md"
DOCS10 = ROOT / "docs" / "10-plano-implementacao.md"

REQUIRED_COMMANDS = (
    "uv sync --extra dev",
    "docker compose up -d db",
    "docker compose --profile target up -d",
    "uv run python scripts/apply_migrations.py",
    "uv run python -m src.ingest.run --priority P0",
    "uv run python -m src.index.run --path fallback",
    "uv run uvicorn src.api.main:app --no-access-log",
    "uv run streamlit run web/app.py",
    'uv run pytest -m "not integration"',
    "uv run pytest -m integration",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run mypy src",
)

FORBIDDEN_CLAIMS = (
    "revisão jurídica concluída",
    "revisão jurídica realizada",
    "parecer jurídico emitido",
    "G4 atingido",
    "G6 atingido",
    "métricas produzidas",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_var_names() -> list[str]:
    names: list[str] = []
    for line in _read(ENV_EXAMPLE).splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match:
            names.append(match.group(1))
    return names


def test_readme_exists_and_is_in_portuguese() -> None:
    assert README.is_file()
    text = _read(README)
    for phrase in ("orientação informativa", "não substitui", "violência doméstica"):
        assert phrase in text


def test_readme_contains_every_required_command() -> None:
    text = _read(README)
    for command in REQUIRED_COMMANDS:
        assert command in text, f"missing command: {command}"


def test_readme_contains_legal_notice_and_emergency_numbers() -> None:
    text = _read(README)
    normalized = " ".join(text.replace(">", " ").split())
    assert "não substitui atendimento jurídico individual" in normalized
    assert "190" in text
    assert "180" in text
    assert "Jusbrasil" in text


def test_readme_documents_every_env_var() -> None:
    text = _read(README)
    for name in _env_var_names():
        assert name in text, f"environment variable missing from README: {name}"


def test_readme_documents_architecture_and_data_flow() -> None:
    text = _read(README)
    for needle in ("Postgres", "pgvector", "Qdrant", "RETRIEVAL_PATH=target", "fonte da verdade"):
        assert needle in text, f"missing architecture detail: {needle}"


def test_readme_documents_model_format_reality() -> None:
    text = _read(README)
    for needle in ("GGUF", "safetensors", "ModelFormatError", "llama.cpp", "fallback"):
        assert needle in text, f"missing model-format detail: {needle}"


def test_readme_documents_evaluation_status_as_pending() -> None:
    text = _read(README)
    assert "PENDENTE" in text
    assert "150" in text
    assert "G4" in text
    assert "G6" in text
    assert "Nenhuma métrica foi produzida" in text


def test_readme_documents_lgpd_and_retention() -> None:
    text = _read(README)
    for needle in ("LOG_QUESTION_TEXT=false", "LOG_RETENTION_DAYS", "retenção zero", "PII"):
        assert needle in text, f"missing LGPD detail: {needle}"


def test_readme_documents_backup_and_restore_commands() -> None:
    text = _read(README)
    for needle in (
        "scripts/backup.sh",
        "scripts/restore.sh",
        "scripts/backup.ps1",
        "ALLOW_PROD_RESTORE",
        "pg_dump",
        "pg_restore",
    ):
        assert needle in text, f"missing backup/restore detail: {needle}"


def test_readme_and_docs10_do_not_claim_human_review_or_live_metrics() -> None:
    for path in (README, DOCS10):
        text = _read(path).lower()
        for claim in FORBIDDEN_CLAIMS:
            assert claim.lower() not in text, f"{path.name} makes a false claim: {claim}"


def test_readme_relative_links_exist() -> None:
    text = _read(README)
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    for link in links:
        if link.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = link.split("#", 1)[0].split("?", 1)[0]
        if not target:
            continue
        assert (ROOT / target).exists(), f"broken relative link in README: {link}"


def test_docs10_keeps_eva04_g4_and_g6_unchecked() -> None:
    text = _read(DOCS10)
    for item in ("EVA-04", "G4", "G6"):
        assert re.search(rf"^- \[ \] {re.escape(item)}\b", text, re.MULTILINE), item
        assert not re.search(rf"^- \[x\] {re.escape(item)}\b", text, re.MULTILINE | re.I)


def test_docs10_status_mentions_real_environment_limits() -> None:
    text = _read(DOCS10)
    for needle in ("Docker", "Postgres", "Qdrant", "GGUF", "safetensors", "PENDENTE"):
        assert needle in text, f"missing status detail in docs/10: {needle}"
    assert "não foram atingidos" in text


def test_docs06_appends_truthful_implementation_status() -> None:
    text = _read(DOCS06)
    assert "Status de implementação" in text
    assert "Implementado e testado" in text
    assert "Revisão jurídica humana: PENDENTE" in text
    assert "Métricas: PENDENTES" in text
    assert "LOG_QUESTION_TEXT=false" in text
