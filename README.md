# SOC_2026_classExpansion
small tool to "fully expand" SOC classifications using O*NET's database of tasks, activities, skills, knowledge, technology skills, etc. 

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
