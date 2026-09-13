# NetSage AI — Applied AI + Network Troubleshooting

An AI-assisted troubleshooter for Cisco Packet Tracer lab problems, with
mandatory human review before any AI diagnosis is treated as a fix.

The pipeline has been run end-to-end with a local qwen3:8b model (via
Ollama) across 32 troubleshooting cases — see `data/ai_responses.json`
for its output and `review/human_review_log.csv` /
`review/responsible_ai_log.md` for the human review of that output
(25 Accepted, 5 Edited, 2 Rejected, 78.1% agreement rate).

## What's in here

```
netsage-ai/
├── data/
│   ├── cases.csv                 # 32 troubleshooting cases
│   ├── device_snapshots.json     # sample parsed device state, feeds rule_checker.py
│   ├── rule_checker_sample_output.json
│   └── ai_responses.json         # AI diagnosis per case
├── prompts/
│   └── diagnose_prompt.md        # system + user prompt, JSON schema, worked examples
├── scripts/
│   ├── generate_cases.py                  # (re)builds data/cases.csv
│   ├── rule_checker.py                    # deterministic config-mistake checker
│   ├── run_ai_diagnosis.py                # calls an OpenAI-compatible API (e.g. Qwen)
│   ├── generate_simulated_ai_responses.py # demo stand-in for AI responses
│   ├── build_review_log.py                # builds the human review log + Responsible AI log
│   ├── build_dashboard_data.py            # aggregates stats for the dashboard
│   └── render_dashboard.py                # bakes stats into dashboard/dashboard.html
├── review/
│   ├── human_review_log.csv      # Accepted / Edited / Rejected per case
│   └── responsible_ai_log.md     # corrected-AI cases, written up
├── dashboard/
│   └── dashboard.html            # standalone, double-clickable dashboard
└── README.md
```

## Connecting an AI API

`scripts/run_ai_diagnosis.py` uses the `openai` Python package against
any OpenAI-compatible chat completions endpoint (DashScope's compatible
mode, Together AI, Groq, a local Ollama server, etc.):

```bash
pip install openai --break-system-packages

export NETSAGE_API_KEY="your-api-key"
export NETSAGE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export NETSAGE_MODEL="qwen2.5-8b-instruct"

python3 scripts/run_ai_diagnosis.py --limit 3   # test on a few cases first
python3 scripts/run_ai_diagnosis.py             # run all cases
```

## Regenerating everything from scratch

```bash
python3 scripts/generate_cases.py
python3 scripts/rule_checker.py --devices data/device_snapshots.json --json data/rule_checker_sample_output.json
python3 scripts/run_ai_diagnosis.py             # or generate_simulated_ai_responses.py for a demo
python3 scripts/build_review_log.py
python3 scripts/build_dashboard_data.py
python3 scripts/render_dashboard.py
```
