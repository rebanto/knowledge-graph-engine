import json
from backend.core.llm_client import generate_json, generate_text

SYNTHESIS_PROMPT = """You are an expert research analyst with deep expertise in knowledge graphs and academic research.
{conversation_context}
Question: {question}
Retrieval method used: {retrieval_type}

Retrieved data (graph records, entity stats, and document passages):
{results}

Return ONLY valid JSON with this exact structure. Every field is required.

{{
  "answer": "Your detailed markdown analysis. Requirements: (1) Open with a direct 1–2 sentence answer grounded in the data. (2) Trace specific relationship chains found in the data using arrow notation, e.g.: **Geoffrey Hinton** → AUTHORED → *Deep Residual Learning* → CITED BY 3 subsequent papers in this dataset. (3) Report actual numbers and statistics from the retrieved data. (4) Identify non-obvious connections and patterns between entities. (5) If the data has a "conflicts" array, it lists disputed claims where two sources disagree about the same pair of entities — explicitly flag each one in the prose (e.g. "**A** and **B**: sources disagree — one SUPPORTS, another CONTRADICTS"), and never present a disputed claim as settled fact. (6) Use **bold** for entity names, *italics* for paper titles. Write at minimum 3 substantive paragraphs when data is rich enough to support it.",

  "key_entities": [
    {{"name": "exact name from the data", "type": "Person|Paper|Concept|Organization|Topic|Event", "role": "one sentence on why this entity matters for the question"}}
  ],

  "insights": [
    /* Pick 1–3 insight types from the list below that genuinely fit the retrieved data.
       DO NOT invent numbers or entities not found in the data. */

    /* BAR_CHART — rankings, counts, or distributions (use when you see aggregation results) */
    {{
      "type": "bar_chart",
      "title": "descriptive title max 50 chars",
      "x_label": "axis label",
      "y_label": "axis label",
      "color": "#c9974a",
      "data": [{{"name": "label ≤25 chars", "value": 42}}]
    }},

    /* FLOW_PATH — chain of connections (use when data shows a traversal path) */
    {{
      "type": "flow_path",
      "title": "title",
      "steps": [
        {{"entity": "EntityA", "entity_type": "Person", "relation": null}},
        {{"entity": "PaperB", "entity_type": "Paper", "relation": "AUTHORED"}},
        {{"entity": "ConceptC", "entity_type": "Concept", "relation": "INTRODUCES"}}
      ]
    }},

    /* STAT_GRID — key numbers (always include at least this type) */
    {{
      "type": "stat_grid",
      "stats": [
        {{"label": "Results Found", "value": "12", "subtitle": "from graph query"}},
        {{"label": "Unique Authors", "value": "7", "subtitle": "across all papers"}}
      ]
    }},

    /* COMPARISON_TABLE — comparing multiple entities on same properties */
    {{
      "type": "comparison_table",
      "title": "title",
      "columns": ["Entity", "Property 1", "Property 2"],
      "rows": [["Row value 1", "val", "val"], ["Row 2", "val", "val"]]
    }},

    /* TIMELINE — chronological events when dates/years are present */
    {{
      "type": "timeline",
      "title": "title",
      "events": [
        {{"year": "2017", "label": "short label max 40 chars", "detail": "optional longer context"}}
      ]
    }}
  ]
}}

Hard rules:
- Every entity name, date, count, and relationship in the answer and insights MUST appear in the retrieved data above.
- If data is sparse: write a short honest answer and include only a stat_grid with "Results Found: 0".
- key_entities: 2–6 items, most important only.
- insights: 1–3 items maximum, no filler. stat_grid should almost always be present.
- bar_chart: max 12 bars; data values must be real numbers extracted or computed from the retrieved data.
- The "answer" field must contain valid markdown only. No JSON inside the answer string.
"""

_FALLBACK_PROMPT = """Answer this research question using ONLY the provided data. Do not use outside knowledge.
{conversation_context}
Question: {question}

Data:
{results}

Write a concise, well-cited prose answer (2–4 paragraphs). Bold entity names."""


# Wraps the history block in an instruction that lets the synthesizer reference
# earlier turns for continuity ("as noted earlier") WITHOUT loosening grounding:
# the conversation is context, never a source of facts. Only the retrieved data
# may be cited. Empty when there is no history (first turn / single-shot).
_CONVERSATION_CONTEXT_TEMPLATE = """
This is a follow-up in an ongoing conversation. Use the history ONLY to understand what the user is referring to and to keep continuity (you may say "as noted earlier"). Do NOT treat anything in the history as a fact to cite — every cited fact must still come from the Retrieved data below.

Conversation so far:
{history}
"""


