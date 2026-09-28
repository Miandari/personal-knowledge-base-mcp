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

    if args.dry_run:
        # A dry run must not write: no reset, no schema, no new file.
        if not config.DB_PATH.exists():
            print(f"No database at {config.DB_PATH}; a real rebuild would create it.")
            return
        if args.force:
            print("Force rebuild (dry run): would drop and recreate the database.")
        conn = get_connection()
    elif args.force:
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
    print(f"Pages relinked: {stats['pages_relinked']}")
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
    print(f"Versioned:  {_git_health(config.VAULT_ROOT)}")

    conn.close()


def _git_health(vault_root) -> str:
    """One-line version-control state for `pkb status`.

    The vault ships git-dependent hooks that fail open — if the repo is missing
    they simply do nothing, forever, without a word. That is how this vault sat
    unversioned for months while its docs drifted from the tool. Surfacing the
    inert case here is the cheap antidote: an unarmed safety net should say so.
    """
    import subprocess
    from pathlib import Path

    root = Path(vault_root)
    if not (root / ".git").exists():
        return "NO — not a git repo, so the auto-commit hooks are inert (`git init`)"
    try:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                               capture_output=True, text=True, timeout=15).stdout.split("\n")
        n = len([ln for ln in dirty if ln.strip()])
        count = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=root,
                               capture_output=True, text=True, timeout=15).stdout.strip()
        commits = f"{count} commits" if count else "no commits yet"
        return f"yes — {commits}" + (f", {n} uncommitted change(s)" if n else ", clean")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown — git unavailable"


def cmd_search(args):
    """Find pages: by id, by query, or by browsing filters.

    Thin shell over search.find() — the same implementation kb_find uses, so
    the CLI and the MCP tool always accept the same filters.
    """
    _load_env()
    from .db import get_connection
    from .search import find
    from .embeddings import get_provider

    if not config.DB_PATH.exists():
        print(f"No database found at {config.DB_PATH}. Run `pkb rebuild` first.")
        sys.exit(1)

    conn = get_connection()
    try:
        query = args.query or ""
        needs_embeddings = bool(query) and args.mode != "bm25"
        try:
            result = find(
                conn,
                query=query, id=args.id or "",
                origin=args.origin, tag=args.tag, sentiment=args.sentiment,
                created_after=args.created_after or "",
                created_before=args.created_before or "",
                published_after=args.published_after or "",
                published_before=args.published_before or "",
                mode=args.mode, sort=args.sort, limit=args.limit,
                embedding_provider=(get_provider(config.EMBEDDING_PROVIDER, conn=conn)
                                    if needs_embeddings else None),
            )
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(2)

        if args.json_output:
            if result is None:
                print("null")
            elif isinstance(result, list):
                print(json.dumps([r.model_dump() for r in result], indent=2, default=str))
            else:
                print(json.dumps(result.model_dump(), indent=2, default=str))
            return

        _render_find_result(result, by_id=bool(args.id), scored=bool(query))
    finally:
        conn.close()


def _render_find_result(result, by_id: bool, scored: bool):
    """Human-readable rendering for the three shapes find() can return."""
    from .dates import relative_time

    if by_id:
        if result is None:
            print("Not found.")
            return
        print(f"{result.title}  [{result.origin}]")
        print(f"  id:      {result.id}")
        print(f"  updated: {result.updated_at}")
        if getattr(result, "tags", None):
            print(f"  tags:    {', '.join(result.tags)}")
        if getattr(result, "body", None):
            print()
            print(result.body)
        return

    if not result:
        print("No results.")
        return

    for i, r in enumerate(result, 1):
        if scored:
            dist_str = f"  vec_dist={r.vec_distance:.4f}" if r.vec_distance is not None else ""
            print(f"{i}. [{r.origin}] {r.title} (score={r.score:.6f}{dist_str})")
            node_id = r.node_id
        else:
            # Browse listing — no score to show.
            print(f"{i}. [{r.origin}] {r.title}")
            node_id = r.id
        rel = relative_time(r.updated_at, "day") or "?"
        print(f"   {node_id}  updated={r.updated_at} ({rel})")
        if r.snippet:
            print(f"   {r.snippet[:120]}...")
        print()


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

    git_msg = _init_git(dest) if not args.no_git else "skipped (--no-git)"

    print(f"Vault initialized at {dest}")
    print(f"Version control: {git_msg}")
    print()
    print("Next steps:")
    print(f"  1. cd {dest}")
    print(f"  2. Copy .env.example to .env and set your VOYAGE_API_KEY")
    print(f"  3. pkb rebuild")
    print(f"  4. Connect your MCP client (see .claude/settings.json)")


