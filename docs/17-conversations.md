# Conversations (Multi-Turn Follow-Ups)

Until now every question was answered in isolation: `answer_question(question,
workspace_id)` routed and retrieved on the literal text of the question. A
follow-up like *"what about his later work?"* searched the graph and the vector
store for those literal words — "his" resolves to nothing, so the answer
collapsed to "no information" even when the previous turn was all about a
specific researcher.

This document describes how the engine threads a conversation across turns so
follow-ups inherit the context of everything asked and answered before them.

---

## The core technique: query rewriting (question condensation)

The single most important idea — and the one every production conversational
RAG system uses (LangChain's *history-aware retriever*, the *condense question*
chain, the coreference handling inside ChatGPT/Claude) — is **query
rewriting**:

> Before routing or retrieving anything, an LLM rewrites the user's possibly
> context-dependent follow-up into a **standalone question** that can be
> understood on its own, using the conversation history. *Then* the existing
> router, graph retriever, and vector retriever run unchanged on that standalone
> question.

So *"what about his later work?"* after a turn about **Geoffrey Hinton** becomes
*"What is Geoffrey Hinton's later research work?"* — which the router classifies,
the Cypher translator grounds, and the embedder embeds, exactly as if the user
had typed the full question. The rest of the pipeline never has to know it was a
follow-up.

Why rewrite at the front instead of stuffing history into every retriever:

- **Retrieval quality.** Graph Cypher generation and vector embedding both work
  far better on a self-contained question. Embedding "what about his later
  work?" lands nowhere useful; embedding the resolved question lands on the
  right chunks.
- **The caches keep working.** Route, Cypher, and embedding caches all key on
  the (standalone) question. Two differently-phrased follow-ups that mean the
  same thing converge on the same cache entry.
- **One narrow LLM job.** Consistent with the project's principle that the LLM
  only translates — it turns a follow-up into a standalone question; it does not
  invent facts.

### First turn pays nothing

The contextualizer is **skipped entirely when there is no prior history**. A
brand-new conversation's first question is already standalone, so we route it
directly with zero added latency or token cost. The rewrite LLM call only fires
from the second turn onward.

---

## Memory management: hybrid window + rolling summary

A conversation can grow without bound, but the context we feed the
contextualizer (and the synthesizer) must stay bounded in tokens. We use the
hybrid strategy that production chatbots converge on:

- **Sliding window** — the last `CONV_WINDOW_TURNS` turns (default 6) are kept
  **verbatim** (question + a trimmed answer). Recent turns carry the most
  coreference weight, so they stay in full.
- **Rolling summary** — everything older than the window is compressed into a
  single running `summary` string stored on the conversation row. When the
  window overflows, the turn that falls out is folded into the summary by a
  cheap LLM call. This is `ConversationSummaryBufferMemory` in LangChain terms.
- **Character budget** — the assembled history is hard-capped at
  `CONV_CONTEXT_CHARS` (default 6000) as a final backstop, trimming oldest-first.

The history block handed to the LLM therefore looks like:

```
[Earlier context summary]
<rolling summary of turns 1..N-6>

[Recent turns]
Q: ...
A: ...
Q: ...
A: ...
```

---

## Data model

Conversations reuse the existing `reports` table for their turns — a report is
already a `(question, answer, sources_used, version)` record, which is exactly a
turn. We add a lightweight parent table and three columns:

```sql
conversations (id, workspace_id, title, summary, created_at, updated_at)

-- new columns on reports:
reports.conversation_id     -- groups turns; NULL for legacy single-shot reports
reports.turn_index          -- 0-based order within the conversation
reports.standalone_question -- the rewritten question actually retrieved on
```

`title` is derived from the first question. `summary` holds the rolling summary.
Legacy reports with a NULL `conversation_id` still render fine as one-turn
conversations.

All migrations are additive `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT
EXISTS` run in the startup lifespan — consistent with how every other column in
this project was added.

---

## Request flow

```
POST /api/question { question, workspace_id, conversation_id? }
        |
   conversation_id given? ──no──► create a new conversation (title = question)
        | yes
   load prior turns (reports) + rolling summary
        |
   build bounded history  (window + summary, char-capped)
        |
   contextualize: history + follow-up ──LLM──► standalone question
        |                                       (skipped if no history)
   ┌────┴─────────────────────────────────────┐
   |  existing pipeline, unchanged:            |
   |  router → graph / vector → synthesizer    |
   |  (synthesizer also gets the history so    |
   |   prose can say "as noted earlier", but   |
   |   grounding rules are unchanged)          |
   └────┬─────────────────────────────────────┘
        |
   save report (conversation_id, turn_index, standalone_question)
   bump conversation.updated_at; fold overflow turn into summary
        |
   return QuestionResponse + conversation_id + standalone_question
```

The streaming (`/api/question/stream`) path mirrors this and emits an extra
`rewrite` progress event when a follow-up is condensed, so the UI can show
*"Resolving follow-up…"*.

---

## API

```
GET    /api/conversations?workspace_id=   → list (id, title, turn_count, updated_at)
GET    /api/conversations/{id}            → conversation + ordered turns
DELETE /api/conversations/{id}            → delete conversation and its turns
```

`POST /api/question` and `GET /api/question/stream` gain an optional
`conversation_id`. The response gains `conversation_id` and
`standalone_question` (null on first turns / when no rewrite happened).

---

## Configuration

| Env var               | Default | Meaning                                            |
|-----------------------|---------|----------------------------------------------------|
| `CONV_WINDOW_TURNS`   | 6       | Recent turns kept verbatim in the window           |
| `CONV_CONTEXT_CHARS`  | 6000    | Hard cap on assembled history characters           |
| `CONV_ANSWER_CHARS`   | 600     | Per-turn answer trim length inside the history     |

---

## Why not just send the whole transcript to one big LLM call?

That is the naive approach and it breaks at this project's scale for three
reasons: (1) the graph and vector retrievers still need a standalone question to
retrieve well — a transcript doesn't help Cypher generation; (2) token cost and
latency grow unbounded with conversation length; (3) the route/Cypher/embedding
caches would never hit, since every prompt is unique. Query rewriting + bounded
memory keeps retrieval sharp, cost flat, and the cache layer effective.
