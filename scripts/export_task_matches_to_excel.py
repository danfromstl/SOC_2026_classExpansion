#!/usr/bin/env python3
"""Export flattened job-posting task matches to an Excel workbook."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATHS = [
    REPO_ROOT / "jobPostings" / "job_postings_itemized_for_embeddings_firstTwoExamples_top5_task_matches.json",
    REPO_ROOT / "jobPostings" / "job_postings_itemized_for_embeddings_top5_task_matches.json",
]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "jobPostings" / "job_postings_all_top5_task_matches.xlsx"
DEFAULT_SHEET_NAME = "Task Matches"
ITEM_INDEX_PATTERN = re.compile(r"__(\d+)$")
INVALID_XML_CHARS = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x84\x86-\x9F]"
)

HEADERS = [
    "OriginID",
    "Job Name",
    "Category",
    "Listing Text",
    "Dan Notes",
    "Task Text",
    "Rank",
    "Score",
    "Task ID",
    "O-SOC Code",
    "O-SOC Title",
]

STRING_COLUMNS = {
    "OriginID",
    "Job Name",
    "Category",
    "Listing Text",
    "Dan Notes",
    "Task Text",
    "Task ID",
    "O-SOC Code",
    "O-SOC Title",
}

COLUMN_WIDTHS = [18, 30, 14, 60, 24, 60, 8, 12, 10, 14, 28]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export flattened job-posting task matches from JSON to Excel."
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        type=Path,
        default=DEFAULT_INPUT_PATHS,
        help="One or more task-match JSON files to flatten into a single workbook.",
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


def sanitize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return INVALID_XML_CHARS.sub("", text)


def repo_relative_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def extract_item_index(result_id: str) -> int:
    match = ITEM_INDEX_PATTERN.search(result_id)
    if match is None:
        raise ValueError(f"Could not extract item index from result id {result_id!r}")
    return int(match.group(1))


def build_origin_id(result: dict[str, object]) -> str:
    source_id = sanitize_text(result.get("job_id"))
    if not source_id:
        source_id = sanitize_text(result.get("job_key"))
    if not source_id:
        source_id = sanitize_text(result.get("id"))

    item_index = extract_item_index(sanitize_text(result.get("id")))
    return f"{source_id}.{item_index}"


def load_rows(input_paths: list[Path]) -> list[dict[str, object]]:
    flattened: list[dict[str, object]] = []
    for input_path in input_paths:
        if not input_path.exists():
            raise FileNotFoundError(f"Input JSON not found: {input_path}")

        payload = json.loads(input_path.read_text(encoding="utf-8"))
        results = payload.get("results")
        if not isinstance(results, list):
            raise ValueError(f"Expected 'results' list in {input_path}")

        for result in results:
            if not isinstance(result, dict):
                raise ValueError(f"Expected result object in {input_path}, found {type(result)!r}")

            matches = result.get("top_task_matches")
            if not isinstance(matches, list):
                raise ValueError(f"Expected 'top_task_matches' list in result {result.get('id')!r}")

            origin_id = build_origin_id(result)
            for match in matches:
                if not isinstance(match, dict):
                    raise ValueError(
                        f"Expected task match object in result {result.get('id')!r}, found {type(match)!r}"
                    )

                flattened.append(
                    {
                        "OriginID": origin_id,
                        "Job Name": sanitize_text(result.get("job_name")),
                        "Category": sanitize_text(result.get("category")),
                        "Listing Text": sanitize_text(result.get("text")),
                        "Dan Notes": "",
                        "Task Text": sanitize_text(match.get("task")),
                        "Rank": int(match["rank"]),
                        "Score": round(float(match["score"]), 6),
                        "Task ID": sanitize_text(match.get("task_id")),
                        "O-SOC Code": sanitize_text(match.get("onet_soc_code")),
                        "O-SOC Title": sanitize_text(match.get("onet_soc_title")),
                    }
                )

    if not flattened:
        raise ValueError("No flattened rows were produced from the supplied inputs.")

    return flattened


def excel_column_name(index: int) -> str:
    result = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def excel_cell_reference(row_index: int, column_index: int) -> str:
    return f"{excel_column_name(column_index)}{row_index}"


def worksheet_dimension(row_count: int, column_count: int) -> str:
    return f"A1:{excel_cell_reference(row_count, column_count)}"


def sheet_name_xml(sheet_name: str) -> str:
    cleaned = sanitize_text(sheet_name).strip() or DEFAULT_SHEET_NAME
    cleaned = cleaned[:31]
    return escape(cleaned)


def cell_xml(
    row_index: int,
    column_index: int,
    value: object,
    *,
    style_id: int,
    as_string: bool,
) -> str:
    ref = excel_cell_reference(row_index, column_index)
    if as_string:
        return (
            f'<c r="{ref}" s="{style_id}" t="inlineStr">'
            f"<is><t xml:space=\"preserve\">{escape(sanitize_text(value))}</t></is>"
            "</c>"
        )

    return f'<c r="{ref}" s="{style_id}"><v>{value}</v></c>'


def build_sheet_xml(sheet_name: str, rows: list[dict[str, object]]) -> str:
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


def build_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        "</fonts>"
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF7"/><bgColor indexed="64"/></patternFill></fill>'
        "</fills>"
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="4">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1">'
        '<alignment horizontal="center" vertical="center" wrapText="1"/>'
        "</xf>"
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment vertical="top" wrapText="1"/>'
        "</xf>"
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment horizontal="center" vertical="top"/>'
        "</xf>"
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


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


def build_workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )


def build_root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def build_content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )


def build_app_xml(sheet_name: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Codex</Application>"
        "<DocSecurity>0</DocSecurity>"
        "<ScaleCrop>false</ScaleCrop>"
        "<HeadingPairs><vt:vector size=\"2\" baseType=\"variant\">"
        "<vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>"
        "<vt:variant><vt:i4>1</vt:i4></vt:variant>"
        "</vt:vector></HeadingPairs>"
        "<TitlesOfParts><vt:vector size=\"1\" baseType=\"lpstr\">"
        f"<vt:lpstr>{escape(sanitize_text(sheet_name))}</vt:lpstr>"
        "</vt:vector></TitlesOfParts>"
        "<Company></Company>"
        "<LinksUpToDate>false</LinksUpToDate>"
        "<SharedDoc>false</SharedDoc>"
        "<HyperlinksChanged>false</HyperlinksChanged>"
        "<AppVersion>1.0</AppVersion>"
        "</Properties>"
    )


def build_core_xml() -> str:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:creator>Codex</dc:creator>"
        "<cp:lastModifiedBy>Codex</cp:lastModifiedBy>"
        "<dc:title>Job Posting Task Matches</dc:title>"
        "<dc:description>Flattened job posting task match results</dc:description>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>'
        "</cp:coreProperties>"
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
        zf.writestr("xl/worksheets/sheet1.xml", build_sheet_xml(sheet_name, rows))


def main() -> int:
    args = parse_args()

    try:
        rows = load_rows(args.inputs)
        write_workbook(args.output, args.sheet_name, rows)
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to export Excel workbook: {exc}", file=sys.stderr)
        return 1

    input_labels = ", ".join(repo_relative_label(path) for path in args.inputs)
    print(f"Wrote {len(rows)} flattened rows to {repo_relative_label(args.output)}")
    print(f"Inputs: {input_labels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
