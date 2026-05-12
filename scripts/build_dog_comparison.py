#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "snippet_jsonl": REPO_ROOT / "jobPostings" / "ai_linkedin_results_itemized_for_embeddings.jsonl",
    "task_embeddings": REPO_ROOT / "scripts" / "task_dwa_embeddings_all_mpnet_base_v2.json",
    "tasks_json": REPO_ROOT / "scripts" / "tasks_to_dwas.json",
    "crosswalk": REPO_ROOT / "scripts" / "soc2018_to_onet2019_crosswalk.json",
}


def sha256_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_task_library(crosswalk_path, tasks_json_path, soc_2018_code, embeddings_by_key):
    with open(crosswalk_path) as f:
        crosswalk = json.load(f)

    entry = crosswalk["by_soc_2018_code"].get(soc_2018_code)
    if not entry:
        print(f"ERROR: SOC 2018 code '{soc_2018_code}' not found in crosswalk.", file=sys.stderr)
        sys.exit(1)

    onet_codes = [o["onet_soc_2019_code"] for o in entry["onet_soc_2019_occupations"]]
    print(f"  SOC {soc_2018_code} → {len(onet_codes)} O*NET-SOC 2019 code(s): {onet_codes}")

    with open(tasks_json_path) as f:
        tasks_db = json.load(f)["by_onet_soc_code"]

    seen_task_ids = set()
    tasks = []
    for onet_code in onet_codes:
        onet_entry = tasks_db.get(onet_code)
        if not onet_entry:
            print(f"  WARNING: O*NET code {onet_code} not in tasks_to_dwas.json")
            continue
        for task in onet_entry.get("tasks", []):
            task_id = task["task_id"]
            if task_id in seen_task_ids:
                continue
            seen_task_ids.add(task_id)

            emb_key = sha256_key(task["task"])
            emb_entry = embeddings_by_key.get(emb_key)
            if emb_entry is None:
                print(f"  WARNING: no embedding for task {task_id}: {task['task'][:60]}")

            tasks.append({
                "task_id": task_id,
                "task": task["task"],
                "onet_soc_codes": [onet_code],
                "dwas": task.get("dwas", []),
                "embedding_key": emb_key,
                "_embedding": emb_entry["embedding"] if emb_entry else None,
            })

    return tasks


def load_snippets(jsonl_path, title_substring):
    snippets_by_posting = defaultdict(list)
    total = 0
    matched = 0
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            record = json.loads(line)
            if title_substring.lower() in record.get("title", "").lower():
                matched += 1
                snippets_by_posting[record["job_key"]].append(record)

    print(f"  {matched}/{total} snippets match title '{title_substring}' across {len(snippets_by_posting)} posting(s)")
    return snippets_by_posting


def embed_snippets(snippets_by_posting, model_name):
    model = SentenceTransformer(model_name)
    all_snippets = [s for ss in snippets_by_posting.values() for s in ss]
    texts = [s.get("text", "") for s in all_snippets]

    print(f"  Embedding {len(texts)} snippets with {model_name}...")
    t0 = time.time()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=True, batch_size=64)
    print(f"  Done in {time.time() - t0:.1f}s")

    for snippet, vec in zip(all_snippets, vecs):
        snippet["_embedding"] = vec.tolist()

    return snippets_by_posting


def compute_scores(snippets_by_posting, tasks):
    valid_indices = [i for i, t in enumerate(tasks) if t["_embedding"] is not None]
    task_matrix = np.array([tasks[i]["_embedding"] for i in valid_indices], dtype=np.float32)

    postings = {}
    for job_key, snippets in snippets_by_posting.items():
        snippet_records = []
        for s in snippets:
            emb = s.get("_embedding")
            if emb is not None and len(valid_indices) > 0:
                sims = task_matrix @ np.array(emb, dtype=np.float32)
                order = np.argsort(-sims)
                task_scores = [
                    {"task_id": tasks[valid_indices[local_i]]["task_id"],
                     "rank": rank + 1,
                     "score": float(sims[local_i])}
                    for rank, local_i in enumerate(order)
                ]
            else:
                task_scores = []

            snippet_records.append({
                "id": s["id"],
                "job_key": s["job_key"],
                "job_name": s.get("job_name", ""),
                "company": s.get("company", ""),
                "title": s.get("title", ""),
                "category": s.get("category", ""),
                "text": s.get("text", ""),
                "is_fluff": False,
                "relevance_score": None,
                "task_scores": task_scores,
            })

        first = snippets[0]
        postings[job_key] = {
            "job_key": job_key,
            "job_name": first.get("job_name", ""),
            "company": first.get("company", ""),
            "title": first.get("title", ""),
            "snippet_count": len(snippets),
            "snippets": snippet_records,
        }

    return postings


