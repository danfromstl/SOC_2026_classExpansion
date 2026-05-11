# SOC_2026_classExpansion
A tool to "fully expand" SOC classifications using O*NET's database of tasks, activities, skills, knowledge, technology skills, etc. — and to use real-world job posting data as empirical evidence for occupational taxonomy gaps.

## Long-Term Vision

The Bureau of Labor Statistics is planning a [2028 SOC revision](https://www.bls.gov/soc/notices/2024/next_revision.htm). A central goal of this project is to contribute to that process by demonstrating, quantitatively, where the current SOC 2018 classification fails to capture distinct clusters of real-world work.

Roles like *Product Manager*, *AI Safety Engineer*, *AI Harness Testing Specialist*, and *Transformer Model Training Specialist* represent work that is:
- **clearly distinct** from one another and from existing Detailed Occupational Groups (DOGs)
- **substantially present** in the current labor market, as evidenced by public job postings

This system is designed to make that case with data: by matching job postings against the O*NET task library and identifying where postings land in occupationally implausible places, we can surface clusters of activity that have no clean home in SOC 2018 — the raw material for new DOG proposals.

## Project Summary

This repository builds a structured bridge from SOC 2018 occupation codes to O*NET occupational subgroups, tasks, DWAs, embeddings, and job-posting similarity matches.

The current workflow:

1. extracts SOC 2018 detailed occupations from the original structure workbook
2. builds a nested SOC hierarchy from the flattened structure workbook
3. enriches detailed groups with descriptions and direct-match title examples
4. maps SOC 2018 detailed groups to O*NET-SOC 2019 subgroup codes
5. maps O*NET-SOC codes to tasks and DWAs
6. embeds the task library with `sentence-transformers/all-mpnet-base-v2`
7. scores itemized job-posting snippets with a reviewed relevance-filter bundle
8. embeds itemized job-posting text and compares it to the task library
9. exports the results into JSON and Excel for manual review

For a fuller project inventory, see [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md).

## Key Inputs

Primary source documents used by the pipeline:

- `sourceDocs/soc_structure_2018.xlsx`
- `sourceDocs/soc_structure_2018_danEdit_flattened.xlsx`
- `sourceDocs/ExtractedDetailedGroupDescriptions.xlsx`
- `sourceDocs/soc_2018_direct_match_title_file.xlsx`
- `sourceDocs/2019_to_SOC_Crosswalk.xlsx`
- `sourceDocs/Tasks to DWAs.xlsx`

Primary job-posting test inputs:

- `jobPostings/job_postings_itemized_for_embeddings_firstTwoExamples.jsonl`
- `jobPostings/job_postings_itemized_for_embeddings.jsonl`
- `jobPostings/linkedin_job_search_results.json`
  Raw LinkedIn scrape with 6 search queries and 36 full posting texts total.

## Generated Outputs

Core generated data files:

- `scripts/soc_2018_detailed_occupations.json`
  Detailed SOC lookup cache with 867 detailed occupation codes.
- `scripts/soc_2018_nested_groups.json`
  Nested SOC hierarchy with 23 major groups, 98 minor groups, 459 broad groups, and 867 detailed groups.
- `scripts/soc2018_to_onet2019_crosswalk.json`
  Crosswalk JSON with 1,016 rows linking SOC 2018 detailed groups to O*NET-SOC 2019 codes.
- `scripts/tasks_to_dwas.json`
  Task-to-DWA JSON with 23,233 rows across 923 O*NET-SOC codes.
- `scripts/task_dwa_embeddings_all_mpnet_base_v2.json`
  Deduplicated embedding library with 19,313 unique embedded texts at 768 dimensions.

Job-posting matching outputs:

- `jobPostings/job_postings_itemized_for_embeddings_firstTwoExamples_top5_task_matches.json`
  Top-5 task matches for 45 posting items across the first two example listings.
- `jobPostings/job_postings_itemized_for_embeddings_top5_task_matches.json`
  Top-5 task matches for 54 posting items across the next three listings.
- `jobPostings/linkedin_job_search_results_itemized_for_embeddings.jsonl`
  Preprocessed JSONL generated from the raw LinkedIn scrape, ready to feed into the existing matcher.
- `scripts/relevance_bundles/job_snippet_relevance_20260510T174010Z`
  Portable relevance scorer bundle exported from the tagging UI's reviewed snippets.
- `jobPostings/job_postings_all_top5_task_matches.xlsx`
  Flattened Excel review sheet with 495 rows across both match result files.

## Script Inventory

SOC hierarchy and lookup:

- `scripts/lookup_soc_2018.py`
- `scripts/build_soc_nested_groups.py`
- `scripts/lookup_SOC_v2.py`
- `scripts/soc_lookup_v3.py`

Crosswalks, tasks, and embeddings:

- `scripts/build_soc2018_to_onet2019_crosswalk.py`
- `scripts/build_tasks_to_dwas.py`
- `scripts/build_task_dwa_embeddings.py`

Job-posting matching and export:

- `scripts/preprocess_linkedin_job_search_results.py`
- `scripts/score_job_posting_relevance.py` - first-pass relevance scorer for itemized snippets
- `scripts/match_job_postings_to_tasks.py` — single-stage (baseline) matcher
- `scripts/run_pipeline.py` — orchestrates relevance scoring, two-stage matching, and run scoring
- `scripts/export_task_matches_to_excel.py`

Two-stage (DOG-filtered) matching pipeline:

- `scripts/build_dog_title_embeddings.py` — embeds DOG title examples for stage-1 classification
- `scripts/match_job_postings_two_stage.py` — DOG-filtered task matcher (improved precision)

Analysis and quality evaluation:

- `scripts/analyze_match_quality.py` — reports DOG alignment statistics for lineman postings
- `scripts/score_match_results.py` — records repeatable DOG-alignment metrics in `jobPostings/scoring_history.json`

## SOC 2018 detailed occupation lookup

Use `scripts/lookup_soc_2018.py` to resolve a detailed occupation code such as `15-1251` to its title.

Examples:

```bash
python scripts/lookup_soc_2018.py 15-1251
python scripts/lookup_soc_2018.py
python scripts/lookup_soc_2018.py --refresh 15-1251
```

The script reads `sourceDocs/soc_structure_2018.xlsx`, extracts the detailed occupation rows, and writes a JSON cache to `scripts/soc_2018_detailed_occupations.json` the first time it runs.

## SOC 2018 nested hierarchy lookup

Use `scripts/build_soc_nested_groups.py` to create the nested hierarchy JSON from `sourceDocs/soc_structure_2018_danEdit_flattened.xlsx`.
It also enriches detailed groups with:

- definitions from `sourceDocs/ExtractedDetailedGroupDescriptions.xlsx`
- direct match titles from `sourceDocs/soc_2018_direct_match_title_file.xlsx`, split into `key_title_examples` and `other_title_examples`

Examples:

```bash
python scripts/build_soc_nested_groups.py
python scripts/build_soc_nested_groups.py --descriptions-xlsx sourceDocs/ExtractedDetailedGroupDescriptions.xlsx
python scripts/build_soc_nested_groups.py --output scripts/soc_2018_nested_groups.json
```

The script writes the nested hierarchy to `scripts/soc_2018_nested_groups.json`. Detailed nodes include `description`, `key_title_examples`, and `other_title_examples`.

Use `scripts/lookup_SOC_v2.py` to read that JSON and return the group type, any parent categories, and the group name for a code.

Examples:

```bash
python scripts/lookup_SOC_v2.py 15-1251
python scripts/lookup_SOC_v2.py 15-1250
python scripts/lookup_SOC_v2.py --json 15-1251
```

Use `scripts/soc_lookup_v3.py` when you also want the matching O*NET-SOC 2019 subgroup list from `scripts/soc2018_to_onet2019_crosswalk.json`.

Examples:

```bash
python scripts/soc_lookup_v3.py 13-1041
python scripts/soc_lookup_v3.py 15-1250
python scripts/soc_lookup_v3.py --json 13-1041
```

The script keeps the v2 hierarchy output and adds:

- `O*NET Subgroups` with a count for any SOC code that appears in the crosswalk JSON
- `Detailed Tasks` for detailed SOC groups, grouped by O*NET subgroup and expanded to DWA IDs and DWA titles

## SOC 2018 to O*NET-SOC 2019 Crosswalk

Use `scripts/build_soc2018_to_onet2019_crosswalk.py` to convert `sourceDocs/2019_to_SOC_Crosswalk.xlsx` into JSON.

Examples:

```bash
python scripts/build_soc2018_to_onet2019_crosswalk.py
python scripts/build_soc2018_to_onet2019_crosswalk.py --output scripts/soc2018_to_onet2019_crosswalk.json
```

The script writes `scripts/soc2018_to_onet2019_crosswalk.json` with:

- `rows` for the raw crosswalk entries
- `by_soc_2018_code` for SOC-first lookup
- `by_onet_soc_2019_code` for O*NET-first lookup

## Tasks to DWAs

Use `scripts/build_tasks_to_dwas.py` to convert `sourceDocs/Tasks to DWAs.xlsx` into JSON.

Examples:

```bash
python scripts/build_tasks_to_dwas.py
python scripts/build_tasks_to_dwas.py --output scripts/tasks_to_dwas.json
```

The script writes `scripts/tasks_to_dwas.json` with:

- `rows` for the raw task-to-DWA table
- `by_onet_soc_code` for grouped lookup by O*NET-SOC code

## Task and DWA Embeddings

Use `scripts/build_task_dwa_embeddings.py` to generate deduplicated embeddings for task text and DWA titles with `sentence-transformers/all-mpnet-base-v2`.

Examples:

```bash
python scripts/build_task_dwa_embeddings.py
python scripts/build_task_dwa_embeddings.py --output scripts/task_dwa_embeddings_all_mpnet_base_v2.json
```

The script reads `scripts/tasks_to_dwas.json`, embeds each unique text once, and writes:

- `embeddings_by_key` with one embedding per unique text
- `by_onet_soc_code` with task and DWA references back to those embedding keys

## LinkedIn Job Search Preprocessing

Use `scripts/preprocess_linkedin_job_search_results.py` to convert the raw LinkedIn scrape JSON into the same itemized JSONL shape used by the existing task matcher.

Examples:

```bash
python scripts/preprocess_linkedin_job_search_results.py
python scripts/match_job_postings_to_tasks.py --input-jsonl jobPostings/linkedin_job_search_results_itemized_for_embeddings.jsonl --top-k 5
```

The preprocessor reads `jobPostings/linkedin_job_search_results.json` and writes `jobPostings/linkedin_job_search_results_itemized_for_embeddings.jsonl`.
It extracts lightweight metadata from the LinkedIn URLs, removes obvious scrape boilerplate such as `Show more` / `Show less`, and itemizes each posting into `overview`, `role`, `requirement`, and `preferred` snippets for downstream embedding and matching.

## Job Posting Relevance Filter

Use `scripts/score_job_posting_relevance.py` to run the portable relevance scorer before SOC/O*NET task matching.
The script adds a `relevance_filter` object to each JSONL row, using the versioned bundle named in `scripts/relevance_bundles/LATEST.txt`.

Examples:

```bash
python scripts/score_job_posting_relevance.py
python scripts/score_job_posting_relevance.py --limit 25 --output-jsonl jobPostings/relevance_smoke_test.jsonl
python scripts/score_job_posting_relevance.py --drop-not-relevant --drop-confidence 0.75 --output-jsonl jobPostings/linkedin_job_search_results_relevance_filtered.jsonl
```

Then feed the scored rows into the two-stage matcher and let it skip rows labeled `not_relevant`:

```bash
python scripts/match_job_postings_two_stage.py --input-jsonl jobPostings/linkedin_job_search_results_relevance_scored.jsonl --skip-not-relevant --skip-confidence 0.75
```

You can also pass a filtered JSONL directly if you used `--drop-not-relevant` in the scoring step.

The reusable Python API lives in `scripts/relevance_filter`:

```python
from relevance_filter import RelevanceScorer

scorer = RelevanceScorer.from_bundle("scripts/relevance_bundles/job_snippet_relevance_20260510T174010Z")
scores = scorer.score_texts(["Compensation ranges vary based on experience."])
```

## Pipeline Orchestrator

Use `scripts/run_pipeline.py` when you want one command to score relevance, run two-stage matching, and append DOG-alignment metrics to a history file.
By default it scores snippets and has the matcher skip high-confidence `not_relevant` rows before embedding.

Examples:

```bash
python scripts/run_pipeline.py --run-name relevance_skip_title
python scripts/run_pipeline.py --run-name relevance_drop_title_company --stage1-text-mode title_company --relevance-mode drop
python scripts/run_pipeline.py --run-name baseline_no_relevance --relevance-mode off
```

Key relevance options:

- `--relevance-mode skip` scores all rows and passes `--skip-not-relevant` into the matcher.
- `--relevance-mode drop` writes a filtered intermediate JSONL before matching.
- `--relevance-mode score` annotates rows but keeps all of them for matching.
- `--relevance-confidence 0.75` controls the skip/drop confidence threshold.

After several runs, compare them with:

```bash
python scripts/score_match_results.py --chart-only --chart-output jobPostings/pipeline_comparison.png
```

## Job Posting Task Matching

Use `scripts/match_job_postings_to_tasks.py` to embed each job posting item and retrieve the closest task matches from `scripts/task_dwa_embeddings_all_mpnet_base_v2.json`.

Examples:

```bash
python scripts/match_job_postings_to_tasks.py
python scripts/match_job_postings_to_tasks.py --input-jsonl jobPostings/job_postings_itemized_for_embeddings_firstTwoExamples.jsonl --top-k 5
```

The script writes a JSON file with the original posting item plus `top_task_matches`, including rank, score, task ID, O*NET-SOC code/title, and task text.

## Job Posting Match Excel Export

Use `scripts/export_task_matches_to_excel.py` to flatten one or more job-posting task-match JSON files into a single Excel workbook for review.

Examples:

```bash
python scripts/export_task_matches_to_excel.py
python scripts/export_task_matches_to_excel.py --inputs jobPostings/job_postings_itemized_for_embeddings_firstTwoExamples_top5_task_matches.json jobPostings/job_postings_itemized_for_embeddings_top5_task_matches.json
```

The workbook includes these columns:

- `OriginID`
- `Job Name`
- `Category`
- `Listing Text`
- `Dan Notes`
- `Task Text`
- `Rank`
- `Score`
- `Task ID`
- `O-SOC Code`
- `O-SOC Title`

## Two-Stage (DOG-Filtered) Matching

The single-stage matcher finds tasks whose text is semantically similar to a job posting bullet — but those tasks may belong to completely unrelated occupational groups. A lineman bullet about "replacing fuses" can surface tasks from Telecommunications Repairers, Computer Network Architects, or Industrial Machinery Mechanics — all reasonable text matches, none the right occupation.

**Baseline quality (lineman postings, measured):**
- Expected DOG (49-9051 electric / 49-9052 telecom) at rank-1: **1.0%** of entries
- Expected DOG anywhere in top-5: **12.7%** of entries

The two-stage approach fixes this by grounding task retrieval in occupational context:

**Stage 1 — DOG classification:** Embed the job title and find the top-N closest DOGs by cosine similarity to their pooled title-example embeddings. Requires building `scripts/dog_title_embeddings_all_mpnet_base_v2.json` first.

**Stage 2 — filtered task retrieval:** Restrict the task library to only tasks from the candidate DOGs (via the SOC 2018 → O*NET 2019 crosswalk), then run standard top-K matching against that subset.

### Step 1: Build DOG title embeddings (one-time)

```bash
python scripts/build_dog_title_embeddings.py
```

Embeds the name, title examples, and first-sentence description for all 867 SOC Detailed groups. Writes `scripts/dog_title_embeddings_all_mpnet_base_v2.json`.

### Step 2: Run two-stage matcher

```bash
# LinkedIn results (default):
python scripts/match_job_postings_two_stage.py

# Custom input, wider DOG net:
python scripts/match_job_postings_two_stage.py \
  --input-jsonl jobPostings/lineman_crawler_results_itemized_for_tagging.jsonl \
  --top-n-dogs 5 \
  --output jobPostings/lineman_crawler_two_stage_matches.json
```

Key options:
- `--top-n-dogs N` — how many DOG candidates to consider per job title (default: 3)
- `--top-k K` — task matches per posting item (default: 5)

Output JSON includes a `stage1_dog_candidates` field per result showing which DOGs were selected and their similarity scores, making the classification transparent and auditable.

## Match Quality Analysis

Use `scripts/analyze_match_quality.py` to check what fraction of top-5 task matches come from expected DOGs for lineman job postings. Requires no external dependencies.

```bash
python scripts/analyze_match_quality.py
python scripts/analyze_match_quality.py --input jobPostings/linkedin_job_search_results_two_stage_top5_task_matches.json
```

Run against both the baseline and two-stage output files to compare DOG alignment rates before and after the pipeline change.
