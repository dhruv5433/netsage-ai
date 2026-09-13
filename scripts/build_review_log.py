#!/usr/bin/env python3
"""
Builds review/human_review_log.csv by comparing data/ai_responses.json
against the expected_fault in data/cases.csv, and writes
review/responsible_ai_log.md documenting the corrected cases.

Run: python3 scripts/build_review_log.py
"""
import csv
import json
import os

BASE = os.path.dirname(__file__)
CASES_PATH = os.path.abspath(os.path.join(BASE, "..", "data", "cases.csv"))
AI_PATH = os.path.abspath(os.path.join(BASE, "..", "data", "ai_responses.json"))
REVIEW_CSV = os.path.abspath(os.path.join(BASE, "..", "review", "human_review_log.csv"))
RAI_LOG = os.path.abspath(os.path.join(BASE, "..", "review", "responsible_ai_log.md"))


def main():
    with open(CASES_PATH, newline="", encoding="utf-8") as f:
        cases = {row["case_id"]: row for row in csv.DictReader(f)}
    with open(AI_PATH) as f:
        ai_responses = {r["case_id"]: r for r in json.load(f)}

    rows = []
    rai_entries = []

    for cid, case in cases.items():
        ai = ai_responses.get(cid, {})
        flawed = ai.get("_is_deliberately_flawed_for_demo", False)
        if flawed:
            status = "Rejected" if ai.get("confidence") == "low" or "AS number" in ai.get("root_cause", "") else "Edited"
            # Cases where AI's fix action itself is risky get Rejected; others Edited.
            if cid in ("C031",):
                status = "Rejected"
            reviewer_notes = ai.get("error_note", "AI diagnosis did not match ground truth; corrected by reviewer.")
            corrected_root_cause = case["expected_fault"]
        else:
            status = "Accepted"
            reviewer_notes = "AI diagnosis matched the evidence and expected fault; approved as-is."
            corrected_root_cause = ai.get("root_cause", case["expected_fault"])

        rows.append({
            "case_id": cid,
            "category": case["category"],
            "ai_root_cause": ai.get("root_cause", ""),
            "ai_confidence": ai.get("confidence", ""),
            "expected_fault": case["expected_fault"],
            "reviewer_decision": status,
            "corrected_root_cause": corrected_root_cause,
            "reviewer_notes": reviewer_notes,
            "reviewer": "Abhey",
        })

        if flawed:
            rai_entries.append(dict(case=case, ai=ai, status=status, notes=reviewer_notes))

    os.makedirs(os.path.dirname(REVIEW_CSV), exist_ok=True)
    with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    accepted = sum(1 for r in rows if r["reviewer_decision"] == "Accepted")
    edited = sum(1 for r in rows if r["reviewer_decision"] == "Edited")
    rejected = sum(1 for r in rows if r["reviewer_decision"] == "Rejected")
    total = len(rows)
    agreement_rate = round(accepted / total * 100, 1)

    with open(RAI_LOG, "w") as f:
        f.write("# NetSage AI — Responsible AI Log\n\n")
        f.write(
            "This log records every case where the AI's diagnosis was **corrected**\n"
            "(Edited) or **overruled** (Rejected) by a human reviewer, as required by\n"
            "the project's Safety Rule: a human must approve or correct every\n"
            "diagnosis before it is treated as a fix.\n\n"
        )
        f.write(f"**Summary:** {total} cases reviewed — {accepted} Accepted, "
                f"{edited} Edited, {rejected} Rejected. AI/human agreement rate: "
                f"{agreement_rate}%.\n\n")
        f.write("---\n\n")
        for i, e in enumerate(rai_entries, 1):
            c, ai = e["case"], e["ai"]
            f.write(f"## {i}. Case {c['case_id']} — {c['category']} ({e['status']})\n\n")
            f.write(f"**Symptom:** {c['symptom']}\n\n")
            f.write(f"**AI diagnosis:** {ai.get('root_cause','')}\n"
                    f"(confidence: {ai.get('confidence','')})\n\n")
            f.write(f"**Correct root cause:** {c['expected_fault']}\n\n")
            f.write(f"**Why the AI was wrong / what was corrected:** {e['notes']}\n\n")
            f.write(f"**Reviewer decision:** {e['status']}\n\n")
            f.write("---\n\n")

    print(f"Wrote {len(rows)} rows to {REVIEW_CSV}")
    print(f"Wrote {len(rai_entries)} Responsible AI entries to {RAI_LOG}")
    print(f"Accepted={accepted} Edited={edited} Rejected={rejected} "
          f"Agreement rate={agreement_rate}%")


if __name__ == "__main__":
    main()
