#!/usr/bin/env python3
"""
Pipeline orchestrator for job posting -> O*NET task matching experiments.

Runs the full pipeline sequentially and records a scored result to
jobPostings/scoring_history.json for cross-run comparison.

Pipeline steps:
  1. Build DOG title embeddings
  2. Optionally filter obvious boilerplate snippets
  3. Score snippets with the portable relevance bundle
  4. Run two-stage task matching
  5. Score results and append to history
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

DEFAULT_INPUT_JSONL = REPO_ROOT / "jobPostings" / "linkedin_job_search_results_itemized_for_embeddings.jsonl"
DEFAULT_TASK_EMB = REPO_ROOT / "scripts" / "task_dwa_embeddings_all_mpnet_base_v2.json"
DEFAULT_DOG_EMB = REPO_ROOT / "scripts" / "dog_title_embeddings_all_mpnet_base_v2.json"
DEFAULT_CROSSWALK = REPO_ROOT / "scripts" / "soc2018_to_onet2019_crosswalk.json"
DEFAULT_HISTORY = REPO_ROOT / "jobPostings" / "scoring_history.json"
DEFAULT_RELEVANCE_BUNDLE_DIR = REPO_ROOT / "scripts" / "relevance_bundles"


BOILERPLATE_PATTERNS = [
    r"open until filled",
    r"applications?\s+(will be|may be|are)\s+(reviewed|accepted|obtained)",
    r"apply\s+online\s+at",
    r"equal\s+opportunity\s+(employer|employment)",
    r"affirmative\s+action",
    r"diversity\s+and\s+inclusion",
    r"strives?\s+for\s+diversity",
    r"standard\s+work\s+week",
    r"\bEEOC\b",
    r"reasonable\s+accommodation",
    r"human\s+resources\s+(department|office|director)?",
    r"veterans?\s+(preference|status)",
    r"background\s+check\s+required",
    r"drug\s+(test|screen)",
]

BOILERPLATE_RE = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)
MIN_WORD_COUNT = 5


def default_bundle_path() -> Path:
    latest_pointer = DEFAULT_RELEVANCE_BUNDLE_DIR / "LATEST.txt"
    if latest_pointer.exists():
        bundle_name = latest_pointer.read_text(encoding="utf-8").strip()
        if bundle_name:
            return DEFAULT_RELEVANCE_BUNDLE_DIR / bundle_name
    return DEFAULT_RELEVANCE_BUNDLE_DIR / "job_snippet_relevance_20260510T174010Z"


def is_boilerplate(text: str) -> bool:
    if len(text.split()) < MIN_WORD_COUNT:
        return True
    return bool(BOILERPLATE_RE.search(text))


def filter_boilerplate(jsonl_path: Path, output_path: Path) -> tuple[int, int]:
    total = 0
    kept = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open(encoding="utf-8") as input_handle, output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as output_handle:
        for line in input_handle:
            line = line.strip()
            if not line:
                continue
            total += 1
            item = json.loads(line)
            if not is_boilerplate(item.get("text", "")):
                output_handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True))
                output_handle.write("\n")
                kept += 1
    return total, kept


def count_jsonl_rows(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orchestrate relevance scoring, task matching, and run scoring.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--run-name", required=True, help="Label recorded in scoring history.")

    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT_JSONL)
    parser.add_argument("--task-embeddings", type=Path, default=DEFAULT_TASK_EMB)
    parser.add_argument("--dog-embeddings", type=Path, default=DEFAULT_DOG_EMB)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)

    parser.add_argument(
        "--skip-dog-embeddings",
        action="store_true",
        help="Skip building DOG embeddings if the file already exists.",
    )
    parser.add_argument(
        "--score-only",
        type=Path,
        default=None,
        metavar="MATCH_JSON",
        help="Skip pipeline steps; just score an existing match JSON.",
    )

    parser.add_argument(
        "--strip-boilerplate",
        action="store_true",
        help="Remove obvious HR/admin boilerplate items before relevance scoring.",
    )
    parser.add_argument(
        "--relevance-mode",
        choices=["off", "score", "skip", "drop"],
        default="skip",
        help=(
            "Relevance handling before matching: off=no scoring, score=annotate rows only, "
            "skip=score and have the matcher skip not_relevant rows, "
            "drop=write a filtered JSONL before matching (default: skip)."
        ),
    )
    parser.add_argument(
        "--relevance-bundle",
        type=Path,
        default=default_bundle_path(),
        help="Path to the exported relevance scorer bundle.",
    )
    parser.add_argument(
        "--relevance-confidence",
        type=float,
        default=0.75,
        help="Minimum confidence for not_relevant rows to skip/drop.",
    )
    parser.add_argument(
        "--relevance-output-jsonl",
        type=Path,
        default=None,
        help="Optional path for the scored/filtered intermediate JSONL.",
    )
    parser.add_argument(
        "--reuse-relevance-scores",
        action="store_true",
        help="Reuse --relevance-output-jsonl if it already exists.",
    )
    parser.add_argument("--relevance-batch-size", type=int, default=32)
    parser.add_argument("--relevance-chunk-size", type=int, default=128)

    parser.add_argument(
        "--stage1-text-mode",
        choices=["title", "title_company"],
        default="title",
        help="Text used for stage-1 DOG classification.",
    )
    parser.add_argument("--top-n-dogs", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", type=str, default=None)

    parser.add_argument("--chart", action="store_true", help="Generate comparison chart after scoring.")
    parser.add_argument(
        "--chart-output",
        type=Path,
        default=None,
        help="Save chart to file instead of displaying interactively.",
    )
    return parser.parse_args()


def safe_run_name(run_name: str) -> str:
    return re.sub(r"[^\w\-]", "_", run_name)


def run_step(label: str, command: list[str]) -> None:
    print(f"\n{'=' * 70}", flush=True)
    print(f"  STEP: {label}", flush=True)
    print(f"  CMD : {' '.join(str(part) for part in command)}", flush=True)
    print(f"{'=' * 70}\n", flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(f"\nError: step '{label}' exited with code {result.returncode}.", file=sys.stderr)
        sys.exit(result.returncode)


def step_build_dog_embeddings(
    dog_embeddings: Path,
    skip_if_exists: bool,
    device: str | None,
) -> None:
    if skip_if_exists and dog_embeddings.exists():
        print(f"\n[skip] DOG embeddings already exist: {dog_embeddings}")
        return
    command = [
        sys.executable,
        str(SCRIPTS / "build_dog_title_embeddings.py"),
        "--output",
        str(dog_embeddings),
    ]
    if device:
        command += ["--device", device]
    run_step(
        "Build DOG title embeddings",
        command,
    )


def step_filter_boilerplate(input_jsonl: Path, safe_name: str) -> tuple[Path, dict]:
    output = REPO_ROOT / "jobPostings" / f"{safe_name}_no_boilerplate.jsonl"
    print(f"\n{'=' * 70}")
    print("  STEP: Filter boilerplate")
    print(f"{'=' * 70}")
    total, kept = filter_boilerplate(input_jsonl, output)
    dropped = total - kept
    pct = 100 * dropped / total if total else 0.0
    print(f"  Read   : {total} items")
    print(f"  Kept   : {kept} items")
    print(f"  Dropped: {dropped} items ({pct:.1f}% boilerplate)")
    print(f"  Output : {output}")
    return output, {
        "input_jsonl": str(input_jsonl),
        "output_jsonl": str(output),
        "input_item_count": total,
        "kept_item_count": kept,
        "dropped_item_count": dropped,
    }


def default_relevance_output(safe_name: str, mode: str) -> Path:
    suffix = "filtered" if mode == "drop" else "scored"
    return REPO_ROOT / "jobPostings" / f"{safe_name}_relevance_{suffix}.jsonl"


def step_score_relevance(
    *,
    input_jsonl: Path,
    output_jsonl: Path,
    bundle: Path,
    mode: str,
    confidence: float,
    batch_size: int,
    chunk_size: int,
    device: str | None,
    reuse_existing: bool,
) -> tuple[Path, dict]:
    if reuse_existing and output_jsonl.exists():
        input_count = count_jsonl_rows(input_jsonl)
        output_count = count_jsonl_rows(output_jsonl)
        print(f"\n[skip] Reusing relevance output: {output_jsonl}")
        return output_jsonl, {
            "mode": mode,
            "bundle": str(bundle),
            "input_jsonl": str(input_jsonl),
            "output_jsonl": str(output_jsonl),
            "confidence": confidence,
            "input_item_count": input_count,
            "written_item_count": output_count,
            "reused_existing_output": True,
        }

    command = [
        sys.executable,
        str(SCRIPTS / "score_job_posting_relevance.py"),
        "--bundle",
        str(bundle),
        "--input-jsonl",
        str(input_jsonl),
        "--output-jsonl",
        str(output_jsonl),
        "--batch-size",
        str(batch_size),
        "--chunk-size",
        str(chunk_size),
    ]
    if device:
        command += ["--device", device]
    if mode == "drop":
        command += ["--drop-not-relevant", "--drop-confidence", str(confidence)]

    run_step("Score relevance", command)

    return output_jsonl, {
        "mode": mode,
        "bundle": str(bundle),
        "input_jsonl": str(input_jsonl),
        "output_jsonl": str(output_jsonl),
        "confidence": confidence,
        "input_item_count": count_jsonl_rows(input_jsonl),
        "written_item_count": count_jsonl_rows(output_jsonl),
        "reused_existing_output": False,
    }


def step_two_stage_match(
    *,
    input_jsonl: Path,
    output_json: Path,
    task_embeddings: Path,
    dog_embeddings: Path,
    crosswalk: Path,
    stage1_text_mode: str,
    top_n_dogs: int,
    top_k: int,
    batch_size: int,
    device: str | None,
    skip_not_relevant: bool,
    skip_confidence: float,
) -> None:
    command = [
        sys.executable,
        str(SCRIPTS / "match_job_postings_two_stage.py"),
        "--input-jsonl",
        str(input_jsonl),
        "--task-embeddings",
        str(task_embeddings),
        "--dog-embeddings",
        str(dog_embeddings),
        "--crosswalk",
        str(crosswalk),
        "--output",
        str(output_json),
        "--stage1-text-mode",
        stage1_text_mode,
        "--top-n-dogs",
        str(top_n_dogs),
        "--top-k",
        str(top_k),
        "--batch-size",
        str(batch_size),
    ]
    if device:
        command += ["--device", device]
    if skip_not_relevant:
        command += ["--skip-not-relevant", "--skip-confidence", str(skip_confidence)]

    run_step("Two-stage task matching", command)


def stamp_match_metadata(
    *,
    output_json: Path,
    run_name: str,
    boilerplate_stripped: bool,
    boilerplate_pipeline: dict | None,
    relevance_pipeline: dict,
) -> None:
    if not output_json.exists():
        return
    with output_json.open(encoding="utf-8") as handle:
        data = json.load(handle)
    data["pipeline_run_name"] = run_name
    data["boilerplate_stripped"] = boilerplate_stripped
    data["boilerplate_pipeline"] = boilerplate_pipeline
    data["relevance_pipeline"] = relevance_pipeline
    with output_json.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def step_score(
    *,
    run_name: str,
    match_json: Path,
    history: Path,
    chart: bool,
    chart_output: Path | None,
) -> None:
    command = [
        sys.executable,
        str(SCRIPTS / "score_match_results.py"),
        "--input",
        str(match_json),
        "--run-name",
        run_name,
        "--history",
        str(history),
    ]
    if chart:
        command.append("--chart")
    if chart_output:
        command += ["--chart-output", str(chart_output)]
    run_step("Score results + update history", command)


def validate_input_files(args: argparse.Namespace) -> None:
    required = [
        (args.input_jsonl, "--input-jsonl"),
        (args.task_embeddings, "--task-embeddings"),
        (args.crosswalk, "--crosswalk"),
    ]
    if args.skip_dog_embeddings:
        required.append((args.dog_embeddings, "--dog-embeddings"))
    if args.relevance_mode != "off":
        required.append((args.relevance_bundle, "--relevance-bundle"))

    for path, label in required:
        if not path.exists():
            print(f"Error: {label} not found: {path}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    args = parse_args()
    safe_name = safe_run_name(args.run_name)

    if args.score_only:
        if not args.score_only.exists():
            print(f"Error: file not found: {args.score_only}", file=sys.stderr)
            sys.exit(1)
        step_score(
            run_name=args.run_name,
            match_json=args.score_only,
            history=args.history,
            chart=args.chart,
            chart_output=args.chart_output,
        )
        return

    validate_input_files(args)

    output_json = REPO_ROOT / "jobPostings" / f"{safe_name}_top{args.top_k}_task_matches.json"
    relevance_output = args.relevance_output_jsonl or default_relevance_output(
        safe_name,
        args.relevance_mode,
    )

    print(f"\nPipeline run: {args.run_name}")
    print(f"  strip_boilerplate  : {args.strip_boilerplate}")
    print(f"  relevance_mode     : {args.relevance_mode}")
    print(f"  relevance_conf     : {args.relevance_confidence}")
    print(f"  stage1_text_mode   : {args.stage1_text_mode}")
    print(f"  top_n_dogs         : {args.top_n_dogs}")
    print(f"  top_k              : {args.top_k}")
    print(f"  output             : {output_json}")

    step_build_dog_embeddings(
        args.dog_embeddings,
        skip_if_exists=args.skip_dog_embeddings,
        device=args.device,
    )

    input_jsonl = args.input_jsonl
    boilerplate_pipeline = None
    if args.strip_boilerplate:
        input_jsonl, boilerplate_pipeline = step_filter_boilerplate(input_jsonl, safe_name)

    relevance_pipeline = {
        "mode": "off",
        "input_jsonl": str(input_jsonl),
        "output_jsonl": str(input_jsonl),
        "confidence": None,
    }
    if args.relevance_mode != "off":
        input_jsonl, relevance_pipeline = step_score_relevance(
            input_jsonl=input_jsonl,
            output_jsonl=relevance_output,
            bundle=args.relevance_bundle,
            mode=args.relevance_mode,
            confidence=args.relevance_confidence,
            batch_size=args.relevance_batch_size,
            chunk_size=args.relevance_chunk_size,
            device=args.device,
            reuse_existing=args.reuse_relevance_scores,
        )

    step_two_stage_match(
        input_jsonl=input_jsonl,
        output_json=output_json,
        task_embeddings=args.task_embeddings,
        dog_embeddings=args.dog_embeddings,
        crosswalk=args.crosswalk,
        stage1_text_mode=args.stage1_text_mode,
        top_n_dogs=args.top_n_dogs,
        top_k=args.top_k,
        batch_size=args.batch_size,
        device=args.device,
        skip_not_relevant=args.relevance_mode == "skip",
        skip_confidence=args.relevance_confidence,
    )

    stamp_match_metadata(
        output_json=output_json,
        run_name=args.run_name,
        boilerplate_stripped=args.strip_boilerplate,
        boilerplate_pipeline=boilerplate_pipeline,
        relevance_pipeline=relevance_pipeline,
    )

    step_score(
        run_name=args.run_name,
        match_json=output_json,
        history=args.history,
        chart=args.chart,
        chart_output=args.chart_output,
    )

    print(f"\nDone. Run '{args.run_name}' complete.")
    print(f"  Match results  : {output_json}")
    print(f"  Scoring history: {args.history}")
    print("\nTo compare all runs:")
    print("  python scripts/score_match_results.py --chart-only --chart-output jobPostings/pipeline_comparison.png")


if __name__ == "__main__":
    main()
