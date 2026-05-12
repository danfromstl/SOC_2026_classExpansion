#!/usr/bin/env python3
"""
SOC Task Classifier
-------------------
Classifies job description snippets against O*NET SOC 15-1212
(Information Security Analyst) tasks using Claude Haiku.

Usage:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...   # or paste it into the config below
    python soc_task_classifier.py

Output:
    soc_classification_results.jsonl  — one JSON record per snippet
    soc_classification_summary.txt    — human-readable summary
"""

import json
import os
import time
from pathlib import Path

import anthropic

# ─────────────────────────────────────────────
# CONFIG — edit these
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "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")

# Point this at your actual JSONL file when you're ready to run for real.
# Set to None to use the built-in test snippets below.
INPUT_JSONL_PATH = None  # e.g. "relevance_skip_title_relevance_scored.jsonl"

# SOC code and role we're classifying against
TARGET_SOC_CODE = "15-1212"
TARGET_SOC_TITLE = "Information Security Analyst"

# How many snippets to process (set to None for all)
MAX_SNIPPETS = 20

# Delay between API calls in seconds (be kind to rate limits)
DELAY_SECONDS = 0.3

OUTPUT_JSONL = "soc_classification_results.jsonl"
OUTPUT_SUMMARY = "soc_classification_summary.txt"

# ─────────────────────────────────────────────
# SOC 15-1212 TASKS (O*NET 2018)
# ─────────────────────────────────────────────

SOC_TASKS = [
    {"id": "5313", "text": "Train users and promote security awareness to ensure system security and to improve server and network efficiency."},
    {"id": "5314", "text": "Develop plans to safeguard computer files against accidental or unauthorized modification, destruction, or disclosure and to meet emergency data processing needs."},
    {"id": "5315", "text": "Confer with users to discuss issues such as computer data access needs, security violations, and programming changes."},
    {"id": "5316", "text": "Monitor current reports of computer viruses to determine when to update virus protection systems."},
    {"id": "5317", "text": "Modify computer security files to incorporate new software, correct errors, or change individual access status."},
    {"id": "5318", "text": "Coordinate implementation of computer system plan with establishment personnel and outside vendors."},
    {"id": "5319", "text": "Monitor use of data files and regulate access to safeguard information in computer files."},
    {"id": "5320", "text": "Perform risk assessments and execute tests of data processing system to ensure functioning of data processing activities and security measures."},
    {"id": "5321", "text": "Encrypt data transmissions and erect firewalls to conceal confidential information as it is being transmitted and to keep out tainted digital transfers."},
    {"id": "5322", "text": "Document computer security and emergency measures policies, procedures, and tests."},
    {"id": "5323", "text": "Review violations of computer security procedures and discuss procedures with violators to ensure violations are not repeated."},
]

# ─────────────────────────────────────────────
# TEST SNIPPETS (used when INPUT_JSONL_PATH is None)
# ─────────────────────────────────────────────
# These are real examples drawn from your actual data files.

