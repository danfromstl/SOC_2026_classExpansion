#!/usr/bin/env python3
"""
Two-stage job posting → O*NET task matcher.

WHY TWO STAGES:
  Single-stage cosine similarity finds tasks whose text is semantically similar
  to a job posting bullet, but those tasks may be assigned to completely unrelated
  occupational groups in O*NET. A lineman bullet about "replacing fuses" can
  surface tasks from Telecommunications Equipment Installers, Computer Network
  Architects, or Industrial Machinery Mechanics — all plausible text matches,
  none the right occupation.

HOW IT WORKS:
  Stage 1 — DOG classification:
    Embed the job posting's `title` field (e.g. "Electric Lineman II") and find
    the top-N closest Detailed Occupational Groups (DOGs) by cosine similarity
    to their pooled title-example embeddings (built by build_dog_title_embeddings.py).

  Stage 2 — filtered task retrieval:
    Restrict the O*NET task library to only tasks belonging to the candidate DOGs
    (via the SOC 2018 → O*NET 2019 crosswalk), then run standard top-K cosine
    similarity matching against that filtered subset.

  Result: task matches that are both lexically relevant AND occupationally grounded.

PREREQUISITES:
  1. scripts/task_dwa_embeddings_all_mpnet_base_v2.json  (build_task_dwa_embeddings.py)
  2. scripts/dog_title_embeddings_all_mpnet_base_v2.json  (build_dog_title_embeddings.py)
  3. scripts/soc2018_to_onet2019_crosswalk.json           (build_soc2018_to_onet2019_crosswalk.py)

Usage:
  # LinkedIn results (default):
  python scripts/match_job_postings_two_stage.py

  # Custom input + wider DOG net:
  python scripts/match_job_postings_two_stage.py \\
    --input-jsonl jobPostings/lineman_crawler_results_itemized_for_tagging.jsonl \\
    --top-n-dogs 5 \\
    --output jobPostings/lineman_crawler_two_stage_matches.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_INPUT_JSONL = (
    REPO_ROOT / "jobPostings" / "linkedin_job_search_results_itemized_for_embeddings.jsonl"
)
DEFAULT_TASK_EMB = REPO_ROOT / "scripts" / "task_dwa_embeddings_all_mpnet_base_v2.json"
DEFAULT_DOG_EMB = REPO_ROOT / "scripts" / "dog_title_embeddings_all_mpnet_base_v2.json"
DEFAULT_CROSSWALK = REPO_ROOT / "scripts" / "soc2018_to_onet2019_crosswalk.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "jobPostings" / "linkedin_job_search_results_two_stage_top5_task_matches.json"
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Two-stage (DOG-filtered) job posting to O*NET task matcher."
    )
    p.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL,
                   help="Job postings JSONL (one item per line).")
    p.add_argument("--task-embeddings", type=Path, default=DEFAULT_TASK_EMB,
                   help="Task/DWA embedding JSON.")
    p.add_argument("--dog-embeddings", type=Path, default=DEFAULT_DOG_EMB,
                   help="DOG title embedding JSON (from build_dog_title_embeddings.py).")
    p.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK,
                   help="SOC 2018 → O*NET 2019 crosswalk JSON.")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--top-k", type=int, default=5,
                   help="Task matches per posting item (default: 5).")
    p.add_argument("--top-n-dogs", type=int, default=3,
                   help="DOG candidates per job title for stage-1 (default: 3).")
    p.add_argument("--batch-size", type=int, default=32,
                   help="Encoding batch size (default: 32).")
    p.add_argument("--device", type=str, default=None,
                   help="Torch device string, e.g. 'cuda', 'cpu' (default: auto).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_job_postings(path: Path) -> list[dict]:
    items: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not item.get("id") or not item.get("text"):
                raise ValueError(f"Line {lineno}: missing 'id' or 'text' field.")
            items.append(item)
    return items


def load_task_library(
    path: Path,
) -> tuple[dict, list[dict], np.ndarray]:
    """Return (raw_data, candidates_list, float32_matrix)."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    emb_by_key = data["embeddings_by_key"]
    candidates: list[dict] = []
    for onet_code, onet_data in data["by_onet_soc_code"].items():
        for task in onet_data.get("tasks", []):
            candidates.append(
                {
                    "task_id": task["task_id"],
                    "task": task["task"],
                    "onet_soc_code": onet_code,
                    "onet_soc_title": onet_data["title"],
                    "embedding_key": task["task_embedding_key"],
                }
            )
    matrix = np.array(
        [emb_by_key[c["embedding_key"]]["embedding"] for c in candidates],
        dtype="float32",
    )
    return data, candidates, matrix


