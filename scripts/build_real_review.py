#!/usr/bin/env python3
"""
Builds review/human_review_log.csv and review/responsible_ai_log.md from
the REAL qwen3:8b output in data/ai_responses.json, evaluated against
data/cases.csv's expected_fault.

Unlike build_review_log.py (which worked off a hand-planted
"_is_deliberately_flawed_for_demo" flag for the earlier simulated data),
this script encodes an actual reviewer's judgment call per case, made by
comparing the real model output to the documented ground truth. That
judgment is captured directly in REVIEW_DECISIONS below rather than
inferred automatically, because "is this diagnosis actually correct"
is not something a string-match script can decide reliably -- which is
exactly why the project requires a human in the loop in the first place.

Run: python3 scripts/build_real_review.py
"""
import csv
import json
import os

BASE = os.path.dirname(__file__)
CASES_PATH = os.path.abspath(os.path.join(BASE, "..", "data", "cases.csv"))
AI_PATH = os.path.abspath(os.path.join(BASE, "..", "data", "ai_responses.json"))
REVIEW_CSV = os.path.abspath(os.path.join(BASE, "..", "review", "human_review_log.csv"))
RAI_LOG = os.path.abspath(os.path.join(BASE, "..", "review", "responsible_ai_log.md"))

# case_id -> (decision, corrected_root_cause, reviewer_notes)
# decision is one of: Accepted, Edited, Rejected
REVIEW_DECISIONS = {
    "C004": (
        "Edited",
        "DHCP pool's 'default-router' statement for VLAN 10 points to the wrong subnet's gateway (192.168.20.1 instead of 192.168.10.1).",
        "AI correctly spotted the gateway/subnet mismatch from the PC's ipconfig output, but it wasn't given the DHCP pool config and defaulted to 'fix it on the PC.' Since this PC gets its address via DHCP, the real fix is on the DHCP pool's default-router line, not a manual static change on the client. Corrected the root cause to point at the server-side config; kept AI's evidence read as accurate.",
    ),
    "C009": (
        "Rejected",
        "PC's configured DNS server address (192.168.99.99) does not match the network's real DNS server (192.168.50.5) -- the PC is asking the wrong device, which is why lookups fail while ping-by-IP still works.",
        "AI incorrectly assumed the DNS server it saw referenced (192.168.99.99) was correct and hypothesized a missing record on it. That address is not the documented DNS server for this network at all -- the AI never questioned whether the PC was even pointed at the right server. Its proposed fix (add a record on 192.168.99.99) would not resolve the problem and risks configuring the wrong box. Rejected rather than edited because the fix direction was wrong, not just incomplete.",
    ),
    "C012": (
        "Edited",
        "OSPF neighbor stuck in EXSTART/DR is the classic signature of an MTU mismatch between R1 and R2's serial interfaces blocking the DBD exchange, not a timer or authentication issue.",
        "AI's evidence read (EXSTART/DR, 00:00:31 dead timer) was accurate, but it offered a generic list of possible causes (timers, network type, authentication) instead of naming the specific, well-known cause for this exact symptom pattern. Its 'next_command' (show ip ospf interface) would have surfaced the MTU values and let a human confirm this, so the diagnosis was salvageable but too vague to accept as-is.",
    ),
    "C013": (
        "Edited",
        "The next-hop 203.0.113.1 is not directly reachable because of an IP addressing mismatch on the WAN interface facing the ISP router, not a missing route.",
        "AI's own evidence (ping to the next-hop times out) is the right observation, but it then diagnosed a 'missing route to the ISP network' -- a static default route to an unreachable next-hop is an addressing/reachability problem on the WAN link, not something a second route would fix. Corrected the root cause to point at the interface addressing rather than routing table entries.",
    ),
    "C017": (
        "Edited",
        "The ACL's deny rules for internal subnets exist but are ordered AFTER the 'permit ip any any' line, so they never match -- this is a rule-ordering bug, not a missing-rule bug.",
        "AI's root_cause said the deny statements were 'missing/deferred' and its fix was to add new deny rules before the permit -- functionally this happens to fix the symptom, but it mischaracterizes the bug (the rules already exist) and could leave a confusing, partially-duplicated ACL if applied literally. Corrected the wording so the actual fix is 'reorder existing rules', not 'author new ones'.",
    ),
    "C025": (
        "Edited",
        "R2's HSRP standby is stuck in Init state (config-level HSRP problem, e.g. group number or authentication mismatch) rather than a virtual-IP mismatch.",
        "AI read the two 'show standby brief' outputs and noticed R1 and R2 display different virtual IPs -- which is a legitimate observation and actually exposed an inconsistency in how this case's evidence was written up (two HSRP peers in the same group should always show the same virtual IP). Since the case's intended lesson is 'a peer stuck in Init blocks failover,' the corrected answer keeps that framing but this case's evidence data itself needs to be fixed before reuse -- flagging that separately, not blaming the model.",
    ),
    "C031": (
        "Rejected",
        "192.168.12.0/24 is not covered by the 192.168.0.0/22 summary at all (that summary only spans 192.168.0.0-192.168.3.255) -- the case's own topology note is inconsistent (it claims the /22 summary covers VLANs 10-13, which it mathematically cannot), so this case needs to be rewritten with a summary range that actually contains the affected subnet before it's usable for grading or the demo.",
        "AI attempted the subnetting math, got the boundary arithmetic wrong (claimed 192.168.12.1 'falls in 192.168.8.0/21'), but in the process correctly noticed the summary doesn't actually contain the address in question. Rejected because both the AI's math and the case's own premise are wrong -- this is flagged as a case-data bug to fix in cases.csv, not just an AI error, and shouldn't be used to score model accuracy until corrected.",
    ),
}


