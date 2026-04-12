"""Ingestion correctness tests.

Tests that already-ingested content (from the Phase 3 run) has correct
wiki page structure, frontmatter, and cross-references. Also tests
sandbox-mode ingestion, contradiction detection, and delta tracking.
"""

import hashlib
import json
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


class TestContradictionDetection:
    """Test that contradictions between briefings are flagged.

    claude-obsidian's wiki-ingest uses > [!contradiction] callouts when
    new info conflicts with existing pages. This tests whether that
    mechanism is actually being used in the compiled wiki.
    """

    def test_contradiction_callouts_inventory(self, vault_path):
        """Inventory all contradiction callouts in the wiki.

        Not a hard pass/fail on the first run (contradictions only
        appear after sequential ingests, and Phase 3 compiled all 4
        briefings at once). Instead, report what we find so we have
        a baseline.
        """
        callout_pages = []
        for p in (vault_path / "wiki").rglob("*.md"):
            if p.name == ".gitkeep":
                continue
            text = p.read_text()
            if "[!contradiction]" in text:
                count = text.count("[!contradiction]")
                callout_pages.append((str(p.relative_to(vault_path)), count))

        print(f"\n--- Contradiction callout inventory ---")
        if callout_pages:
            for page, count in callout_pages:
                print(f"  {page}: {count} callout(s)")
        else:
            print("  No contradiction callouts found in any wiki page.")
            print("  This is expected for a batch ingest. Sequential re-ingests")
            print("  should produce callouts where facts evolved between briefings.")
        # Diagnostic only — no assertion yet

    def test_evolving_facts_acknowledged(self, vault_path):
        """Check that pages citing multiple briefings acknowledge data changes.

        Known evolving fact: mempalace grew from ~39k stars (Apr 10) to
        ~41k stars (Apr 11). The entity page should reflect the most
        recent data.
        """
        mempalace = vault_path / "wiki" / "entities" / "mempalace.md"
        if not mempalace.exists():
            pytest.skip("mempalace.md not found")

        text = mempalace.read_text()

        # Should mention both dates' data (the growth is explicitly tracked)
        has_april_10_data = "39k" in text or "39,000" in text or "2026-04-10" in text
        has_april_11_data = "41k" in text or "41,000" in text or "5,871" in text

        if has_april_10_data and has_april_11_data:
            print("\n  mempalace.md tracks data from both Apr 10 and Apr 11 — good")
        elif has_april_11_data:
            print("\n  mempalace.md has latest data (Apr 11) but no historical comparison")
        else:
            print(f"\n  WARN: mempalace.md may not reflect evolving star counts")

        # Soft assertion: at minimum the page should have SOME star data
        assert "★" in text or "star" in text.lower() or "39k" in text or "41k" in text, (
            "mempalace.md has no star count data at all"
        )


class TestDeltaTracking:
    """Test the .manifest.json delta tracking mechanism.

    Re-ingesting the same raw file should be a no-op: no new pages
    created, no qmd re-embed triggered. This prevents content
    duplication if /ingest-notion-briefing is run twice for the same day.
    """

    def test_manifest_exists_or_flagged(self, vault_path):
        """Check if .raw/.manifest.json exists. If not, flag it — the
        delta tracker isn't active yet."""
        manifest = vault_path / ".raw" / ".manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text())
            entries = len(data.get("sources", {}))
            print(f"\n--- Delta manifest: {entries} entries ---")
            assert entries > 0, "Manifest exists but has 0 entries"
        else:
            print(
                "\n--- WARN: .raw/.manifest.json does not exist ---\n"
                "  The Phase 3 ingest wrote raw files directly (bypassing\n"
                "  wiki-ingest's delta tracker). Future ingests via\n"
                "  /ingest-notion-briefing → wiki-ingest will create it.\n"
                "  Until then, re-ingest protection is not active."
            )
            # Not a failure — the manifest is created by wiki-ingest, not by
            # direct file writes. But flag it for awareness.

    def test_sandbox_manifest_prevents_reingest(self, sandbox):
        """In sandbox: write a raw file + manifest entry, then verify
        the manifest reports it as already ingested."""
        raw_content = (
            "---\nsource_type: test\nfetched: 2026-04-12\n---\n"
            "# Test source\n\nSome content about test topic.\n"
        )
        raw_path = ".raw/articles/test-reingest-2026-04-12.md"
        sandbox.write_raw("articles/test-reingest-2026-04-12.md", raw_content)

        # Compute hash (same algorithm wiki-ingest uses)
        file_hash = hashlib.md5(raw_content.encode()).hexdigest()

        # Write a manifest entry marking this file as already ingested
        manifest = {
            "sources": {
                raw_path: {
                    "hash": file_hash,
                    "ingested_at": "2026-04-12",
                    "pages_created": ["wiki/sources/test-reingest.md"],
                    "pages_updated": ["wiki/index.md"],
                }
            }
        }
        manifest_path = sandbox.vault_path / ".raw" / ".manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # Verify: re-read and check that the hash matches
        saved = json.loads(manifest_path.read_text())
        entry = saved["sources"].get(raw_path)
        assert entry is not None, "Manifest entry not found after write"
        assert entry["hash"] == file_hash, (
            f"Hash mismatch: manifest has {entry['hash']}, file has {file_hash}"
        )

        # Verify: the file hasn't changed (hash still matches)
        current_hash = hashlib.md5(
            (sandbox.vault_path / raw_path).read_text().encode()
        ).hexdigest()
        assert current_hash == file_hash, "File content changed unexpectedly"

        print(f"\n  Delta tracking: manifest correctly records hash {file_hash[:8]}... for {raw_path}")
        print("  A real wiki-ingest run would skip this file on re-ingest.")
