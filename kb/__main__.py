"""CLI: python -m kb rebuild [--force] [--dry-run] | server | status | search "..." """

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from vault root
_vault_root = Path(__file__).resolve().parent.parent
_env_file = _vault_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

from . import config
from .db import get_connection, init_schema, reset_db
from .indexer import Indexer
from .embeddings import get_provider
from .search import hybrid_search, fts_search, get_status


def cmd_rebuild(args):
    """Rebuild the SQLite index from wiki/ markdown files."""
    if args.force:
        print("Force rebuild: dropping and recreating database...")
        conn = reset_db()
    else:
        conn = get_connection()
        init_schema(conn)

    # Choose embedding provider
    provider_name = "noop" if args.no_embed else config.EMBEDDING_PROVIDER
    provider = get_provider(provider_name, conn=conn)

    indexer = Indexer(conn, embedding_provider=provider, dry_run=args.dry_run)
    stats = indexer.rebuild(force=args.force)

    print(f"Files scanned:  {stats['files_scanned']}")
    print(f"Files indexed:  {stats['files_indexed']}")
    print(f"Files skipped:  {stats['files_skipped']}")
    print(f"Files deleted:  {stats['files_deleted']}")
    print(f"Chunks created: {stats['chunks_created']}")
    print(f"Chunks embedded:{stats['chunks_embedded']}")
    if stats['errors']:
        print(f"Errors ({len(stats['errors'])}):")
        for e in stats['errors']:
            print(f"  - {e}")

    if args.dry_run:
        print("\n(dry run — no changes written)")

    conn.close()


def cmd_status(args):
    """Show index health."""
    if not config.DB_PATH.exists():
        print("No database found. Run `python -m kb rebuild` first.")
        sys.exit(1)

    conn = get_connection()
    status = get_status(conn)

    print(f"Nodes:      {status.node_count}")
    print(f"Edges:      {status.edge_count}")
    print(f"Chunks:     {status.chunk_count}")
    print(f"Embedded:   {status.embedded_chunks}")
    print(f"Coverage:   {status.embedding_coverage:.0%}")
    print(f"Stale:      {status.stale_count}")
    print(f"Orphans:    {status.orphan_chunks}")
    print(f"Types:      {json.dumps(status.types)}")

    conn.close()


def cmd_search(args):
    """Search the index."""
    if not config.DB_PATH.exists():
        print("No database found. Run `python -m kb rebuild` first.")
        sys.exit(1)

    conn = get_connection()

    # Determine search mode
    filters = {}
    if args.type:
        filters["type"] = args.type
    if args.sentiment:
        filters["sentiment"] = args.sentiment

    if args.mode == "bm25":
        results = fts_search(conn, args.query, limit=args.limit, filters=filters)
    else:
        provider = get_provider(config.EMBEDDING_PROVIDER, conn=conn) if args.mode != "bm25" else None
        results = hybrid_search(conn, args.query, limit=args.limit, filters=filters, embedding_provider=provider)

    if args.json_output:
        print(json.dumps([r.model_dump() for r in results], indent=2))
    else:
        if not results:
            print("No results.")
        for i, r in enumerate(results, 1):
            dist_str = f"  vec_dist={r.vec_distance:.4f}" if r.vec_distance is not None else ""
            print(f"{i}. [{r.type}] {r.title} (score={r.score:.6f}{dist_str})")
            print(f"   {r.node_id}  updated={r.updated}")
            if r.snippet:
                print(f"   {r.snippet[:120]}...")
            print()

    conn.close()


def cmd_server(args):
    """Start the MCP server."""
    from .server import mcp
    mcp.run()


def main():
    parser = argparse.ArgumentParser(prog="kb", description="compiled-knowledge-base CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # rebuild
    p_rebuild = subparsers.add_parser("rebuild", help="Index wiki/ into SQLite")
    p_rebuild.add_argument("--force", action="store_true", help="Drop and recreate DB")
    p_rebuild.add_argument("--dry-run", action="store_true", help="Report what would change")
    p_rebuild.add_argument("--no-embed", action="store_true", help="Skip embedding (FTS5 only)")
    p_rebuild.set_defaults(func=cmd_rebuild)

    # status
    p_status = subparsers.add_parser("status", help="Show index health")
    p_status.set_defaults(func=cmd_status)

    # search
    p_search = subparsers.add_parser("search", help="Search the index")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("-n", "--limit", type=int, default=10, help="Max results")
    p_search.add_argument("--mode", choices=["hybrid", "bm25"], default="hybrid", help="Search mode")
    p_search.add_argument("--type", help="Filter by node type")
    p_search.add_argument("--sentiment", help="Filter by sentiment")
    p_search.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    p_search.set_defaults(func=cmd_search)

    # server
    p_server = subparsers.add_parser("server", help="Start MCP server")
    p_server.set_defaults(func=cmd_server)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
