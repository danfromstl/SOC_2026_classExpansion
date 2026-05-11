#!/usr/bin/env python3
"""
Structured scoring for job posting -> O*NET task match results.

Computes DOG alignment metrics for lineman postings, saves each run to a
persistent scoring history JSON, and optionally generates a comparison chart.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY = REPO_ROOT / "jobPostings" / "scoring_history.json"

ELECTRIC_CODE = "49-9051"
TELECOM_CODE = "49-9052"
EXPECTED_SOC = {ELECTRIC_CODE, TELECOM_CODE}
LINEMAN_KEYWORDS = {"lineman", "linemen", "lineworker", "line installer", "line worker"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score match results and record to history.")
    parser.add_argument("--input", type=Path, default=None, help="Match results JSON to score.")
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Label for this run in the history (required with --input).",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY,
        help="Path to scoring history JSON.",
    )
    parser.add_argument(
        "--chart",
        action="store_true",
        help="Generate a comparison chart of all runs after scoring.",
    )
    parser.add_argument(
        "--chart-only",
        action="store_true",
        help="Skip scoring; just render the chart from existing history.",
    )
    parser.add_argument(
        "--chart-output",
        type=Path,
        default=None,
        help="Save chart to this path instead of displaying interactively.",
    )
    return parser.parse_args()


def is_lineman(entry: dict) -> bool:
    for field in ("title", "job_name"):
        value = (entry.get(field) or "").lower()
        if any(keyword in value for keyword in LINEMAN_KEYWORDS):
            return True
    search_query = (entry.get("search_query") or "").lower()
    return any(keyword in search_query for keyword in LINEMAN_KEYWORDS)


def soc6(onet_code: str) -> str:
    return onet_code[:7] if len(onet_code) >= 7 else onet_code


def compute_metrics(results: list[dict]) -> dict:
    lineman = [result for result in results if is_lineman(result)]
    lineman_count = len(lineman)
    if lineman_count == 0:
        return {
            "error": "no lineman entries found",
            "total_entries": len(results),
            "lineman_entries": 0,
        }

    top1_codes: Counter = Counter()
    any5_codes: Counter = Counter()

    for entry in lineman:
        matches = entry.get("top_task_matches", [])
        if matches:
            top1_codes[soc6(matches[0].get("onet_soc_code", ""))] += 1

        seen: set[str] = set()
        for match in matches:
            code = soc6(match.get("onet_soc_code", ""))
            if code and code not in seen:
                any5_codes[code] += 1
                seen.add(code)

    top1_expected = sum(count for code, count in top1_codes.items() if code in EXPECTED_SOC)
    any5_expected = sum(count for code, count in any5_codes.items() if code in EXPECTED_SOC)

    return {
        "total_entries": len(results),
        "lineman_entries": lineman_count,
        "unique_job_titles": sorted({entry.get("title", "") for entry in lineman}),
        "unique_companies": sorted({entry.get("company", "") for entry in lineman}),
        "expected_at_rank1": {
            "count": top1_expected,
            "pct": round(100 * top1_expected / lineman_count, 1),
        },
        "expected_in_top5": {
            "count": any5_expected,
            "pct": round(100 * any5_expected / lineman_count, 1),
        },
        "no_expected_dog": {
            "count": lineman_count - any5_expected,
            "pct": round(100 * (lineman_count - any5_expected) / lineman_count, 1),
        },
        "dog_distribution_rank1": {code: count for code, count in top1_codes.most_common(20)},
        "dog_distribution_any5": {code: count for code, count in any5_codes.most_common(20)},
    }


def extract_run_params(data: dict) -> dict:
    return {
        "top_k": data.get("top_k"),
        "top_n_dogs": data.get("top_n_dogs"),
        "stage1_text_mode": data.get("stage1_text_mode", "title"),
        "model_name": data.get("model_name"),
        "input_jsonl": data.get("input_jsonl_path"),
        "input_item_count": data.get("input_item_count"),
        "item_count": data.get("item_count"),
        "boilerplate_stripped": data.get("boilerplate_stripped", False),
        "relevance_filter_skipped_count": data.get("relevance_filter_skipped_count", 0),
        "relevance_filter_skip_confidence": data.get("relevance_filter_skip_confidence"),
        "relevance_pipeline": data.get("relevance_pipeline"),
    }


def load_history(path: Path) -> list[dict]:
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    return []


def save_history(history: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(history, handle, indent=2, ensure_ascii=False)


def upsert_run(history: list[dict], run_name: str, record: dict) -> list[dict]:
    updated = [existing for existing in history if existing.get("run_name") != run_name]
    updated.append(record)
    return updated


def print_metrics(run_name: str, metrics: dict) -> None:
    print(f"\n{'=' * 70}")
    print(f"  Run: {run_name}")
    print(f"{'=' * 70}")

    if metrics.get("error"):
        print(f"  {metrics['error']}")
        print(f"  Total entries: {metrics.get('total_entries', 0)}")
        return

    lineman_count = metrics["lineman_entries"]
    print(f"  Lineman entries     : {lineman_count}")
    print(
        f"  Expected DOG rank-1 : {metrics['expected_at_rank1']['count']:3d} / {lineman_count}"
        f"  = {metrics['expected_at_rank1']['pct']:5.1f}%"
    )
    print(
        f"  Expected DOG top-5  : {metrics['expected_in_top5']['count']:3d} / {lineman_count}"
        f"  = {metrics['expected_in_top5']['pct']:5.1f}%"
    )
    print(
        f"  No expected DOG     : {metrics['no_expected_dog']['count']:3d} / {lineman_count}"
        f"  = {metrics['no_expected_dog']['pct']:5.1f}%"
    )

    print("\n  Top-10 DOGs in rank-1 matches:")
    for code, count in list(metrics["dog_distribution_rank1"].items())[:10]:
        marker = " << EXPECTED" if code in EXPECTED_SOC else ""
        print(f"    {code}  {count:3d}  ({100 * count / lineman_count:5.1f}%){marker}")


def print_comparison_table(history: list[dict]) -> None:
    if not history:
        return

    print(f"\n{'=' * 90}")
    print(f"  COMPARISON TABLE  ({len(history)} runs)")
    print(f"{'=' * 90}")
    print(f"  {'Run name':<35}  {'Rank-1':>8}  {'Top-5':>8}  {'No match':>9}")
    print("  " + "-" * 68)
    for record in history:
        metrics = record.get("metrics", {})
        print(
            f"  {record['run_name']:<35}  "
            f"{metrics.get('expected_at_rank1', {}).get('pct', 0.0):7.1f}%  "
            f"{metrics.get('expected_in_top5', {}).get('pct', 0.0):7.1f}%  "
            f"{metrics.get('no_expected_dog', {}).get('pct', 0.0):8.1f}%"
        )


def generate_chart(history: list[dict], output_path: Path | None = None) -> None:
    try:
        import matplotlib

        if output_path:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping chart. Run: pip install matplotlib")
        return

    if not history:
        print("No history to chart.")
        return

    run_names = [record["run_name"] for record in history]
    rank1_pcts = [
        record.get("metrics", {}).get("expected_at_rank1", {}).get("pct", 0.0)
        for record in history
    ]
    top5_pcts = [
        record.get("metrics", {}).get("expected_in_top5", {}).get("pct", 0.0)
        for record in history
    ]
    no_match_pcts = [
        record.get("metrics", {}).get("no_expected_dog", {}).get("pct", 0.0)
        for record in history
    ]

    x_values = range(len(run_names))
    width = 0.25

    _, ax = plt.subplots(figsize=(max(8, len(run_names) * 2.5), 6))
    bars1 = ax.bar(
        [x - width for x in x_values],
        rank1_pcts,
        width,
        label="Expected DOG @ rank-1",
        color="#2196F3",
    )
    bars2 = ax.bar(x_values, top5_pcts, width, label="Expected DOG in top-5", color="#4CAF50")
    bars3 = ax.bar(
        [x + width for x in x_values],
        no_match_pcts,
        width,
        label="No expected DOG",
        color="#F44336",
    )

    def add_labels(bars: list) -> None:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                f"{height:.1f}%",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    add_labels(bars1)
    add_labels(bars2)
    add_labels(bars3)

    ax.set_ylabel("% of lineman entries")
    ax.set_title(
        "DOG Alignment Quality - Pipeline Comparison\n"
        "(Expected: 49-9051 Electric Power-Line or 49-9052 Telecom Line)"
    )
    ax.set_xticks(list(x_values))
    ax.set_xticklabels(run_names, rotation=15, ha="right", fontsize=9)
    ax.set_ylim(0, 105)
    ax.legend(loc="upper left")
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    plt.tight_layout()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150)
        print(f"Chart saved to: {output_path}")
    else:
        plt.show()


def main() -> int:
    args = parse_args()
    history = load_history(args.history)

    if args.chart_only:
        if not history:
            print(f"No history found at: {args.history}")
            return 0
        print_comparison_table(history)
        generate_chart(history, args.chart_output)
        return 0

    if not args.input:
        print("Error: --input is required (or use --chart-only to render existing history).")
        return 1
    if not args.run_name:
        print("Error: --run-name is required when scoring a new file.")
        return 1
    if not args.input.exists():
        print(f"Error: file not found: {args.input}")
        return 1

    print(f"Loading: {args.input}")
    with args.input.open(encoding="utf-8") as handle:
        data = json.load(handle)
    results = data.get("results", [])

    metrics = compute_metrics(results)
    print_metrics(args.run_name, metrics)

    record = {
        "run_name": args.run_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_file": str(args.input),
        "params": extract_run_params(data),
        "metrics": metrics,
    }

    history = upsert_run(history, args.run_name, record)
    save_history(history, args.history)
    print(f"\nSaved to history: {args.history}  ({len(history)} total runs)")
    print_comparison_table(history)

    if args.chart:
        generate_chart(history, args.chart_output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
