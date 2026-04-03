#!/usr/bin/env python3
"""Embed job posting items and retrieve the closest task matches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_JSONL = (
    REPO_ROOT / "jobPostings" / "job_postings_itemized_for_embeddings_firstTwoExamples.jsonl"
)
DEFAULT_EMBEDDINGS_JSON = (
    Path(__file__).resolve().with_name("task_dwa_embeddings_all_mpnet_base_v2.json")
)
DEFAULT_TOP_K = 5


def default_output_path(input_jsonl: Path, top_k: int) -> Path:
    return input_jsonl.with_name(f"{input_jsonl.stem}_top{top_k}_task_matches.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed job posting items and retrieve the closest task matches."
    )
    parser.add_argument(
        "--input-jsonl",
        type=Path,
        default=DEFAULT_INPUT_JSONL,
        help=f"Path to the job posting JSONL input. Defaults to {DEFAULT_INPUT_JSONL}",
    )
    parser.add_argument(
        "--embeddings-json",
        type=Path,
        default=DEFAULT_EMBEDDINGS_JSON,
        help=f"Path to the task embedding JSON. Defaults to {DEFAULT_EMBEDDINGS_JSON}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output JSON path. Defaults to a file next to the input JSONL.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Number of task matches to keep per posting item. Defaults to 5.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for embedding the job posting texts. Defaults to 32.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Optional torch device string such as cpu, cuda, or cuda:0.",
    )
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be at least 1.")
    return args


def load_json(path: Path, missing_message: str) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"{missing_message}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_job_postings(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Job posting JSONL not found: {path}")

    postings: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception as exc:
            raise ValueError(f"Invalid JSON on line {line_number} of {path}: {exc}") from exc

        if not isinstance(item, dict):
            raise ValueError(f"Expected JSON object on line {line_number} of {path}")

        item_id = item.get("id")
        text = item.get("text")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f"Missing or invalid id on line {line_number} of {path}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Missing or invalid text on line {line_number} of {path}")

        postings.append(item)

    if not postings:
        raise ValueError(f"No posting items were found in {path}")

    return postings


def load_task_embedding_library(path: Path) -> tuple[dict[str, object], list[dict[str, str]], np.ndarray]:
    data = load_json(
        path,
        "Task embedding JSON not found. Run scripts/build_task_dwa_embeddings.py first",
    )

    embeddings_by_key = data.get("embeddings_by_key", {})
    by_onet_soc_code = data.get("by_onet_soc_code", {})
    if not isinstance(embeddings_by_key, dict):
        raise ValueError("Embedding JSON is missing a valid embeddings_by_key section.")
    if not isinstance(by_onet_soc_code, dict):
        raise ValueError("Embedding JSON is missing a valid by_onet_soc_code section.")

    task_candidates: list[dict[str, str]] = []
    task_vectors: list[list[float]] = []

    for onet_soc_code, onet_entry in by_onet_soc_code.items():
        if not isinstance(onet_entry, dict):
            continue
        onet_title = str(onet_entry.get("title", ""))
        tasks = onet_entry.get("tasks", [])
        if not isinstance(tasks, list):
            continue

        for task in tasks:
            if not isinstance(task, dict):
                continue

            embedding_key = task.get("task_embedding_key")
            if not isinstance(embedding_key, str) or embedding_key not in embeddings_by_key:
                continue

            embedding_entry = embeddings_by_key[embedding_key]
            if not isinstance(embedding_entry, dict):
                continue
            vector = embedding_entry.get("embedding")
            if not isinstance(vector, list):
                continue

            task_candidates.append(
                {
                    "task_id": str(task.get("task_id", "")),
                    "task": str(task.get("task", "")),
                    "onet_soc_code": str(onet_soc_code),
                    "onet_soc_title": onet_title,
                    "embedding_key": embedding_key,
                }
            )
            task_vectors.append([float(value) for value in vector])

    if not task_candidates:
        raise ValueError("No task candidates were found in the embedding JSON.")

    task_matrix = np.asarray(task_vectors, dtype=np.float32)
    return data, task_candidates, task_matrix


def encode_texts(
    texts: list[str],
    model_name: str,
    batch_size: int,
    device: str | None,
) -> np.ndarray:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - import guard for runtime dependency
        raise RuntimeError(
            "sentence_transformers is required to embed job posting text."
        ) from exc

    model_kwargs = {}
    if device:
        model_kwargs["device"] = device
    model = SentenceTransformer(model_name, **model_kwargs)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return np.asarray(embeddings, dtype=np.float32)


def top_k_matches(
    query_vector: np.ndarray,
    task_candidates: list[dict[str, str]],
    task_matrix: np.ndarray,
    top_k: int,
) -> list[dict[str, object]]:
    scores = task_matrix @ query_vector
    k = min(top_k, len(task_candidates))
    top_indices = np.argpartition(scores, -k)[-k:]
    ordered_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

    matches: list[dict[str, object]] = []
    for rank, index in enumerate(ordered_indices, start=1):
        candidate = task_candidates[int(index)]
        matches.append(
            {
                "rank": rank,
                "score": round(float(scores[int(index)]), 6),
                "task_id": candidate["task_id"],
                "task": candidate["task"],
                "onet_soc_code": candidate["onet_soc_code"],
                "onet_soc_title": candidate["onet_soc_title"],
                "embedding_key": candidate["embedding_key"],
            }
        )
    return matches


def build_matches(
    postings: list[dict[str, object]],
    embedding_data: dict[str, object],
    task_candidates: list[dict[str, str]],
    task_matrix: np.ndarray,
    batch_size: int,
    device: str | None,
    top_k: int,
    input_jsonl_path: Path,
    embeddings_json_path: Path,
) -> dict[str, object]:
    model_name = str(embedding_data.get("model_name", "sentence-transformers/all-mpnet-base-v2"))
    texts = [str(posting["text"]) for posting in postings]
    query_embeddings = encode_texts(texts, model_name=model_name, batch_size=batch_size, device=device)

    results = []
    for posting, query_vector in zip(postings, query_embeddings):
        result_item = dict(posting)
        result_item["top_task_matches"] = top_k_matches(
            query_vector=query_vector,
            task_candidates=task_candidates,
            task_matrix=task_matrix,
            top_k=top_k,
        )
        results.append(result_item)

    return {
        "input_jsonl_path": str(input_jsonl_path),
        "task_embedding_json": str(embeddings_json_path),
        "model_name": model_name,
        "top_k": top_k,
        "item_count": len(results),
        "results": results,
    }


def main() -> int:
    args = parse_args()
    output_path = args.output or default_output_path(args.input_jsonl, args.top_k)

    try:
        postings = load_job_postings(args.input_jsonl)
        embedding_data, task_candidates, task_matrix = load_task_embedding_library(args.embeddings_json)
        payload = build_matches(
            postings=postings,
            embedding_data=embedding_data,
            task_candidates=task_candidates,
            task_matrix=task_matrix,
            batch_size=args.batch_size,
            device=args.device,
            top_k=args.top_k,
            input_jsonl_path=args.input_jsonl,
            embeddings_json_path=args.embeddings_json,
        )
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to match job postings to tasks: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote task match results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
