#!/usr/bin/env python3
"""Build a JSON crosswalk between 2018 SOC codes and O*NET-SOC 2019 codes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


SOC_2018_CODE_PATTERN = re.compile(r"^\d{2}-\d{4}$")
ONET_SOC_2019_CODE_PATTERN = re.compile(r"^\d{2}-\d{4}\.\d{2}$")
WHITESPACE_PATTERN = re.compile(r"\s+")
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {
    "main": MAIN_NS,
    "pkgrel": PKG_REL_NS,
}

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX_PATH = REPO_ROOT / "sourceDocs" / "2019_to_SOC_Crosswalk.xlsx"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().with_name("soc2018_to_onet2019_crosswalk.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a JSON crosswalk between 2018 SOC codes and O*NET-SOC 2019 codes."
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX_PATH,
        help=f"Path to the crosswalk workbook. Defaults to {DEFAULT_XLSX_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the JSON crosswalk. Defaults to {DEFAULT_OUTPUT_PATH}",
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


def build_crosswalk(xlsx_path: Path) -> dict[str, object]:
    rows = load_sheet_rows(xlsx_path, sheet_name="O-NET-SOC 2019 Occupation Listi")

    crosswalk_rows: list[dict[str, str]] = []
    by_soc_2018_code: dict[str, dict[str, object]] = {}
    by_onet_soc_2019_code: dict[str, dict[str, str]] = {}

    for row in rows:
        onet_code = row.get("O*NET-SOC 2019 Code")
        onet_title = row.get("O*NET-SOC 2019 Title")
        soc_code = row.get("2018 SOC Code")
        soc_title = row.get("2018 SOC Title")

        if not onet_code or not onet_title or not soc_code or not soc_title:
            raise ValueError(f"Missing crosswalk data in row: {row}")
        if not ONET_SOC_2019_CODE_PATTERN.match(onet_code):
            raise ValueError(f"Invalid O*NET-SOC 2019 code {onet_code!r}")
        if not SOC_2018_CODE_PATTERN.match(soc_code):
            raise ValueError(f"Invalid 2018 SOC code {soc_code!r}")
        if onet_code in by_onet_soc_2019_code:
            raise ValueError(f"Duplicate O*NET-SOC 2019 code found: {onet_code}")

        crosswalk_row = {
            "onet_soc_2019_code": onet_code,
            "onet_soc_2019_title": onet_title,
            "soc_2018_code": soc_code,
            "soc_2018_title": soc_title,
        }
        crosswalk_rows.append(crosswalk_row)
        by_onet_soc_2019_code[onet_code] = dict(crosswalk_row)

        soc_bucket = by_soc_2018_code.setdefault(
            soc_code,
            {
                "soc_2018_code": soc_code,
                "soc_2018_title": soc_title,
                "onet_soc_2019_occupations": [],
            },
        )
        if soc_bucket["soc_2018_title"] != soc_title:
            raise ValueError(f"Conflicting 2018 SOC titles found for {soc_code}")

        occupations = soc_bucket["onet_soc_2019_occupations"]
        if not isinstance(occupations, list):  # pragma: no cover - defensive typing
            raise TypeError("Expected list for onet_soc_2019_occupations")
        occupations.append(
            {
                "onet_soc_2019_code": onet_code,
                "onet_soc_2019_title": onet_title,
            }
        )

    return {
        "source_workbook": repo_relative_label(xlsx_path),
        "counts": {
            "crosswalk_rows": len(crosswalk_rows),
            "soc_2018_codes": len(by_soc_2018_code),
            "onet_soc_2019_codes": len(by_onet_soc_2019_code),
        },
        "rows": crosswalk_rows,
        "by_soc_2018_code": by_soc_2018_code,
        "by_onet_soc_2019_code": by_onet_soc_2019_code,
    }


def main() -> int:
    args = parse_args()

    try:
        crosswalk = build_crosswalk(args.xlsx)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(crosswalk, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to build crosswalk JSON: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote SOC 2018 to O*NET-SOC 2019 crosswalk JSON to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
