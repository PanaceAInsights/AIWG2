"""ACD Research Intelligence Platform — AI chatbot backend.

Uses Claude claude-sonnet-4-5 with extended thinking + prompt caching for the
natural-language interface to the ACD research dataset.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Generator

logger = logging.getLogger("acd.ai")

_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 8000
_THINKING_BUDGET = 5000

_SYSTEM_PROMPT = """You are the ACD Research Intelligence Assistant — an expert AI
embedded in the Australasian College of Dermatologists (ACD) Research Intelligence
Platform. You have access to a comprehensive dataset of Australian and New Zealand
dermatologists, their publications, funding grants, and clinical trials.

Your role is to help healthcare researchers, administrators, and policy makers
understand the dermatology research landscape in Australia and New Zealand.

You can answer questions such as:
- Who are the top researchers in psoriasis / melanoma / atopic dermatitis?
- Which states have the most active clinical trial investigators?
- What is the funding landscape for skin cancer research?
- Who collaborates most with whom?
- What are the emerging research topics in Australian dermatology?

Always be precise, cite specific numbers from the data, and acknowledge
uncertainty when data is incomplete. Do not fabricate statistics.

Current dataset snapshot:
{snapshot}
"""

SUGGESTED_QUESTIONS = [
    "Who are the top 10 dermatologists by total publications?",
    "Which states have the most active clinical trial investigators?",
    "What are the most common dermatology research topics?",
    "Who are the leading melanoma researchers in Australia?",
    "Which dermatologists have the most funding grants?",
    "What is the trend in dermatology publications over the last 10 years?",
    "Who are the top collaborators in paediatric dermatology?",
    "Which institutions produce the most dermatology research?",
]


def _build_snapshot(data: dict) -> str:
    """Build a concise text snapshot of the dataset for the system prompt."""
    lines = []
    kpis = data.get("kpis", {})
    if kpis:
        lines.append("=== DATASET OVERVIEW ===")
        lines.append(f"Total dermatologists in registry: {kpis.get('n_total', 'N/A')}")
        lines.append(f"Successfully resolved to OpenAlex: {kpis.get('n_resolved', 'N/A')}")
        lines.append(f"Flagged for manual review: {kpis.get('n_review', 'N/A')}")
        lines.append(f"Total publications indexed: {kpis.get('n_pubs', 'N/A')}")
        lines.append(f"Dermatology-relevant publications: {kpis.get('n_derm_pubs', 'N/A')}")
        lines.append(f"Total citations: {kpis.get('total_citations', 'N/A')}")
        lines.append(f"Clinical trials matched: {kpis.get('n_trials', 'N/A')}")
        lines.append(f"Members with funding grants: {kpis.get('n_funded', 'N/A')}")

    top_researchers = data.get("top_researchers", [])
    if top_researchers:
        lines.append("\n=== TOP 20 RESEARCHERS BY PUBLICATIONS ===")
        for r in top_researchers[:20]:
            lines.append(
                f"  {r.get('acd_name', '')} ({r.get('state', '')}) — "
                f"{r.get('works_count', 0)} works, {r.get('total_citations', 0)} citations"
            )

    top_topics = data.get("top_topics", [])
    if top_topics:
        lines.append("\n=== TOP RESEARCH TOPICS ===")
        for t in top_topics[:15]:
            lines.append(f"  {t.get('SubTopic', t.get('topic', ''))} — {t.get('count', 0)} publications")

    state_dist = data.get("state_distribution", {})
    if state_dist:
        lines.append("\n=== MEMBERS BY STATE ===")
        for state, count in sorted(state_dist.items(), key=lambda x: -x[1]):
            lines.append(f"  {state}: {count}")

    return "\n".join(lines) if lines else "Dataset not yet loaded."


def build_context_snapshot() -> str:
    """Build snapshot from live data module."""
    try:
        from dashboard.data import (
            get_summary_kpis, load_authors, load_publications, load_stats
        )
        import pandas as pd

        kpis = get_summary_kpis()
        authors = load_authors()
        pubs = load_publications()
        stats = load_stats()

        top_researchers = []
        if not stats.empty and "acd_name" in stats.columns:
            sort_col = "total_works" if "total_works" in stats.columns else "works_count"
            if sort_col in stats.columns:
                top = stats.nlargest(20, sort_col)
                for _, row in top.iterrows():
                    top_researchers.append({
                        "acd_name": row.get("acd_name", ""),
                        "state": row.get("state", ""),
                        "works_count": int(row.get(sort_col, 0)),
                        "total_citations": int(row.get("total_citations", 0)),
                    })
        elif not authors.empty:
            sort_col = "works_count"
            if sort_col in authors.columns:
                top = authors.nlargest(20, sort_col)
                for _, row in top.iterrows():
                    top_researchers.append({
                        "acd_name": row.get("acd_name", ""),
                        "state": row.get("state", ""),
                        "works_count": int(row.get("works_count", 0)),
                        "total_citations": 0,
                    })

        top_topics = []
        if not pubs.empty and "SubTopic" in pubs.columns:
            tc = pubs["SubTopic"].dropna().value_counts().head(15)
            top_topics = [{"SubTopic": k, "count": int(v)} for k, v in tc.items()]

        state_dist = {}
        if not authors.empty and "state" in authors.columns:
            state_dist = authors["state"].value_counts().to_dict()

        return _build_snapshot({
            "kpis": kpis,
            "top_researchers": top_researchers,
            "top_topics": top_topics,
            "state_distribution": state_dist,
        })
    except Exception as exc:
        logger.warning("Could not build context snapshot: %s", exc)
        return "Dataset snapshot unavailable."


def stream_response(
    messages: list[dict],
    system_snapshot: str | None = None,
) -> Generator[str, None, None]:
    """Stream a Claude response token by token."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield "Error: ANTHROPIC_API_KEY not configured."
        return

    snapshot = system_snapshot or build_context_snapshot()
    system = _SYSTEM_PROMPT.format(snapshot=snapshot)

    try:
        import anthropic  # lazy import — avoids 1.5s cold-start penalty
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            thinking={
                "type": "enabled",
                "budget_tokens": _THINKING_BUDGET,
            },
            messages=messages,
        ) as stream:
            for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "type") and delta.type == "text_delta":
                            yield delta.text
    except Exception as exc:
        logger.error("Error in stream_response: %s", exc)
        yield f"\n\n*Error: {exc}*"