TEST_SNIPPETS = [
    {
        "id": "test_001",
        "job": "Information System Security Officer",
        "text": "Monitor security information and event management (SIEM) systems and other security tools for suspicious activity.",
    },
    {
        "id": "test_002",
        "job": "Information System Security Officer",
        "text": "Triage and prioritize security alerts and events based on their potential risk and impact.",
    },
    {
        "id": "test_003",
        "job": "Information System Security Officer",
        "text": "Analyze network traffic, log data, and system alerts to identify potential security incidents.",
    },
    {
        "id": "test_004",
        "job": "Information System Security Officer",
        "text": "Follow established incident response playbooks to investigate and contain security incidents.",
    },
    {
        "id": "test_005",
        "job": "Information System Security Officer",
        "text": "Assist in performing routine vulnerability scans on internal and external systems.",
    },
    {
        "id": "test_006",
        "job": "Information System Security Officer",
        "text": "Assess breaches of security to determine their impact on system operations and the confidentiality, integrity, and reliability of the information stored.",
    },
    {
        "id": "test_007",
        "job": "Information System Security Officer",
        "text": "User creation and conditional email assignment of user and administrative accounts on CGFS General Support Systems.",
    },
    {
        "id": "test_008",
        "job": "Information System Security Officer",
        "text": "Active role in network and systems design to ensure that appropriate systems security policies and procedures are contemplated and introduced into design.",
    },
    {
        "id": "test_009",
        "job": "Security Analyst",
        "text": "You'll be responsible for analyzing network traffic to identify threats, executing incident response playbooks to contain breaches, and collaborating with senior analysts on root cause investigations to ensure effective remediation.",
    },
    {
        "id": "test_010",
        "job": "Security Analyst",
        "text": "Beyond active defense, you will drive proactive security measures by conducting vulnerability scans and coordinating with IT teams to ensure timely patching.",
    },
    {
        "id": "test_011",
        "job": "Security Analyst",
        "text": "Your role also involves maintaining documentation of incidents and fostering a culture of vigilance by developing security awareness materials and educating colleagues on essential best practices like phishing prevention.",
    },
    {
        "id": "test_012",
        "job": "Information System Security Officer",
        "text": "Four-year degree in computer science, business, or closely related area.",
    },
    {
        "id": "test_013",
        "job": "Information System Security Officer",
        "text": "Security+ certification is required.",
    },
    {
        "id": "test_014",
        "job": "AI Safety Engineer",
        "text": "Design and implement safety evaluation frameworks to assess risks in large language model deployments, including red-teaming, adversarial testing, and alignment verification.",
    },
    {
        "id": "test_015",
        "job": "AI Safety Engineer",
        "text": "Collaborate with ML researchers to identify and mitigate potential failure modes in AI systems before production deployment.",
    },
    {
        "id": "test_016",
        "job": "Information System Security Officer",
        "text": "new IA developments and applications",
    },
    {
        "id": "test_017",
        "job": "Information System Security Officer",
        "text": "project management principles and methods.",
    },
    {
        "id": "test_018",
        "job": "Security Analyst",
        "text": "Monitor CrowdStrike Falcon alerts, investigate endpoint detections, and escalate confirmed incidents to the IR team.",
    },
    {
        "id": "test_019",
        "job": "Security Analyst",
        "text": "Build and tune Splunk dashboards to surface anomalous authentication patterns and lateral movement indicators.",
    },
    {
        "id": "test_020",
        "job": "Information System Security Officer",
        "text": "CGFS Charleston ISSO Information Assurance and Risk Management Framework (RMF).",
    },
]

# ─────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────

def build_system_prompt():
    task_list = "\n".join(
        f"  [{t['id']}] {t['text']}" for t in SOC_TASKS
    )
    return f"""You are a labor economist classifying job description snippets against O*NET SOC occupational tasks.

The target occupation is: {TARGET_SOC_TITLE} (SOC {TARGET_SOC_CODE})

O*NET tasks for this occupation (from the 2018 SOC system):
{task_list}

For each snippet, respond with a single JSON object using this exact schema:

{{
  "classification": "<see labels below>",
  "matched_task_ids": ["5313", ...],   // list of matching task IDs, or empty []
  "reasoning": "<1-2 sentence explanation>",
  "new_technology_noted": "<tool/tech name if relevant, else null>",
  "subtasks": ["...", "..."]           // only populated for MULTI_TASK, else []
}}

Classification labels:
- EXACT_MATCH       : snippet clearly maps to one or more SOC tasks (same concept, similar wording)
- CONCEPT_MATCH     : same underlying work as a SOC task, but uses modern tooling/terminology not in 2018 SOC (e.g. SIEM, Splunk, CrowdStrike, EDR, cloud, zero-trust)
- ROLE_EXTENSION    : a task that belongs to this role but is genuinely absent from the 2018 SOC (e.g. threat hunting, AI-assisted detection) — suggest which existing task it extends
- NEW_ROLE          : suggests a distinct new occupation not covered by {TARGET_SOC_CODE} (e.g. AI Safety Engineer, ML Security Researcher)
- MULTI_TASK        : snippet contains 2+ distinct tasks — decompose into subtasks and classify each subtask separately in the subtasks array
- NOT_RELEVANT      : boilerplate text, job requirements, credentials, education, or skills — not a task description

Return ONLY the JSON object. No preamble, no markdown fences."""


def build_user_prompt(snippet_text):
    return f'Classify this job description snippet:\n\n"{snippet_text}"'


# ─────────────────────────────────────────────
# CLASSIFIER
# ─────────────────────────────────────────────

def classify_snippet(client, snippet_text, system_prompt):
    """Call Haiku and parse the JSON response."""
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": build_user_prompt(snippet_text)}
        ],
    )

    raw = message.content[0].text.strip()

    # Strip markdown fences if the model added them anyway
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return {"classification": "PARSE_ERROR", "raw_response": raw}, raw


# ─────────────────────────────────────────────
# LOADER
# ─────────────────────────────────────────────