def load_dog_embeddings(path: Path) -> tuple[list[str], np.ndarray]:
    """
    Return (soc_codes_ordered, dog_pooled_matrix).
    Each row = mean-pooled + re-normalized embedding of all title texts for one DOG.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    emb_by_key = data["embeddings_by_key"]
    by_code = data["by_soc_2018_code"]
    soc_codes = list(by_code.keys())
    dog_vecs: list[np.ndarray] = []
    for code in soc_codes:
        keys = [e["embedding_key"] for e in by_code[code]["text_entries"]]
        vecs = np.array([emb_by_key[k]["embedding"] for k in keys], dtype="float32")
        pooled = vecs.mean(axis=0)
        norm = np.linalg.norm(pooled)
        dog_vecs.append(pooled / norm if norm > 0 else pooled)
    return soc_codes, np.array(dog_vecs, dtype="float32")


def load_crosswalk(path: Path) -> dict[str, list[str]]:
    """Return {soc_2018_code: [onet_soc_2019_code, ...]}."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        soc: [o["onet_soc_2019_code"] for o in entry["onet_soc_2019_occupations"]]
        for soc, entry in data["by_soc_2018_code"].items()
    }


# ---------------------------------------------------------------------------
# Stage 1: classify job title → candidate DOGs
# ---------------------------------------------------------------------------

