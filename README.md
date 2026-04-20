# SOC_2026_classExpansion
small tool to "fully expand" SOC classifications using O*NET's database of tasks, activities, skills, knowledge, technology skills, etc. 

## Project Summary

This repository builds a structured bridge from SOC 2018 occupation codes to O*NET occupational subgroups, tasks, DWAs, embeddings, and job-posting similarity matches.

The current workflow:

1. extracts SOC 2018 detailed occupations from the original structure workbook
2. builds a nested SOC hierarchy from the flattened structure workbook
3. enriches detailed groups with descriptions and direct-match title examples
4. maps SOC 2018 detailed groups to O*NET-SOC 2019 subgroup codes
5. maps O*NET-SOC codes to tasks and DWAs
6. embeds the task library with `sentence-transformers/all-mpnet-base-v2`
7. embeds itemized job-posting text and compares it to the task library
8. exports the results into JSON and Excel for manual review

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
- `scripts/match_job_postings_to_tasks.py`
- `scripts/export_task_matches_to_excel.py`

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