def get_single_response(
    messages: list[dict],
    system_snapshot: str | None = None,
) -> str:
    """Non-streaming response for programmatic use."""
    return "".join(stream_response(messages, system_snapshot))


# ---------------------------------------------------------------------------
# RMSANZ-compatible chat function (used by app.py callback)
# ---------------------------------------------------------------------------
def chat(
    user_message: str,
    history: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Single-call chat with extended thinking and prompt caching.

    Falls back gracefully: thinking → standard → plain.
    Returns (assistant_text, updated_history).
    """
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY not configured.", list(history or [])

    client = anthropic.Anthropic(api_key=api_key)
    snapshot = build_context_snapshot()
    system_text = _SYSTEM_PROMPT.format(snapshot=snapshot)
    system_blocks = [
        {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
    ]
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    def _extract(response) -> str:
        return "\n".join(
            b.text for b in response.content
            if getattr(b, "type", None) == "text" and hasattr(b, "text")
        )

    def _finalise(text: str) -> tuple[str, list[dict]]:
        messages.append({"role": "assistant", "content": text})
        trimmed = messages[-12:] if len(messages) > 12 else messages
        return text, trimmed

    # Attempt 1: extended thinking + caching
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16_000,
            thinking={"type": "enabled", "budget_tokens": 10_000},
            system=system_blocks,
            messages=messages,
        )
        return _finalise(_extract(resp))
    except Exception as exc:
        err = str(exc).lower()
        if not any(k in err for k in ("thinking", "not supported", "invalid", "parameter")):
            logger.warning("Thinking call failed (%s), trying standard", exc)

    # Attempt 2: standard + caching
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4_096,
            system=system_blocks,
            messages=messages,
        )
        return _finalise(_extract(resp))
    except Exception as exc:
        logger.warning("Cached call failed (%s), trying plain", exc)

    # Attempt 3: plain
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4_096,
        system=system_text,
        messages=messages,
    )
    return _finalise(_extract(resp))