def classify_titles_batch(
    titles: list[str],
    model,
    dog_soc_codes: list[str],
    dog_matrix: np.ndarray,
    top_n: int,
) -> dict[str, list[tuple[str, float]]]:
    """
    Encode all unique titles at once; return {title: [(soc_code, score), ...]}.
    """
    vecs = model.encode(
        titles,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype("float32")

    result: dict[str, list[tuple[str, float]]] = {}
    for title, vec in zip(titles, vecs):
        scores = dog_matrix @ vec
        top_idx = np.argpartition(scores, -top_n)[-top_n:]
        top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
        result[title] = [(dog_soc_codes[i], round(float(scores[i]), 4)) for i in top_idx]
    return result


# ---------------------------------------------------------------------------
# Stage 2: filter task matrix to candidate DOGs, then top-K match
# ---------------------------------------------------------------------------

def build_filtered_subset(
    candidate_soc_codes: list[str],
    crosswalk: dict[str, list[str]],
    all_candidates: list[dict],
    all_matrix: np.ndarray,
) -> tuple[list[dict], np.ndarray]:
    allowed: set[str] = set()
    for soc in candidate_soc_codes:
        allowed.update(crosswalk.get(soc, []))

    indices = [i for i, c in enumerate(all_candidates) if c["onet_soc_code"] in allowed]
    if not indices:
        return [], np.empty((0, all_matrix.shape[1]), dtype="float32")
    return [all_candidates[i] for i in indices], all_matrix[np.array(indices)]


def top_k_from_matrix(
    query_vec: np.ndarray,
    candidates: list[dict],
    matrix: np.ndarray,
    top_k: int,
) -> list[dict]:
    if not candidates:
        return []
    scores = matrix @ query_vec
    actual_k = min(top_k, len(candidates))
    top_idx = np.argpartition(scores, -actual_k)[-actual_k:]
    top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
    return [
        {
            "rank": rank + 1,
            "score": round(float(scores[i]), 6),
            "task_id": candidates[i]["task_id"],
            "task": candidates[i]["task"],
            "onet_soc_code": candidates[i]["onet_soc_code"],
            "onet_soc_title": candidates[i]["onet_soc_title"],
            "embedding_key": candidates[i]["embedding_key"],
        }
        for rank, i in enumerate(top_idx)
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("Error: pip install sentence-transformers numpy", file=sys.stderr)
        sys.exit(1)

    for path, label in [
        (args.input_jsonl, "--input-jsonl"),
        (args.task_embeddings, "--task-embeddings"),
        (args.dog_embeddings, "--dog-embeddings"),
        (args.crosswalk, "--crosswalk"),
    ]:
        if not path.exists():
            print(f"Error: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    print("Loading job postings...", flush=True)
    postings = load_job_postings(args.input_jsonl)
    print(f"  {len(postings)} posting items")

    print("Loading task embedding library...", flush=True)
    task_data, all_candidates, all_matrix = load_task_library(args.task_embeddings)
    model_name = task_data.get("model_name", DEFAULT_TASK_EMB.stem)
    print(f"  {len(all_candidates)} task candidates, matrix {all_matrix.shape}")

    print("Loading DOG title embeddings...", flush=True)
    dog_soc_codes, dog_matrix = load_dog_embeddings(args.dog_embeddings)
    print(f"  {len(dog_soc_codes)} DOGs")

    print("Loading crosswalk...", flush=True)
    crosswalk = load_crosswalk(args.crosswalk)

    print(f"Loading model: {model_name}", flush=True)
    model = SentenceTransformer(model_name, device=args.device)

    # Stage 1: classify all unique job titles at once
    unique_titles = list({p.get("title", "") for p in postings if p.get("title")})
    print(f"Stage 1: classifying {len(unique_titles)} unique job titles → top-{args.top_n_dogs} DOGs...", flush=True)
    title_to_dogs = classify_titles_batch(unique_titles, model, dog_soc_codes, dog_matrix, args.top_n_dogs)

    # Stage 2: encode all posting texts, then per-item filtered matching
    print(f"Encoding {len(postings)} posting texts...", flush=True)
    texts = [p["text"] for p in postings]
    text_vecs = model.encode(
        texts,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    ).astype("float32")

    print("Stage 2: running filtered task matching...", flush=True)
    results: list[dict] = []
    # Cache filtered subsets per unique title to avoid rebuilding for every item
    filtered_cache: dict[str, tuple[list[dict], np.ndarray]] = {}

    for posting, vec in zip(postings, text_vecs):
        job_title = posting.get("title", "")
        dog_candidates = title_to_dogs.get(job_title, [])
        candidate_soc_codes = [code for code, _ in dog_candidates]

        cache_key = "|".join(sorted(candidate_soc_codes))
        if cache_key not in filtered_cache:
            filtered_cache[cache_key] = build_filtered_subset(
                candidate_soc_codes, crosswalk, all_candidates, all_matrix
            )
        filtered_candidates, filtered_matrix = filtered_cache[cache_key]

        matches = top_k_from_matrix(vec, filtered_candidates, filtered_matrix, args.top_k)
        results.append(
            {
                **posting,
                "stage1_dog_candidates": [
                    {"soc_2018_code": c, "score": s} for c, s in dog_candidates
                ],
                "top_task_matches": matches,
            }
        )

    payload = {
        "input_jsonl_path": str(args.input_jsonl),
        "task_embedding_json": str(args.task_embeddings),
        "dog_embedding_json": str(args.dog_embeddings),
        "crosswalk_json": str(args.crosswalk),
        "model_name": model_name,
        "top_k": args.top_k,
        "top_n_dogs": args.top_n_dogs,
        "item_count": len(results),
        "results": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Done. {len(results)} results saved to: {args.output}")


if __name__ == "__main__":
    main()
