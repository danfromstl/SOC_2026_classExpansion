#!/usr/bin/env python3
"""Build an enriched nested SOC 2018 hierarchy JSON from source workbooks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


CODE_PATTERN = re.compile(r"^\d{2}-\d{4}$")
WHITESPACE_PATTERN = re.compile(r"\s+")
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {
    "main": MAIN_NS,
    "pkgrel": PKG_REL_NS,
}

TYPE_COLUMN = {
    "Major": "Major",
    "Minor": "Minor",
    "Broad": "Broad",
    "Detailed": "Detailed",
}
PARENT_COLUMN = {
    "Major": None,
    "Minor": "Major",
    "Broad": "Minor",
    "Detailed": "Broad",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STRUCTURE_XLSX_PATH = REPO_ROOT / "sourceDocs" / "soc_structure_2018_danEdit_flattened.xlsx"
DEFAULT_DESCRIPTIONS_XLSX_PATH = REPO_ROOT / "sourceDocs" / "ExtractedDetailedGroupDescriptions.xlsx"
DEFAULT_DIRECT_MATCH_XLSX_PATH = REPO_ROOT / "sourceDocs" / "soc_2018_direct_match_title_file.xlsx"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().with_name("soc_2018_nested_groups.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an enriched nested SOC 2018 hierarchy JSON from source workbooks."
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_STRUCTURE_XLSX_PATH,
        help=f"Path to the flattened structure workbook. Defaults to {DEFAULT_STRUCTURE_XLSX_PATH}",
    )
    parser.add_argument(
        "--descriptions-xlsx",
        type=Path,
        default=DEFAULT_DESCRIPTIONS_XLSX_PATH,
        help=f"Path to the detailed descriptions workbook. Defaults to {DEFAULT_DESCRIPTIONS_XLSX_PATH}",
    )
    parser.add_argument(
        "--direct-match-xlsx",
        type=Path,
        default=DEFAULT_DIRECT_MATCH_XLSX_PATH,
        help=f"Path to the direct match title workbook. Defaults to {DEFAULT_DIRECT_MATCH_XLSX_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the nested JSON. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    return parser.parse_args()


def workbook_sheet_path(zf: ZipFile, preferred_sheet_name: str | None = None) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    relationships = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
    }

    if preferred_sheet_name is not None:
        for sheet in workbook.findall("main:sheets/main:sheet", NS):
            if sheet.attrib.get("name", "") == preferred_sheet_name:
                rel_id = sheet.attrib[f"{{{DOC_REL_NS}}}id"]
                target = rel_map[rel_id]
                return target if target.startswith("xl/") else f"xl/{target}"

    first_sheet = workbook.find("main:sheets/main:sheet", NS)
    if first_sheet is None:
        raise ValueError("Workbook does not contain any sheets.")

    rel_id = first_sheet.attrib[f"{{{DOC_REL_NS}}}id"]
    target = rel_map[rel_id]
    return target if target.startswith("xl/") else f"xl/{target}"


def shared_strings(zf: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", NS):
        parts = [node.text or "" for node in item.findall(".//main:t", NS)]
        values.append("".join(parts))
    return values


def column_name(cell_ref: str) -> str:
    return "".join(char for char in cell_ref if char.isalpha())


def column_index(column: str) -> int:
    result = 0
    for char in column:
        result = result * 26 + (ord(char.upper()) - 64)
    return result


def cell_text(cell: ET.Element, strings: list[str]) -> str | None:
    value = cell.find("main:v", NS)
    if value is None:
        return None

    if cell.attrib.get("t") == "s":
        return strings[int(value.text)]

    return value.text


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = WHITESPACE_PATTERN.sub(" ", value).strip()
    return cleaned or None


def normalize_value(value: str | None) -> str | None:
    cleaned = sanitize_text(value)
    if cleaned is None or cleaned.lower() == "n/a":
        return None
    return cleaned


def repo_relative_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def load_sheet_rows(xlsx_path: Path, sheet_name: str | None = None) -> list[dict[str, str | None]]:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Workbook not found: {xlsx_path}")

    with ZipFile(xlsx_path) as zf:
        strings = shared_strings(zf)
        worksheet = ET.fromstring(zf.read(workbook_sheet_path(zf, sheet_name)))
        rows = worksheet.findall("main:sheetData/main:row", NS)
        if not rows:
            raise ValueError(f"No rows were found in {xlsx_path}")

        header_map: dict[str, str] | None = None
        parsed_rows: list[dict[str, str | None]] = []
        for row in rows:
            values_by_column: dict[str, str | None] = {}
            for cell in row.findall("main:c", NS):
                column = column_name(cell.attrib.get("r", "A1"))
                values_by_column[column] = cell_text(cell, strings)

            if not values_by_column:
                continue

            if header_map is None:
                header_map = {}
                for column in sorted(values_by_column, key=column_index):
                    header = normalize_value(values_by_column[column])
                    if header:
                        header_map[column] = header
                continue

            record = {
                header: normalize_value(values_by_column.get(column))
                for column, header in header_map.items()
            }
            parsed_rows.append(record)

    if not parsed_rows:
        raise ValueError(f"No data rows were extracted from {xlsx_path}")

    return parsed_rows


def dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def load_detailed_descriptions(xlsx_path: Path) -> dict[str, dict[str, str]]:
    rows = load_sheet_rows(xlsx_path)
    descriptions: dict[str, dict[str, str]] = {}

    for row in rows:
        group_type = row.get("SOC Group")
        code = row.get("SOC Code")
        title = row.get("SOC Title")
        definition = row.get("SOC Definition")

        if group_type != "Detailed":
            raise ValueError(f"Unexpected SOC Group value {group_type!r} in {xlsx_path}")
        if not code or not title or not definition:
            raise ValueError(f"Missing description data in row: {row}")
        if not CODE_PATTERN.match(code):
            raise ValueError(f"Invalid SOC code {code!r} in descriptions file")

        existing = descriptions.get(code)
        if existing is None:
            descriptions[code] = {
                "title": title,
                "description": definition,
            }
            continue

        if existing["title"] != title or existing["description"] != definition:
            raise ValueError(f"Conflicting description rows found for code {code}")

    return descriptions


def load_direct_match_titles(xlsx_path: Path) -> dict[str, dict[str, list[str] | str]]:
    rows = load_sheet_rows(xlsx_path, sheet_name="Sorted by SOC")
    grouped: dict[str, dict[str, list[str] | str]] = {}

    for row in rows:
        code = row.get("2018 SOC Code")
        soc_title = row.get("2018 SOC Title")
        direct_match_title = row.get("2018 SOC Direct Match Title")
        illustrative_flag = (row.get("Illustrative Example") or "").lower()

        if not code or not soc_title or not direct_match_title:
            raise ValueError(f"Missing direct match title data in row: {row}")
        if not CODE_PATTERN.match(code):
            raise ValueError(f"Invalid SOC code {code!r} in direct match title file")
        if illustrative_flag not in {"", "x"}:
            raise ValueError(
                f"Unexpected Illustrative Example flag {illustrative_flag!r} for code {code}"
            )

        bucket = grouped.setdefault(
            code,
            {
                "title": soc_title,
                "key_title_examples": [],
                "other_title_examples": [],
            },
        )
        if bucket["title"] != soc_title:
            raise ValueError(f"Conflicting SOC titles found for code {code} in direct match file")

        target_key = "key_title_examples" if illustrative_flag == "x" else "other_title_examples"
        target_list = bucket[target_key]
        if not isinstance(target_list, list):  # pragma: no cover - defensive typing
            raise TypeError(f"Expected list for {target_key}")
        target_list.append(direct_match_title)

    for code, bucket in grouped.items():
        key_titles = dedupe_preserving_order(bucket["key_title_examples"])  # type: ignore[arg-type]
        other_titles = dedupe_preserving_order(bucket["other_title_examples"])  # type: ignore[arg-type]
        key_title_set = set(key_titles)
        bucket["key_title_examples"] = key_titles
        bucket["other_title_examples"] = [title for title in other_titles if title not in key_title_set]

    return grouped


def enrich_detailed_nodes(
    nodes: dict[str, dict[str, object]],
    descriptions: dict[str, dict[str, str]],
    direct_match_titles: dict[str, dict[str, list[str] | str]],
) -> None:
    detailed_codes = {
        code for code, node in nodes.items() if node.get("group_type") == "Detailed"
    }

    missing_description_codes = sorted(detailed_codes - descriptions.keys())
    if missing_description_codes:
        raise ValueError(
            f"Missing detailed descriptions for {len(missing_description_codes)} SOC codes"
        )

    extra_description_codes = sorted(descriptions.keys() - detailed_codes)
    if extra_description_codes:
        raise ValueError(
            f"Descriptions were provided for unknown SOC codes: {', '.join(extra_description_codes[:10])}"
        )

    extra_title_codes = sorted(direct_match_titles.keys() - detailed_codes)
    if extra_title_codes:
        raise ValueError(
            f"Direct match titles were provided for unknown SOC codes: {', '.join(extra_title_codes[:10])}"
        )

    for code in detailed_codes:
        node = nodes[code]
        description_info = descriptions[code]
        if description_info["title"] != node["name"]:
            raise ValueError(
                f"Description title mismatch for {code}: {description_info['title']!r} "
                f"!= {node['name']!r}"
            )

        node["description"] = description_info["description"]

        title_info = direct_match_titles.get(code)
        if title_info is None:
            node["key_title_examples"] = []
            node["other_title_examples"] = []
            continue

        node["key_title_examples"] = list(title_info["key_title_examples"])  # type: ignore[arg-type]
        node["other_title_examples"] = list(title_info["other_title_examples"])  # type: ignore[arg-type]


def build_nested_hierarchy(
    structure_xlsx_path: Path,
    descriptions_xlsx_path: Path,
    direct_match_xlsx_path: Path,
) -> dict[str, object]:
    rows = load_sheet_rows(structure_xlsx_path, sheet_name="2018 Structure")

    nodes: dict[str, dict[str, object]] = {}
    child_codes: dict[str, list[str]] = {}
    root_codes: list[str] = []
    counts: Counter[str] = Counter()

    for row in rows:
        group_type = row.get("GroupType")
        if group_type not in TYPE_COLUMN:
            raise ValueError(f"Unexpected GroupType value: {group_type!r}")

        code = row.get(TYPE_COLUMN[group_type])
        name = row.get("NameMirror")
        if not code or not name:
            raise ValueError(f"Missing code or name in row: {row}")
        if not CODE_PATTERN.match(code):
            raise ValueError(f"Invalid SOC code {code!r} in row: {row}")

        counts[group_type] += 1
        existing = nodes.get(code)
        if existing is None:
            nodes[code] = {
                "code": code,
                "group_type": group_type,
                "name": name,
            }
        elif existing["group_type"] != group_type or existing["name"] != name:
            raise ValueError(f"Conflicting definitions found for code {code}")

        parent_column = PARENT_COLUMN[group_type]
        parent_code = row.get(parent_column) if parent_column else None
        if parent_code is None:
            if code not in root_codes:
                root_codes.append(code)
            continue
        if not CODE_PATTERN.match(parent_code):
            raise ValueError(f"Invalid parent SOC code {parent_code!r} in row: {row}")

        siblings = child_codes.setdefault(parent_code, [])
        if code not in siblings:
            siblings.append(code)

    for parent_code in child_codes:
        if parent_code not in nodes:
            raise ValueError(f"Missing parent definition for code {parent_code}")

    descriptions = load_detailed_descriptions(descriptions_xlsx_path)
    direct_match_titles = load_direct_match_titles(direct_match_xlsx_path)
    enrich_detailed_nodes(nodes, descriptions, direct_match_titles)

    def clone_tree(code: str) -> dict[str, object]:
        node = dict(nodes[code])
        node["children"] = [clone_tree(child_code) for child_code in child_codes.get(code, [])]
        return node

    detailed_codes_with_direct_matches = sum(
        1 for node in nodes.values() if node.get("group_type") == "Detailed" and (
            node.get("key_title_examples") or node.get("other_title_examples")
        )
    )

    return {
        "source_workbook": repo_relative_label(structure_xlsx_path),
        "source_workbooks": {
            "structure": repo_relative_label(structure_xlsx_path),
            "detailed_descriptions": repo_relative_label(descriptions_xlsx_path),
            "direct_match_titles": repo_relative_label(direct_match_xlsx_path),
        },
        "group_counts": {
            "Major": counts["Major"],
            "Minor": counts["Minor"],
            "Broad": counts["Broad"],
            "Detailed": counts["Detailed"],
        },
        "enrichment_counts": {
            "detailed_descriptions": len(descriptions),
            "detailed_codes_with_direct_match_titles": detailed_codes_with_direct_matches,
            "illustrative_example_titles": sum(
                len(node.get("key_title_examples", []))
                for node in nodes.values()
                if node.get("group_type") == "Detailed"
            ),
            "other_direct_match_titles": sum(
                len(node.get("other_title_examples", []))
                for node in nodes.values()
                if node.get("group_type") == "Detailed"
            ),
        },
        "major_groups": [clone_tree(code) for code in root_codes],
    }


def main() -> int:
    args = parse_args()

    try:
        hierarchy = build_nested_hierarchy(
            args.xlsx,
            args.descriptions_xlsx,
            args.direct_match_xlsx,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(hierarchy, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to build SOC hierarchy: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote nested SOC hierarchy to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
