"""Thin wrapper around the qmd CLI for use in tests.

qmd JSON format (v2.1.0):
  - "file": "qmd://collection/path/to/file.md" (NOT "path" or "displayPath")
  - "score": rank-based (1/rank) in hybrid mode, 0 in BM25 mode
  - "docid": "#hexid"
  - "title", "snippet", "context": as expected

Scores are NOT similarity scores. They are positional: 1.0 for rank 1,
0.5 for rank 2, 0.33 for rank 3, etc. Use result order (position) for
ranking comparisons, not the score values.
"""

import json
import subprocess
from dataclasses import dataclass


@dataclass
class QmdResult:
    title: str
    file: str       # full qmd URI, e.g. "qmd://kb/concepts/ai-coding-agents.md"
    path: str       # just the path part after qmd://collection/, e.g. "concepts/ai-coding-agents.md"
    docid: str
    score: float    # rank-based, NOT similarity
    snippet: str
    context: str


def _parse_file_to_path(file_uri: str) -> str:
    """Extract the wiki-relative path from a qmd URI.

    "qmd://kb/concepts/ai-coding-agents.md" → "concepts/ai-coding-agents.md"
    """
    if "://" in file_uri:
        # Strip qmd://collection/ prefix
        after_scheme = file_uri.split("://", 1)[1]
        # Skip the collection name (first path segment)
        parts = after_scheme.split("/", 1)
        return parts[1] if len(parts) > 1 else after_scheme
    return file_uri


def qmd_query(
    query: str,
    collection: str = "kb",
    n: int = 10,
    mode: str = "hybrid",
    min_score: float = 0.0,
) -> list[QmdResult]:
    """Run a qmd query and return parsed results.

    mode: "hybrid" (qmd query), "bm25" (qmd search), "vector" (qmd vsearch),
          "hybrid_no_rerank" (qmd query --no-rerank)
    """
    cmd_map = {
        "hybrid": ["qmd", "query"],
        "hybrid_no_rerank": ["qmd", "query", "--no-rerank"],
        "bm25": ["qmd", "search"],
        "vector": ["qmd", "vsearch"],
    }
    base_cmd = cmd_map.get(mode, cmd_map["hybrid"])
    cmd = [*base_cmd, query, "-c", collection, "-n", str(n), "--json"]
    if min_score > 0:
        cmd.extend(["--min-score", str(min_score)])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"qmd failed: {result.stderr}")

    # qmd may print progress lines to stderr before the JSON on stdout
    stdout = result.stdout.strip()
    if not stdout:
        return []

    raw = json.loads(stdout)
    return [
        QmdResult(
            title=r.get("title", ""),
            file=r.get("file", ""),
            path=_parse_file_to_path(r.get("file", "")),
            docid=r.get("docid", ""),
            score=float(r.get("score", 0)),
            snippet=r.get("snippet", ""),
            context=r.get("context", ""),
        )
        for r in raw
    ]


def qmd_get(docid_or_path: str, full: bool = True) -> str:
    """Fetch a single document from qmd by docid or path."""
    cmd = ["qmd", "get", docid_or_path]
    if full:
        cmd.append("--full")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"qmd get failed: {result.stderr}")
    # qmd get without --json returns the raw document text
    return result.stdout


def qmd_status(collection: str = "kb") -> dict:
    """Return index health info."""
    result = subprocess.run(
        ["qmd", "status"], capture_output=True, text=True, timeout=15
    )
    return {"returncode": result.returncode, "output": result.stdout}


def precision_at_k(results: list[QmdResult], expected_paths: list[str], k: int = 5) -> float:
    """Fraction of expected paths found in the top-k results."""
    top_k_paths = {r.path for r in results[:k]}
    found = sum(1 for p in expected_paths if any(p in tp for tp in top_k_paths))
    return found / len(expected_paths) if expected_paths else 0.0


def mrr(results: list[QmdResult], target_path: str) -> float:
    """Mean Reciprocal Rank: 1/(rank of first result containing target_path), or 0."""
    for i, r in enumerate(results):
        if target_path in r.path:
            return 1.0 / (i + 1)
    return 0.0
