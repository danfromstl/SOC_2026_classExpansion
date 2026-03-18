#!/usr/bin/env python3
"""Build deduplicated task and DWA embeddings with all-mpnet-base-v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASKS_JSON_PATH = Path(__file__).resolve().with_name("tasks_to_dwas.json")
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().with_name("task_dwa_embeddings_all_mpnet_base_v2.json")
DEFAULT_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deduplicated task and DWA embeddings with all-mpnet-base-v2."
    )
    parser.add_argument(
        "--tasks-json",
        type=Path,
        default=DEFAULT_TASKS_JSON_PATH,
        help=f"Path to tasks_to_dwas.json. Defaults to {DEFAULT_TASKS_JSON_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the embedding JSON. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_NAME,
        help=f"Sentence Transformers model name. Defaults to {DEFAULT_MODEL_NAME}",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Batch size for embedding generation. Defaults to 64.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Optional torch device string such as cpu, cuda, or cuda:0.",
    )
    parser.add_argument(
        "--round-decimals",
        type=int,
        default=6,
        help="Number of decimal places to keep in the JSON embedding vectors. Defaults to 6.",
    )
    return parser.parse_args()


def load_tasks_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(
            f"Tasks to DWAs JSON not found: {path}. Run scripts/build_tasks_to_dwas.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def repo_relative_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def embedding_key_for_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_embedding_payload(
    tasks_data: dict[str, object],
    model_name: str,
    batch_size: int,
    device: str | None,
    round_decimals: int,
) -> dict[str, object]:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - import guard for runtime dependency
        raise RuntimeError(
            "sentence_transformers is required to build embeddings. "
            "Install it before running this script."
        ) from exc

    by_onet_soc_code = tasks_data.get("by_onet_soc_code", {})
    if not isinstance(by_onet_soc_code, dict):
        raise ValueError("tasks_to_dwas.json is missing a valid by_onet_soc_code section.")

    embedding_entries: dict[str, dict[str, object]] = {}
    task_text_occurrences = 0
    dwa_text_occurrences = 0
    unique_task_texts: set[str] = set()
    unique_dwa_titles: set[str] = set()

    grouped_output: dict[str, dict[str, object]] = {}
    for onet_soc_code, onet_entry in by_onet_soc_code.items():
        if not isinstance(onet_entry, dict):
            continue

        title = str(onet_entry.get("title", ""))
        tasks = onet_entry.get("tasks", [])
        if not isinstance(tasks, list):
            continue

        grouped_tasks = []
        for task in tasks:
            if not isinstance(task, dict):
                continue

            task_text = str(task.get("task", ""))
            task_id = str(task.get("task_id", ""))
            task_dates = list(task.get("dates", [])) if isinstance(task.get("dates", []), list) else []
            task_domain_sources = (
                list(task.get("domain_sources", []))
                if isinstance(task.get("domain_sources", []), list)
                else []
            )

            task_key = embedding_key_for_text(task_text)
            task_entry = embedding_entries.setdefault(
                task_key,
                {
                    "text": task_text,
                    "text_types": set(),
                    "occurrence_count": 0,
                },
            )
            text_types = task_entry["text_types"]
            if not isinstance(text_types, set):  # pragma: no cover - defensive typing
                raise TypeError("Expected set for text_types")
            text_types.add("task")
            task_entry["occurrence_count"] = int(task_entry["occurrence_count"]) + 1
            task_text_occurrences += 1
            unique_task_texts.add(task_text)

            grouped_dwas = []
            dwas = task.get("dwas", [])
            if not isinstance(dwas, list):
                dwas = []
            for dwa in dwas:
                if not isinstance(dwa, dict):
                    continue

                dwa_id = str(dwa.get("dwa_id", ""))
                dwa_title = str(dwa.get("dwa_title", ""))
                dwa_key = embedding_key_for_text(dwa_title)

                dwa_entry = embedding_entries.setdefault(
                    dwa_key,
                    {
                        "text": dwa_title,
                        "text_types": set(),
                        "occurrence_count": 0,
                    },
                )
                dwa_text_types = dwa_entry["text_types"]
                if not isinstance(dwa_text_types, set):  # pragma: no cover - defensive typing
                    raise TypeError("Expected set for text_types")
                dwa_text_types.add("dwa")
                dwa_entry["occurrence_count"] = int(dwa_entry["occurrence_count"]) + 1
                dwa_text_occurrences += 1
                unique_dwa_titles.add(dwa_title)

                grouped_dwas.append(
                    {
                        "dwa_id": dwa_id,
                        "dwa_title": dwa_title,
                        "embedding_key": dwa_key,
                    }
                )

            grouped_tasks.append(
                {
                    "task_id": task_id,
                    "task": task_text,
                    "task_embedding_key": task_key,
                    "dates": task_dates,
                    "domain_sources": task_domain_sources,
                    "dwas": grouped_dwas,
                }
            )

        grouped_output[str(onet_soc_code)] = {
            "onet_soc_code": str(onet_soc_code),
            "title": title,
            "task_count": len(grouped_tasks),
            "tasks": grouped_tasks,
        }

    ordered_keys = list(embedding_entries.keys())
    ordered_texts = [str(embedding_entries[key]["text"]) for key in ordered_keys]

    model_kwargs = {}
    if device:
        model_kwargs["device"] = device
    model = SentenceTransformer(model_name, **model_kwargs)
    embeddings = model.encode(
        ordered_texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    embeddings_by_key: dict[str, dict[str, object]] = {}
    embedding_dimension = 0
    for index, key in enumerate(ordered_keys):
        vector = embeddings[index].tolist()
        if round_decimals >= 0:
            vector = [round(float(value), round_decimals) for value in vector]
        else:
            vector = [float(value) for value in vector]
        embedding_dimension = len(vector)

        text_types = embedding_entries[key]["text_types"]
        if not isinstance(text_types, set):  # pragma: no cover - defensive typing
            raise TypeError("Expected set for text_types")
        embeddings_by_key[key] = {
            "text": str(embedding_entries[key]["text"]),
            "text_types": sorted(text_types),
            "occurrence_count": int(embedding_entries[key]["occurrence_count"]),
            "embedding": vector,
        }

    return {
        "source_tasks_json": repo_relative_label(Path(str(tasks_data.get("_source_path", ""))))
        if tasks_data.get("_source_path")
        else repo_relative_label(DEFAULT_TASKS_JSON_PATH),
        "model_name": model_name,
        "normalize_embeddings": True,
        "embedding_dimension": embedding_dimension,
        "counts": {
            "task_occurrences": task_text_occurrences,
            "unique_task_texts": len(unique_task_texts),
            "dwa_occurrences": dwa_text_occurrences,
            "unique_dwa_titles": len(unique_dwa_titles),
            "unique_texts_embedded": len(embeddings_by_key),
        },
        "embeddings_by_key": embeddings_by_key,
        "by_onet_soc_code": grouped_output,
    }


def main() -> int:
    args = parse_args()

    try:
        tasks_data = load_tasks_json(args.tasks_json)
        tasks_data["_source_path"] = str(args.tasks_json)
        payload = build_embedding_payload(
            tasks_data,
            model_name=args.model,
            batch_size=args.batch_size,
            device=args.device,
            round_decimals=args.round_decimals,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to build task/DWA embeddings JSON: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote task/DWA embeddings JSON to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
