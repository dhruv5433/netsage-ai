#!/usr/bin/env python3
"""
Injects dashboard/summary.json and the flawed-case rows from
review/human_review_log.csv into dashboard/dashboard.html so the file
is a standalone, double-clickable HTML dashboard.

Run: python3 scripts/build_dashboard_data.py && python3 scripts/render_dashboard.py
"""
import csv
import json
import os

BASE = os.path.dirname(__file__)
SUMMARY = os.path.abspath(os.path.join(BASE, "..", "dashboard", "summary.json"))
REVIEW = os.path.abspath(os.path.join(BASE, "..", "review", "human_review_log.csv"))
TEMPLATE = os.path.abspath(os.path.join(BASE, "..", "dashboard", "dashboard_template.html"))
OUT = os.path.abspath(os.path.join(BASE, "..", "dashboard", "dashboard.html"))


def main():
    with open(SUMMARY) as f:
        summary = json.load(f)
    with open(REVIEW, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rai_sample = [r for r in rows if r["reviewer_decision"] in ("Edited", "Rejected")]

    with open(TEMPLATE) as f:
        html = f.read()

    html = html.replace("__SUMMARY_JSON__", json.dumps(summary))
    html = html.replace("__RAI_SAMPLE_JSON__", json.dumps(rai_sample))

    with open(OUT, "w") as f:
        f.write(html)
    print(f"Rendered {OUT}")


if __name__ == "__main__":
    main()
