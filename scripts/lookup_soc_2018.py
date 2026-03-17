#!/usr/bin/env python3
"""Resolve an SOC 2018 detailed occupation code to its title."""

from __future__ import annotations

import argparse
import json
import re
import sys
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

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX_PATH = REPO_ROOT / "sourceDocs" / "soc_structure_2018.xlsx"
DEFAULT_CACHE_PATH = Path(__file__).resolve().with_name("soc_2018_detailed_occupations.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Look up an SOC 2018 detailed occupation title from its code."
    )
    parser.add_argument(
        "code",
        nargs="?",
        help='SOC 2018 detailed occupation code, for example "15-1251".',
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX_PATH,
        help=f"Path to the source workbook. Defaults to {DEFAULT_XLSX_PATH}",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"Path to the JSON cache. Defaults to {DEFAULT_CACHE_PATH}",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild the JSON cache from the workbook before looking up the code.",
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


def extract_detailed_occupations(xlsx_path: Path) -> dict[str, str]:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Workbook not found: {xlsx_path}")

    results: dict[str, str] = {}
    with ZipFile(xlsx_path) as zf:
        strings = shared_strings(zf)
        worksheet = ET.fromstring(zf.read(workbook_sheet_path(zf)))

        for row in worksheet.findall("main:sheetData/main:row", NS):
            code = None
            title = None
            for cell in row.findall("main:c", NS):
                ref = cell.attrib.get("r", "")
                col = column_name(ref)
                if col == "D":
                    code = cell_text(cell, strings)
                elif col == "E":
                    title = cell_text(cell, strings)

            if code and title and CODE_PATTERN.match(code):
                results[code] = title

    if not results:
        raise ValueError(f"No detailed occupation rows were extracted from {xlsx_path}")

    return results


def load_mapping(cache_path: Path, xlsx_path: Path, refresh: bool) -> dict[str, str]:
    if not refresh and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    mapping = extract_detailed_occupations(xlsx_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(mapping, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return mapping


def prompt_for_code() -> str:
    return input('Enter an SOC 2018 detailed occupation code (for example "15-1251"): ').strip()


def main() -> int:
    args = parse_args()

    try:
        mapping = load_mapping(args.cache, args.xlsx, args.refresh)
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to load SOC mapping: {exc}", file=sys.stderr)
        return 1

    code = (args.code or prompt_for_code()).strip()
    if not CODE_PATTERN.match(code):
        print(
            f'Invalid SOC 2018 detailed occupation code: "{code}". Expected format NN-NNNN.',
            file=sys.stderr,
        )
        return 1

    title = mapping.get(code)
    if title is None:
        print(f'No SOC 2018 detailed occupation was found for code "{code}".', file=sys.stderr)
        return 1

    print(title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
