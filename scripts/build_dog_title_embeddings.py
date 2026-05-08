#!/usr/bin/env python3
"""
Build sentence embeddings for DOG (Detailed Occupational Group) title examples.

For each SOC 2018 Detailed group node in soc_2018_nested_groups.json, embeds:
  - The DOG name itself
  - All key_title_examples
  - All other_title_examples
  - First sentence of the DOG description (occupational context, within token budget)

Deduplicates texts by SHA-256 before encoding — same pattern as
build_task_dwa_embeddings.py — so shared title strings are encoded once.

Output is used by match_job_postings_two_stage.py: each job posting's title
field is embedded and compared against pooled DOG embeddings to select a
candidate shortlist of DOGs before task retrieval.

Usage:
  python scripts/build_dog_title_embeddings.py
  python scripts/build_dog_title_embeddings.py --model sentence-transformers/all-mpnet-base-v2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NESTED_GROUPS = REPO_ROOT / "scripts" / "soc_2018_nested_groups.json"
DEFAULT_MODEL = "sentence-transformers/all-mpnet-base-v2"
DEFAULT_OUTPUT = REPO_ROOT / "scripts" / "dog_title_embeddings_all_mpnet_base_v2.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build DOG title embeddings for two-stage job matching.")
    p.add_argument(
        "--nested-groups",
        type=Path,
        default=DEFAULT_NESTED_GROUPS,
        help="Path to soc_2018_nested_groups.json",
    )
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--model", type=str, default=DEFAULT_MODEL)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--device", type=str, default=None)
    p.add_argument("--round-decimals", type=int, default=6)
    return p.parse_args()


def embedding_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_detailed_nodes(nested_groups: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk the nested SOC hierarchy and return all Detailed-level group nodes."""
    detailed: list[dict] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            if node.get("group_type") == "Detailed":
                detailed.append(node)
            walk(node.get("children", []))

    walk(nested_groups.get("major_groups", []))
    return detailed


def build_dog_text_index(detailed_nodes: list[dict]) -> dict[str, dict[str, Any]]:
    """
    For each DOG, collect all representative texts with their roles.

    Text roles (in descending signal strength):
      name                    — official SOC DOG name
      key_title_example       — primary job title examples (BLS-designated)
      other_title_example     — alternative / common-usage titles
      description_first_sent  — first sentence of the occupational description
    """
    index: dict[str, dict] = {}
    for node in detailed_nodes:
        code = node["code"]
        texts: list[dict[str, str]] = []

        texts.append({"text": node["name"], "role": "name"})

        desc = (node.get("description") or "").strip()
        if desc:
            first_sent = desc.split(".")[0].strip()
            if first_sent:
                texts.append({"text": first_sent, "role": "description_first_sent"})

        for t in node.get("key_title_examples", []):
            if t:
                texts.append({"text": t, "role": "key_title_example"})
        for t in node.get("other_title_examples", []):
            if t:
                texts.append({"text": t, "role": "other_title_example"})

        for item in texts:
            item["embedding_key"] = embedding_key(item["text"])

        index[code] = {
            "code": code,
            "name": node["name"],
            "description": node.get("description", ""),
            "texts": texts,
        }
    return index


def build_payload(
    dog_index: dict[str, dict],
    model_name: str,
    batch_size: int,
    device: str | None,
    round_decimals: int,
    nested_groups_path: Path,
) -> dict[str, Any]:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("Error: install dependencies with:  pip install sentence-transformers numpy", file=sys.stderr)
        sys.exit(1)

    # Deduplicate all texts across all DOGs
    unique_texts: dict[str, str] = {}  # embedding_key -> text
    for dog_data in dog_index.values():
        for item in dog_data["texts"]:
            k = item["embedding_key"]
            if k not in unique_texts:
                unique_texts[k] = item["text"]

    print(f"  Unique texts to embed: {len(unique_texts)}", flush=True)

    keys_ordered = list(unique_texts.keys())
    texts_ordered = [unique_texts[k] for k in keys_ordered]

    print(f"  Loading model: {model_name}", flush=True)
    model = SentenceTransformer(model_name, device=device)
    vectors = model.encode(
        texts_ordered,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype("float32")

    embeddings_by_key = {
        k: {
            "text": unique_texts[k],
            "embedding": [round(float(v), round_decimals) for v in vectors[i]],
        }
        for i, k in enumerate(keys_ordered)
    }

    by_soc_2018_code = {
        code: {
            "soc_2018_code": code,
            "name": dog_data["name"],
            "description": dog_data["description"],
            "text_entries": [
                {
                    "text": item["text"],
                    "role": item["role"],
                    "embedding_key": item["embedding_key"],
                }
                for item in dog_data["texts"]
            ],
        }
        for code, dog_data in dog_index.items()
    }

    return {
        "source_nested_groups": str(nested_groups_path.relative_to(REPO_ROOT)),
        "model_name": model_name,
        "normalize_embeddings": True,
        "embedding_dimension": int(vectors.shape[1]),
        "counts": {
            "detailed_dogs": len(dog_index),
            "unique_texts_embedded": len(unique_texts),
        },
        "embeddings_by_key": embeddings_by_key,
        "by_soc_2018_code": by_soc_2018_code,
    }


def main() -> None:
    args = parse_args()

    print(f"Loading nested groups: {args.nested_groups}")
    with args.nested_groups.open(encoding="utf-8") as f:
        nested_groups = json.load(f)

    detailed_nodes = collect_detailed_nodes(nested_groups)
    print(f"Detailed DOG nodes: {len(detailed_nodes)}")

    dog_index = build_dog_text_index(detailed_nodes)
    total_texts = sum(len(d["texts"]) for d in dog_index.values())
    print(f"Total text entries (pre-dedup): {total_texts}")

    print("Building embeddings...")
    payload = build_payload(dog_index, args.model, args.batch_size, args.device, args.round_decimals, args.nested_groups)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Saved: {args.output}")
    print(f"  DOGs: {payload['counts']['detailed_dogs']}")
    print(f"  Unique embedded texts: {payload['counts']['unique_texts_embedded']}")


if __name__ == "__main__":
    main()
