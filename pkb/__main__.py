"""CLI: pkb [--vault PATH] rebuild|server|status|search|init"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import config


def _load_env():
    """Load .env from vault root if it exists."""
    env_file = config.VAULT_ROOT / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass


def cmd_rebuild(args):
    """Rebuild the SQLite index from wiki/ markdown files."""
    _load_env()
    from .db import get_connection, init_schema, reset_db
    from .indexer import Indexer
    from .embeddings import get_provider

    if args.force:
        print("Force rebuild: dropping and recreating database...")
        conn = reset_db()
    else:
        conn = get_connection()
        init_schema(conn)

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
    _load_env()
    from .db import get_connection
    from .search import get_status

    if not config.DB_PATH.exists():
        print(f"No database found at {config.DB_PATH}. Run `pkb rebuild` first.")
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
    print(f"Origins:    {json.dumps(status.origins)}")

    conn.close()


def cmd_search(args):
    """Search the index."""
    _load_env()
    from .db import get_connection
    from .search import hybrid_search, fts_search
    from .embeddings import get_provider

    if not config.DB_PATH.exists():
        print(f"No database found at {config.DB_PATH}. Run `pkb rebuild` first.")
        sys.exit(1)

    conn = get_connection()

    filters = {}
    if args.origin:
        filters["origin"] = args.origin
    if args.sentiment:
        filters["sentiment"] = args.sentiment

    if args.mode == "bm25":
        results = fts_search(conn, args.query, limit=args.limit, filters=filters)
    else:
        provider = get_provider(config.EMBEDDING_PROVIDER, conn=conn)
        results = hybrid_search(conn, args.query, limit=args.limit, filters=filters, embedding_provider=provider)

    if args.json_output:
        print(json.dumps([r.model_dump() for r in results], indent=2))
    else:
        if not results:
            print("No results.")
        from .dates import relative_time
        for i, r in enumerate(results, 1):
            dist_str = f"  vec_dist={r.vec_distance:.4f}" if r.vec_distance is not None else ""
            print(f"{i}. [{r.origin}] {r.title} (score={r.score:.6f}{dist_str})")
            rel = relative_time(r.updated_at, "day") or "?"
            print(f"   {r.node_id}  updated={r.updated_at} ({rel})")
            if r.snippet:
                print(f"   {r.snippet[:120]}...")
            print()

    conn.close()


def cmd_server(args):
    """Start the MCP server."""
    _load_env()
    from .server import mcp, _KB_TOKEN

    if args.transport == "http":
        import uvicorn
        app = mcp.streamable_http_app()

        if _KB_TOKEN and not args.no_auth:
            import secrets
            from starlette.middleware.base import BaseHTTPMiddleware
            from starlette.responses import JSONResponse

            class BearerAuthMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    if request.method == "OPTIONS":
                        return await call_next(request)
                    auth = request.headers.get("Authorization", "")
                    if not auth.startswith("Bearer ") or not secrets.compare_digest(auth[7:], _KB_TOKEN):
                        return JSONResponse({"error": "Unauthorized"}, status_code=401)
                    return await call_next(request)

            app.add_middleware(BearerAuthMiddleware)

        uvicorn.run(app, host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


def cmd_init(args):
    """Initialize a new vault directory."""
    dest = Path(args.path).resolve()

    # Guard: refuse to overwrite existing vault
    if (dest / "wiki").is_dir():
        print(f"Error: {dest}/wiki/ already exists. This looks like an existing vault.")
        sys.exit(1)
    if (dest / "pkb.db").exists():
        print(f"Error: {dest}/pkb.db already exists. This looks like an existing vault.")
        sys.exit(1)

    # Find templates directory (inside the installed package)
    templates_dir = Path(__file__).parent / "templates"
    if not templates_dir.is_dir():
        print(f"Error: templates directory not found at {templates_dir}")
        sys.exit(1)

    # Copy templates to destination
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(templates_dir, dest, dirs_exist_ok=True)

    print(f"Vault initialized at {dest}")
    print()
    print("Next steps:")
    print(f"  1. cd {dest}")
    print(f"  2. Copy .env.example to .env and set your VOYAGE_API_KEY")
    print(f"  3. pkb rebuild")
    print(f"  4. Connect your MCP client (see .claude/settings.json)")


def main():
    parser = argparse.ArgumentParser(prog="pkb", description="Personal knowledge base MCP server")
    parser.add_argument("--vault", type=Path, metavar="PATH",
                       help="Vault directory (default: PKB_VAULT_ROOT env or cwd)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new vault")
    p_init.add_argument("path", nargs="?", default=".", help="Directory to initialize (default: .)")
    p_init.set_defaults(func=cmd_init)

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
    p_search.add_argument("--origin", help="Filter by origin (webpage, paper, note, ...)")
    p_search.add_argument("--sentiment", help="Filter by sentiment")
    p_search.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    p_search.set_defaults(func=cmd_search)

    # server
    p_server = subparsers.add_parser("server", help="Start MCP server")
    p_server.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                          help="Transport: stdio (default) or http (Streamable HTTP)")
    p_server.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    p_server.add_argument("--port", type=int, default=8181, help="HTTP port")
    p_server.add_argument("--no-auth", action="store_true",
                          help="Disable auth even if KB_MCP_TOKEN is set")
    p_server.set_defaults(func=cmd_server)

    args = parser.parse_args()

    # Apply --vault before running any command
    if args.vault:
        config.set_vault_root(args.vault)

    args.func(args)


if __name__ == "__main__":
    main()
