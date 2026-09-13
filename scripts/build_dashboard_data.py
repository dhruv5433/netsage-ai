#!/usr/bin/env python3
"""
Aggregates cases.csv + human_review_log.csv into dashboard/summary.json,
which dashboard/dashboard.html renders as charts.

Run: python3 scripts/build_dashboard_data.py
"""
import csv
import json
import os
from collections import Counter

BASE = os.path.dirname(__file__)
CASES = os.path.abspath(os.path.join(BASE, "..", "data", "cases.csv"))
REVIEW = os.path.abspath(os.path.join(BASE, "..", "review", "human_review_log.csv"))
OUT = os.path.abspath(os.path.join(BASE, "..", "dashboard", "summary.json"))


def main():
    with open(CASES, newline="", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    with open(REVIEW, newline="", encoding="utf-8") as f:
        review = list(csv.DictReader(f))

    by_category = Counter(c["category"] for c in cases)
    by_severity = Counter(c["severity"] for c in cases)
    by_osi = Counter(c["osi_layer"] for c in cases)
    by_decision = Counter(r["reviewer_decision"] for r in review)

    total = len(review)
    accepted = by_decision.get("Accepted", 0)
    agreement_rate = round(accepted / total * 100, 1) if total else 0

    summary = {
        "total_cases": len(cases),
        "by_category": dict(sorted(by_category.items(), key=lambda x: -x[1])),
        "by_severity": dict(by_severity),
        "by_osi_layer": dict(sorted(by_osi.items(), key=lambda x: -x[1])),
        "by_reviewer_decision": dict(by_decision),
        "ai_human_agreement_rate_pct": agreement_rate,
    }

    with open(OUT, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
