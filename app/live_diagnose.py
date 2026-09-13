#!/usr/bin/env python3
"""
NetSage AI — Live Diagnosis App

A small local web app: pick (or type) a case, hit "Diagnose", and watch
the AI call your local Qwen model in real time and return a structured
diagnosis. Then Accept / Edit / Reject it as the human reviewer — each
decision is appended live to review/human_review_log.csv.

This is the "real-time diagnosis" demo surface for the project video:
it's the same prompt/schema as prompts/diagnose_prompt.md and the same
model call as scripts/run_ai_diagnosis.py, just wrapped in a UI instead
of a batch script.

Run:
    pip install flask openai --break-system-packages
    export NETSAGE_API_KEY="ollama"
    export NETSAGE_BASE_URL="http://localhost:11434/v1"
    export NETSAGE_MODEL="qwen3:8b"
    python3 app/live_diagnose.py

Then open http://127.0.0.1:5050 in your browser.
"""
import csv
import json
import os
import re
import sys
import time
from datetime import datetime

from flask import Flask, jsonify, render_template_string, request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(BASE, "data", "cases.csv")
REVIEW_PATH = os.path.join(BASE, "review", "human_review_log.csv")

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
4. Always propose exactly one concrete "next_command", or null if none is needed.
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

FEW_SHOT = [
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

USER_TEMPLATE = """CASE ID: {case_id}
CATEGORY: {category}

SYMPTOM:
{symptom}

TOPOLOGY NOTE:
{topology_note}

SHOW-COMMAND OUTPUT:
{show_output}

Diagnose this case and return the JSON object described in your instructions."""

app = Flask(__name__)


def load_cases():
    if not os.path.exists(CASES_PATH):
        return []
    with open(CASES_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_client():
    from openai import OpenAI
    api_key = os.environ.get("NETSAGE_API_KEY", "ollama")
    base_url = os.environ.get("NETSAGE_BASE_URL", "http://localhost:11434/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def extract_json(text):
    """Finds the largest balanced {...} block in text rather than a naive
    greedy regex, so prose the model wrote around/instead of JSON doesn't
    accidentally get matched into garbage. Returns the parsed dict, or None."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def diagnose(case_id, category, symptom, topology_note, show_output, retries=2):
    client = get_client()
    model = os.environ.get("NETSAGE_MODEL", "qwen3:8b")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + FEW_SHOT + [
        {"role": "user", "content": USER_TEMPLATE.format(
            case_id=case_id, category=category, symptom=symptom,
            topology_note=topology_note, show_output=show_output,
        )}
    ]
    start = time.time()
    last_text = ""
    for attempt in range(retries + 1):
        # NOTE: deliberately NOT passing response_format={"type": "json_object"} --
        # forcing grammar-constrained JSON decoding made a "thinking"-style model
        # like qwen3 stall/hang instead of just generating normally. Plain calls
        # + the retry-with-clearer-instructions below is what's actually reliable.
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.2)
        text = resp.choices[0].message.content.strip()
        last_text = text
        parsed = extract_json(text)
        if parsed is not None:
            parsed["_elapsed_seconds"] = round(time.time() - start, 1)
            parsed["_model"] = model
            parsed["_attempts"] = attempt + 1
            return parsed
        # model didn't return JSON at all (e.g. wrote prose/reasoning instead) --
        # tell it plainly and try again rather than giving up after one shot.
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": (
            "That response did not contain a valid JSON object. "
            "Do not explain your reasoning in prose. Reply with ONLY the JSON "
            "object matching the schema, nothing else."
        )})
    elapsed = round(time.time() - start, 1)
    return {"error": "failed_to_parse_json", "raw": last_text, "_elapsed_seconds": elapsed,
            "_model": model, "_attempts": retries + 1}


DEFAULT_REVIEW_FIELDS = ["timestamp", "case_id", "category", "ai_root_cause", "ai_confidence",
                         "expected_fault", "reviewer_decision", "corrected_root_cause",
                         "reviewer_notes", "reviewer"]


def existing_review_header():
    """Returns the actual header row already on disk, if any, so appended
    rows always line up with whatever columns the file already has --
    otherwise a file created by a different script (no 'timestamp' column,
    say) gets silently corrupted the first time this app appends to it."""
    if not os.path.exists(REVIEW_PATH):
        return None
    with open(REVIEW_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            return next(reader)
        except StopIteration:
            return None


def append_review(row):
    header = existing_review_header()
    if header:
        fieldnames = header
        # if this row has fields the existing file doesn't have a column for
        # (e.g. an older log with no 'timestamp' column), add those columns
        # by rewriting the file with the fuller header rather than silently
        # dropping/misaligning data.
        missing = [k for k in DEFAULT_REVIEW_FIELDS if k not in fieldnames and k in row]
        if missing:
            with open(REVIEW_PATH, newline="", encoding="utf-8") as f:
                existing_rows = list(csv.DictReader(f))
            fieldnames = fieldnames + missing
            with open(REVIEW_PATH, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in existing_rows:
                    writer.writerow(r)
    else:
        fieldnames = DEFAULT_REVIEW_FIELDS
        os.makedirs(os.path.dirname(REVIEW_PATH), exist_ok=True)
        with open(REVIEW_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()

    with open(REVIEW_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writerow(row)


def load_review_rows():
    if not os.path.exists(REVIEW_PATH):
        return []
    with open(REVIEW_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # defensive: drop any stray None-keyed values from ragged historical rows
    # so a single bad row can never take down the whole dashboard again.
    for r in rows:
        r.pop(None, None)
    return rows


def compute_live_summary():
    """Recomputes every dashboard stat fresh from cases.csv + human_review_log.csv
    on every call, so the dashboard always reflects the latest reviews --
    including ones just logged from the live diagnosis panel above."""
    cases = load_cases()
    reviews = load_review_rows()

    def counter(items, key):
        out = {}
        for it in items:
            v = it.get(key) or "Unspecified"
            out[v] = out.get(v, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    by_category = counter(cases, "category")
    by_severity = counter(cases, "severity")
    by_osi = counter(cases, "osi_layer")
    by_decision = counter(reviews, "reviewer_decision")
    by_confidence = counter(reviews, "ai_confidence")

    total_reviewed = len(reviews)
    accepted = by_decision.get("Accepted", 0)
    agreement_rate = round(accepted / total_reviewed * 100, 1) if total_reviewed else 0.0

    # per-category agreement rate: needs category on the review row (present for
    # cases run through the batch script or the live app when a category was set)
    cat_totals, cat_accepted = {}, {}
    for r in reviews:
        cat = r.get("category") or "Unspecified"
        cat_totals[cat] = cat_totals.get(cat, 0) + 1
        if r.get("reviewer_decision") == "Accepted":
            cat_accepted[cat] = cat_accepted.get(cat, 0) + 1
    agreement_by_category = {
        cat: round(cat_accepted.get(cat, 0) / total * 100, 1)
        for cat, total in cat_totals.items()
    }

    # most recent activity, newest first (works whether or not rows have a timestamp)
    recent = list(reversed(reviews))[:12]

    return {
        "total_cases": len(cases),
        "total_reviewed": total_reviewed,
        "by_category": by_category,
        "by_severity": by_severity,
        "by_osi_layer": by_osi,
        "by_reviewer_decision": by_decision,
        "by_ai_confidence": by_confidence,
        "ai_human_agreement_rate_pct": agreement_rate,
        "agreement_by_category": agreement_by_category,
        "recent_activity": recent,
    }


@app.route("/")
def index():
    return render_template_string(PAGE, cases=load_cases())


@app.route("/api/case/<case_id>")
def api_case(case_id):
    for c in load_cases():
        if c["case_id"] == case_id:
            return jsonify(c)
    return jsonify({"error": "not found"}), 404


@app.route("/api/diagnose", methods=["POST"])
def api_diagnose():
    data = request.get_json()
    try:
        result = diagnose(
            data.get("case_id", "LIVE-CASE"),
            data.get("category", "Unspecified"),
            data.get("symptom", ""),
            data.get("topology_note", ""),
            data.get("show_output", ""),
        )
        return jsonify(result)
    except Exception as e:  # noqa
        return jsonify({"error": str(e)}), 500


@app.route("/api/summary")
def api_summary():
    try:
        return jsonify(compute_live_summary())
    except Exception as e:  # noqa
        return jsonify({"error": str(e)}), 500


@app.route("/api/review", methods=["POST"])
def api_review():
    data = request.get_json()
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "case_id": data.get("case_id", ""),
        "category": data.get("category", ""),
        "ai_root_cause": data.get("ai_root_cause", ""),
        "ai_confidence": data.get("ai_confidence", ""),
        "expected_fault": data.get("expected_fault", ""),
        "reviewer_decision": data.get("reviewer_decision", ""),
        "corrected_root_cause": data.get("corrected_root_cause", ""),
        "reviewer_notes": data.get("reviewer_notes", ""),
        "reviewer": data.get("reviewer", "Abhey"),
    }
    append_review(row)
    return jsonify({"ok": True})


PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>NetSage AI — Live Diagnosis</title>
<style>
  :root{--bg:#0b1220;--panel:#121b2e;--text:#e8edf7;--muted:#94a3b8;--accent:#4f8cff;--good:#22c55e;--warn:#f59e0b;--bad:#ef4444;--border:#22314d;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:24px}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:var(--muted);font-size:13px;margin-bottom:20px}
  .layout{display:grid;grid-template-columns:1fr 1fr;gap:20px;max-width:1300px;margin:0 auto}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px}
  label{display:block;font-size:12px;color:var(--muted);margin:12px 0 4px;text-transform:uppercase;letter-spacing:.03em}
  select,textarea,input{width:100%;background:#0e1526;border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px;font-family:inherit;font-size:13px}
  textarea{min-height:70px;font-family:ui-monospace,monospace;resize:vertical}
  button{cursor:pointer;border:none;border-radius:8px;padding:10px 16px;font-weight:600;font-size:13px}
  .btn-primary{background:var(--accent);color:white;margin-top:14px;width:100%}
  .btn-primary:disabled{opacity:.5;cursor:wait}
  .result{margin-top:14px}
  .field{margin-bottom:10px}
  .field .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.03em}
  .field .v{font-size:14px;margin-top:2px}
  .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:700}
  .pill.high{background:rgba(34,197,94,.15);color:var(--good)}
  .pill.medium{background:rgba(245,158,11,.15);color:var(--warn)}
  .pill.low{background:rgba(239,68,68,.15);color:var(--bad)}
  .review-row{display:flex;gap:8px;margin-top:16px}
  .review-row button{flex:1}
  .btn-accept{background:rgba(34,197,94,.15);color:var(--good)}
  .btn-edit{background:rgba(245,158,11,.15);color:var(--warn)}
  .btn-reject{background:rgba(239,68,68,.15);color:var(--bad)}
  .status{font-size:12px;color:var(--good);margin-top:8px;min-height:16px}
  .spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:white;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:6px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .placeholder{color:var(--muted);font-size:13px}
  fieldset{border:1px solid var(--border);border-radius:8px;margin-top:14px;padding:10px}
  legend{color:var(--muted);font-size:11px;padding:0 6px}

  .live-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--good);margin-right:6px;animation:pulse 1.6s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:20px 0 16px}
  .kpi{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px;text-align:center}
  .kpi .num{font-size:26px;font-weight:700}
  .kpi .lbl{font-size:11px;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.03em}
  .dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
  .dgrid .card h2{font-size:13px;margin:0 0 14px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
  .bar-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;font-size:13px}
  .bar-label{width:110px;flex-shrink:0;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .bar-track{flex:1;background:rgba(128,128,128,.15);border-radius:6px;height:16px;overflow:hidden}
  .bar-fill{height:100%;border-radius:6px;transition:width .4s ease}
  .bar-val{width:36px;text-align:right;flex-shrink:0;font-variant-numeric:tabular-nums}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}
  th{color:var(--muted);font-weight:600}
  tbody tr{transition:background .15s ease}
  tbody tr:hover{background:rgba(255,255,255,.03)}
  .empty{color:var(--muted);font-size:13px;padding:8px 0}
  .dash-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:4px}
  .btn-refresh{background:var(--panel);border:1px solid var(--border) !important;color:var(--text);display:inline-flex;align-items:center;gap:6px;padding:8px 14px;white-space:nowrap}
  .btn-refresh:hover{border-color:var(--accent) !important;color:var(--accent)}
  .btn-refresh.spinning #refreshIcon{display:inline-block;animation:spin .6s linear infinite}
  .kpi .num{transition:color .3s ease}
  .kpi.bump .num{color:var(--accent)}
  .donut-card{display:flex;flex-direction:column}
  .donut-wrap{display:flex;align-items:center;gap:18px;flex:1}
  .donut{width:110px;height:110px;border-radius:50%;flex-shrink:0;background:conic-gradient(var(--border) 0deg 360deg);position:relative;transition:background 1s ease}
  .donut::after{content:attr(data-total);position:absolute;inset:14px;border-radius:50%;background:var(--panel);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:var(--text)}
  .donut-legend{display:flex;flex-direction:column;gap:8px;font-size:12.5px}
  .legend-row{display:flex;align-items:center;gap:8px}
  .legend-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
  .legend-label{color:var(--muted)}
  .legend-val{font-weight:700;margin-left:auto}
</style>
</head>
<body>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
    <h1 style="margin:0">NetSage AI — Live Diagnosis</h1>
    <button class="btn-refresh" onclick="location.reload()" title="Reload the whole page">⟳ Refresh page</button>
  </div>
  <div class="sub">Pick a case or paste your own symptom/evidence, then diagnose in real time against your local Qwen model.</div>

  <div class="layout">
    <div class="card">
      <label>Load an existing case (optional)</label>
      <select id="caseSelect">
        <option value="">— type your own below —</option>
        {% for c in cases %}
        <option value="{{ c.case_id }}">{{ c.case_id }} — {{ c.category }}: {{ c.symptom[:60] }}...</option>
        {% endfor %}
      </select>

      <label>Case ID</label>
      <input id="caseId" value="LIVE-001">

      <label>Category</label>
      <input id="category" value="VLAN">

      <label>Symptom</label>
      <textarea id="symptom" placeholder="e.g. PC gets an IP but cannot reach the file server..."></textarea>

      <label>Topology note</label>
      <textarea id="topology" placeholder="e.g. PC connects to SW1 Fa0/6, VLAN 20..."></textarea>

      <label>Show-command output</label>
      <textarea id="showOutput" placeholder="paste show vlan brief / show ip route / etc. output here" style="min-height:110px"></textarea>

      <button class="btn-primary" id="diagnoseBtn" onclick="runDiagnosis()">Diagnose now</button>
      <div class="status" id="callStatus"></div>
    </div>

    <div class="card">
      <label style="margin-top:0">AI diagnosis</label>
      <div id="resultBox" class="placeholder">Run a diagnosis to see the AI's structured response here.</div>

      <fieldset id="reviewSection" style="display:none">
        <legend>Human review (required before this is treated as a fix)</legend>
        <label>Corrected root cause (edit if needed)</label>
        <textarea id="correctedRootCause"></textarea>
        <label>Reviewer notes</label>
        <textarea id="reviewerNotes" placeholder="Why accepted / what was wrong / what to check next"></textarea>
        <div class="review-row">
          <button class="btn-accept" onclick="submitReview('Accepted')">✓ Accept</button>
          <button class="btn-edit" onclick="submitReview('Edited')">✎ Edited</button>
          <button class="btn-reject" onclick="submitReview('Rejected')">✕ Reject</button>
        </div>
        <div class="status" id="reviewStatus"></div>
      </fieldset>
    </div>
  </div>

  <hr id="dashboardDivider" hidden style="max-width:1300px;margin:36px auto;border:none;border-top:1px solid var(--border)">

  <div id="dashboard" hidden style="max-width:1300px;margin:0 auto">
    <div class="dash-head">
      <div>
        <h1 style="display:inline-block;margin-right:10px">Live Analytics Dashboard</h1>
        <span class="sub" style="display:inline-flex;align-items:center;gap:6px"><span class="live-dot"></span>Auto-refreshes every 5s · last updated <span id="lastUpdated">—</span></span>
      </div>
      <button id="refreshBtn" class="btn-refresh" onclick="manualRefresh()"><span id="refreshIcon">⟳</span> Refresh now</button>
    </div>

    <div class="kpis" id="kpis"></div>

    <div class="dgrid">
      <div class="card"><h2>Cases by fault category</h2><div id="byCategory"></div></div>
      <div class="card"><h2>Cases by severity</h2><div id="bySeverity"></div></div>
      <div class="card"><h2>Cases by OSI layer</h2><div id="byOsi"></div></div>
      <div class="card donut-card">
        <h2>AI vs human review outcome</h2>
        <div class="donut-wrap">
          <div class="donut" id="decisionDonut"></div>
          <div class="donut-legend" id="decisionLegend"></div>
        </div>
      </div>
      <div class="card"><h2>AI confidence distribution (reviewed cases)</h2><div id="byConfidence"></div></div>
      <div class="card"><h2>Agreement rate by category</h2><div id="byCatAgreement"></div></div>
    </div>

    <div class="card" style="margin:16px 0 40px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
        <h2 style="margin:0">Recent review activity</h2>
        <input id="activityFilter" placeholder="Filter by case ID, category, or decision..." oninput="renderRecent()" style="max-width:280px;width:100%;background:#0e1526;border:1px solid var(--border);border-radius:8px;color:var(--text);padding:6px 10px;font-size:12.5px">
      </div>
      <table style="margin-top:12px">
        <thead><tr><th>When</th><th>Case</th><th>AI said</th><th>Reviewer decision</th><th>Notes</th></tr></thead>
        <tbody id="recentTable"></tbody>
      </table>
      <div class="empty" id="recentEmpty" style="display:none">No reviews logged yet — diagnose a case above and Accept/Edit/Reject it.</div>
    </div>
  </div>

<script>
let lastResult = null;
let lastCase = null;

document.getElementById('caseSelect').addEventListener('change', async (e) => {
  const id = e.target.value;
  if (!id) return;
  const res = await fetch('/api/case/' + id);
  const c = await res.json();
  document.getElementById('caseId').value = c.case_id;
  document.getElementById('category').value = c.category;
  document.getElementById('symptom').value = c.symptom;
  document.getElementById('topology').value = c.topology_note;
  document.getElementById('showOutput').value = c.show_output;
  lastCase = c;
});

async function runDiagnosis(){
  const btn = document.getElementById('diagnoseBtn');
  const statusEl = document.getElementById('callStatus');
  const box = document.getElementById('resultBox');
  btn.disabled = true;
  statusEl.innerHTML = '<span class="spinner"></span>Calling your local Qwen model via Ollama...';
  box.innerHTML = '<div class="placeholder">Waiting for model response...</div>';
  document.getElementById('reviewSection').style.display = 'none';

  const payload = {
    case_id: document.getElementById('caseId').value,
    category: document.getElementById('category').value,
    symptom: document.getElementById('symptom').value,
    topology_note: document.getElementById('topology').value,
    show_output: document.getElementById('showOutput').value,
  };

  try {
    const res = await fetch('/api/diagnose', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await res.json();
    lastResult = data;
    if (data.error) {
      box.innerHTML = '<div class="placeholder">Error: ' + data.error +
        ' (tried ' + (data._attempts||1) + ' time(s) — the model wrote prose instead of JSON). ' +
        'Try clicking Diagnose now again, or simplify the show-command output.' +
        (data.raw ? '<br><br>Raw output: ' + data.raw : '') + '</div>';
      statusEl.textContent = 'Failed after ' + (data._attempts||1) + ' attempt(s) in ' + data._elapsed_seconds + 's';
      btn.disabled = false;
      return;
    }
    renderResult(data);
    statusEl.textContent = 'Done in ' + data._elapsed_seconds + 's (' + data._model + ')';
    document.getElementById('correctedRootCause').value = data.root_cause || '';
    document.getElementById('reviewSection').style.display = 'block';
    revealDashboard();
  } catch (err) {
    box.innerHTML = '<div class="placeholder">Request failed: ' + err + '. Is the app running with NETSAGE_BASE_URL pointed at Ollama?</div>';
    statusEl.textContent = '';
  }
  btn.disabled = false;
}

function renderResult(d){
  const box = document.getElementById('resultBox');
  const confClass = (d.confidence || 'medium').toLowerCase();
  box.innerHTML = `
    <div class="field"><span class="k">Root cause</span><div class="v">${d.root_cause || ''}</div></div>
    <div class="field"><span class="k">OSI layer</span><div class="v">${d.osi_layer || ''}</div></div>
    <div class="field"><span class="k">Confidence</span><div class="v"><span class="pill ${confClass}">${(d.confidence||'').toUpperCase()}</span></div></div>
    <div class="field"><span class="k">Evidence</span><div class="v">${d.evidence || ''}</div></div>
    <div class="field"><span class="k">Next command</span><div class="v">${d.next_command || '(none)'}</div></div>
    <div class="field"><span class="k">Fix steps</span><div class="v"><ol>${(d.fix_steps||[]).map(s=>'<li>'+s+'</li>').join('')}</ol></div></div>
  `;
}

async function submitReview(decision){
  const statusEl = document.getElementById('reviewStatus');
  const payload = {
    case_id: document.getElementById('caseId').value,
    category: document.getElementById('category').value,
    ai_root_cause: lastResult ? lastResult.root_cause : '',
    ai_confidence: lastResult ? lastResult.confidence : '',
    expected_fault: lastCase ? lastCase.expected_fault : '',
    reviewer_decision: decision,
    corrected_root_cause: document.getElementById('correctedRootCause').value,
    reviewer_notes: document.getElementById('reviewerNotes').value,
    reviewer: 'Abhey',
  };
  const res = await fetch('/api/review', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const data = await res.json();
  if (data.ok) {
    statusEl.style.color = 'var(--good)';
    statusEl.textContent = '✓ Logged as "' + decision + '" to review/human_review_log.csv';
    revealDashboard();
  } else {
    statusEl.style.color = 'var(--bad)';
    statusEl.textContent = 'Failed to log review.';
  }
}

// ---- Live analytics dashboard (same page, no navigation) ----
// Hidden until the first diagnosis completes, so first-time landing on the
// page shows only the diagnosis panel -- the dashboard appears beneath it
// (and polling only starts) once there's something to show.
let dashboardRevealed = false;
let dashboardTimer = null;

function revealDashboard(){
  const section = document.getElementById('dashboard');
  const divider = document.getElementById('dashboardDivider');
  if (!dashboardRevealed) {
    dashboardRevealed = true;
    section.hidden = false;
    divider.hidden = false;
    refreshDashboard();
    dashboardTimer = setInterval(refreshDashboard, 5000);
    setTimeout(() => divider.scrollIntoView({behavior: 'smooth', block: 'start'}), 150);
  } else {
    refreshDashboard();
  }
}

const DCOLORS = ["#4f8cff","#22c55e","#f59e0b","#ef4444","#a855f7","#06b6d4","#eab308","#f97316"];
function decisionColor(l){ if(l==="Accepted") return "#22c55e"; if(l==="Edited") return "#f59e0b"; return "#ef4444"; }
function confColor(l){ l=(l||'').toLowerCase(); if(l==="high") return "#22c55e"; if(l==="medium") return "#f59e0b"; return "#ef4444"; }
function agreementColor(v){ if(v>=80) return "#22c55e"; if(v>=50) return "#f59e0b"; return "#ef4444"; }

function renderBars(id, obj, colorFn, suffix){
  const el = document.getElementById(id);
  if(!el) return;
  el.innerHTML = "";
  const entries = Object.entries(obj || {});
  if(!entries.length){ el.innerHTML = '<div class="empty">No data yet.</div>'; return; }
  const max = Math.max(...entries.map(e=>e[1]));
  entries.forEach(([label,val],i)=>{
    const color = colorFn ? colorFn(label, val) : DCOLORS[i % DCOLORS.length];
    const pct = max ? (val/max*100) : 0;
    el.innerHTML += `<div class="bar-row">
      <div class="bar-label" title="${label}">${label}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
      <div class="bar-val">${val}${suffix||''}</div>
    </div>`;
  });
}

let lastActivity = [];
let previousKpis = {};

function animateNumber(el, from, to, isPercent){
  const dur = 500, start = performance.now();
  function step(now){
    const t = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - t, 3);
    const val = from + (to - from) * eased;
    el.textContent = isPercent ? val.toFixed(1) + '%' : Math.round(val);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

function renderKpis(s){
  const defs = [
    ['total_cases', 'Total cases', false],
    ['total_reviewed', 'Reviewed so far', false],
    ['ai_human_agreement_rate_pct', 'AI/human agreement', true],
    ['_edited', 'Edited', false],
    ['_rejected', 'Rejected', false],
  ];
  const values = {
    total_cases: s.total_cases, total_reviewed: s.total_reviewed,
    ai_human_agreement_rate_pct: s.ai_human_agreement_rate_pct,
    _edited: s.by_reviewer_decision.Edited || 0, _rejected: s.by_reviewer_decision.Rejected || 0,
  };
  const container = document.getElementById('kpis');
  if (!container.children.length || container.dataset.built !== '1') {
    container.innerHTML = defs.map(([key,label]) =>
      `<div class="kpi" id="kpi-${key}"><div class="num" id="kpi-${key}-num">0</div><div class="lbl">${label}</div></div>`
    ).join('');
    container.dataset.built = '1';
  }
  defs.forEach(([key,label,isPercent]) => {
    const numEl = document.getElementById(`kpi-${key}-num`);
    const kpiEl = document.getElementById(`kpi-${key}`);
    const prev = previousKpis[key] ?? 0;
    const next = values[key];
    if (prev !== next) {
      animateNumber(numEl, prev, next, isPercent);
      kpiEl.classList.add('bump');
      setTimeout(() => kpiEl.classList.remove('bump'), 600);
    } else if (!(key in previousKpis)) {
      numEl.textContent = isPercent ? next.toFixed(1) + '%' : next;
    }
  });
  previousKpis = values;
}

function renderDonut(byDecision){
  const order = ['Accepted', 'Edited', 'Rejected'];
  const colors = {Accepted:'#22c55e', Edited:'#f59e0b', Rejected:'#ef4444'};
  const total = order.reduce((sum,k) => sum + (byDecision[k]||0), 0);
  const donut = document.getElementById('decisionDonut');
  const legend = document.getElementById('decisionLegend');
  donut.dataset.total = total;
  if (!total) {
    donut.style.background = 'conic-gradient(var(--border) 0deg 360deg)';
    legend.innerHTML = '<div class="empty">No reviews yet.</div>';
    return;
  }
  let angle = 0;
  const stops = [];
  order.forEach(k => {
    const val = byDecision[k] || 0;
    if (!val) return;
    const deg = (val/total) * 360;
    stops.push(`${colors[k]} ${angle}deg ${angle+deg}deg`);
    angle += deg;
  });
  donut.style.background = `conic-gradient(${stops.join(',')})`;
  legend.innerHTML = order.map(k => {
    const val = byDecision[k] || 0;
    const pct = total ? Math.round(val/total*100) : 0;
    return `<div class="legend-row"><span class="legend-dot" style="background:${colors[k]}"></span><span class="legend-label">${k}</span><span class="legend-val">${val} (${pct}%)</span></div>`;
  }).join('');
}

function renderRecent(){
  const tbody = document.getElementById('recentTable');
  const emptyMsg = document.getElementById('recentEmpty');
  const filterVal = (document.getElementById('activityFilter').value || '').toLowerCase();
  const filtered = lastActivity.filter(r => {
    if (!filterVal) return true;
    return [r.case_id, r.category, r.reviewer_decision, r.ai_root_cause]
      .some(v => (v||'').toLowerCase().includes(filterVal));
  });
  tbody.innerHTML = "";
  if (!filtered.length) {
    emptyMsg.style.display = 'block';
    emptyMsg.textContent = lastActivity.length ? 'No activity matches that filter.' : 'No reviews logged yet — diagnose a case above and Accept/Edit/Reject it.';
  } else {
    emptyMsg.style.display = 'none';
    filtered.forEach(r => {
      const cls = (r.reviewer_decision||'').toLowerCase();
      tbody.innerHTML += `<tr>
        <td>${r.timestamp || ''}</td>
        <td>${r.case_id || ''}</td>
        <td>${(r.ai_root_cause||'').slice(0,80)}</td>
        <td><span class="pill ${cls}">${r.reviewer_decision||''}</span></td>
        <td>${(r.reviewer_notes||'').slice(0,80)}</td>
      </tr>`;
    });
  }
}

async function refreshDashboard(){
  let s;
  try {
    const res = await fetch('/api/summary');
    s = await res.json();
    if (s.error) throw new Error(s.error);
  } catch (err) {
    document.getElementById('kpis').innerHTML =
      `<div class="kpi" style="grid-column:1/-1;text-align:left;color:var(--bad)">Dashboard failed to load: ${err}</div>`;
    return;
  }

  renderKpis(s);
  renderBars('byCategory', s.by_category);
  renderBars('bySeverity', s.by_severity);
  renderBars('byOsi', s.by_osi_layer);
  renderDonut(s.by_reviewer_decision);
  renderBars('byConfidence', s.by_ai_confidence, confColor);

  const agreeObj = {};
  for (const [cat, pct] of Object.entries(s.agreement_by_category || {})) agreeObj[cat] = pct;
  renderBars('byCatAgreement', agreeObj, agreementColor, '%');

  lastActivity = s.recent_activity || [];
  renderRecent();

  document.getElementById('lastUpdated').textContent = new Date().toLocaleTimeString();
}

async function manualRefresh(){
  const btn = document.getElementById('refreshBtn');
  btn.classList.add('spinning');
  btn.disabled = true;
  await refreshDashboard();
  setTimeout(() => { btn.classList.remove('spinning'); btn.disabled = false; }, 300);
}

// dashboard stays hidden and unpolled until revealDashboard() runs
// (triggered by a completed diagnosis or a submitted review above).
</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"NetSage AI Live Diagnosis running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
