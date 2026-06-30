"""
Multi-agent "Deep Research" orchestrator.

A single-shot question runs one retrieval and one synthesis. That is the right
default, but it caps out on genuinely compound questions ("compare how the
funding networks behind A and B differ, and which findings each cites") because
one Cypher query / one vector pull can't fan out across several distinct
sub-investigations.

This module layers a lead-agent / sub-agent pattern ON TOP of the existing
`answer_question` pipeline — it does not replace it:

    plan      → a planner LLM decomposes the question into focused sub-questions,
                each with a suggested retrieval route.
    research  → each sub-question runs through the UNCHANGED qa pipeline
                (router → graph/vector → synthesizer), in bounded parallel.
                Each sub-agent is therefore independently grounded.
    synthesize→ a lead LLM fuses the sub-answers into one report, grounded ONLY
                in what the sub-agents found.
    verify    → the existing faithfulness judge (backend/eval/judge.py) scores the
                final report against the union of all retrieved evidence. The
                supported-claim fraction is surfaced to the user as a trust score.

The whole thing is opt-in: the regular /question path is untouched and remains
the always-working fallback (matching the project's "simple path always
survives" principle). Every fact still traces to retrieved data — the planner
and lead never introduce sources, they only route and fuse.
"""
import os
import json
import asyncio

from backend.core.qa_pipeline import answer_question
from backend.core.llm_client import generate_json, generate_text
from backend.eval.judge import judge_faithfulness
from backend.core.trust import trust_from_claims

# Bound fan-out so a 4-way decomposition doesn't fire 4× the LLM calls at once
# into the free-tier per-minute quota. The pipeline already backs off on 429s;
# this keeps the burst small enough that it rarely has to.
_CONCURRENCY = int(os.environ.get("DEEP_RESEARCH_CONCURRENCY", 2))
_MAX_SUBQUESTIONS = int(os.environ.get("DEEP_RESEARCH_MAX_SUBQUESTIONS", 4))

_VALID_ROUTES = {"graph", "vector", "hybrid"}


PLAN_PROMPT = """You are the lead researcher of a knowledge-graph research engine. Break the user's
question into focused sub-questions that, answered together, fully address it.

The engine answers each sub-question two ways:
- a knowledge GRAPH of entities (Person, Organization, Paper, Concept, Event, Topic)
  connected by typed relationships — best for connections, paths, collaborations,
  citations, funding, contradictions between named entities.
- a VECTOR store of document passages — best for content, findings, summaries,
  evidence, open problems.

Rules:
- Produce between 1 and {max_sub} sub-questions. Use the FEWEST that fully cover
  the question — a simple question may need only 1.
- Each sub-question must be self-contained (no pronouns referring to other
  sub-questions) and independently answerable.
- For each, pick the best route: "graph", "vector", or "hybrid".
- Do NOT answer the questions. Only decompose and route.

User question: {question}

Return ONLY JSON:
{{"subquestions": [{{"question": "string", "route": "graph"|"vector"|"hybrid", "why": "short reason"}}]}}"""


SYNTHESIS_PROMPT = """You are the lead researcher writing the final report. Below are the findings your
sub-agents gathered, each from the engine's knowledge graph and document store.

Original question:
{question}

Sub-agent findings:
{findings}

Write a single cohesive answer to the original question. Strict rules:
- Use ONLY the information in the sub-agent findings above. Do NOT add outside
  knowledge. If the findings don't cover part of the question, say so plainly.
- Synthesize across sub-agents — connect and contrast their findings, don't just
  concatenate them.
- Be specific: name the entities, relationships, and sources the findings contain.
- Write in clear prose (markdown allowed). No preamble like "Based on the findings".

Return ONLY the report text."""


async def plan_research(question: str, workspace_id: str) -> list[dict]:
    """Decompose a question into routed sub-questions. Falls back to a single
    hybrid sub-question (the original) if the planner returns nothing usable, so
    deep research degrades to a normal one-shot rather than failing."""
    data = await generate_json(
        PLAN_PROMPT.format(question=question, max_sub=_MAX_SUBQUESTIONS)
    )
    raw = data.get("subquestions")
    plan: list[dict] = []
    if isinstance(raw, list):
        for item in raw[:_MAX_SUBQUESTIONS]:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question", "")).strip()
            if not q:
                continue
            route = str(item.get("route", "")).lower()
            if route not in _VALID_ROUTES:
                route = "hybrid"
            plan.append({"question": q, "route": route,
                         "why": str(item.get("why", ""))[:200]})
    if not plan:
        plan = [{"question": question, "route": "hybrid",
                 "why": "Could not decompose — answering directly."}]
    return plan


async def _research_one(sub: dict, workspace_id: str) -> dict:
    """Run one sub-question through the existing pipeline, pinned to its route."""
    res = await answer_question(
        sub["question"], workspace_id, force_route=sub["route"]
    )
    return {
        "question": sub["question"],
        "route": sub["route"],
        "why": sub["why"],
        "answer": res.get("answer", ""),
        "graph_records": res.get("graph_records", []),
        "vector_chunks": res.get("vector_chunks", []),
        "conflicts": res.get("conflicts", []),
        "key_entities": res.get("key_entities", []),
    }


