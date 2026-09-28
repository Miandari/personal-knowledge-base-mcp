"""Synthesis pages: origin validation, source warnings, and kb_find freshness fields."""

from datetime import date

import pytest

from pkb import config
from pkb.db import get_connection
from pkb.embeddings import NoopEmbedding
from pkb.indexer import Indexer
from pkb.server import _SAVE_DESC, kb_find, kb_save


def _page(wiki, slug, updated, body="Body.", origin="note", extra=""):
    (wiki / f"{slug}.md").write_text(
        f"---\ntitle: {slug}\norigin: {origin}\n{extra}"
        f"created_at: {updated}\nupdated_at: {updated}\n---\n\n# {slug}\n\n{body}\n"
    )


def _index(wiki):
    conn = get_connection()
    Indexer(conn, wiki_dir=wiki, embedding_provider=NoopEmbedding()).rebuild()
    conn.close()


@pytest.fixture
def wiki(tmp_path, monkeypatch):
    """An empty vault that config and kb_* tools point at for one test."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(config, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(config, "WIKI_DIR", wiki)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pkb.db")
    monkeypatch.setenv("KB_EMBEDDING_PROVIDER", "noop")
    return wiki


class TestOriginValidation:
    def test_unknown_origin_is_rejected(self, wiki):
        r = kb_save(title="A talk", origin="video", body="Notes.")
        assert "error" in r and "video" in r["error"] and "synthesis" in r["error"]
        assert not (wiki / "a-talk.md").exists()

    def test_every_origin_is_documented_in_the_tool(self):
        for origin in config.ORIGINS:
            assert origin in _SAVE_DESC


class TestSourceWarnings:
    def test_synthesis_without_sources_is_nudged(self, wiki):
        r = kb_save(title="Field map", origin="synthesis", body="Summary.")
        assert "error" not in r
        assert any("lists no wiki pages" in w for w in r["warnings"])

    def test_url_in_sources_is_flagged(self, wiki):
        r = kb_save(
            title="Field map", origin="synthesis", body="Summary.",
            sources=["https://example.com/paper"],
        )
        assert any("https://example.com/paper" in w and "## Sources" in w for w in r["warnings"])
        assert any("lists no wiki pages" in w for w in r["warnings"])

    def test_synthesis_with_wiki_sources_has_no_warnings(self, wiki):
        _page(wiki, "input-a", "2026-01-01")
        _index(wiki)
        r = kb_save(title="Field map", origin="synthesis", body="Summary.", sources=["input-a"])
        assert "warnings" not in r

    def test_non_synthesis_without_sources_is_not_nudged(self, wiki):
        r = kb_save(title="Plain note", origin="note", body="Thought.")
        assert "warnings" not in r

    def test_mutual_sources_are_flagged(self, wiki):
        _page(wiki, "earlier", "2026-01-01", extra='sources:\n  - "[[later]]"\n')
        _page(wiki, "later", "2026-02-01")
        _index(wiki)
        r = kb_save(id="later", sources=["earlier"])
        assert any("earlier" in w and "each other" in w for w in r["warnings"])

    def test_bracketed_page_ids_are_accepted(self, wiki):
        _page(wiki, "input-a", "2026-01-01")
        _index(wiki)
        r = kb_save(title="Field map", origin="synthesis", body="Summary.", sources=["[[input-a]]"])
        assert "warnings" not in r
        assert '"[[input-a]]"' in (wiki / "field-map.md").read_text()

    def test_hand_written_page_with_unknown_origin_is_flagged_on_reindex(self, wiki):
        _page(wiki, "talk", "2026-01-01", origin="video")
        _index(wiki)
        r = kb_save(id="talk")
        assert any("'video'" in w for w in r["warnings"])

    def test_self_source_is_not_called_mutual(self, wiki):
        _page(wiki, "selfie", "2026-01-01", origin="synthesis", extra='sources:\n  - "[[selfie]]"\n')
        _index(wiki)
        r = kb_save(id="selfie")
        assert not any("each other" in w for w in r["warnings"])
        assert any("lists no wiki pages" in w for w in r["warnings"])

    def test_update_with_unresolved_source_is_flagged(self, wiki):
        kb_save(title="Field map", origin="synthesis", body="Summary.")
        r = kb_save(id="field-map", sources=["no-such-page"])
        assert any("no-such-page" in w for w in r["warnings"])


class TestFreshness:
    def test_stale_sources_lists_inputs_updated_after_the_page(self, wiki):
        _page(wiki, "input-new", "2026-02-01")
        _page(wiki, "input-old", "2025-12-01")
        _page(wiki, "synth", "2026-01-01", origin="synthesis",
              extra='sources:\n  - "[[input-new]]"\n  - "[[input-old]]"\n')
        _index(wiki)

        page = kb_find(id="synth")

        assert [s["id"] for s in page["stale_sources"]] == ["input-new"]

    def test_new_since_keeps_only_newer_unlinked_pages(self, wiki):
        declares = 'related:\n  - "[[synth]]"\n'
        _page(wiki, "synth", "2026-01-01", origin="synthesis", body="See [[linked-newer]].")
        _page(wiki, "newer", "2026-03-01", extra=declares)
        _page(wiki, "older", "2025-11-01", extra=declares)  # e.g. a sibling from the same run
        _page(wiki, "linked-newer", "2026-03-01", extra=declares)  # the synthesis already links it
        _index(wiki)

        page = kb_find(id="synth")

        assert [p["id"] for p in page["new_since"]] == ["newer"]

    def test_new_since_skips_pages_built_on_the_synthesis(self, wiki):
        _page(wiki, "synth", "2026-01-01", origin="synthesis")
        _page(wiki, "builds-on-synth", "2026-03-01",
              extra='sources:\n  - "[[synth]]"\nrelated:\n  - "[[synth]]"\n')
        _index(wiki)

        assert kb_find(id="synth")["new_since"] == []

    def test_id_lookup_survives_a_bad_embedding_setting(self, wiki, monkeypatch):
        _page(wiki, "synth", "2026-01-01", origin="synthesis")
        _index(wiki)
        monkeypatch.setenv("KB_EMBEDDING_PROVIDER", "none")

        assert kb_find(id="synth")["id"] == "synth"

    def test_new_since_is_only_for_synthesis_pages(self, wiki):
        _page(wiki, "plain", "2026-01-01")
        _page(wiki, "newer", "2026-03-01", extra='related:\n  - "[[plain]]"\n')
        _index(wiki)

        assert kb_find(id="plain")["new_since"] == []


class TestUpdatedAt:
    """updated_at records content edits, which is what staleness compares."""

    def _updated(self, wiki, slug):
        return kb_find(id=slug)["updated_at"]

    def test_section_edit_bumps_it_and_makes_dependants_stale(self, wiki):
        _page(wiki, "input-a", "2026-01-01")
        _page(wiki, "synth", "2026-02-01", origin="synthesis", extra='sources:\n  - "[[input-a]]"\n')
        _index(wiki)
        assert kb_find(id="synth")["stale_sources"] == []

        kb_save(id="input-a", section="Update", body="New finding.")

        assert self._updated(wiki, "input-a") == date.today().isoformat()
        assert [s["id"] for s in kb_find(id="synth")["stale_sources"]] == ["input-a"]

    def test_body_replacement_bumps_it(self, wiki):
        _page(wiki, "input-a", "2026-01-01")
        _index(wiki)
        kb_save(id="input-a", body="Rewritten.")
        assert self._updated(wiki, "input-a") == date.today().isoformat()

    def test_tag_only_edit_leaves_it(self, wiki):
        _page(wiki, "input-a", "2026-01-01")
        _index(wiki)
        kb_save(id="input-a", tags=["retagged"])
        assert self._updated(wiki, "input-a") == "2026-01-01"
