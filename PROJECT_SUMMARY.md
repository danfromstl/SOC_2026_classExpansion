# Project Summary

This repository builds a structured bridge from SOC 2018 occupation codes to O*NET occupational subgroups, tasks, DWAs, embeddings, and job-posting similarity matches.

At a high level, the workflow does four things:

1. Builds a clean SOC 2018 hierarchy from raw and manually flattened structure files.
2. Enriches that hierarchy with detailed descriptions and example titles.
3. Connects SOC 2018 detailed groups to O*NET-SOC 2019 subgroups, then to tasks and DWAs.
4. Embeds task text and uses those embeddings to compare job-posting line items against the task library.

## Pipeline Overview

The current pipeline is:

1. `sourceDocs/soc_structure_2018.xlsx`
   Produces `scripts/soc_2018_detailed_occupations.json`
2. `sourceDocs/soc_structure_2018_danEdit_flattened.xlsx`
   Produces `scripts/soc_2018_nested_groups.json`
3. `sourceDocs/ExtractedDetailedGroupDescriptions.xlsx`
   Enriches `scripts/soc_2018_nested_groups.json`
4. `sourceDocs/soc_2018_direct_match_title_file.xlsx`
   Enriches `scripts/soc_2018_nested_groups.json`
5. `sourceDocs/2019_to_SOC_Crosswalk.xlsx`
   Produces `scripts/soc2018_to_onet2019_crosswalk.json`
6. `sourceDocs/Tasks to DWAs.xlsx`
   Produces `scripts/tasks_to_dwas.json`
7. `scripts/tasks_to_dwas.json`
   Produces `scripts/task_dwa_embeddings_all_mpnet_base_v2.json`
8. `jobPostings/*.jsonl`
   Produces job-posting task-match JSON outputs
9. Job-posting task-match JSON outputs
   Produce a flattened Excel review workbook

## Source Documents

These are the primary source inputs currently used by the scripts:

- `sourceDocs/soc_structure_2018.xlsx`
  Original SOC 2018 structure workbook used for the first detailed lookup cache.
- `sourceDocs/soc_structure_2018_danEdit_flattened.xlsx`
  Flattened hierarchy workbook where each row already contains its higher-level category values.
- `sourceDocs/ExtractedDetailedGroupDescriptions.xlsx`
  Detailed SOC group descriptions used to attach a `description` field to detailed nodes.
- `sourceDocs/soc_2018_direct_match_title_file.xlsx`
  Direct-match title workbook used to populate `key_title_examples` and `other_title_examples`.
- `sourceDocs/2019_to_SOC_Crosswalk.xlsx`
  Crosswalk between SOC 2018 detailed groups and O*NET-SOC 2019 occupation codes.
- `sourceDocs/Tasks to DWAs.xlsx`
  O*NET task-to-DWA mapping source used to build the task library.

Reference files currently present but not part of the main scripted pipeline:

- `sourceDocs/soc_2018_definitions.xlsx`
- `sourceDocs/soc_structure_2018_danEdit.xlsx`
- `sourceDocs/ForTheUninitiated_lol_-_onet_x_soc_taxonomy.png`

## Script Inventory

### SOC Structure and Lookup

- `scripts/lookup_soc_2018.py`
  Reads `soc_structure_2018.xlsx`, extracts detailed occupation codes and titles, caches them in JSON, and supports direct code lookup.
- `scripts/build_soc_nested_groups.py`
  Builds the nested SOC hierarchy JSON from the flattened structure workbook and enriches detailed groups with descriptions and example titles.
- `scripts/lookup_SOC_v2.py`
  Reads the nested hierarchy JSON and prints the group name, group type, parent categories, and one-level child categories.
- `scripts/soc_lookup_v3.py`
  Extends v2 by also reading the SOC-to-O*NET crosswalk and task JSON so it can show O*NET subgroups and detailed task/DWA expansions.

### Crosswalks, Tasks, and Embeddings

- `scripts/build_soc2018_to_onet2019_crosswalk.py`
  Converts the SOC 2018 to O*NET-SOC 2019 workbook into a JSON crosswalk indexed in both directions.