def main():
    parser = argparse.ArgumentParser(description="Build per-DOG snippet-vs-task comparison JSON.")
    parser.add_argument("--snippet-jsonl", default=str(DEFAULTS["snippet_jsonl"]))
    parser.add_argument("--job-title-substring", required=True,
                        help="Case-insensitive substring matched against snippet 'title' field")
    parser.add_argument("--soc-2018-code", required=True,
                        help="Target SOC 2018 detailed occupation code, e.g. 15-1212")
    parser.add_argument("--task-embeddings", default=str(DEFAULTS["task_embeddings"]))
    parser.add_argument("--tasks-json", default=str(DEFAULTS["tasks_json"]))
    parser.add_argument("--crosswalk", default=str(DEFAULTS["crosswalk"]))
    parser.add_argument("--relevance-bundle", default=None,
                        help="(Optional) path to relevance bundle for fluff scoring — skipped if absent")
    parser.add_argument("--out", default=None,
                        help="Output path (default: annotations/dog_comparison_<soc>_<slug>.json)")
    args = parser.parse_args()

    slug = re.sub(r"[^a-z0-9]+", "-", args.job_title_substring.lower()).strip("-")
    if args.out is None:
        out_dir = REPO_ROOT / "annotations"
        out_dir.mkdir(exist_ok=True)
        args.out = str(out_dir / f"dog_comparison_{args.soc_2018_code}_{slug}.json")

    print(f"\n=== build_dog_comparison ===")
    print(f"  SOC 2018 code  : {args.soc_2018_code}")
    print(f"  Title filter   : '{args.job_title_substring}'")
    print(f"  Output         : {args.out}")

    print("\n[1/4] Loading task embeddings...")
    with open(args.task_embeddings) as f:
        emb_data = json.load(f)
    embeddings_by_key = emb_data["embeddings_by_key"]
    model_name = emb_data.get("model_name", "sentence-transformers/all-mpnet-base-v2")
    print(f"  {len(embeddings_by_key):,} unique embedded texts | model: {model_name}")

    print("\n[2/4] Building DOG task library...")
    tasks = load_task_library(args.crosswalk, args.tasks_json, args.soc_2018_code, embeddings_by_key)
    tasks_with_emb = sum(1 for t in tasks if t["_embedding"] is not None)
    print(f"  {len(tasks)} unique tasks | {tasks_with_emb} have embeddings")

    if not tasks:
        print("ERROR: No tasks found for this DOG. Exiting.", file=sys.stderr)
        sys.exit(1)

    print("\n[3/4] Loading and filtering snippets...")
    snippets_by_posting = load_snippets(args.snippet_jsonl, args.job_title_substring)
    if not snippets_by_posting:
        print("ERROR: No snippets matched. Check --job-title-substring.", file=sys.stderr)
        sys.exit(1)

    print("\n[4/4] Embedding snippets...")
    snippets_by_posting = embed_snippets(snippets_by_posting, model_name)

    print("\nComputing cosine similarities...")
    postings = compute_scores(snippets_by_posting, tasks)

    tasks_out = [{k: v for k, v in t.items() if k != "_embedding"} for t in tasks]

    output = {
        "meta": {
            "soc_2018_code": args.soc_2018_code,
            "job_title_substring": args.job_title_substring,
            "snippet_jsonl": args.snippet_jsonl,
            "model_name": model_name,
            "task_count": len(tasks),
            "tasks_with_embeddings": tasks_with_emb,
            "posting_count": len(postings),
            "total_snippets": sum(p["snippet_count"] for p in postings.values()),
        },
        "tasks": tasks_out,
        "postings": postings,
    }

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote: {args.out}")
    print(f"  {len(tasks)} tasks | {len(postings)} postings | {output['meta']['total_snippets']} snippets total")


if __name__ == "__main__":
    main()