def _init_git(dest: Path) -> str:
    """Put a freshly scaffolded vault under git.

    The scaffold ships a .gitignore and two git-dependent hooks (auto-commit on
    Write|Edit, and an uncommitted-changes warning on Stop). Both are guarded by
    `[ -d .git ]`, so without this step a new vault is born with complete but
    permanently inert versioning — which is exactly how the original vault spent
    three months drifting with no record of when or why. Scaffolding the machinery
    and not switching it on is worse than not shipping it.
    """
    import subprocess

    if (dest / ".git").exists():
        return "already a git repo — left alone"
    try:
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True,
                       capture_output=True, timeout=30)
        subprocess.run(["git", "add", "-A"], cwd=dest, check=True,
                       capture_output=True, timeout=30)
        subprocess.run(["git", "commit", "-q", "-m", "Initial commit: pkb vault"],
                       cwd=dest, check=True, capture_output=True, timeout=30)
        return "git repo initialized, initial commit made"
    except FileNotFoundError:
        return "git not found on PATH — vault is NOT versioned (hooks will no-op)"
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode().strip().splitlines()
        hint = detail[-1] if detail else f"exit {e.returncode}"
        return f"git init failed ({hint}) — vault is NOT versioned"
    except subprocess.TimeoutExpired:
        return "git timed out — vault is NOT versioned"


def main():
    parser = argparse.ArgumentParser(prog="pkb", description="Personal knowledge base MCP server")
    parser.add_argument("--vault", type=Path, metavar="PATH",
                       help="Vault directory (default: PKB_VAULT_ROOT env or cwd)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new vault")
    p_init.add_argument("path", nargs="?", default=".", help="Directory to initialize (default: .)")
    p_init.add_argument("--no-git", action="store_true",
                        help="Skip git init (the vault's auto-commit hooks will then no-op)")
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

    # search / find — same surface as the kb_find MCP tool
    p_search = subparsers.add_parser(
        "search", aliases=["find"],
        help="Find pages by query, by id, or by browsing filters",
        description="Omit the query to browse: `pkb search --origin paper --sort created_at`.",
    )
    p_search.add_argument("query", nargs="?", default="",
                          help="Search query (omit to browse by filters)")
    p_search.add_argument("--id", help="Fetch one page by id (ignores query/filters)")
    p_search.add_argument("-n", "--limit", type=int, default=10, help="Max results")
    p_search.add_argument("--mode", choices=["hybrid", "bm25"], default="hybrid", help="Search mode")
    p_search.add_argument("--origin", help="Filter by origin (webpage, paper, note, ...)")
    p_search.add_argument("--tag", help="Filter by tag")
    p_search.add_argument("--sentiment", help="Filter by sentiment")
    p_search.add_argument("--created-after", dest="created_after",
                          help="Created on/after YYYY, YYYY-MM, or YYYY-MM-DD")
    p_search.add_argument("--created-before", dest="created_before",
                          help="Created before YYYY, YYYY-MM, or YYYY-MM-DD")
    p_search.add_argument("--published-after", dest="published_after",
                          help="Published after YYYY, YYYY-MM, or YYYY-MM-DD")
    p_search.add_argument("--published-before", dest="published_before",
                          help="Published before YYYY, YYYY-MM, or YYYY-MM-DD")
    p_search.add_argument("--sort", choices=["updated_at", "created_at", "published_at", "title"],
                          default="updated_at", help="Sort order when browsing")
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
