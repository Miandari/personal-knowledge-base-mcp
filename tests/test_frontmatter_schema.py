"""Frontmatter schema compliance tests.

Walks every wiki page and validates YAML frontmatter against the schema
defined in .claude/skills/wiki/references/frontmatter.md.
"""

import re
from pathlib import Path

import pytest
import yaml


VALID_TYPES = {"source", "entity", "concept", "domain", "comparison", "question", "overview", "meta"}
VALID_STATUSES = {"seed", "developing", "mature", "evergreen"}
VALID_SENTIMENTS = {"critical", "skeptical", "neutral", "mixed", "enthusiastic"}
VALID_SOURCE_TYPES = {"article", "video", "podcast", "paper", "book", "transcript", "data", "notion_briefing", "blog_article", "image"}
VALID_ENTITY_TYPES = {"person", "organization", "product", "repository", "place"}
VALID_INGESTED_VIA = {"notion_briefing", "manual", "web_fetch", "youtube_mcp"}
VALID_CONFIDENCE = {"high", "medium", "low"}

# Date format: YYYY-MM-DD
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _extract_frontmatter(path: Path) -> dict | None:
    """Extract YAML frontmatter from a markdown file. Returns None if no frontmatter."""
    text = path.read_text()
    if not text.startswith("---"):
        return None
    end = text.index("---", 3)
    fm_text = text[3:end].strip()
    if not fm_text:
        return None
    return yaml.safe_load(fm_text)


def _all_wiki_pages(vault_path: Path) -> list[Path]:
    """Return all .md files under wiki/ (excluding .gitkeep)."""
    return [p for p in (vault_path / "wiki").rglob("*.md") if p.name != ".gitkeep"]


class TestFrontmatterPresence:
    """Every wiki page must have frontmatter."""

    def test_all_pages_have_frontmatter(self, vault_path):
        pages = _all_wiki_pages(vault_path)
        missing = [str(p.relative_to(vault_path)) for p in pages if _extract_frontmatter(p) is None]
        assert not missing, f"Pages without frontmatter:\n" + "\n".join(missing)


class TestUniversalFields:
    """Universal fields that every page should have."""

    def test_required_fields(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None:
                continue  # caught by presence test
            rel = str(page.relative_to(vault_path))
            for field in ("type", "title", "created", "updated", "status"):
                if field not in fm:
                    failures.append(f"{rel}: missing required field '{field}'")
        assert not failures, f"Frontmatter violations:\n" + "\n".join(failures)

    def test_type_values(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None or "type" not in fm:
                continue
            if fm["type"] not in VALID_TYPES:
                rel = str(page.relative_to(vault_path))
                failures.append(f"{rel}: type='{fm['type']}' not in {VALID_TYPES}")
        assert not failures, "\n".join(failures)

    def test_status_values(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None or "status" not in fm:
                continue
            if fm["status"] not in VALID_STATUSES:
                rel = str(page.relative_to(vault_path))
                failures.append(f"{rel}: status='{fm['status']}' not in {VALID_STATUSES}")
        assert not failures, "\n".join(failures)

    def test_date_formats(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None:
                continue
            rel = str(page.relative_to(vault_path))
            for field in ("created", "updated", "briefing_date"):
                if field in fm and fm[field] is not None:
                    val = str(fm[field])
                    if not DATE_RE.match(val):
                        failures.append(f"{rel}: {field}='{val}' is not YYYY-MM-DD")
        assert not failures, "\n".join(failures)


class TestOptionalFieldValues:
    """Optional fields, when present, should have valid values."""

    def test_sentiment_values(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None or "sentiment" not in fm:
                continue
            if fm["sentiment"] and fm["sentiment"] not in VALID_SENTIMENTS:
                rel = str(page.relative_to(vault_path))
                failures.append(f"{rel}: sentiment='{fm['sentiment']}' not in {VALID_SENTIMENTS}")
        assert not failures, "\n".join(failures)

    def test_ingested_via_values(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None or "ingested_via" not in fm:
                continue
            if fm["ingested_via"] and fm["ingested_via"] not in VALID_INGESTED_VIA:
                rel = str(page.relative_to(vault_path))
                failures.append(f"{rel}: ingested_via='{fm['ingested_via']}' not in {VALID_INGESTED_VIA}")
        assert not failures, "\n".join(failures)

    def test_confidence_values(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None or "confidence" not in fm:
                continue
            if fm["confidence"] and fm["confidence"] not in VALID_CONFIDENCE:
                rel = str(page.relative_to(vault_path))
                failures.append(f"{rel}: confidence='{fm['confidence']}' not in {VALID_CONFIDENCE}")
        assert not failures, "\n".join(failures)

    def test_no_empty_optional_fields(self, vault_path):
        """Optional provenance fields should be omitted, not set to empty string."""
        failures = []
        optional_fields = ("sentiment", "ingested_via", "briefing_date")
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None:
                continue
            rel = str(page.relative_to(vault_path))
            for field in optional_fields:
                if field in fm and fm[field] == "":
                    failures.append(f"{rel}: '{field}' is empty string — should be omitted instead")
        assert not failures, "\n".join(failures)


class TestFlatYAML:
    """Frontmatter must be flat — no nested objects (Obsidian requirement)."""

    def test_no_nested_objects(self, vault_path):
        failures = []
        for page in _all_wiki_pages(vault_path):
            fm = _extract_frontmatter(page)
            if fm is None:
                continue
            rel = str(page.relative_to(vault_path))
            for key, val in fm.items():
                if isinstance(val, dict):
                    failures.append(f"{rel}: field '{key}' is a nested object — must be flat YAML")
        assert not failures, "\n".join(failures)