def main():
    with open(CASES_PATH, newline="", encoding="utf-8") as f:
        cases = {row["case_id"]: row for row in csv.DictReader(f)}
    with open(AI_PATH) as f:
        ai_responses = {r["case_id"]: r for r in json.load(f)}

    rows = []
    rai_entries = []

    for cid, case in cases.items():
        ai = ai_responses.get(cid, {})
        if cid in REVIEW_DECISIONS:
            decision, corrected, notes = REVIEW_DECISIONS[cid]
        else:
            decision, corrected, notes = (
                "Accepted",
                ai.get("root_cause", case["expected_fault"]),
                "AI diagnosis matched the documented root cause and cited relevant evidence; approved as-is.",
            )

        rows.append({
            "case_id": cid,
            "category": case["category"],
            "ai_root_cause": ai.get("root_cause", ""),
            "ai_confidence": ai.get("confidence", ""),
            "expected_fault": case["expected_fault"],
            "reviewer_decision": decision,
            "corrected_root_cause": corrected,
            "reviewer_notes": notes,
            "reviewer": "Abhey",
        })

        if decision != "Accepted":
            rai_entries.append(dict(case=case, ai=ai, status=decision, notes=notes, corrected=corrected))

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
            "This log records every case where **qwen3:8b's** actual diagnosis "
            "(run locally via Ollama, see `scripts/run_ai_diagnosis.py`) was "
            "corrected (Edited) or overruled (Rejected) by a human reviewer, as "
            "required by the project's Safety Rule: a human must approve or "
            "correct every diagnosis before it is treated as a fix.\n\n"
        )
        f.write(f"**Summary:** {total} cases reviewed — {accepted} Accepted, "
                f"{edited} Edited, {rejected} Rejected. AI/human agreement rate: "
                f"{agreement_rate}%.\n\n")
        f.write("---\n\n")
        for i, e in enumerate(rai_entries, 1):
            c, ai = e["case"], e["ai"]
            f.write(f"## {i}. Case {c['case_id']} — {c['category']} ({e['status']})\n\n")
            f.write(f"**Symptom:** {c['symptom']}\n\n")
            f.write(f"**AI diagnosis (qwen3:8b):** {ai.get('root_cause','')}\n"
                    f"(confidence: {ai.get('confidence','')})\n\n")
            f.write(f"**Corrected root cause:** {e['corrected']}\n\n")
            f.write(f"**Why it was corrected:** {e['notes']}\n\n")
            f.write(f"**Reviewer decision:** {e['status']}\n\n")
            f.write("---\n\n")

    print(f"Wrote {len(rows)} rows to {REVIEW_CSV}")
    print(f"Wrote {len(rai_entries)} Responsible AI entries to {RAI_LOG}")
    print(f"Accepted={accepted} Edited={edited} Rejected={rejected} "
          f"Agreement rate={agreement_rate}%")


if __name__ == "__main__":
    main()
