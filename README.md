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

Use `scripts/lookup_SOC_v2.py` to build a nested hierarchy from `sourceDocs/soc_structure_2018_danEdit_flattened.xlsx` and look up any SOC group code.

Examples:

```bash
python scripts/lookup_SOC_v2.py 15-1251
python scripts/lookup_SOC_v2.py 15-1250
python scripts/lookup_SOC_v2.py --json 15-1251
python scripts/lookup_SOC_v2.py --refresh 15-1251
```

The script writes the nested hierarchy to `scripts/soc_2018_nested_groups.json` and returns the group type, any parent categories, and the group name for the code you query.
