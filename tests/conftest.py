"""Shared pytest fixtures for the KB test suite."""

import os
from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv

# Load .env from vault root (parent of tests/)
_vault_root = Path(__file__).resolve().parent.parent
_env_file = _vault_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


@pytest.fixture(scope="session")
def vault_path() -> Path:
    """Path to the vault under test."""
    return Path(os.getenv("TEST_VAULT_PATH", str(_vault_root)))


@pytest.fixture(scope="session")
def qmd_collection() -> str:
    return os.getenv("TEST_QMD_COLLECTION", "kb")


@pytest.fixture(scope="session")
def use_live_vault() -> bool:
    return os.getenv("TEST_USE_LIVE_VAULT", "false").lower() == "true"


@pytest.fixture(scope="session")
def retrieval_cases() -> list[dict]:
    """Load retrieval test cases from the YAML fixture."""
    fixture = Path(__file__).parent / "fixtures" / "retrieval_cases.yaml"
    with open(fixture) as f:
        data = yaml.safe_load(f)
    return data["cases"]


@pytest.fixture(scope="session")
def judge_fn():
    """Return the configured LLM judge function."""
    from lib.llm_judge import get_judge
    return get_judge()


@pytest.fixture
def sandbox(vault_path):
    """Provide a temporary vault sandbox. Skips if TEST_USE_LIVE_VAULT=true."""
    if os.getenv("TEST_USE_LIVE_VAULT", "false").lower() == "true":
        pytest.skip("Sandbox disabled — running against live vault")
    from lib.vault_sandbox import VaultSandbox
    with VaultSandbox(vault_path) as sb:
        yield sb
