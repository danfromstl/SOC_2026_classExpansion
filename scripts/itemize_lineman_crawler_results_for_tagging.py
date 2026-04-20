#!/usr/bin/env python3
"""Itemize grouped crawler job results and export a manual-tagging workbook."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from export_task_matches_to_excel import (
    ZIP_DEFLATED,
    ZipFile,
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
)
from preprocess_linkedin_job_search_results import (
    OVERVIEW_LABELS,
    PREFERRED_LABELS,
    REQUIREMENT_LABELS,
    ROLE_LABELS,
    SKIP_INLINE_LABELS,
    SKIP_LABELS,
    clean_text,
    extract_location,
    extract_url_metadata,
    heading_key,
    looks_like_heading,
    split_inline_label,
    split_sentences,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = REPO_ROOT / "jobPostings" / "lineman_crawler_results.json"
DEFAULT_OUTPUT_JSONL_PATH = REPO_ROOT / "jobPostings" / "lineman_crawler_results_itemized_for_tagging.jsonl"
DEFAULT_OUTPUT_XLSX_PATH = REPO_ROOT / "jobPostings" / "lineman_crawler_results_itemized_for_tagging.xlsx"
DEFAULT_SHEET_NAME = "Manual Tagging"

TAG_HEADER = "manual_tag (OCC/ACT/REQ/CTX/LVL/NOISE)"
HEADERS = [
    "id",
    "group",
    "title",
    "company",
    "category",
    "text",
    TAG_HEADER,
    "manual_notes",
    "source_queries",
]
STRING_COLUMNS = set(HEADERS)
COLUMN_WIDTHS = [52, 26, 30, 24, 14, 82, 24, 28, 32]

NOISE_MARKERS = (
    "benefits",
    "benefit package",
    "medical insurance",
    "dental insurance",
    "vision insurance",
    "401k",
    "retirement",
    "paid vacation",
    "paid leave",
    "company match",
    "short-term disability",
    "long-term disability",
    "life insurance",
    "equal opportunity employer",
    "do not discriminate",
    "salary",
    "hourly",
    "pay rate",
    "application deadline",
    "visit our website",
    "submit",
    "mail",
    "our core values",
    "our values",
    "our mission",
    "join our team",
    "contact human resources",
    "questions?",
    "position is an hourly, union position",
    "benefits information is not available",
)
REQUIREMENT_MARKERS = (
    "years of experience",
    "experience required",
    "experience preferred",
    "valid cdl",
    "commercial driver",
    "driver's license",
    "high school diploma",
    "associate degree",
    "certificate",
    "must be able to",
    "ability to",
    "must have",
    "required",
    "qualification",
    "knowledge of",
    "medical card",
    "drug screening",
    "background check",
)
PREFERRED_MARKERS = (
    "preferred",
    "recommended",
    "desired",
    "a plus",
    "is a plus",
    "strongly preferred",
    "highly preferred",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Itemize grouped crawler job results and export a manual-tagging workbook."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Path to the crawler results JSON. Defaults to {DEFAULT_INPUT_PATH}",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=DEFAULT_OUTPUT_JSONL_PATH,
        help=f"Path to write the itemized JSONL. Defaults to {DEFAULT_OUTPUT_JSONL_PATH}",
    )
    parser.add_argument(
        "--output-xlsx",
        type=Path,
        default=DEFAULT_OUTPUT_XLSX_PATH,
        help=f"Path to write the manual-tagging workbook. Defaults to {DEFAULT_OUTPUT_XLSX_PATH}",
    )
    parser.add_argument(
        "--sheet-name",
        default=DEFAULT_SHEET_NAME,
        help=f"Worksheet name to use. Defaults to {DEFAULT_SHEET_NAME!r}",
    )
    return parser.parse_args()


def detect_heading_category_for_tagging(label: str) -> str | None:
    key = heading_key(label)
    if key in PREFERRED_LABELS:
        return "preferred"
    if key in REQUIREMENT_LABELS:
        return "requirement"
    if key in ROLE_LABELS:
        return "role"
    if key in OVERVIEW_LABELS:
        return "overview"
    if key in SKIP_LABELS:
        return "noise"
    if "benefit" in key or "salary" in key or "application" in key or "questions" in key:
        return "noise"
    return None


def infer_category_for_tagging(text: str, current_category: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in NOISE_MARKERS):
        return "noise"
    if any(marker in lowered for marker in PREFERRED_MARKERS):
        return "preferred"
    if any(marker in lowered for marker in REQUIREMENT_MARKERS):
        return "requirement"
    return current_category


def should_skip_text_for_tagging(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if lowered in {"show more", "show less"}:
        return True
    if len(text.split()) < 2:
        return True
    return False


def itemize_job_text_for_tagging(job_text: str) -> list[tuple[str, str]]:
    lines = clean_text(job_text).split("\n")
    items: list[tuple[str, str]] = []
    seen_texts: set[tuple[str, str]] = set()
    current_category = "overview"

    for line in lines:
        heading_category = detect_heading_category_for_tagging(line)
        if heading_category is not None:
            current_category = heading_category
            continue

        if looks_like_heading(line):
            continue

        inline = split_inline_label(line)
        line_category = current_category
        emit_text = line

        if inline is not None:
            label, remainder = inline
            if heading_key(label) in SKIP_INLINE_LABELS:
                continue

            inline_category = detect_heading_category_for_tagging(label)
            if inline_category is not None:
                line_category = inline_category
                current_category = inline_category
            else:
                line_category = infer_category_for_tagging(remainder, current_category)
            emit_text = line
        else:
            line_category = infer_category_for_tagging(line, current_category)

        for segment in split_sentences(emit_text):
            if should_skip_text_for_tagging(segment):
                continue
            segment_category = infer_category_for_tagging(segment, line_category)
            dedupe_key = (segment_category, segment.lower())
            if dedupe_key in seen_texts:
                continue
            seen_texts.add(dedupe_key)
            items.append((segment_category, segment))

    return items


def load_grouped_results(input_path: Path) -> list[dict[str, object]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise ValueError(f"Expected top-level 'groups' list in {input_path}")

    records: list[dict[str, object]] = []
    global_index = 0
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError(f"Expected group object in {input_path}, found {type(group)!r}")

        group_key = sanitize_text(group.get("key"))
        group_label = sanitize_text(group.get("label"))
        results = group.get("deduped_results")
        if not isinstance(results, list):
            raise ValueError(f"Expected 'deduped_results' list for group {group_key!r}")

        for result_index, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                raise ValueError(f"Expected result object in group {group_key!r}")

            job_text = clean_text(str(result.get("job_text", "")))
            if not job_text:
                continue

            global_index += 1
            metadata = extract_url_metadata(str(result.get("url", "")), group_label or group_key, global_index)
            metadata["location"] = extract_location(job_text.split("\n"))

            source_queries = result.get("source_queries")
            if not isinstance(source_queries, list):
                source_queries = []

            itemized_segments = itemize_job_text_for_tagging(job_text)
            for item_index, (category, text) in enumerate(itemized_segments, start=1):
                records.append(
                    {
                        "id": f"{metadata['job_key']}__{category}__{item_index:03d}",
                        "group_key": group_key,
                        "group_label": group_label,
                        "job_key": metadata["job_key"],
                        "job_name": metadata["job_name"],
                        "company": metadata["company"],
                        "title": metadata["title"],
                        "location": metadata["location"],
                        "job_id": metadata["job_id"],
                        "category": category,
                        "text": text,
                        "source_file": metadata["source_file"],
                        "source_queries": source_queries,
                        "source_status": result.get("status"),
                        "source_note": result.get("note"),
                    }
                )

    if not records:
        raise ValueError(f"No itemized records were extracted from {input_path}")

    return records


def write_jsonl(output_path: Path, records: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def build_tagging_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        rows.append(
            {
                "id": sanitize_text(record.get("id")),
                "group": sanitize_text(record.get("group_label")),
                "title": sanitize_text(record.get("title")),
                "company": sanitize_text(record.get("company")),
                "category": sanitize_text(record.get("category")),
                "text": sanitize_text(record.get("text")),
                TAG_HEADER: "",
                "manual_notes": "",
                "source_queries": " | ".join(str(item) for item in record.get("source_queries", [])),
            }
        )
    return rows


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
            cells.append(
                cell_xml(
                    row_index,
                    column_index,
                    row[header],
                    style_id=2,
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
        records = load_grouped_results(args.input)
        write_jsonl(args.output_jsonl, records)
        workbook_rows = build_tagging_rows(records)
        write_workbook(args.output_xlsx, args.sheet_name, workbook_rows)
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to itemize crawler results for tagging: {exc}", file=sys.stderr)
        return 1

    category_counts = Counter(record["category"] for record in records)
    job_keys = {record["job_key"] for record in records}
    print(f"Wrote {len(records)} itemized records across {len(job_keys)} postings to {repo_relative_label(args.output_jsonl)}")
    print("Category counts:", json.dumps(category_counts, sort_keys=True))
    print(f"Wrote tagging workbook to {repo_relative_label(args.output_xlsx)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
