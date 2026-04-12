"""Thin wrapper around the qmd CLI for use in tests."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class QmdResult:
    title: str
    path: str
    docid: str
    score: float
    snippet: str
    context: str


def qmd_query(
    query: str,
    collection: str = "kb",
    n: int = 10,
    mode: str = "hybrid",
    min_score: float = 0.0,
) -> list[QmdResult]:
    """Run a qmd query and return parsed results.

    mode: "hybrid" (qmd query), "bm25" (qmd search), "vector" (qmd vsearch)
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

    raw = json.loads(result.stdout)
    return [
        QmdResult(
            title=r.get("title", ""),
            path=r.get("displayPath", r.get("path", "")),
            docid=r.get("docid", ""),
            score=float(r.get("score", 0)),
            snippet=r.get("snippet", ""),
            context=r.get("context", ""),
        )
        for r in raw
    ]


def qmd_get(docid_or_path: str, full: bool = True) -> str:
    """Fetch a single document from qmd by docid or path."""
    cmd = ["qmd", "get", docid_or_path, "--json"]
    if full:
        cmd.append("--full")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"qmd get failed: {result.stderr}")
    data = json.loads(result.stdout)
    return data.get("content", data.get("text", str(data)))


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
