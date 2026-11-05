import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PACKAGE_DIRS = [
    "src/obs",
    "src/ingest",
    "src/index",
    "src/retrieve",
    "src/generate",
    "src/safety",
    "src/api",
    "src/eval",
]

ENV_KEYS = {
    "RETRIEVAL_PATH",
    "EMBEDDING_PROVIDER",
    "LLM_PROVIDER",
    "MAX_DEVICES",
    "MAX_CONTEXT_TOKENS",
    "MAX_SUBQUESTIONS",
    "MAX_AGENT_LOOPS",
    "DATABASE_URL",
    "QDRANT_URL",
    "PPX_9B_MODEL_PATH",
    "PPX_06B_MODEL_PATH",
    "HARRIER_MODEL_PATH",
    "LLM_MODEL",
    "LOG_LEVEL",
}


def test_package_tree_exists() -> None:
    for rel in PACKAGE_DIRS:
        assert (ROOT / rel / "__init__.py").is_file(), f"missing package {rel}"


def test_data_directories_exist() -> None:
    dirs = (
        "data/raw",
        "data/processed",
        "data/eval",
        "tests/unit",
        "tests/integration",
        "tests/fixtures",
    )
    for rel in dirs:
        assert (ROOT / rel).is_dir(), f"missing directory {rel}"


def test_pyproject_metadata() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "res-ia-legal-rag"
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.12"

    deps = " ".join(project["dependencies"]).lower()
    for expected in (
        "pydantic",
        "pydantic-settings",
        "pyyaml",
        "httpx",
        "fastapi",
        "uvicorn",
        "streamlit",
        "psycopg",
        "pgvector",
        "qdrant-client",
    ):
        assert expected in deps, f"missing dependency {expected}"

    optional = project["optional-dependencies"]

    def names(items: list[str]) -> set[str]:
        return {re.split(r"[\[<>=!~; ]", item.lower())[0] for item in items}

    assert {"pytest", "pytest-asyncio", "ruff", "mypy", "types-pyyaml"} <= names(optional["dev"])
    assert {"sentence-transformers", "transformers", "torch"} <= names(optional["ml"])

    tool = data["tool"]
    assert tool["ruff"]["line-length"] == 100
    assert tool["ruff"]["target-version"] == "py312"
    assert tool["mypy"]["python_version"] == "3.12"
    assert tool["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_env_example_has_all_keys() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    keys = {
        line.split("=", 1)[0].strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    }
    assert ENV_KEYS <= keys
