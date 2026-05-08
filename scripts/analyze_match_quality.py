#!/usr/bin/env python3
"""
Analyze current (single-stage) match quality for lineman job postings.

Reports what fraction of top-5 task matches come from the expected DOGs:
  49-9051  Electrical Power-Line Installers and Repairers  (electric utility linemen)
  49-9052  Telecommunications Line Installers and Repairers (telecom/OSP linemen)

No external dependencies required — stdlib only.

Usage:
  python scripts/analyze_match_quality.py
  python scripts/analyze_match_quality.py --input jobPostings/some_other_matches.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ELECTRIC_CODE = "49-9051"
TELECOM_CODE = "49-9052"
LINEMAN_EXPECTED_SOC = {ELECTRIC_CODE, TELECOM_CODE}

LINEMAN_KEYWORDS = {"lineman", "linemen", "lineworker", "line installer", "line worker"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze match quality for lineman job postings.")
    p.add_argument(
        "--input",
        type=Path,
        default=REPO_ROOT / "jobPostings" / "linkedin_job_search_results_itemized_for_embeddings_top5_task_matches.json",
        help="Path to a top_task_matches JSON output file.",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Number of lineman entries to print in detail (default: 10).",
    )
    return p.parse_args()


def is_lineman(entry: dict) -> bool:
    for field in ("title", "job_name"):
        val = (entry.get(field) or "").lower()
        if any(kw in val for kw in LINEMAN_KEYWORDS):
            return True
    sq = (entry.get("search_query") or "").lower()
    return any(kw in sq for kw in LINEMAN_KEYWORDS)


def soc6(onet_code: str) -> str:
    """Convert O*NET code '49-9051.00' → SOC-6 '49-9051'."""
    return onet_code[:7] if len(onet_code) >= 7 else onet_code


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {args.input}")
    with args.input.open(encoding="utf-8") as f:
        data = json.load(f)
    results = data.get("results", [])

    lineman = [r for r in results if is_lineman(r)]

    print(f"\nTotal entries in file : {len(results)}")
    print(f"Lineman entries found : {len(lineman)}")
    if not lineman:
        print("No lineman entries found — check LINEMAN_KEYWORDS or input file.")
        sys.exit(0)

    unique_titles = sorted(set(e.get("title", "") for e in lineman))
    unique_companies = sorted(set(e.get("company", "") for e in lineman))
    print(f"Unique job titles     : {unique_titles}")
    print(f"Unique companies      : {unique_companies}")

    # ------------------------------------------------------------------
    # Detailed sample
    # ------------------------------------------------------------------
    print("\n" + "=" * 90)
    print(f"DETAILED SAMPLE — first {args.sample} lineman entries")
    print("=" * 90)

    for entry in lineman[: args.sample]:
        print(f"\n  JOB : {entry.get('title')} @ {entry.get('company')}")
        print(f"  CAT : {entry.get('category')}")
        text = entry.get("text", "")
        print(f"  TEXT: \"{text[:80]}{'...' if len(text) > 80 else ''}\"")
        for m in entry.get("top_task_matches", []):
            code = soc6(m.get("onet_soc_code", ""))
            flag = "EXPECTED" if code in LINEMAN_EXPECTED_SOC else "---"
            print(
                f"    [{m['rank']}] {m['score']:.4f}  "
                f"{m['onet_soc_code']:15} "
                f"{m['onet_soc_title'][:42]:42} "
                f"{flag}"
            )
            task_text = m.get("task", "")
            print(f"          \"{task_text[:78]}{'...' if len(task_text) > 78 else ''}\"")

    # ------------------------------------------------------------------
    # Aggregate statistics
    # ------------------------------------------------------------------
    n = len(lineman)

    top1_by_code: Counter = Counter()
    for entry in lineman:
        matches = entry.get("top_task_matches", [])
        if matches:
            top1_by_code[soc6(matches[0].get("onet_soc_code", ""))] += 1

    any5_by_code: Counter = Counter()
    for entry in lineman:
        seen: set[str] = set()
        for m in entry.get("top_task_matches", []):
            c = soc6(m.get("onet_soc_code", ""))
            if c not in seen:
                any5_by_code[c] += 1
                seen.add(c)

    top1_exp = sum(v for k, v in top1_by_code.items() if k in LINEMAN_EXPECTED_SOC)
    any5_exp = sum(v for k, v in any5_by_code.items() if k in LINEMAN_EXPECTED_SOC)

    print("\n" + "=" * 90)
    print("TOP-1 MATCH — DOG distribution (top 20)")
    print("=" * 90)
    for code, cnt in top1_by_code.most_common(20):
        mark = " << EXPECTED" if code in LINEMAN_EXPECTED_SOC else ""
        print(f"  {code}  {cnt:4d}  ({100 * cnt / n:5.1f}%){mark}")

    print("\n" + "=" * 90)
    print("ANY-OF-5 MATCH - DOG distribution (top 20, distinct DOGs per entry)")
    print("=" * 90)
    for code, cnt in any5_by_code.most_common(20):
        mark = " << EXPECTED" if code in LINEMAN_EXPECTED_SOC else ""
        print(f"  {code}  {cnt:4d}  ({100 * cnt / n:5.1f}%){mark}")

    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"  Expected DOG at rank-1          : {top1_exp:4d} / {n} = {100 * top1_exp / n:5.1f}%")
    print(f"  Expected DOG anywhere in top-5  : {any5_exp:4d} / {n} = {100 * any5_exp / n:5.1f}%")
    print(f"  Entries with NO expected DOG    : {n - any5_exp:4d} / {n} = {100 * (n - any5_exp) / n:5.1f}%")


if __name__ == "__main__":
    main()
