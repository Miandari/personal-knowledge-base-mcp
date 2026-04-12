"""Test suite configuration -- checked into git.

Project-level defaults for the KB test suite. These are NOT secrets.
Override per-run via pytest CLI flags (see conftest.py pytest_addoption).

Secrets (API keys) live in .env at vault root and are gitignored.
"""

from pathlib import Path

# -- Vault ------------------------------------------------------------
# Derived from the repo layout: tests/ is one level below the vault root.
VAULT_PATH = Path(__file__).resolve().parent.parent

# -- LLM judge --------------------------------------------------------
# Which provider to use for LLM-as-judge grading.
# Options: "anthropic", "openai", "google", "openrouter"
JUDGE_PROVIDER = "anthropic"

# Which model to use. Provider-specific defaults:
#   anthropic  -> claude-sonnet-4-20250514
#   openai     -> gpt-4.1
#   google     -> gemini-2.5-pro
#   openrouter -> anthropic/claude-sonnet-4
JUDGE_MODEL = "claude-sonnet-4-20250514"
