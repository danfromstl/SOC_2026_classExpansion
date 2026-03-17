#!/usr/bin/env python3
"""Look up SOC 2018 group details from the nested hierarchy JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


CODE_PATTERN = re.compile(r"^\d{2}-\d{4}$")
DEFAULT_CACHE_PATH = Path(__file__).resolve().with_name("soc_2018_nested_groups.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Look up any SOC 2018 group and report its type, parents, and name."
    )
    parser.add_argument(
        "code",
        nargs="?",
        help='SOC group code, for example "15-1251" or "15-1250".',
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"Path to the nested JSON cache. Defaults to {DEFAULT_CACHE_PATH}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the lookup result as JSON instead of human-readable text.",
    )
    return parser.parse_args()


def load_hierarchy(cache_path: Path) -> dict[str, object]:
    if not cache_path.exists():
        raise FileNotFoundError(
            f"Nested SOC hierarchy not found: {cache_path}. "
            "Run scripts/build_soc_nested_groups.py first."
        )

    return json.loads(cache_path.read_text(encoding="utf-8"))


def prompt_for_code() -> str:
    return input('Enter an SOC group code (for example "15-1251"): ').strip()


def find_group(
    node: dict[str, object],
    code: str,
    parents: list[dict[str, str]] | None = None,
) -> tuple[dict[str, object], list[dict[str, str]]] | None:
    lineage = parents or []
    if node["code"] == code:
        return node, lineage

    next_parents = lineage + [
        {
            "code": str(node["code"]),
            "group_type": str(node["group_type"]),
            "name": str(node["name"]),
        }
    ]
    for child in node.get("children", []):
        result = find_group(child, code, next_parents)
        if result is not None:
            return result

    return None


def lookup_group(hierarchy: dict[str, object], code: str) -> dict[str, object] | None:
    for major_group in hierarchy.get("major_groups", []):
        result = find_group(major_group, code)
        if result is None:
            continue

        node, parents = result
        return {
            "code": str(node["code"]),
            "group_type": str(node["group_type"]),
            "group_name": str(node["name"]),
            "parents": parents,
        }

    return None


def print_text_result(result: dict[str, object]) -> None:
    print(f'Group Type: {result["group_type"]}')
    parents = result["parents"]
    if parents:
        print("Parent Categories:")
        for parent in parents:
            print(f'  {parent["group_type"]}: {parent["code"]} - {parent["name"]}')
    else:
        print("Parent Categories: None")
    print(f'Group Name: {result["group_name"]}')


def main() -> int:
    args = parse_args()

    try:
        hierarchy = load_hierarchy(args.cache)
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to load SOC hierarchy: {exc}", file=sys.stderr)
        return 1

    code = (args.code or prompt_for_code()).strip()
    if not CODE_PATTERN.match(code):
        print(f'Invalid SOC code: "{code}". Expected format NN-NNNN.', file=sys.stderr)
        return 1

    result = lookup_group(hierarchy, code)
    if result is None:
        print(f'No SOC 2018 group was found for code "{code}".', file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_text_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
