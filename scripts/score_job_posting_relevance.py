#!/usr/bin/env python3
"""
Score itemized job-posting snippets with the reviewed relevance-filter bundle.

This is intended as the first pass before O*NET task matching:

  1. add a `relevance_filter` object to each JSONL row
  2. optionally drop high-confidence not-relevant rows
  3. feed the scored or filtered JSONL into match_job_postings_two_stage.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

from relevance_filter.score_jsonl import score_jsonl_file


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE_DIR = REPO_ROOT / "scripts" / "relevance_bundles"
DEFAULT_INPUT_JSONL = (
    REPO_ROOT / "jobPostings" / "linkedin_job_search_results_itemized_for_embeddings.jsonl"
)
DEFAULT_OUTPUT_JSONL = (
    REPO_ROOT / "jobPostings" / "linkedin_job_search_results_relevance_scored.jsonl"
)


def default_bundle_path() -> Path:
    latest_pointer = DEFAULT_BUNDLE_DIR / "LATEST.txt"
    if latest_pointer.exists():
        bundle_name = latest_pointer.read_text(encoding="utf-8").strip()
        if bundle_name:
            return DEFAULT_BUNDLE_DIR / bundle_name
    return DEFAULT_BUNDLE_DIR / "job_snippet_relevance_20260510T174010Z"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score job-posting JSONL rows for relevance before SOC/O*NET matching."
    )
    parser.add_argument("--bundle", type=Path, default=default_bundle_path())
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--chunk-size", type=int, default=128)
    parser.add_argument("--device", default=None, help="Torch device string, e.g. cuda or cpu.")
    parser.add_argument("--top-examples", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="Score only the first N rows.")
    parser.add_argument(
        "--drop-not-relevant",
        action="store_true",
        help="Write only rows whose relevance label is not 'not_relevant'.",
    )
    parser.add_argument(
        "--drop-confidence",
        type=float,
        default=0.0,
        help="When dropping, require label=not_relevant and confidence >= this value.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    processed, written = score_jsonl_file(
        bundle=args.bundle,
        input_jsonl=args.input_jsonl,
        output_jsonl=args.output_jsonl,
        batch_size=args.batch_size,
        chunk_size=args.chunk_size,
        device=args.device,
        top_examples=args.top_examples,
        limit=args.limit,
        drop_not_relevant=args.drop_not_relevant,
        drop_confidence=args.drop_confidence,
    )
    print(f"Done. Scored {processed} rows; wrote {written} rows to {args.output_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
