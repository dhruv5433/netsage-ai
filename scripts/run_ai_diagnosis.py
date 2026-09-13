#!/usr/bin/env python3
"""
NetSage AI — AI Diagnosis Runner

Feeds every case in data/cases.csv through an OpenAI-compatible chat
completions endpoint (works with Qwen via DashScope/Together/Groq/
Ollama's OpenAI-compatible mode, or OpenAI/Anthropic-compatible
gateways) using the prompt in prompts/diagnose_prompt.md, and writes
one JSON diagnosis per case to data/ai_responses.json.

Setup:
    pip install openai
    export NETSAGE_API_KEY="..."
    export NETSAGE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"   # example for Qwen
    export NETSAGE_MODEL="qwen2.5-8b-instruct"   # or your exact model name

Usage:
    python3 scripts/run_ai_diagnosis.py --cases data/cases.csv --out data/ai_responses.json
"""
import argparse
import csv
import json
import os
import re
import sys
import time

SYSTEM_PROMPT = """You are NetSage AI, a network troubleshooting assistant for Cisco
Packet Tracer labs. You help junior engineers connect a symptom to a
root cause using ONLY the evidence given to you (topology notes and
show-command output). You never invent commands, interfaces, or
output that was not provided.

Rules:
1. Base your diagnosis strictly on the evidence in the case. If the
   evidence is insufficient to be confident, say so and lower your
   confidence score instead of guessing.
2. Always quote or paraphrase the specific line(s) of show-command
   output that support your diagnosis in the "evidence" field.
3. Always name the most relevant OSI layer for the fault.
4. Always propose exactly one concrete "next_command", or null if
   none is needed.
5. Your output is a SUGGESTION for a human reviewer. Never state or
   imply the fix has been applied. You are not authorized to change
   device configuration.
6. Return ONLY valid JSON matching this schema, no prose before or after:
{
  "case_id": string, "root_cause": string, "osi_layer": string,
  "confidence": "low"|"medium"|"high", "evidence": string,
  "next_command": string|null, "fix_steps": [string]
}
"""

USER_TEMPLATE = """CASE ID: {case_id}
CATEGORY: {category}

SYMPTOM:
{symptom}

TOPOLOGY NOTE:
{topology_note}

SHOW-COMMAND OUTPUT:
{show_output}

Diagnose this case and return the JSON object described in your instructions."""


def load_cases(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def call_model(client, model, case, few_shot_messages, temperature=0.2, retries=1):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + few_shot_messages + [
        {"role": "user", "content": USER_TEMPLATE.format(
            case_id=case["case_id"], category=case["category"],
            symptom=case["symptom"], topology_note=case["topology_note"],
            show_output=case["show_output"],
        )}
    ]
    for attempt in range(retries + 1):
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
        )
        text = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": "Your last response was not valid JSON. Return ONLY the JSON object."})
    return {"case_id": case["case_id"], "error": "failed_to_parse_json", "raw": text}


def few_shot():
    """Loads the 3 worked examples inline (kept in sync with prompts/diagnose_prompt.md)."""
    return [
        {"role": "user", "content": "CASE ID: EX-01\nCATEGORY: VLAN\n\nSYMPTOM:\nPC1 in VLAN 10 cannot ping PC2 also in VLAN 10, but both get correct IPs from DHCP.\n\nTOPOLOGY NOTE:\nPC1 and PC2 connect to SW1 access ports Fa0/2 and Fa0/4. Both should be in VLAN 10.\n\nSHOW-COMMAND OUTPUT:\nSW1# show vlan brief\nVLAN Name    Status  Ports\n10  Sales    active  Fa0/2\n20  Guest    active  Fa0/4\n\nDiagnose this case and return the JSON object described in your instructions."},
        {"role": "assistant", "content": json.dumps({
            "case_id": "EX-01",
            "root_cause": "Fa0/4 is assigned to VLAN 20 (Guest) instead of VLAN 10 (Sales).",
            "osi_layer": "Layer 2", "confidence": "high",
            "evidence": "show vlan brief lists Fa0/2 under VLAN 10 but Fa0/4 under VLAN 20.",
            "next_command": "show running-config interface fa0/4",
            "fix_steps": ["Enter interface config for Fa0/4.", "Run 'switchport access vlan 10'.",
                          "Verify with 'show vlan brief'.", "Re-test connectivity."]
        })},
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="data/cases.csv")
    ap.add_argument("--out", default="data/ai_responses.json")
    ap.add_argument("--limit", type=int, default=None, help="Only run the first N cases (for testing)")
    args = ap.parse_args()

    try:
        from openai import OpenAI
    except ImportError:
        print("Install the client library first:  pip install openai --break-system-packages")
        sys.exit(1)

    api_key = os.environ.get("NETSAGE_API_KEY")
    base_url = os.environ.get("NETSAGE_BASE_URL")
    model = os.environ.get("NETSAGE_MODEL", "qwen2.5-8b-instruct")
    if not api_key:
        print("Set NETSAGE_API_KEY (and NETSAGE_BASE_URL for Qwen/non-OpenAI endpoints) first.")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]

    shots = few_shot()
    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] Diagnosing {case['case_id']}...")
        result = call_model(client, model, case, shots)
        results.append(result)
        time.sleep(0.2)

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {len(results)} AI diagnoses to {args.out}")


if __name__ == "__main__":
    main()
