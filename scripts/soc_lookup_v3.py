#!/usr/bin/env python3
"""Look up SOC 2018 group details and matching O*NET-SOC 2019 subgroups."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


CODE_PATTERN = re.compile(r"^\d{2}-\d{4}$")
DEFAULT_CACHE_PATH = Path(__file__).resolve().with_name("soc_2018_nested_groups.json")
DEFAULT_CROSSWALK_PATH = Path(__file__).resolve().with_name("soc2018_to_onet2019_crosswalk.json")
DEFAULT_TASKS_PATH = Path(__file__).resolve().with_name("tasks_to_dwas.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Look up any SOC 2018 group and report its type, hierarchy, and O*NET subgroups."
    )
    parser.add_argument(
        "code",
        nargs="?",
        help='SOC group code, for example "13-1041" or "15-1250".',
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"Path to the nested SOC JSON cache. Defaults to {DEFAULT_CACHE_PATH}",
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=DEFAULT_CROSSWALK_PATH,
        help=f"Path to the SOC/O*NET crosswalk JSON. Defaults to {DEFAULT_CROSSWALK_PATH}",
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        default=DEFAULT_TASKS_PATH,
        help=f"Path to the Tasks to DWAs JSON. Defaults to {DEFAULT_TASKS_PATH}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the lookup result as JSON instead of human-readable text.",
    )
    return parser.parse_args()


def load_json(path: Path, missing_message: str) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"{missing_message}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_hierarchy(cache_path: Path) -> dict[str, object]:
    return load_json(
        cache_path,
        "Nested SOC hierarchy not found. Run scripts/build_soc_nested_groups.py first",
    )


def load_crosswalk(crosswalk_path: Path) -> dict[str, object]:
    return load_json(
        crosswalk_path,
        "SOC/O*NET crosswalk JSON not found. Run scripts/build_soc2018_to_onet2019_crosswalk.py first",
    )


def load_tasks(tasks_path: Path) -> dict[str, object]:
    return load_json(
        tasks_path,
        "Tasks to DWAs JSON not found. Run scripts/build_tasks_to_dwas.py first",
    )


def prompt_for_code() -> str:
    return input('Enter an SOC group code (for example "13-1041"): ').strip()


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


def lookup_group(
    hierarchy: dict[str, object],
    crosswalk: dict[str, object],
    tasks_data: dict[str, object],
    code: str,
) -> dict[str, object] | None:
    by_soc_2018_code = crosswalk.get("by_soc_2018_code", {})
    if not isinstance(by_soc_2018_code, dict):
        raise ValueError("Crosswalk JSON is missing a valid by_soc_2018_code section.")
    by_onet_soc_code = tasks_data.get("by_onet_soc_code", {})
    if not isinstance(by_onet_soc_code, dict):
        raise ValueError("Tasks to DWAs JSON is missing a valid by_onet_soc_code section.")

    for major_group in hierarchy.get("major_groups", []):
        result = find_group(major_group, code)
        if result is None:
            continue

        node, parents = result
        children = [
            {
                "code": str(child["code"]),
                "group_type": str(child["group_type"]),
                "name": str(child["name"]),
            }
            for child in node.get("children", [])
        ]

        onet_subgroups: list[dict[str, str]] = []
        crosswalk_entry = by_soc_2018_code.get(code)
        if isinstance(crosswalk_entry, dict):
            occupations = crosswalk_entry.get("onet_soc_2019_occupations", [])
            if isinstance(occupations, list):
                onet_subgroups = [
                    {
                        "onet_soc_2019_code": str(occupation["onet_soc_2019_code"]),
                        "onet_soc_2019_title": str(occupation["onet_soc_2019_title"]),
                    }
                    for occupation in occupations
                    if isinstance(occupation, dict)
                    and "onet_soc_2019_code" in occupation
                    and "onet_soc_2019_title" in occupation
                ]

        tasks_by_onet_subgroup: list[dict[str, object]] = []
        total_task_count = 0
        if str(node["group_type"]) == "Detailed":
            for subgroup in onet_subgroups:
                subgroup_code = subgroup["onet_soc_2019_code"]
                task_bucket = by_onet_soc_code.get(subgroup_code)
                if not isinstance(task_bucket, dict):
                    continue

                task_entries = task_bucket.get("tasks", [])
                if not isinstance(task_entries, list):
                    continue

                tasks_for_subgroup = []
                for task_entry in task_entries:
                    if not isinstance(task_entry, dict):
                        continue
                    dwas = task_entry.get("dwas", [])
                    if not isinstance(dwas, list):
                        continue
                    tasks_for_subgroup.append(
                        {
                            "task_id": str(task_entry.get("task_id", "")),
                            "task": str(task_entry.get("task", "")),
                            "dwas": [
                                {
                                    "dwa_id": str(dwa.get("dwa_id", "")),
                                    "dwa_title": str(dwa.get("dwa_title", "")),
                                }
                                for dwa in dwas
                                if isinstance(dwa, dict)
                            ],
                        }
                    )

                if tasks_for_subgroup:
                    total_task_count += len(tasks_for_subgroup)
                    tasks_by_onet_subgroup.append(
                        {
                            "onet_soc_2019_code": subgroup["onet_soc_2019_code"],
                            "onet_soc_2019_title": subgroup["onet_soc_2019_title"],
                            "task_count": len(tasks_for_subgroup),
                            "tasks": tasks_for_subgroup,
                        }
                    )

        return {
            "code": str(node["code"]),
            "group_type": str(node["group_type"]),
            "group_name": str(node["name"]),
            "parents": parents,
            "child_categories": children,
            "onet_subgroups": onet_subgroups,
            "onet_subgroup_count": len(onet_subgroups),
            "tasks_by_onet_subgroup": tasks_by_onet_subgroup,
            "task_count_total": total_task_count,
        }

    return None


def print_text_result(result: dict[str, object]) -> None:
    print(f'Group Name: {result["group_name"]}')
    print()
    print(f'Group Type: {result["group_type"]}')
    print()

    parents = result["parents"]
    if parents:
        print("Parent Categories:")
        for parent in parents:
            print(f'  {parent["group_type"]}: {parent["code"]} - {parent["name"]}')
    else:
        print("Parent Categories: None")

    child_categories = result["child_categories"]
    if child_categories:
        print()
        print("Child Categories:")
        for child in child_categories:
            print(f'  {child["group_type"]}: {child["code"]} - {child["name"]}')

    print()
    print(f'O*NET Subgroups: ({result["onet_subgroup_count"]})')
    for subgroup in result["onet_subgroups"]:
        print(f'  {subgroup["onet_soc_2019_code"]} - {subgroup["onet_soc_2019_title"]}')

    if result["group_type"] == "Detailed":
        print()
        print(f'Detailed Tasks: ({result["task_count_total"]})')
        for subgroup in result["tasks_by_onet_subgroup"]:
            print(
                f'  {subgroup["onet_soc_2019_code"]} - {subgroup["onet_soc_2019_title"]} '
                f'({subgroup["task_count"]})'
            )
            for task in subgroup["tasks"]:
                print(f'    Task {task["task_id"]}: {task["task"]}')
                for dwa in task["dwas"]:
                    print(f'      {dwa["dwa_id"]} - {dwa["dwa_title"]}')


def main() -> int:
    args = parse_args()

    try:
        hierarchy = load_hierarchy(args.cache)
        crosswalk = load_crosswalk(args.crosswalk)
        tasks_data = load_tasks(args.tasks)
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to load SOC lookup data: {exc}", file=sys.stderr)
        return 1

    code = (args.code or prompt_for_code()).strip()
    if not CODE_PATTERN.match(code):
        print(f'Invalid SOC code: "{code}". Expected format NN-NNNN.', file=sys.stderr)
        return 1

    result = lookup_group(hierarchy, crosswalk, tasks_data, code)
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