def load_snippets(path, max_count):
    snippets = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            text = d.get("relevance_filter", {}).get("input_text", "").strip()
            if not text or len(text) < 10:
                continue
            snippets.append({
                "id": d.get("id", ""),
                "job": d.get("job_name", ""),
                "text": text,
                "original_label": d.get("relevance_filter", {}).get("label", ""),
            })
            if max_count and len(snippets) >= max_count:
                break
    return snippets


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    if ANTHROPIC_API_KEY.startswith("sk-ant-PASTE"):
        print("ERROR: Please set your Anthropic API key in the script or via the ANTHROPIC_API_KEY env variable.")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system_prompt = build_system_prompt()

    # Load snippets
    if INPUT_JSONL_PATH and Path(INPUT_JSONL_PATH).exists():
        print(f"Loading snippets from {INPUT_JSONL_PATH}...")
        snippets = load_snippets(INPUT_JSONL_PATH, MAX_SNIPPETS)
    else:
        print("No input file set (or file not found) — using built-in test snippets.")
        snippets = TEST_SNIPPETS[:MAX_SNIPPETS] if MAX_SNIPPETS else TEST_SNIPPETS

    print(f"Processing {len(snippets)} snippets with Claude Haiku ({TARGET_SOC_CODE})...\n")

    results = []
    counts = {}

    with open(OUTPUT_JSONL, "w", encoding="utf-8") as out_f:
        for i, snippet in enumerate(snippets, 1):
            print(f"[{i:02d}/{len(snippets)}] {snippet['text'][:80]}...")

            result, raw = classify_snippet(client, snippet["text"], system_prompt)
            label = result.get("classification", "ERROR")
            counts[label] = counts.get(label, 0) + 1

            record = {
                "snippet_id": snippet.get("id", f"snippet_{i:04d}"),
                "job": snippet.get("job", ""),
                "text": snippet["text"],
                "original_label": snippet.get("original_label", ""),
                "classification": label,
                "matched_task_ids": result.get("matched_task_ids", []),
                "reasoning": result.get("reasoning", ""),
                "new_technology_noted": result.get("new_technology_noted"),
                "subtasks": result.get("subtasks", []),
            }

            print(f"          -> {label}", end="")
            if result.get("matched_task_ids"):
                print(f"  (tasks: {result['matched_task_ids']})", end="")
            if result.get("new_technology_noted"):
                print(f"  [new tech: {result['new_technology_noted']}]", end="")
            print()

            results.append(record)
            out_f.write(json.dumps(record) + "\n")

            if i < len(snippets):
                time.sleep(DELAY_SECONDS)

    # -- Summary --
    print("\n" + "-"*60)
    print("CLASSIFICATION SUMMARY")
    print("-"*60)
    total = len(results)
    for label, count in sorted(counts.items(), key=lambda x: -x[1]):
        bar = "#" * count
        print(f"  {label:<20} {count:3d} ({count/total*100:.0f}%)  {bar}")

    print(f"\nTotal processed: {total}")
    print(f"Results saved to: {OUTPUT_JSONL}")

    # Notable cases worth human review
    interesting = [
        r for r in results
        if r["classification"] in ("CONCEPT_MATCH", "ROLE_EXTENSION", "NEW_ROLE", "MULTI_TASK")
    ]
    if interesting:
        print("\n" + "-"*60)
        print(f"FLAGGED FOR REVIEW ({len(interesting)} snippets)")
        print("-"*60)
        for r in interesting:
            print(f"\n  [{r['classification']}] {r['job']}")
            print(f"  Text: {r['text'][:120]}")
            print(f"  Reason: {r['reasoning']}")
            if r.get("new_technology_noted"):
                print(f"  New tech: {r['new_technology_noted']}")
            if r.get("subtasks"):
                for st in r["subtasks"]:
                    print(f"    * {st}")

    # Write human-readable summary file
    with open(OUTPUT_SUMMARY, "w", encoding="utf-8") as sf:
        sf.write("SOC Task Classification Results\n")
        sf.write(f"Target: {TARGET_SOC_TITLE} ({TARGET_SOC_CODE})\n")
        sf.write(f"Total snippets: {total}\n\n")
        sf.write("COUNTS BY LABEL\n" + "-"*40 + "\n")
        for label, count in sorted(counts.items(), key=lambda x: -x[1]):
            sf.write(f"  {label:<20} {count:3d} ({count/total*100:.0f}%)\n")
        sf.write("\nFLAGGED FOR REVIEW\n" + "-"*40 + "\n")
        for r in interesting:
            sf.write(f"\n[{r['classification']}] {r['job']}\n")
            sf.write(f"Text: {r['text']}\n")
            sf.write(f"Reason: {r['reasoning']}\n")
            if r.get("new_technology_noted"):
                sf.write(f"New tech: {r['new_technology_noted']}\n")
            if r.get("subtasks"):
                sf.write("Subtasks:\n")
                for st in r["subtasks"]:
                    sf.write(f"  * {st}\n")

    print(f"\nSummary saved to: {OUTPUT_SUMMARY}")
    print("\nDone!")


if __name__ == "__main__":
    main()
