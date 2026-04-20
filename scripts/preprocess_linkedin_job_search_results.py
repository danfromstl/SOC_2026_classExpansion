#!/usr/bin/env python3
"""Preprocess LinkedIn job-search scrape JSON into itemized JSONL for task matching."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = REPO_ROOT / "jobPostings" / "linkedin_job_search_results.json"
DEFAULT_OUTPUT_PATH = (
    REPO_ROOT / "jobPostings" / "linkedin_job_search_results_itemized_for_embeddings.jsonl"
)

WHITESPACE_PATTERN = re.compile(r"[ \t]+")
JOB_VIEW_PATTERN = re.compile(r"/jobs/view/(?P<slug>[^/?#]+)")
TRAILING_JOB_ID_PATTERN = re.compile(r"-(?P<job_id>\d+)$")
ITEM_INDEX_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
CITY_STATE_PATTERN = re.compile(r"^[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}$")

ROLE_LABELS = {
    "job responsibilities",
    "responsibilities",
    "responsibility",
    "essential duties and responsibilities",
    "essential duties",
    "key responsibilities",
    "what you'll do",
    "what you’ll do",
    "what you will do",
    "what you'll achieve",
    "what you’ll achieve",
    "what does the day-to-day look like?",
    "what does the day-to-day look like",
    "in this role, you will",
    "the security analyst will play a key role in",
    "the analyst will play a key role in",
}
REQUIREMENT_LABELS = {
    "minimum requirements",
    "requirements",
    "minimum requirements for the role",
    "qualifications",
    "competencies",
    "education and/or experience",
    "education and experience",
    "about you",
    "what you'll bring",
    "what you’ll bring",
    "qualities that will help you thrive in this role",
    "our most successful employees in this position demonstrate",
    "other qualifications",
    "minimum qualifications",
    "knowledge of",
    "familiarity with",
}
PREFERRED_LABELS = {
    "preferred",
    "plusses",
    "an ideal candidate also has",
    "nice to have",
}
OVERVIEW_LABELS = {
    "department overview",
    "company summary",
    "company description",
    "job summary",
    "about the role",
    "about medallion",
    "about vallarta supermarkets",
    "what's the role?",
    "what’s the role?",
    "what's this team like at etsy?",
    "what’s this team like at etsy?",
}
SKIP_LABELS = {
    "salary range",
    "base salary",
    "annual base salary",
    "pay range",
    "total rewards",
    "what we'll offer",
    "what we’ll offer",
    "flexible working",
    "belonging at samsara",
    "accommodations",
    "our commitment to authenticity",
    "fraudulent employment offers",
    "about us",
    "our promise",
    "additional information",
    "what's next",
    "what’s next",
    "join asana’s talent network",
    "join asana's talent network",
    "security clearance requirement",
    "work schedule",
    "software systems utilized",
    "formal job-specific training requirements",
}
SKIP_INLINE_LABELS = {
    "location",
    "department",
    "reports to",
    "note",
    "job title",
}
COMPENSATION_MARKERS = (
    "salary",
    "equity",
    "bonus",
    "benefits",
    "equal opportunity",
    "visa sponsorship",
    "accommodation",
    "work authorization",
    "pay range",
)
COMMON_UPPER_TOKENS = {"ai", "api", "aws", "b2b", "crm", "gtm", "it", "llm", "ml", "pm", "saas", "soc", "ux", "ui"}
OVERVIEW_KEEP_MARKERS = (
    "analyst",
    "architect",
    "automation",
    "build",
    "business",
    "capabilit",
    "cloud",
    "compliance",
    "customer",
    "cyber",
    "data",
    "deploy",
    "detect",
    "develop",
    "engineer",
    "experience",
    "incident",
    "integrat",
    "investigat",
    "manage",
    "market",
    "model",
    "monitor",
    "network",
    "operation",
    "platform",
    "product",
    "project",
    "responsib",
    "risk",
    "roadmap",
    "role",
    "security",
    "solution",
    "strateg",
    "support",
    "system",
    "technology",
    "threat",
    "workflow",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert LinkedIn job-search scrape JSON into itemized JSONL for task matching."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Path to the LinkedIn search-results JSON. Defaults to {DEFAULT_INPUT_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the itemized JSONL. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    return parser.parse_args()


def clean_text(value: str | None) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00A0", " ")
    lines = []
    for raw_line in text.split("\n"):
        line = WHITESPACE_PATTERN.sub(" ", raw_line).strip()
        if not line:
            continue
        if line.lower() in {"show more", "show less"}:
            continue
        lines.append(line)
    return "\n".join(lines)


def slugify(value: str) -> str:
    return NON_WORD_PATTERN.sub("_", value.lower()).strip("_")


def humanize_slug(slug: str) -> str:
    tokens = [token for token in slug.replace("_", "-").split("-") if token]
    words: list[str] = []
    for token in tokens:
        if token in COMMON_UPPER_TOKENS:
            words.append(token.upper())
        elif token.isdigit():
            words.append(token)
        else:
            words.append(token.title())
    return " ".join(words)


def heading_key(value: str) -> str:
    lowered = value.lower().strip()
    lowered = lowered.rstrip(":")
    return lowered


def detect_heading_category(label: str) -> str | None:
    key = heading_key(label)
    if key in SKIP_LABELS:
        return "skip"
    if key in PREFERRED_LABELS:
        return "preferred"
    if key in REQUIREMENT_LABELS:
        return "requirement"
    if key in ROLE_LABELS:
        return "role"
    if key in OVERVIEW_LABELS:
        return "overview"
    return None


def looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.endswith(":") and len(stripped.split()) <= 10:
        return True
    if len(stripped) <= 70 and stripped == stripped.title() and stripped.lower() not in {"u.s.", "show more"}:
        return True
    if detect_heading_category(stripped) is not None:
        return True
    return False


def split_inline_label(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    label, remainder = line.split(":", 1)
    label = label.strip()
    remainder = remainder.strip()
    if not label or not remainder:
        return None
    if len(label.split()) > 8:
        return None
    return label, remainder


def infer_category_from_text(text: str, current_category: str) -> str:
    if current_category == "skip":
        return "skip"

    lowered = text.lower()
    if any(marker in lowered for marker in ("preferred", "nice to have", "plus", "plusses")):
        return "preferred"
    if any(
        marker in lowered
        for marker in (
            "years of experience",
            "degree",
            "certification",
            "knowledge of",
            "familiarity with",
            "ability to",
            "must have",
            "required",
            "qualification",
            "experience with",
        )
    ):
        return "requirement"
    return current_category


def split_sentences(text: str) -> list[str]:
    parts = [text]
    if ";" in text:
        semicolon_split = [part.strip() for part in text.split(";") if part.strip()]
        if len(semicolon_split) > 1:
            parts = semicolon_split

    sentences: list[str] = []
    for part in parts:
        if len(part) > 260 or part.count(".") > 1:
            sentences.extend(segment.strip() for segment in ITEM_INDEX_PATTERN.split(part) if segment.strip())
        else:
            sentences.append(part.strip())
    return sentences


def should_skip_text(text: str) -> bool:
    lowered = text.lower()
    if len(text.split()) < 3:
        return True
    if CITY_STATE_PATTERN.match(text):
        return True
    if lowered in {"show more", "show less"}:
        return True
    if any(marker in lowered for marker in COMPENSATION_MARKERS):
        return True
    if any(
        marker in lowered
        for marker in (
            "days on-site",
            "office-centric hybrid schedule",
            "work from home",
            "interviewing for this role",
            "candidate privacy notice",
            "official communication will only come",
            "equal employment opportunity",
            "all qualified applicants will receive consideration",
            "speak with your recruiter",
            "reasonable accommodations",
            "fraud detection tool",
            "talent network",
        )
    ):
        return True
    return False


def keep_overview_text(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in OVERVIEW_KEEP_MARKERS)


def extract_url_metadata(url: str, fallback_query: str, fallback_index: int) -> dict[str, str]:
    parsed = urlparse(url)
    path = parsed.path
    match = JOB_VIEW_PATTERN.search(path)
    slug = match.group("slug") if match else slugify(fallback_query) + f"-{fallback_index}"

    job_id = ""
    core_slug = slug
    job_id_match = TRAILING_JOB_ID_PATTERN.search(slug)
    if job_id_match:
        job_id = job_id_match.group("job_id")
        core_slug = slug[: job_id_match.start()]

    title_slug = core_slug
    company_slug = ""
    if "-at-" in core_slug:
        title_slug, company_slug = core_slug.rsplit("-at-", 1)

    title = humanize_slug(title_slug) or fallback_query
    company = humanize_slug(company_slug)
    job_name = f"{company} {title}".strip() if company else title

    key_parts = [slugify(company), slugify(title)]
    if job_id:
        key_parts.append(job_id)
    else:
        key_parts.append(f"{fallback_index:02d}")

    return {
        "job_key": "_".join(part for part in key_parts if part),
        "job_name": job_name,
        "company": company,
        "title": title,
        "job_id": job_id,
        "source_file": url,
    }


def extract_location(lines: list[str]) -> str:
    for line in lines[:20]:
        inline = split_inline_label(line)
        if inline is None:
            continue
        label, remainder = inline
        if heading_key(label) == "location":
            return remainder
    return ""


def itemize_job_text(job_text: str) -> list[tuple[str, str]]:
    lines = clean_text(job_text).split("\n")
    items: list[tuple[str, str]] = []
    seen_texts: set[tuple[str, str]] = set()
    current_category = "overview"

    for line in lines:
        heading_category = detect_heading_category(line)
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

            inline_category = detect_heading_category(label)
            if inline_category == "skip":
                continue
            if inline_category is not None:
                line_category = inline_category
                current_category = inline_category
            else:
                line_category = infer_category_from_text(remainder, current_category)
            emit_text = line
        else:
            line_category = infer_category_from_text(line, current_category)

        if line_category == "skip":
            continue

        for segment in split_sentences(emit_text):
            segment_category = infer_category_from_text(segment, line_category)
            if segment_category == "skip":
                continue
            if should_skip_text(segment):
                continue
            if segment_category == "overview" and not keep_overview_text(segment):
                continue
            dedupe_key = (segment_category, segment.lower())
            if dedupe_key in seen_texts:
                continue
            seen_texts.add(dedupe_key)
            items.append((segment_category, segment))

    return items


def load_results(input_path: Path) -> list[dict[str, object]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    queries = payload.get("queries")
    if not isinstance(queries, list):
        raise ValueError(f"Expected top-level 'queries' list in {input_path}")

    records: list[dict[str, object]] = []
    global_index = 0
    for query_index, query in enumerate(queries, start=1):
        query_name = str(query.get("query", "")).strip() or f"Query {query_index}"
        results = query.get("results")
        if not isinstance(results, list):
            raise ValueError(f"Expected 'results' list for query {query_name!r}")

        for result_index, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                raise ValueError(f"Expected result object for query {query_name!r}")

            job_text = clean_text(str(result.get("job_text", "")))
            if not job_text:
                continue

            global_index += 1
            metadata = extract_url_metadata(
                str(result.get("url", "")),
                query_name,
                global_index,
            )
            lines = job_text.split("\n")
            metadata["location"] = extract_location(lines)

            itemized_segments = itemize_job_text(job_text)
            for item_index, (category, text) in enumerate(itemized_segments, start=1):
                records.append(
                    {
                        "id": f"{metadata['job_key']}__{category}__{item_index:03d}",
                        "job_key": metadata["job_key"],
                        "job_name": metadata["job_name"],
                        "company": metadata["company"],
                        "title": metadata["title"],
                        "location": metadata["location"],
                        "job_id": metadata["job_id"],
                        "category": category,
                        "text": text,
                        "source_file": metadata["source_file"],
                        "search_query": query_name,
                        "search_result_rank": result_index,
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


def main() -> int:
    args = parse_args()

    try:
        records = load_results(args.input)
        write_jsonl(args.output, records)
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Failed to preprocess LinkedIn job-search results: {exc}", file=sys.stderr)
        return 1

    category_counts = Counter(record["category"] for record in records)
    job_keys = {record["job_key"] for record in records}
    print(f"Wrote {len(records)} itemized records across {len(job_keys)} postings to {args.output}")
    print("Category counts:", json.dumps(category_counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
