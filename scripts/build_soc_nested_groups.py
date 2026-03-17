#!/usr/bin/env python3
"""Build a nested SOC 2018 hierarchy JSON from the flattened workbook."""

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
DEFAULT_XLSX_PATH = REPO_ROOT / "sourceDocs" / "soc_structure_2018_danEdit_flattened.xlsx"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().with_name("soc_2018_nested_groups.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a nested SOC 2018 hierarchy JSON from the flattened workbook."
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX_PATH,
        help=f"Path to the flattened workbook. Defaults to {DEFAULT_XLSX_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the nested JSON. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    return parser.parse_args()


def workbook_sheet_path(zf: ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    relationships = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
    }

    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        name = sheet.attrib.get("name", "")
        if name == "2018 Structure":
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


def cell_text(cell: ET.Element, strings: list[str]) -> str | None:
    value = cell.find("main:v", NS)
    if value is None:
        return None

    if cell.attrib.get("t") == "s":
        return strings[int(value.text)]

    return value.text


def normalize_value(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped or stripped.lower() == "n/a":
        return None

    return stripped


def load_flattened_rows(xlsx_path: Path) -> list[dict[str, str | None]]:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Workbook not found: {xlsx_path}")

    with ZipFile(xlsx_path) as zf:
        strings = shared_strings(zf)
        worksheet = ET.fromstring(zf.read(workbook_sheet_path(zf)))

        rows = worksheet.findall("main:sheetData/main:row", NS)
        if not rows:
            raise ValueError(f"No rows were found in {xlsx_path}")

        headers: list[str] | None = None
        parsed_rows: list[dict[str, str | None]] = []
        for row in rows:
            values_by_column: dict[str, str | None] = {}
            for cell in row.findall("main:c", NS):
                col = column_name(cell.attrib.get("r", "A1"))
                values_by_column[col] = cell_text(cell, strings)

            if headers is None:
                ordered_headers = [values_by_column[col] for col in sorted(values_by_column)]
                headers = [header for header in ordered_headers if header]
                continue

            record: dict[str, str | None] = {}
            for index, header in enumerate(headers):
                col = chr(ord("A") + index)
                record[header] = normalize_value(values_by_column.get(col))
            parsed_rows.append(record)

    if not parsed_rows:
        raise ValueError(f"No data rows were extracted from {xlsx_path}")

    return parsed_rows


def build_nested_hierarchy(xlsx_path: Path) -> dict[str, object]:
    rows = load_flattened_rows(xlsx_path)

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

    def clone_tree(code: str) -> dict[str, object]:
        node = nodes[code]
        return {
            "code": node["code"],
            "group_type": node["group_type"],
            "name": node["name"],
            "children": [clone_tree(child_code) for child_code in child_codes.get(code, [])],
        }

    try:
        source_path = xlsx_path.resolve().relative_to(REPO_ROOT.resolve())
        source_label = str(source_path)
    except ValueError:
        source_label = str(xlsx_path.resolve())

    return {
        "source_workbook": source_label,
        "group_counts": {
            "Major": counts["Major"],
            "Minor": counts["Minor"],
            "Broad": counts["Broad"],
            "Detailed": counts["Detailed"],
        },
        "major_groups": [clone_tree(code) for code in root_codes],
    }


def main() -> int:
    args = parse_args()

    try:
        hierarchy = build_nested_hierarchy(args.xlsx)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(hierarchy, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to build SOC hierarchy: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote nested SOC hierarchy to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
