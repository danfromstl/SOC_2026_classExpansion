#!/usr/bin/env python3
"""Build a JSON export of the O*NET Tasks to DWAs table."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ONET_SOC_CODE_PATTERN = re.compile(r"^\d{2}-\d{4}\.\d{2}$")
WHITESPACE_PATTERN = re.compile(r"\s+")
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {
    "main": MAIN_NS,
    "pkgrel": PKG_REL_NS,
}

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX_PATH = REPO_ROOT / "sourceDocs" / "Tasks to DWAs.xlsx"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().with_name("tasks_to_dwas.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a JSON export of the O*NET Tasks to DWAs table."
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX_PATH,
        help=f"Path to the Tasks to DWAs workbook. Defaults to {DEFAULT_XLSX_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the JSON output. Defaults to {DEFAULT_OUTPUT_PATH}",
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
                    header = sanitize_text(values_by_column[column])
                    if header:
                        header_map[column] = header
                continue

            parsed_rows.append(
                {
                    header: sanitize_text(values_by_column.get(column))
                    for column, header in header_map.items()
                }
            )

    if not parsed_rows:
        raise ValueError(f"No data rows were extracted from {xlsx_path}")

    return parsed_rows


def repo_relative_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def build_tasks_to_dwas_json(xlsx_path: Path) -> dict[str, object]:
    rows = load_sheet_rows(xlsx_path, sheet_name="Tasks to DWAs")

    raw_rows: list[dict[str, str]] = []
    by_onet_soc_code: dict[str, dict[str, object]] = {}
    unique_dwa_ids: set[str] = set()
    unique_task_keys: set[tuple[str, str]] = set()

    for row in rows:
        onet_soc_code = row.get("O*NET-SOC Code")
        title = row.get("Title")
        task_id = row.get("Task ID")
        task = row.get("Task")
        dwa_id = row.get("DWA ID")
        dwa_title = row.get("DWA Title")
        date = row.get("Date")
        domain_source = row.get("Domain Source")

        if not onet_soc_code or not title or not task_id or not task or not dwa_id or not dwa_title:
            raise ValueError(f"Missing task/DWA data in row: {row}")
        if not ONET_SOC_CODE_PATTERN.match(onet_soc_code):
            raise ValueError(f"Invalid O*NET-SOC code {onet_soc_code!r}")

        raw_row = {
            "onet_soc_code": onet_soc_code,
            "title": title,
            "task_id": task_id,
            "task": task,
            "dwa_id": dwa_id,
            "dwa_title": dwa_title,
            "date": date or "",
            "domain_source": domain_source or "",
        }
        raw_rows.append(raw_row)
        unique_dwa_ids.add(dwa_id)
        unique_task_keys.add((onet_soc_code, task_id))

        onet_bucket = by_onet_soc_code.setdefault(
            onet_soc_code,
            {
                "onet_soc_code": onet_soc_code,
                "title": title,
                "tasks": [],
            },
        )
        if onet_bucket["title"] != title:
            raise ValueError(f"Conflicting titles found for O*NET-SOC code {onet_soc_code}")

        tasks = onet_bucket["tasks"]
        if not isinstance(tasks, list):  # pragma: no cover - defensive typing
            raise TypeError("Expected list for tasks")

        task_entry = None
        for existing_task in tasks:
            if isinstance(existing_task, dict) and existing_task.get("task_id") == task_id:
                task_entry = existing_task
                break

        if task_entry is None:
            task_entry = {
                "task_id": task_id,
                "task": task,
                "dates": [date] if date else [],
                "domain_sources": [domain_source] if domain_source else [],
                "dwas": [],
            }
            tasks.append(task_entry)
        else:
            if task_entry["task"] != task:
                raise ValueError(
                    f"Conflicting task text found for {onet_soc_code} task {task_id}"
                )
            if date and date not in task_entry["dates"]:
                task_entry["dates"].append(date)
            if domain_source and domain_source not in task_entry["domain_sources"]:
                task_entry["domain_sources"].append(domain_source)

        dwas = task_entry["dwas"]
        if not isinstance(dwas, list):  # pragma: no cover - defensive typing
            raise TypeError("Expected list for dwas")

        dwa_entry = {
            "dwa_id": dwa_id,
            "dwa_title": dwa_title,
        }
        if dwa_entry not in dwas:
            dwas.append(dwa_entry)

    for onet_bucket in by_onet_soc_code.values():
        tasks = onet_bucket["tasks"]
        if not isinstance(tasks, list):  # pragma: no cover - defensive typing
            raise TypeError("Expected list for tasks")
        onet_bucket["task_count"] = len(tasks)

    return {
        "source_workbook": repo_relative_label(xlsx_path),
        "counts": {
            "rows": len(raw_rows),
            "onet_soc_codes": len(by_onet_soc_code),
            "unique_tasks": len(unique_task_keys),
            "unique_dwa_ids": len(unique_dwa_ids),
        },
        "rows": raw_rows,
        "by_onet_soc_code": by_onet_soc_code,
    }


def main() -> int:
    args = parse_args()

    try:
        data = build_tasks_to_dwas_json(args.xlsx)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to build Tasks to DWAs JSON: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote Tasks to DWAs JSON to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
