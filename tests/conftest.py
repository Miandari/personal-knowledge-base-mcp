"""Shared pytest fixtures and CLI options for the KB test suite.

Configuration lives in config.py (checked in). Secrets live in .env (gitignored).
Per-run overrides come from pytest CLI flags: --live-vault, --judge-provider, --judge-model.
"""

from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv

from . import config

# Load .env for API keys only (secrets, not config)
_env_file = config.VAULT_PATH / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


# ── pytest CLI options ───────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption(
        "--live-vault",
        action="store_true",
        default=False,
        help="Run tests against the live vault instead of a sandbox copy.",
    )
    parser.addoption(
        "--judge-provider",
        default=config.JUDGE_PROVIDER,
        choices=["anthropic", "openai", "google", "openrouter"],
        help=f"LLM provider for judge tests (default: {config.JUDGE_PROVIDER}).",
    )
    parser.addoption(
        "--judge-model",
        default=config.JUDGE_MODEL,
        help=f"Model for judge tests (default: {config.JUDGE_MODEL}).",
    )


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def vault_path() -> Path:
    """Path to the vault under test (from config.py, not .env)."""
    return config.VAULT_PATH


@pytest.fixture(scope="session")
def qmd_collection() -> str:
    """qmd collection name (from config.py)."""
    return config.QMD_COLLECTION


@pytest.fixture(scope="session")
def use_live_vault(request) -> bool:
    """Whether we're running against the live vault (from --live-vault flag)."""
    return request.config.getoption("--live-vault")


@pytest.fixture(scope="session")
def retrieval_cases() -> list[dict]:
    """Load retrieval test cases from the YAML fixture."""
    fixture = Path(__file__).parent / "fixtures" / "retrieval_cases.yaml"
    with open(fixture) as f:
        data = yaml.safe_load(f)
    return data["cases"]


@pytest.fixture(scope="session")
def judge_fn(request):
    """Return the configured LLM judge function, respecting CLI flags."""
    import os
    provider = request.config.getoption("--judge-provider")
    model = request.config.getoption("--judge-model")

    # Temporarily set env vars so the judge module picks them up
    os.environ["TEST_JUDGE_PROVIDER"] = provider
    os.environ["TEST_JUDGE_MODEL"] = model

    from .lib.llm_judge import get_judge
    return get_judge()


@pytest.fixture
def sandbox(vault_path, use_live_vault):
    """Provide a temporary vault sandbox. Skips if --live-vault is set."""
    if use_live_vault:
        pytest.skip("Sandbox disabled — running against live vault (--live-vault)")
    from .lib.vault_sandbox import VaultSandbox
    with VaultSandbox(vault_path) as sb:
        yield sb
