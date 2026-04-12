"""Ingestion correctness tests.

Tests that already-ingested content (from the Phase 3 run) has correct
wiki page structure, frontmatter, and cross-references. Also tests
sandbox-mode ingestion for new sources.
"""

import re
from pathlib import Path

import pytest
import yaml


def _extract_frontmatter(path: Path) -> dict | None:
    text = path.read_text()
    if not text.startswith("---"):
        return None
    end = text.index("---", 3)
    return yaml.safe_load(text[3:end].strip())


class TestRawDumps:
    """Validate .raw/notion/ dumps from the Phase 3 ingest."""

    EXPECTED_DATES = ["2026-03-27", "2026-03-28", "2026-04-10", "2026-04-11"]

    def test_raw_files_exist(self, vault_path):
        missing = []
        for date in self.EXPECTED_DATES:
            path = vault_path / ".raw" / "notion" / f"{date}.md"
            if not path.exists():
                missing.append(str(path))
        assert not missing, f"Missing raw dumps: {missing}"

    def test_raw_frontmatter(self, vault_path):
        failures = []
        for date in self.EXPECTED_DATES:
            path = vault_path / ".raw" / "notion" / f"{date}.md"
            if not path.exists():
                continue
            fm = _extract_frontmatter(path)
            if fm is None:
                failures.append(f"{date}: no frontmatter")
                continue
            for field in ("source_type", "briefing_date", "ingested_via"):
                if field not in fm:
                    failures.append(f"{date}: missing '{field}'")
            if fm.get("ingested_via") != "notion_briefing":
                failures.append(f"{date}: ingested_via='{fm.get('ingested_via')}' should be 'notion_briefing'")
        assert not failures, "\n".join(failures)


class TestCompiledPages:
    """Validate wiki pages produced by the ingestion."""

    def test_concept_pages_exist(self, vault_path):
        expected = [
            "concepts/ai-coding-agents.md",
            "concepts/llm-wiki-pattern.md",
            "concepts/agent-memory.md",
            "concepts/llm-context-scaling.md",
            "concepts/mcp-ecosystem.md",
        ]
        missing = [p for p in expected if not (vault_path / "wiki" / p).exists()]
        assert not missing, f"Missing concept pages: {missing}"

    def test_entity_pages_exist(self, vault_path):
        expected = [
            "entities/claude-code.md",
            "entities/mempalace.md",
            "entities/obra-superpowers.md",
            "entities/claude-obsidian.md",
        ]
        missing = [p for p in expected if not (vault_path / "wiki" / p).exists()]
        assert not missing, f"Missing entity pages: {missing}"

    def test_source_page_exists(self, vault_path):
        path = vault_path / "wiki" / "sources" / "uncomfortable-truths-ai-coding-agents.md"
        assert path.exists(), "Missing: sources/uncomfortable-truths-ai-coding-agents.md"

    def test_uncomfortable_truths_frontmatter(self, vault_path):
        """The critical retrieval target must have correct frontmatter for BM25 matching."""
        path = vault_path / "wiki" / "sources" / "uncomfortable-truths-ai-coding-agents.md"
        fm = _extract_frontmatter(path)
        assert fm is not None, "No frontmatter"
        assert fm.get("sentiment") == "critical", f"sentiment should be 'critical', got '{fm.get('sentiment')}'"
        assert fm.get("ingested_via") == "notion_briefing", f"ingested_via wrong: {fm.get('ingested_via')}"
        assert fm.get("briefing_date") == "2026-03-28" or str(fm.get("briefing_date")) == "2026-03-28"
        assert "ai-coding-agents" in (fm.get("tags") or []), f"tags missing 'ai-coding-agents': {fm.get('tags')}"
        assert fm.get("url") or fm.get("source_url"), "Missing source URL"

    def test_concept_pages_have_sources(self, vault_path):
        """Concept pages should reference raw briefings as sources."""
        failures = []
        for p in (vault_path / "wiki" / "concepts").glob("*.md"):
            fm = _extract_frontmatter(p)
            if fm is None:
                continue
            sources = fm.get("sources") or []
            if not sources:
                failures.append(f"{p.name}: no sources listed")
        assert not failures, f"Concept pages without sources:\n" + "\n".join(failures)


class TestStructuralPages:
    """Validate index, log, hot cache."""

    def test_index_exists(self, vault_path):
        assert (vault_path / "wiki" / "index.md").exists()

    def test_log_exists(self, vault_path):
        assert (vault_path / "wiki" / "log.md").exists()

    def test_hot_exists(self, vault_path):
        assert (vault_path / "wiki" / "hot.md").exists()

    def test_index_references_concepts(self, vault_path):
        index_text = (vault_path / "wiki" / "index.md").read_text()
        expected_links = ["ai-coding-agents", "llm-wiki-pattern", "agent-memory"]
        missing = [link for link in expected_links if link not in index_text]
        assert not missing, f"index.md missing references to: {missing}"

    def test_log_has_entries(self, vault_path):
        log_text = (vault_path / "wiki" / "log.md").read_text()
        assert "ingest" in log_text.lower(), "log.md has no ingest entries"


class TestSandboxIngestion:
    """Tests that write new content into a sandbox vault."""

    def test_new_wiki_page_can_be_written(self, sandbox):
        """Smoke test: write a wiki page to the sandbox, verify it exists."""
        sandbox.write_wiki(
            "sources/test-article.md",
            "---\ntype: source\ntitle: Test Article\ncreated: 2026-04-11\n"
            "updated: 2026-04-11\nstatus: seed\ntags:\n  - test\n---\n\n# Test\n\nBody.\n",
        )
        assert sandbox.wiki_exists("sources/test-article.md")

    def test_sandbox_qmd_indexes_new_page(self, sandbox):
        """Write a page, reindex, verify qmd finds it."""
        sandbox.write_wiki(
            "concepts/test-concept.md",
            "---\ntype: concept\ntitle: Test Concept\ncreated: 2026-04-11\n"
            "updated: 2026-04-11\nstatus: seed\ntags:\n  - test\n---\n\n"
            "# Test Concept\n\nThis is about banana quantum computing.\n",
        )
        sandbox.qmd_update_and_embed()
        results = sandbox.qmd_query("banana quantum computing")
        paths = [r.get("displayPath", r.get("path", "")) for r in results]
        found = any("test-concept" in p for p in paths)
        assert found, f"test-concept not found in qmd results: {paths}"