- `scripts/build_tasks_to_dwas.py`
  Converts the O*NET Tasks-to-DWAs workbook into grouped JSON keyed by O*NET-SOC code.
- `scripts/build_task_dwa_embeddings.py`
  Uses `sentence-transformers/all-mpnet-base-v2` to embed task text and DWA titles while deduplicating repeated text before encoding.

### Job Posting Matching and Review

- `scripts/match_job_postings_to_tasks.py`
  Embeds each job-posting item and compares it against the task embedding library to return the nearest task matches.
- `scripts/export_task_matches_to_excel.py`
  Flattens one or more job-posting match JSON files into a single `.xlsx` workbook for manual review.

## Outputs and Data Files

### Core SOC Outputs

- `scripts/soc_2018_detailed_occupations.json`
  Simple lookup cache of detailed SOC 2018 codes to titles.
  Current count: 867 detailed occupation codes.
- `scripts/soc_2018_nested_groups.json`
  Fully nested SOC hierarchy with major, minor, broad, and detailed groups.
  Current group counts: 23 major, 98 minor, 459 broad, 867 detailed.
  Current enrichment counts: 867 detailed descriptions, 864 detailed groups with direct-match titles, 2,408 key title examples, and 4,112 other title examples.

### O*NET Mapping Outputs

- `scripts/soc2018_to_onet2019_crosswalk.json`
  SOC 2018 to O*NET-SOC 2019 crosswalk with:
  `rows`, `by_soc_2018_code`, and `by_onet_soc_2019_code`.
  Current counts: 1,016 crosswalk rows, 867 SOC 2018 codes, and 1,016 O*NET-SOC 2019 codes.
- `scripts/tasks_to_dwas.json`
  Grouped task-to-DWA library keyed by O*NET-SOC code.
  Current counts: 23,233 rows, 923 O*NET-SOC codes, 18,495 unique tasks, and 2,082 unique DWA IDs.

### Embedding Output

- `scripts/task_dwa_embeddings_all_mpnet_base_v2.json`
  Deduplicated embedding library for task text and DWA titles.
  Model: `sentence-transformers/all-mpnet-base-v2`
  Current counts: 18,495 task occurrences, 17,238 unique task texts, 23,233 DWA occurrences, 2,082 unique DWA titles, and 19,313 unique embedded texts.
  Embedding size: 768 dimensions.

### Job Posting Inputs

- `jobPostings/job_postings_itemized_for_embeddings_firstTwoExamples.jsonl`
  45 itemized posting records across:
  `mastercard_senior_product_manager_technical_r267359`
  `slalom_senior_principal_product_management_delivery_jo260227275`
- `jobPostings/job_postings_itemized_for_embeddings.jsonl`
  54 itemized posting records across:
  `emerson_senior_product_manager_26002939`
  `enterprise_mobility_product_manager_ii_enterprise_applications`
  `microsoft_senior_product_manager_200015570`

### Job Posting Matching Outputs

- `jobPostings/job_postings_itemized_for_embeddings_firstTwoExamples_top5_task_matches.json`
  Top-5 task matches for the first two example listings.
  Current size: 45 matched posting items.
- `jobPostings/job_postings_itemized_for_embeddings_top5_task_matches.json`
  Top-5 task matches for the next three listings.
  Current size: 54 matched posting items.
- `jobPostings/job_postings_all_top5_task_matches.xlsx`
  Flattened Excel review export combining both match JSONs.
  Current size: 495 flattened rows.

## Data Relationships

The important data relationships are:

- SOC 2018 detailed code -> detailed SOC title
- SOC 2018 detailed code -> nested SOC parent hierarchy
- SOC 2018 detailed code -> description and example titles
- SOC 2018 detailed code -> O*NET-SOC 2019 subgroup code(s)
- O*NET-SOC 2019 subgroup code -> task(s)
- task -> DWA(s)
- task text and DWA title -> embedding vector
- job-posting item text -> nearest task matches

## Current Repo State

The repository now supports three levels of use:

1. Simple SOC code lookup
2. Hierarchical SOC and O*NET inspection
3. Embedding-based comparison between job-posting text and the task library

This makes the repo usable both as a taxonomy exploration tool and as a base for future crosswalk or semantic-matching work.
