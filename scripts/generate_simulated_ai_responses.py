#!/usr/bin/env python3
"""
Generates data/ai_responses.json — SIMULATED AI diagnoses for demo/dashboard
purposes, so the project runs end-to-end without an API key or budget.

Most responses match the case's expected_fault closely (as a real 8B model
would, given good few-shot prompting). A deliberate subset (~7 cases) are
made wrong or partially wrong on purpose, so the human-review step and the
Responsible AI log have real material — this mirrors what actually happens
when you run this against a real small model, so swap this file out for
scripts/run_ai_diagnosis.py's real output once you have API access.

Run: python3 scripts/generate_simulated_ai_responses.py
"""
import csv
import json
import os

# case_id -> deliberately flawed AI response (wrong / partially wrong / overconfident)
DELIBERATE_ERRORS = {
    "C002": dict(
        root_cause="The trunk link between SW1 and SW2 is down.",
        osi_layer="Layer 1", confidence="medium",
        evidence="Interfaces trunk output was reviewed.",
        next_command="show interfaces gi0/1 status",
        fix_steps=["Check the physical cable between SW1 and SW2.", "Re-seat the cable.", "Retest."],
        error_note="AI guessed a physical-layer cause; missed that the trunk is UP but VLAN 10 is pruned from the allowed-VLAN list.",
    ),
    "C007": dict(
        root_cause="The DHCP server is out of leases because too many devices are on the network.",
        osi_layer="Layer 3", confidence="medium",
        evidence="Leased addresses: 254 shown in the pool output.",
        next_command="show ip dhcp pool VLAN10_POOL",
        fix_steps=["Expand the DHCP pool to a larger subnet.", "Add a second DHCP scope."],
        error_note="AI focused on the 'Leased addresses: 254' figure and concluded organic exhaustion, but missed the 'Excluded addresses: 192.168.10.1 - 192.168.10.254' line, which is the actual root cause (mis-scoped exclusion, not real demand).",
    ),
    "C012": dict(
        root_cause="OSPF is misconfigured on R1; the area number is wrong.",
        osi_layer="Layer 3", confidence="medium",
        evidence="Neighbor is stuck and not reaching FULL state.",
        next_command="show ip ospf interface brief",
        fix_steps=["Verify OSPF area numbers match on both routers.", "Re-enable the OSPF process."],
        error_note="AI proposed a generic 'area mismatch' guess. The evidence actually shows EXSTART/DR specifically, which is the classic signature of an MTU mismatch during DBD exchange, not an area mismatch (area mismatches show as a different neighbor state / log message).",
    ),
    "C017": dict(
        root_cause="The GUEST_ISOLATION ACL is missing deny rules for internal subnets entirely.",
        osi_layer="Layer 3", confidence="high",
        evidence="ACL only shows a permit ip any any statement.",
        next_command="show access-lists GUEST_ISOLATION",
        fix_steps=["Add deny statements for internal subnets to the ACL.", "Apply the ACL to the guest VLAN interface."],
        error_note="AI said the deny rules are 'missing entirely,' but the case note says they exist and are simply ordered AFTER the permit statement — an ordering bug, not a missing-rule bug. The fix AI proposed (add new deny rules) would not fix a duplicate/ordering problem and could make the ACL confusing without reordering the existing rules.",
    ),
    "C019": dict(
        root_cause="Some hosts are not connected to the switch properly.",
        osi_layer="Layer 1", confidence="low",
        evidence="Inconsistent internet access reported.",
        next_command="show interfaces status",
        fix_steps=["Check cabling for the affected hosts.", "Confirm switchport status."],
        error_note="AI defaulted to a vague physical-layer guess instead of reading the NAT ACL wildcard mask (0.0.0.15), which only covers 16 addresses of the /24 and is the actual root cause. This is a case where a low-confidence, evidence-light AI answer should always be sent to human review rather than trusted.",
    ),
    "C025": dict(
        root_cause="R2 is completely offline / powered down.",
        osi_layer="Layer 1", confidence="medium",
        evidence="R2 standby state shown as unusual.",
        next_command="show standby brief on R2",
        fix_steps=["Power-cycle R2.", "Check console access to R2."],
        error_note="AI over-interpreted 'Init' state as R2 being offline; the show output actually indicates R2 is reachable and running HSRP but stuck in Init (a config-level HSRP issue, e.g. group/auth mismatch), not a power/connectivity outage.",
    ),
    "C031": dict(
        root_cause="HQ-R1's routing table is corrupted and needs a reboot.",
        osi_layer="Layer 3", confidence="low",
        evidence="Route to summarized range 192.168.0.0/22 exists but a ping inside it fails.",
        next_command="reload HQ-R1",
        fix_steps=["Reboot HQ-R1 to clear the routing table.", "Re-verify OSPF neighbors after reboot."],
        error_note="AI's proposed fix (rebooting the router) is not evidence-based and is operationally risky for a production-style device. The real issue is a route-summarization black hole for one /24 that was never actually configured behind R2 — a reboot would not fix this and this response should never be auto-applied.",
    ),
}


def build_correct_response(case):
    return dict(
        case_id=case["case_id"],
        root_cause=case["expected_fault"],
        osi_layer=case["osi_layer"],
        confidence="high" if case["severity"] in ("High", "Medium") else "medium",
        evidence=f"Derived from show-command output: {case['show_output'].splitlines()[-1][:160]}",
        next_command=default_next_command(case),
        fix_steps=default_fix_steps(case),
    )


def default_next_command(case):
    mapping = {
        "VLAN": "show vlan brief",
        "Gateway": "show ip interface brief",
        "DHCP": "show ip dhcp binding",
        "DNS": "show hosts",
        "Routing": "show ip route",
        "ACL": "show access-lists",
        "NAT": "show ip nat translations",
        "Wireless": "show wireless client summary",
    }
    return mapping.get(case["category"], "show running-config")


def default_fix_steps(case):
    return [
        f"Confirm the fault described: {case['expected_fault']}",
        "Apply the corrective configuration change on the affected device.",
        "Re-run the relevant show command to confirm the change took effect.",
        "Re-test the original symptom end-to-end from the client.",
    ]


def main():
    base = os.path.dirname(__file__)
    cases_path = os.path.abspath(os.path.join(base, "..", "data", "cases.csv"))
    out_path = os.path.abspath(os.path.join(base, "..", "data", "ai_responses.json"))

    with open(cases_path, newline="", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    responses = []
    for case in cases:
        cid = case["case_id"]
        if cid in DELIBERATE_ERRORS:
            r = dict(DELIBERATE_ERRORS[cid])
            r["case_id"] = cid
            r["_is_deliberately_flawed_for_demo"] = True
        else:
            r = build_correct_response(case)
        responses.append(r)

    with open(out_path, "w") as f:
        json.dump(responses, f, indent=2)
    print(f"Wrote {len(responses)} simulated AI responses to {out_path} "
          f"({len(DELIBERATE_ERRORS)} deliberately flawed for the Responsible AI log).")


if __name__ == "__main__":
    main()