def _conversation_context(history_block: str | None) -> str:
    if not history_block or not history_block.strip():
        return ""
    return _CONVERSATION_CONTEXT_TEMPLATE.format(history=history_block.strip())


# Large enough to hold the full retrieved set (top-k vector chunks + graph
# records). The old 8k cap silently dropped most retrieved chunks before the
# LLM saw them, which made answers miss content that was actually retrieved.
_SYNTH_INPUT_CHARS = 40000


async def synthesize_answer(
    question: str,
    results: dict,
    retrieval_type: str = "hybrid",
    conversation_context: str | None = None,
) -> dict:
    ctx = _conversation_context(conversation_context)
    prompt = SYNTHESIS_PROMPT.format(
        conversation_context=ctx,
        question=question,
        retrieval_type=retrieval_type,
        results=json.dumps(results, indent=2, default=str)[:_SYNTH_INPUT_CHARS],
    )

    structured = await generate_json(prompt)
    answer = structured.get("answer", "").strip()

    if not answer:
        answer = await generate_text(
            _FALLBACK_PROMPT.format(
                conversation_context=ctx,
                question=question,
                results=json.dumps(results, default=str)[:5000],
            )
        )
        return {"answer": answer, "key_entities": [], "insights": []}

    return {
        "answer": answer,
        "key_entities": _clean_entities(structured.get("key_entities", [])),
        "insights": _clean_insights(structured.get("insights", [])),
    }


def _clean_entities(raw: list) -> list:
    valid = []
    for e in raw:
        if isinstance(e, dict) and e.get("name") and e.get("type"):
            valid.append({
                "name": str(e["name"])[:100],
                "type": str(e.get("type", "Concept")),
                "role": str(e.get("role", ""))[:200],
            })
    return valid[:6]


def _clean_insights(raw: list) -> list:
    valid_types = {"bar_chart", "flow_path", "stat_grid", "comparison_table", "timeline"}
    out = []
    for ins in raw:
        if not isinstance(ins, dict):
            continue
        t = ins.get("type")
        if t not in valid_types:
            continue
        try:
            if t == "bar_chart":
                data = [
                    {"name": str(d.get("name", ""))[:30], "value": float(d.get("value", 0))}
                    for d in (ins.get("data") or [])
                    if isinstance(d, dict)
                ]
                if data:
                    out.append({
                        "type": t,
                        "title": str(ins.get("title", ""))[:60],
                        "x_label": str(ins.get("x_label", "")),
                        "y_label": str(ins.get("y_label", "")),
                        "color": str(ins.get("color", "#c9974a")),
                        "data": data[:14],
                    })
            elif t == "flow_path":
                steps = [
                    {
                        "entity": str(s.get("entity", ""))[:80],
                        "entity_type": str(s.get("entity_type", "Concept")),
                        "relation": s.get("relation"),
                    }
                    for s in (ins.get("steps") or [])
                    if isinstance(s, dict)
                ]
                if len(steps) >= 2:
                    out.append({"type": t, "title": str(ins.get("title", ""))[:60], "steps": steps[:10]})
            elif t == "stat_grid":
                stats = [
                    {
                        "label": str(s.get("label", ""))[:40],
                        "value": str(s.get("value", ""))[:20],
                        "subtitle": str(s.get("subtitle", ""))[:60] if s.get("subtitle") else None,
                    }
                    for s in (ins.get("stats") or [])
                    if isinstance(s, dict)
                ]
                if stats:
                    out.append({"type": t, "stats": stats[:8]})
            elif t == "comparison_table":
                cols = [str(c)[:40] for c in (ins.get("columns") or [])]
                rows = [
                    [str(v)[:60] for v in row]
                    for row in (ins.get("rows") or [])
                    if isinstance(row, list)
                ]
                if cols and rows:
                    out.append({
                        "type": t,
                        "title": str(ins.get("title", ""))[:60],
                        "columns": cols,
                        "rows": rows[:15],
                    })
            elif t == "timeline":
                events = [
                    {
                        "year": str(e.get("year", ""))[:10],
                        "label": str(e.get("label", ""))[:60],
                        "detail": str(e.get("detail", ""))[:200] if e.get("detail") else None,
                    }
                    for e in (ins.get("events") or [])
                    if isinstance(e, dict)
                ]
                if events:
                    out.append({"type": t, "title": str(ins.get("title", ""))[:60], "events": events[:20]})
        except Exception:
            continue
    return out[:4]