def _aggregate_evidence(subanswers: list[dict]) -> dict:
    """Union the structured evidence across sub-agents into one results payload —
    the same shape qa_pipeline hands the synthesizer/judge, so the judge can
    fact-check the fused report against everything that was retrieved."""
    graph_records: list[dict] = []
    vector_passages: list[dict] = []
    conflicts: list[dict] = []
    seen_conflicts: set = set()
    for sa in subanswers:
        graph_records.extend(sa.get("graph_records", []))
        vector_passages.extend(sa.get("vector_chunks", []))
        for c in sa.get("conflicts", []):
            key = (c.get("source"), c.get("target"))
            if key not in seen_conflicts:
                seen_conflicts.add(key)
                conflicts.append(c)
    results: dict = {}
    if graph_records:
        results["graph_records"] = graph_records
    if vector_passages:
        results["vector_passages"] = vector_passages
    if conflicts:
        results["conflicts"] = conflicts
    return results


def _dedupe_entities(subanswers: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set = set()
    for sa in subanswers:
        for e in sa.get("key_entities", []):
            name = (e.get("name") or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(e)
    return out


def _findings_block(subanswers: list[dict]) -> str:
    parts = []
    for i, sa in enumerate(subanswers, 1):
        parts.append(
            f"### Sub-question {i} ({sa['route']}): {sa['question']}\n"
            f"{sa['answer'] or '(no findings)'}"
        )
    return "\n\n".join(parts)


def _trust(claims: list[dict]) -> dict:
    """Turn the judge's per-claim verdicts into a surfaced trust score."""
    return trust_from_claims(claims)


async def deep_research(
    question: str,
    workspace_id: str,
    *,
    on_event=None,
) -> dict:
    """Run the full plan → research → synthesize → verify loop.

    `on_event(name, payload)` is an optional async callback used by the SSE route
    to stream progress; it is None for the plain request/response path. The return
    value is the same dict either way.
    """
    async def emit(name: str, payload: dict):
        if on_event is not None:
            await on_event(name, payload)

    # ── Plan ───────────────────────────────────────────────────────────────────
    await emit("status", {"phase": "planning", "message": "Decomposing the question…"})
    plan = await plan_research(question, workspace_id)
    await emit("plan", {"subquestions": plan})

    # ── Research (bounded parallel sub-agents) ─────────────────────────────────
    sem = asyncio.Semaphore(_CONCURRENCY)
    subanswers: list[dict | None] = [None] * len(plan)

    async def _run(idx: int, sub: dict):
        async with sem:
            await emit("subagent", {
                "index": idx, "status": "running",
                "question": sub["question"], "route": sub["route"],
            })
            try:
                result = await _research_one(sub, workspace_id)
            except Exception as exc:  # one sub-agent failing must not sink the run
                result = {
                    "question": sub["question"], "route": sub["route"],
                    "why": sub["why"], "answer": "", "graph_records": [],
                    "vector_chunks": [], "conflicts": [], "key_entities": [],
                    "error": str(exc),
                }
            subanswers[idx] = result
            await emit("subagent", {
                "index": idx, "status": "done",
                "question": sub["question"], "route": sub["route"],
                "answer": result["answer"],
                "evidence": {
                    "graph_records": len(result["graph_records"]),
                    "passages": len(result["vector_chunks"]),
                    "conflicts": len(result["conflicts"]),
                },
            })

    await asyncio.gather(*(_run(i, sub) for i, sub in enumerate(plan)))
    answers: list[dict] = [sa for sa in subanswers if sa is not None]

    # ── Synthesize (lead agent fuses the sub-answers) ──────────────────────────
    await emit("status", {"phase": "synthesizing", "message": "Fusing the findings…"})
    final_answer = await generate_text(
        SYNTHESIS_PROMPT.format(question=question, findings=_findings_block(answers))
    )

    # ── Verify (faithfulness judge → trust score) ──────────────────────────────
    await emit("status", {"phase": "verifying", "message": "Fact-checking the report…"})
    evidence = _aggregate_evidence(answers)
    claims = await judge_faithfulness(final_answer, evidence)
    trust = _trust(claims)
    await emit("trust", trust)

    conflicts = evidence.get("conflicts", [])
    return {
        "type": "deep_research",
        "question": question,
        "answer": final_answer,
        "subquestions": [
            {"question": a["question"], "route": a["route"], "why": a["why"],
             "answer": a["answer"], "error": a.get("error")}
            for a in answers
        ],
        "key_entities": _dedupe_entities(answers),
        "conflicts": conflicts,
        "trust": trust,
        "graph_records": evidence.get("graph_records", []),
        "vector_chunks": [p for a in answers for p in a.get("vector_chunks", [])],
    }
