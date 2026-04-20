#!/usr/bin/env python3
"""Temp export of LinkedIn task-match results to a simplified Excel workbook."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from export_task_matches_to_excel import (
    build_app_xml,
    build_content_types_xml,
    build_core_xml,
    build_root_rels_xml,
    build_styles_xml,
    build_workbook_rels_xml,
    cell_xml,
    repo_relative_label,
    sanitize_text,
    sheet_name_xml,
    worksheet_dimension,
    ZIP_DEFLATED,
    ZipFile,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = (
    REPO_ROOT / "jobPostings" / "linkedin_job_search_results_itemized_for_embeddings_top5_task_matches.json"
)
DEFAULT_OUTPUT_PATH = (
    REPO_ROOT / "jobPostings" / "linkedin_job_search_results_itemized_match_scores.xlsx"
)
DEFAULT_SHEET_NAME = "LinkedIn Matches"

HEADERS = [
    "id",
    "title",
    "category",
    "text",
    "match.score",
    "match.task",
    "match.soc_code",
    "match.soc_title",
]

STRING_COLUMNS = {
    "id",
    "title",
    "category",
    "text",
    "match.task",
    "match.soc_code",
    "match.soc_title",
}

COLUMN_WIDTHS = [52, 32, 14, 70, 12, 70, 14, 28]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export simplified LinkedIn match-score rows to Excel."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Path to the LinkedIn task-match JSON. Defaults to {DEFAULT_INPUT_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Workbook path to write. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--sheet-name",
        default=DEFAULT_SHEET_NAME,
        help=f"Worksheet name to use. Defaults to {DEFAULT_SHEET_NAME!r}",
    )
    return parser.parse_args()


def build_workbook_xml(sheet_name: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        f'<sheet name="{sheet_name_xml(sheet_name)}" sheetId="1" r:id="rId1"/>'
        "</sheets>"
        "</workbook>"
    )


def load_rows(input_path: Path) -> list[dict[str, object]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError(f"Expected 'results' list in {input_path}")

    flattened: list[dict[str, object]] = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError(f"Expected result object in {input_path}, found {type(result)!r}")

        matches = result.get("top_task_matches")
        if not isinstance(matches, list):
            raise ValueError(f"Expected 'top_task_matches' list in result {result.get('id')!r}")

        for match in matches:
            if not isinstance(match, dict):
                raise ValueError(
                    f"Expected task match object in result {result.get('id')!r}, found {type(match)!r}"
                )

            flattened.append(
                {
                    "id": sanitize_text(result.get("id")),
                    "title": sanitize_text(result.get("title")),
                    "category": sanitize_text(result.get("category")),
                    "text": sanitize_text(result.get("text")),
                    "match.score": round(float(match["score"]), 6),
                    "match.task": sanitize_text(match.get("task")),
                    "match.soc_code": sanitize_text(match.get("onet_soc_code")),
                    "match.soc_title": sanitize_text(match.get("onet_soc_title")),
                }
            )

    if not flattened:
        raise ValueError("No flattened match rows were produced from the input JSON.")

    return flattened


def build_sheet_xml(rows: list[dict[str, object]]) -> str:
    row_xml: list[str] = []

    header_cells = [
        cell_xml(1, column_index, header, style_id=1, as_string=True)
        for column_index, header in enumerate(HEADERS, start=1)
    ]
    row_xml.append(f'<row r="1" ht="24" customHeight="1">{"".join(header_cells)}</row>')

    for row_index, row in enumerate(rows, start=2):
        cells: list[str] = []
        for column_index, header in enumerate(HEADERS, start=1):
            value = row[header]
            style_id = 2 if header in STRING_COLUMNS else 3
            cells.append(
                cell_xml(
                    row_index,
                    column_index,
                    value,
                    style_id=style_id,
                    as_string=header in STRING_COLUMNS,
                )
            )
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    cols_xml = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(COLUMN_WIDTHS, start=1)
    )
    dimension = worksheet_dimension(len(rows) + 1, len(HEADERS))

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<dimension ref=\"{dimension}\"/>"
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{cols_xml}</cols>"
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        f'<autoFilter ref="{dimension}"/>'
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        "</worksheet>"
    )


def write_workbook(output_path: Path, sheet_name: str, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", build_content_types_xml())
        zf.writestr("_rels/.rels", build_root_rels_xml())
        zf.writestr("docProps/app.xml", build_app_xml(sheet_name))
        zf.writestr("docProps/core.xml", build_core_xml())
        zf.writestr("xl/workbook.xml", build_workbook_xml(sheet_name))
        zf.writestr("xl/_rels/workbook.xml.rels", build_workbook_rels_xml())
        zf.writestr("xl/styles.xml", build_styles_xml())
        zf.writestr("xl/worksheets/sheet1.xml", build_sheet_xml(rows))


def main() -> int:
    args = parse_args()

    try:
        rows = load_rows(args.input)
        write_workbook(args.output, args.sheet_name, rows)
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to export LinkedIn match workbook: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(rows)} rows to {repo_relative_label(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
