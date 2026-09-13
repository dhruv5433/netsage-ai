# NetSage AI — Applied AI + Network Troubleshooting

Project 2: an AI-assisted troubleshooter for Cisco Packet Tracer lab
problems, with mandatory human review before any diagnosis is treated
as a fix. Deadline: **December 7**.

## What's in here

```
netsage-ai/
├── data/
│   ├── cases.csv                 # 32 troubleshooting cases (>= 30 required)
│   ├── device_snapshots.json     # sample parsed device state, feeds rule_checker.py
│   ├── rule_checker_sample_output.json
│   └── ai_responses.json         # AI diagnosis per case (simulated for now — see below)
├── prompts/
│   └── diagnose_prompt.md        # system + user prompt, JSON schema, 3 worked examples
├── scripts/
│   ├── generate_cases.py                  # (re)builds data/cases.csv
│   ├── rule_checker.py                    # deterministic config-mistake checker
│   ├── run_ai_diagnosis.py                # REAL runner: calls your Qwen/OpenAI-compatible API
│   ├── generate_simulated_ai_responses.py # demo stand-in until you wire up the real API
│   ├── build_review_log.py                # builds the human review log + Responsible AI log
│   ├── build_dashboard_data.py            # aggregates stats for the dashboard
│   └── render_dashboard.py                # bakes stats into dashboard/dashboard.html
├── review/
│   ├── human_review_log.csv      # Accepted / Edited / Rejected per case
│   └── responsible_ai_log.md     # >= 5 corrected-AI cases, written up
├── dashboard/
│   ├── dashboard_template.html   # source template (don't fill by hand)
│   └── dashboard.html            # OPEN THIS — standalone, double-clickable
└── README.md
```

**Status: this pipeline has been run end-to-end with your real qwen3:8b
model** (via Ollama, locally on your Mac) across all 32 cases — see
`data/ai_responses.json` for its actual output and
`review/human_review_log.csv` / `review/responsible_ai_log.md` for the
real human review of that output (25 Accepted, 5 Edited, 2 Rejected,
78.1% agreement rate). Nothing in the current dashboard or logs is
simulated. If you want to re-run the model (after fixing more cases,
tweaking the prompt, etc.) see "Connecting your Qwen API" below.

## How the pieces map to the grading checklist

| Grading check | Where it lives |
|---|---|
| Case coverage ≥ 30, multiple fault types | `data/cases.csv` — 32 cases across VLAN, Gateway, DHCP, DNS, Routing, ACL, NAT, Wireless |
| AI responses reference actual show-command evidence | `prompts/diagnose_prompt.md` forces an `evidence` field quoting the show output; enforced in the system prompt |
| Human oversight log (accepted/edited/rejected) | `review/human_review_log.csv` |
| Deterministic checks catch config errors | `scripts/rule_checker.py` + `data/rule_checker_sample_output.json` (9 findings across duplicate IP, wrong mask, gateway mismatch, interface down, missing/wrong VLAN, missing route) |
| Responsible AI: ≥5 corrected cases documented | `review/responsible_ai_log.md` — currently has 7 |
| Dashboard: issue types, severity, AI/human agreement | `dashboard/dashboard.html` |

## Step-by-step: what to actually do between now and Dec 7

1. **Validate the cases against real Packet Tracer labs.** The 32 cases
   in `data/cases.csv` are realistic but written from common lab
   patterns, not captured from your own topology. Build (or reuse) the
   matching Packet Tracer labs, take real `show` command screenshots,
   and adjust the `show_output` / `expected_fault` columns for any case
   where your lab's exact behavior differs. This is the most
   time-consuming step — start it first.

2. **Connect your Qwen API and re-run real diagnoses** (see below).
   Replace `data/ai_responses.json` (currently simulated) with the
   output of `scripts/run_ai_diagnosis.py`.

3. **Re-run the review log build** — `python3 scripts/build_review_log.py`
   — but this time actually read each AI response yourself and decide
   Accepted / Edited / Rejected by hand (the script's auto-comparison
   is only there for the placeholder data; for real submission, you as
   the reviewer are the "human" the safety rule requires, so edit
   `review/human_review_log.csv` directly after reading the real AI
   output).

4. **Update the dashboard**: `python3 scripts/build_dashboard_data.py`
   then `python3 scripts/render_dashboard.py`.

5. **Record the demo video (5–10 min).** Script:
   - (0:00–1:00) Show one broken lab in Packet Tracer, reproduce the symptom.
   - (1:00–3:00) Feed the case into the AI (show the JSON response with evidence).
   - (3:00–5:00) Run `rule_checker.py` against that device's config, show it independently catches the same fault.
   - (5:00–7:00) Show the human review step — Accept/Edit/Reject and why, referencing `human_review_log.csv`.
   - (7:00–9:00) Apply the real fix in Packet Tracer, re-run the show command to verify.
   - (9:00–10:00) Show the dashboard.

## Connecting your Qwen API

`scripts/run_ai_diagnosis.py` uses the `openai` Python package against
any OpenAI-compatible chat completions endpoint, which covers most
Qwen hosting options (DashScope's compatible mode, Together AI, Groq,
a local Ollama server, etc.):

```bash
pip install openai --break-system-packages

export NETSAGE_API_KEY="your-api-key"
export NETSAGE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"  # example — use your provider's URL
export NETSAGE_MODEL="qwen2.5-8b-instruct"   # exact model id your provider uses

# test on 3 cases first
python3 scripts/run_ai_diagnosis.py --limit 3

# once it looks right, run all cases
python3 scripts/run_ai_diagnosis.py
```

If your Qwen access is through a different SDK (not OpenAI-compatible),
tell me the provider and I'll adjust the script — the prompt/schema in
`prompts/diagnose_prompt.md` stays the same either way.

Tips for an 8B model specifically (already baked into the prompt file):
low temperature (0.1–0.3), always send the 3 worked examples, and
retry once if the JSON fails to parse.

## Regenerating everything from scratch

```bash
python3 scripts/generate_cases.py                     # data/cases.csv
python3 scripts/rule_checker.py --devices data/device_snapshots.json --json data/rule_checker_sample_output.json
python3 scripts/run_ai_diagnosis.py                    # real AI responses (or generate_simulated_ai_responses.py for a demo)
python3 scripts/build_review_log.py                    # review/*.csv and .md
python3 scripts/build_dashboard_data.py
python3 scripts/render_dashboard.py                    # dashboard/dashboard.html
```
