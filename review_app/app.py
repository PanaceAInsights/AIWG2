"""
ACD Entity Resolution Review Interface
=======================================
Flask web app for manually reviewing and adjudicating REVIEW-tier and
flagged entity resolution results.

Run:
    python review_app/app.py
    # → http://localhost:5050

Features:
- Shows all REVIEW + common-name flagged members
- Warning badges for: SUSPICIOUS_VOLUME, NO_AUNZ_HISTORY, SPECIALTY_WEAK,
  COMMON_NAME_RISK, LLM_DISAGREEMENT, COUNTRY_MISMATCH
- Click any row to see full evidence: scores, LLM reasoning, OpenAlex profile link
- Accept / Reject / Override actions
- Saves decisions to data/input/manual_resolver_overrides.csv and
  data/input/manual_fp_overrides.csv
- Progress bar showing how many have been reviewed
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template_string, request, redirect, url_for, jsonify

ROOT = Path(__file__).resolve().parent.parent
RESOLVED_CSV     = ROOT / "data" / "processed" / "authors_resolved.csv"
REVIEW_CSV       = ROOT / "data" / "processed" / "review_queue.csv"
COMMON_NAME_CSV  = ROOT / "data" / "processed" / "common_name_review.csv"
OVERRIDES_CSV    = ROOT / "data" / "input" / "manual_resolver_overrides.csv"
FP_OVERRIDES_CSV = ROOT / "data" / "input" / "manual_fp_overrides.csv"
DECISIONS_CSV    = ROOT / "data" / "processed" / "review_decisions.csv"

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _load_decisions() -> dict[str, dict]:
    rows = _read_csv(DECISIONS_CSV)
    return {r["acd_name"]: r for r in rows}


def _save_decision(acd_name: str, action: str, override_id: str, notes: str) -> None:
    decisions = _load_decisions()
    decisions[acd_name] = {
        "acd_name": acd_name,
        "action": action,
        "override_openalex_id": override_id,
        "notes": notes,
        "reviewed_at": datetime.now().isoformat(),
    }
    _write_csv(DECISIONS_CSV, list(decisions.values()),
               ["acd_name", "action", "override_openalex_id", "notes", "reviewed_at"])

    # Also update overrides / FP overrides files
    if action == "accept_override" and override_id:
        overrides = _read_csv(OVERRIDES_CSV)
        existing = {r["acd_name"] for r in overrides}
        if acd_name not in existing:
            overrides.append({"acd_name": acd_name, "correct_openalex_id": override_id})
            _write_csv(OVERRIDES_CSV, overrides, ["acd_name", "correct_openalex_id"])
    elif action == "reject":
        # Add current candidate to FP overrides
        resolved = {r["acd_name"]: r for r in _read_csv(RESOLVED_CSV)}
        row = resolved.get(acd_name, {})
        oid = row.get("openalex_id", "")
        if oid:
            fp = _read_csv(FP_OVERRIDES_CSV)
            fp.append({"acd_name": acd_name, "openalex_id_to_reject": oid})
            _write_csv(FP_OVERRIDES_CSV, fp, ["acd_name", "openalex_id_to_reject"])


def _flag_badges(flags_str: str) -> list[dict]:
    """Convert pipe-separated flags to badge dicts with colour and label."""
    flag_map = {
        "SUSPICIOUS_VOLUME":  {"label": "High Volume", "color": "#AD6A3C", "icon": "⚠"},
        "NO_AUNZ_HISTORY":    {"label": "No AU/NZ History", "color": "#8B0000", "icon": "🌏"},
        "SPECIALTY_WEAK":     {"label": "Weak Specialty", "color": "#553E51", "icon": "🔬"},
        "COMMON_NAME_RISK":   {"label": "Common Name", "color": "#814C7E", "icon": "👥"},
        "LLM_DISAGREEMENT":   {"label": "LLM Disagreement", "color": "#575571", "icon": "🤖"},
        "COUNTRY_MISMATCH":   {"label": "Country Mismatch", "color": "#C27D4E", "icon": "🗺"},
        "WRONG_SPECIALTY":    {"label": "Wrong Specialty", "color": "#8B0000", "icon": "❌"},
    }
    badges = []
    for flag in (flags_str or "").split("|"):
        flag = flag.strip()
        if flag and flag in flag_map:
            badges.append({**flag_map[flag], "flag": flag})
    return badges


def _load_review_members() -> list[dict]:
    """Load all REVIEW + flagged members with decision status."""
    resolved = {r["acd_name"]: r for r in _read_csv(RESOLVED_CSV)}
    review_names = {r["acd_name"] for r in _read_csv(REVIEW_CSV)}
    common_names = {r["acd_name"] for r in _read_csv(COMMON_NAME_CSV)}
    decisions = _load_decisions()

    members = []
    for name in sorted(review_names | common_names):
        row = resolved.get(name, {"acd_name": name})
        flags_str = row.get("ambiguity_flags", "")
        decision = decisions.get(name, {})
        members.append({
            "acd_name": name,
            "state": row.get("state", ""),
            "openalex_id": row.get("openalex_id", ""),
            "openalex_display_name": row.get("openalex_display_name", ""),
            "last_known_institution": row.get("last_known_institution", ""),
            "institution_country": row.get("institution_country", ""),
            "aunz_ever": row.get("aunz_ever", "0"),
            "works_count": row.get("works_count", "0"),
            "h_index": row.get("h_index", "0"),
            "total_score": row.get("total_score", "0"),
            "confidence": row.get("confidence", "REVIEW"),
            "resolution_method": row.get("resolution_method", ""),
            "llm_reasoning": row.get("llm_reasoning", ""),
            "ambiguity_flags": flags_str,
            "badges": _flag_badges(flags_str),
            "profile_url": row.get("profile_url", ""),
            "score_name": row.get("score_name", "0"),
            "score_country": row.get("score_country", "0"),
            "score_inst": row.get("score_inst", "0"),
            "score_topic": row.get("score_topic", "0"),
            "score_state": row.get("score_state", "0"),
            "score_hospital": row.get("score_hospital", "0"),
            "score_semantic": row.get("score_semantic", "0"),
            "score_llm": row.get("score_llm", "0"),
            "is_review": name in review_names,
            "is_flagged": name in common_names,
            "decision": decision.get("action", ""),
            "decision_at": decision.get("reviewed_at", ""),
            "override_id": decision.get("override_openalex_id", ""),
        })
    return members


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ACD Entity Resolution Review</title>
<style>
  :root {
    --bg:       #1B1424;
    --panel:    #3D3149;
    --mauve:    #814C7E;
    --violet:   #553E51;
    --copper:   #C27D4E;
    --burnt:    #AD6A3C;
    --tan:      #D99561;
    --cream:    #ECE7DF;
    --white:    #FFFFFE;
    --accent:   #575571;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--white); font-family: 'Segoe UI', sans-serif; min-height: 100vh; }

  /* Header */
  .header {
    background: linear-gradient(135deg, var(--panel) 0%, var(--mauve) 100%);
    padding: 20px 32px;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 2px solid var(--copper);
  }
  .header h1 { font-size: 1.4rem; font-weight: 700; color: var(--white); }
  .header .subtitle { font-size: 0.85rem; color: var(--cream); opacity: 0.8; margin-top: 2px; }
  .progress-bar-wrap { width: 260px; }
  .progress-label { font-size: 0.8rem; color: var(--cream); margin-bottom: 4px; text-align: right; }
  .progress-bar { background: var(--violet); border-radius: 8px; height: 10px; overflow: hidden; }
  .progress-fill { background: linear-gradient(90deg, var(--copper), var(--tan)); height: 100%; border-radius: 8px; transition: width 0.4s; }

  /* Stats bar */
  .stats-bar {
    background: var(--panel); padding: 12px 32px;
    display: flex; gap: 24px; align-items: center;
    border-bottom: 1px solid var(--accent);
  }
  .stat-chip { background: var(--violet); border-radius: 20px; padding: 4px 14px; font-size: 0.8rem; color: var(--cream); }
  .stat-chip.green { background: #2d5a3d; }
  .stat-chip.red { background: #5a2d2d; }
  .stat-chip.amber { background: #5a4a2d; }

  /* Filters */
  .filters { padding: 14px 32px; background: var(--bg); display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
  .filters input, .filters select {
    background: var(--panel); border: 1px solid var(--accent); color: var(--white);
    border-radius: 6px; padding: 7px 12px; font-size: 0.85rem;
  }
  .filters input::placeholder { color: var(--cream); opacity: 0.5; }
  .filter-label { font-size: 0.8rem; color: var(--cream); opacity: 0.7; }

  /* Table */
  .table-wrap { padding: 0 32px 32px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  thead th {
    background: var(--panel); color: var(--tan); padding: 10px 12px;
    text-align: left; font-weight: 600; position: sticky; top: 0; z-index: 2;
    border-bottom: 2px solid var(--copper);
  }
  tbody tr { border-bottom: 1px solid var(--accent); cursor: pointer; transition: background 0.15s; }
  tbody tr:hover { background: var(--panel); }
  tbody tr.decided { opacity: 0.55; }
  tbody tr.decided-accept { border-left: 3px solid #4CAF50; }
  tbody tr.decided-reject { border-left: 3px solid #f44336; }
  tbody tr.decided-override { border-left: 3px solid var(--copper); }
  td { padding: 9px 12px; vertical-align: middle; }

  /* Badges */
  .badge {
    display: inline-block; border-radius: 12px; padding: 2px 8px;
    font-size: 0.72rem; font-weight: 600; margin: 1px 2px; white-space: nowrap;
  }
  .badge-review { background: #3d2d4a; color: #c9a0dc; border: 1px solid #814C7E; }
  .badge-flagged { background: #3d2d1a; color: var(--tan); border: 1px solid var(--copper); }
  .badge-decided { background: #1a3d1a; color: #90ee90; border: 1px solid #4CAF50; }
  .badge-rejected { background: #3d1a1a; color: #ff9999; border: 1px solid #f44336; }

  /* Score bar */
  .score-bar { display: flex; align-items: center; gap: 6px; }
  .score-val { font-weight: 700; color: var(--tan); min-width: 32px; }
  .score-track { flex: 1; background: var(--accent); border-radius: 4px; height: 6px; max-width: 80px; }
  .score-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--copper), var(--tan)); }

  /* Detail panel */
  .detail-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
    z-index: 100; align-items: center; justify-content: center;
  }
  .detail-overlay.open { display: flex; }
  .detail-panel {
    background: var(--panel); border: 1px solid var(--copper);
    border-radius: 12px; width: 760px; max-width: 95vw; max-height: 90vh;
    overflow-y: auto; padding: 28px; position: relative;
  }
  .detail-panel h2 { color: var(--tan); font-size: 1.2rem; margin-bottom: 4px; }
  .detail-panel .sub { color: var(--cream); font-size: 0.85rem; opacity: 0.7; margin-bottom: 20px; }
  .detail-close {
    position: absolute; top: 16px; right: 20px;
    background: none; border: none; color: var(--cream); font-size: 1.4rem; cursor: pointer;
  }
  .detail-section { margin-bottom: 20px; }
  .detail-section h3 { color: var(--copper); font-size: 0.9rem; text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 10px; border-bottom: 1px solid var(--accent); padding-bottom: 4px; }
  .score-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .score-item { background: var(--violet); border-radius: 8px; padding: 8px 12px; }
  .score-item .label { font-size: 0.75rem; color: var(--cream); opacity: 0.7; }
  .score-item .value { font-size: 1.1rem; font-weight: 700; color: var(--tan); }
  .reasoning-box {
    background: var(--bg); border: 1px solid var(--accent); border-radius: 8px;
    padding: 12px; font-size: 0.85rem; color: var(--cream); line-height: 1.5;
    white-space: pre-wrap; max-height: 140px; overflow-y: auto;
  }
  .openalex-link { color: var(--tan); text-decoration: none; font-size: 0.85rem; }
  .openalex-link:hover { text-decoration: underline; }

  /* Action buttons */
  .action-bar { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 20px; }
  .btn {
    border: none; border-radius: 8px; padding: 10px 20px; font-size: 0.9rem;
    font-weight: 600; cursor: pointer; transition: opacity 0.15s;
  }
  .btn:hover { opacity: 0.85; }
  .btn-accept { background: #4CAF50; color: #fff; }
  .btn-reject { background: #f44336; color: #fff; }
  .btn-override { background: var(--copper); color: var(--bg); }
  .btn-skip { background: var(--accent); color: var(--white); }
  .override-input {
    background: var(--bg); border: 1px solid var(--copper); color: var(--white);
    border-radius: 6px; padding: 8px 12px; font-size: 0.85rem; width: 100%;
    margin-top: 10px; display: none;
  }
  .notes-input {
    background: var(--bg); border: 1px solid var(--accent); color: var(--white);
    border-radius: 6px; padding: 8px 12px; font-size: 0.85rem; width: 100%;
    margin-top: 8px; resize: vertical; min-height: 60px;
  }
  .decision-status {
    background: var(--bg); border-radius: 8px; padding: 10px 14px;
    font-size: 0.85rem; color: var(--cream); margin-top: 12px;
  }

  /* Empty state */
  .empty { text-align: center; padding: 60px; color: var(--cream); opacity: 0.5; }
  .empty .icon { font-size: 3rem; margin-bottom: 12px; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>ACD Entity Resolution Review</h1>
    <div class="subtitle">Manual adjudication of REVIEW-tier and flagged dermatologist profiles</div>
  </div>
  <div class="progress-bar-wrap">
    <div class="progress-label">{{ decided }} / {{ total }} reviewed</div>
    <div class="progress-bar">
      <div class="progress-fill" style="width: {{ pct }}%"></div>
    </div>
  </div>
</div>

<div class="stats-bar">
  <span class="stat-chip">Total: {{ total }}</span>
  <span class="stat-chip amber">REVIEW: {{ n_review }}</span>
  <span class="stat-chip amber">Flagged: {{ n_flagged }}</span>
  <span class="stat-chip green">Accepted: {{ n_accepted }}</span>
  <span class="stat-chip red">Rejected: {{ n_rejected }}</span>
  <span class="stat-chip">Pending: {{ total - decided }}</span>
</div>

<div class="filters">
  <span class="filter-label">Filter:</span>
  <input type="text" id="searchInput" placeholder="Search name or institution..." oninput="filterTable()">
  <select id="statusFilter" onchange="filterTable()">
    <option value="">All statuses</option>
    <option value="pending">Pending only</option>
    <option value="decided">Decided only</option>
    <option value="REVIEW">REVIEW tier</option>
    <option value="flagged">Flagged only</option>
  </select>
  <select id="stateFilter" onchange="filterTable()">
    <option value="">All states</option>
    {% for s in states %}<option value="{{ s }}">{{ s }}</option>{% endfor %}
  </select>
</div>

<div class="table-wrap">
{% if members %}
<table id="reviewTable">
  <thead>
    <tr>
      <th>#</th>
      <th>Name</th>
      <th>State</th>
      <th>OpenAlex Match</th>
      <th>Institution</th>
      <th>Works</th>
      <th>Score</th>
      <th>Flags</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
  {% for m in members %}
  <tr class="member-row {% if m.decision %}decided decided-{{ m.decision }}{% endif %}"
      data-name="{{ m.acd_name }}"
      data-state="{{ m.state }}"
      data-status="{{ 'decided' if m.decision else 'pending' }}"
      data-tier="{{ 'REVIEW' if m.is_review else '' }}"
      data-flagged="{{ 'flagged' if m.is_flagged else '' }}"
      onclick="openDetail('{{ m.acd_name | e }}')">
    <td style="color: var(--accent); font-size: 0.8rem;">{{ loop.index }}</td>
    <td style="font-weight: 600; color: var(--white);">{{ m.acd_name }}</td>
    <td><span style="color: var(--cream); font-size: 0.8rem;">{{ m.state }}</span></td>
    <td style="color: var(--cream);">
      {% if m.openalex_display_name %}
        {{ m.openalex_display_name }}
        {% if m.profile_url %}
          <a href="{{ m.profile_url }}" target="_blank" class="openalex-link" onclick="event.stopPropagation()">↗</a>
        {% endif %}
      {% else %}
        <span style="opacity: 0.4; font-style: italic;">No match found</span>
      {% endif %}
    </td>
    <td style="color: var(--cream); font-size: 0.8rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
      {{ m.last_known_institution or '—' }}
    </td>
    <td style="color: var(--cream);">{{ m.works_count }}</td>
    <td>
      <div class="score-bar">
        <span class="score-val">{{ m.total_score }}</span>
        <div class="score-track"><div class="score-fill" style="width: {{ [int(m.total_score|string or '0') * 100 // 155, 100]|min }}%"></div></div>
      </div>
    </td>
    <td>
      {% if m.is_review %}<span class="badge badge-review">REVIEW</span>{% endif %}
      {% if m.is_flagged %}<span class="badge badge-flagged">FLAGGED</span>{% endif %}
      {% for b in m.badges %}
        <span class="badge" style="background: {{ b.color }}22; color: {{ b.color }}; border: 1px solid {{ b.color }}55;">
          {{ b.icon }} {{ b.label }}
        </span>
      {% endfor %}
    </td>
    <td>
      {% if m.decision == 'accept' %}<span class="badge badge-decided">✓ Accepted</span>
      {% elif m.decision == 'reject' %}<span class="badge badge-rejected">✗ Rejected</span>
      {% elif m.decision == 'accept_override' %}<span class="badge" style="background: #3d2d1a; color: var(--tan); border: 1px solid var(--copper);">⤷ Override</span>
      {% elif m.decision == 'skip' %}<span class="badge" style="background: var(--accent)22; color: var(--cream);">→ Skipped</span>
      {% else %}<span style="color: var(--accent); font-size: 0.8rem;">Pending</span>{% endif %}
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<div class="empty">
  <div class="icon">✅</div>
  <div>No members require review.</div>
  <div style="margin-top: 8px; font-size: 0.85rem;">Run the resolver first to generate review_queue.csv</div>
</div>
{% endif %}
</div>

<!-- Detail overlay -->
<div class="detail-overlay" id="detailOverlay" onclick="closeDetailOnBg(event)">
  <div class="detail-panel" id="detailPanel">
    <button class="detail-close" onclick="closeDetail()">✕</button>
    <h2 id="dp-name"></h2>
    <div class="sub" id="dp-sub"></div>

    <div class="detail-section">
      <h3>OpenAlex Match</h3>
      <div id="dp-match"></div>
    </div>

    <div class="detail-section">
      <h3>Scoring Breakdown</h3>
      <div class="score-grid" id="dp-scores"></div>
    </div>

    <div class="detail-section" id="dp-llm-section">
      <h3>LLM Reasoning</h3>
      <div class="reasoning-box" id="dp-llm"></div>
    </div>

    <div class="detail-section">
      <h3>Warning Flags</h3>
      <div id="dp-flags"></div>
    </div>

    <div class="detail-section">
      <h3>Decision</h3>
      <div class="action-bar">
        <button class="btn btn-accept" onclick="submitDecision('accept')">✓ Accept Match</button>
        <button class="btn btn-reject" onclick="submitDecision('reject')">✗ Reject Match</button>
        <button class="btn btn-override" onclick="toggleOverride()">⤷ Override ID</button>
        <button class="btn btn-skip" onclick="submitDecision('skip')">→ Skip</button>
      </div>
      <input type="text" class="override-input" id="overrideInput" placeholder="Enter correct OpenAlex ID (e.g. A1234567890)">
      <button class="btn btn-override" id="overrideSubmit" style="display:none; margin-top: 8px;" onclick="submitDecision('accept_override')">Submit Override</button>
      <textarea class="notes-input" id="notesInput" placeholder="Optional notes..."></textarea>
      <div class="decision-status" id="dp-decision"></div>
    </div>
  </div>
</div>

<script>
const MEMBERS = {{ members_json | safe }};
let currentName = null;

function openDetail(name) {
  currentName = name;
  const m = MEMBERS.find(x => x.acd_name === name);
  if (!m) return;

  document.getElementById('dp-name').textContent = m.acd_name;
  document.getElementById('dp-sub').textContent = `State: ${m.state} | Priority: ${m.priority || '—'} | AHPRA: ${m.ahpra_proven === '1' ? 'Proven' : 'Not proven'}`;

  // Match
  const matchEl = document.getElementById('dp-match');
  if (m.openalex_display_name) {
    matchEl.innerHTML = `
      <strong style="color: var(--white);">${m.openalex_display_name}</strong>
      ${m.profile_url ? `<a href="${m.profile_url}" target="_blank" class="openalex-link" style="margin-left: 8px;">View on OpenAlex ↗</a>` : ''}<br>
      <span style="color: var(--cream); font-size: 0.85rem;">
        ${m.last_known_institution || '—'} · ${m.institution_country || '—'} · 
        Works: ${m.works_count} · h-index: ${m.h_index} · AU/NZ ever: ${m.aunz_ever === '1' ? 'Yes' : 'No'}
      </span>`;
  } else {
    matchEl.innerHTML = '<span style="color: var(--accent); font-style: italic;">No candidate found</span>';
  }

  // Scores
  const scores = [
    {label: 'Name', val: m.score_name}, {label: 'Country', val: m.score_country},
    {label: 'Institution', val: m.score_inst}, {label: 'Topic', val: m.score_topic},
    {label: 'State', val: m.score_state}, {label: 'Hospital', val: m.score_hospital},
    {label: 'Semantic', val: m.score_semantic}, {label: 'LLM', val: m.score_llm},
    {label: 'TOTAL', val: m.total_score},
  ];
  document.getElementById('dp-scores').innerHTML = scores.map(s => `
    <div class="score-item" style="${s.label === 'TOTAL' ? 'border: 1px solid var(--copper);' : ''}">
      <div class="label">${s.label}</div>
      <div class="value" style="${parseInt(s.val) < 0 ? 'color: #f44336;' : ''}">${s.val}</div>
    </div>`).join('');

  // LLM reasoning
  const llmSection = document.getElementById('dp-llm-section');
  if (m.llm_reasoning) {
    llmSection.style.display = '';
    document.getElementById('dp-llm').textContent = m.llm_reasoning;
  } else {
    llmSection.style.display = 'none';
  }

  // Flags
  const flagsEl = document.getElementById('dp-flags');
  if (m.badges && m.badges.length > 0) {
    flagsEl.innerHTML = m.badges.map(b =>
      `<span class="badge" style="background: ${b.color}22; color: ${b.color}; border: 1px solid ${b.color}55; font-size: 0.8rem; padding: 4px 10px; margin: 3px;">
        ${b.icon} ${b.label}
      </span>`).join('');
  } else {
    flagsEl.innerHTML = '<span style="color: var(--accent); font-size: 0.85rem;">No warning flags</span>';
  }

  // Decision status
  const decEl = document.getElementById('dp-decision');
  if (m.decision) {
    decEl.innerHTML = `<strong style="color: var(--tan);">Previous decision:</strong> ${m.decision} 
      ${m.decision_at ? `<span style="color: var(--accent); font-size: 0.8rem;">(${m.decision_at.slice(0,16)})</span>` : ''}
      ${m.override_id ? `<br>Override ID: <code style="color: var(--copper);">${m.override_id}</code>` : ''}`;
  } else {
    decEl.innerHTML = '<span style="color: var(--accent); font-size: 0.85rem;">No decision yet</span>';
  }

  document.getElementById('overrideInput').style.display = 'none';
  document.getElementById('overrideSubmit').style.display = 'none';
  document.getElementById('notesInput').value = '';
  document.getElementById('detailOverlay').classList.add('open');
}

function closeDetail() {
  document.getElementById('detailOverlay').classList.remove('open');
  currentName = null;
}

function closeDetailOnBg(e) {
  if (e.target === document.getElementById('detailOverlay')) closeDetail();
}

function toggleOverride() {
  const inp = document.getElementById('overrideInput');
  const btn = document.getElementById('overrideSubmit');
  const show = inp.style.display === 'none';
  inp.style.display = show ? 'block' : 'none';
  btn.style.display = show ? 'block' : 'none';
}

function submitDecision(action) {
  if (!currentName) return;
  const overrideId = document.getElementById('overrideInput').value.trim();
  const notes = document.getElementById('notesInput').value.trim();
  fetch('/decide', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({acd_name: currentName, action, override_id: overrideId, notes}),
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      // Update local member
      const m = MEMBERS.find(x => x.acd_name === currentName);
      if (m) { m.decision = action; m.override_id = overrideId; }
      // Update row
      const row = document.querySelector(`tr[data-name="${CSS.escape(currentName)}"]`);
      if (row) {
        row.className = `member-row decided decided-${action}`;
        row.cells[8].innerHTML = action === 'accept'
          ? '<span class="badge badge-decided">✓ Accepted</span>'
          : action === 'reject'
          ? '<span class="badge badge-rejected">✗ Rejected</span>'
          : action === 'accept_override'
          ? '<span class="badge" style="background: #3d2d1a; color: var(--tan); border: 1px solid var(--copper);">⤷ Override</span>'
          : '<span class="badge" style="background: var(--accent)22; color: var(--cream);">→ Skipped</span>';
      }
      closeDetail();
      // Refresh stats
      location.reload();
    }
  });
}

function filterTable() {
  const search = document.getElementById('searchInput').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const state  = document.getElementById('stateFilter').value;
  document.querySelectorAll('#reviewTable tbody tr').forEach(row => {
    const name  = (row.dataset.name || '').toLowerCase();
    const inst  = (row.cells[4]?.textContent || '').toLowerCase();
    const rState = row.dataset.state || '';
    const rStatus = row.dataset.status || '';
    const rTier  = row.dataset.tier || '';
    const rFlagged = row.dataset.flagged || '';

    let show = true;
    if (search && !name.includes(search) && !inst.includes(search)) show = false;
    if (state && rState !== state) show = false;
    if (status === 'pending' && rStatus !== 'pending') show = false;
    if (status === 'decided' && rStatus !== 'decided') show = false;
    if (status === 'REVIEW' && rTier !== 'REVIEW') show = false;
    if (status === 'flagged' && rFlagged !== 'flagged') show = false;
    row.style.display = show ? '' : 'none';
  });
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    members = _load_review_members()
    decisions = _load_decisions()
    decided = sum(1 for m in members if m["decision"])
    total = len(members)
    pct = round(decided / total * 100) if total else 0
    n_review = sum(1 for m in members if m["is_review"])
    n_flagged = sum(1 for m in members if m["is_flagged"])
    n_accepted = sum(1 for m in members if m["decision"] in ("accept", "accept_override"))
    n_rejected = sum(1 for m in members if m["decision"] == "reject")
    states = sorted({m["state"] for m in members if m["state"]})
    return render_template_string(
        _TEMPLATE,
        members=members,
        members_json=json.dumps(members),
        total=total,
        decided=decided,
        pct=pct,
        n_review=n_review,
        n_flagged=n_flagged,
        n_accepted=n_accepted,
        n_rejected=n_rejected,
        states=states,
    )


@app.route("/decide", methods=["POST"])
def decide():
    data = request.get_json(force=True)
    acd_name   = data.get("acd_name", "").strip()
    action     = data.get("action", "skip")
    override_id = data.get("override_id", "").strip()
    notes      = data.get("notes", "").strip()
    if not acd_name:
        return jsonify({"ok": False, "error": "missing acd_name"})
    _save_decision(acd_name, action, override_id, notes)
    return jsonify({"ok": True})


@app.route("/export")
def export():
    """Download the current decisions as CSV."""
    rows = _read_csv(DECISIONS_CSV)
    from flask import Response
    import io
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=review_decisions.csv"},
    )


@app.route("/api/stats")
def api_stats():
    members = _load_review_members()
    decided = sum(1 for m in members if m["decision"])
    return jsonify({
        "total": len(members),
        "decided": decided,
        "pending": len(members) - decided,
        "accepted": sum(1 for m in members if m["decision"] in ("accept", "accept_override")),
        "rejected": sum(1 for m in members if m["decision"] == "reject"),
    })


if __name__ == "__main__":
    port = int(os.environ.get("REVIEW_PORT", 5050))
    print(f"\n{'='*60}")
    print("ACD Entity Resolution Review Interface")
    print(f"{'='*60}")
    print(f"  → http://localhost:{port}")
    print(f"  Review CSV  : {REVIEW_CSV}")
    print(f"  Decisions   : {DECISIONS_CSV}")
    print(f"{'='*60}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
