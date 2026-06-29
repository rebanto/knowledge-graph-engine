# Project Overview — in plain language

*What this product is, the problem it solves, what makes it different from the
tools you've heard of, and where it's headed. Written to be readable without a
computer-science background.*

---

## 1. What it is, in one breath

It's a **research assistant that actually understands how things connect.**

You give it sources — research papers, news feeds, web pages, PDFs you upload —
and ask questions in plain English. Instead of skimming the text and guessing
like a normal chatbot, it first builds a **map of everything in your sources and
how they relate**: who wrote what, which ideas build on which, which findings
agree or disagree, who works with whom. Then it answers your questions by
*walking that map*, and shows you exactly where every fact came from.

Two simple ideas make it work:

- **A "connection map"** (a *knowledge graph*) — think of a giant corkboard with
  pins for every person, paper, organization, and idea, and labelled strings
  between them ("wrote", "cites", "disagrees with", "funded by").
- **A "meaning search"** (a *vector store*) — for when you want the *content* of
  the documents ("summarize what the research says about X") rather than the
  connections.

The system decides which one to use for each question — or both — and the AI's
only job is to translate your question into a search and turn the results into a
readable answer. **It never makes up facts.** Everything it says traces back to
something in your sources.

---

## 2. The problem it solves

Normal AI chatbots have three weaknesses when you use them for real research:

1. **They guess.** Ask a chatbot a factual question and it produces something
   that *sounds* right. Sometimes it's wrong, and you can't easily tell.
2. **They can't see connections.** "Which researchers share a collaborator but
   never published together?" is a *relationship* question. A chatbot reading
   text one passage at a time simply can't answer it reliably — there's no map.
3. **They hide disagreement.** If two of your sources contradict each other, a
   chatbot usually just picks one and sounds confident.

This product is built to fix exactly those three things: **don't guess, follow
real connections, and surface disagreements** — with a receipt for every claim.

---

## 3. How it works (the friendly version)

**When you add a source:** the system reads it, pulls out the important things
(people, organizations, papers, concepts) and the relationships between them, and
pins them onto the connection map. It also stores the raw text so it can be
searched by meaning later. If a new source contradicts an existing one, it marks
the disagreement automatically.

**When you ask a question:**

1. It works out whether your question is about **connections** (use the map),
   **content** (use the meaning search), or **both**.
2. It gathers the relevant evidence — a chain through the map, the most relevant
   passages, any conflicts, and which items are most central/influential.
3. The AI turns that evidence into a clear written answer **with citations**.
4. It saves the answer so you can revisit or re-run it.

You also get a **visual map** you can explore, and answers come with little
"insight cards" (mini charts, timelines, comparison tables) when they help.

---

## 4. What makes it different — the headline features

These are the things that, taken together, **no single competitor offers**:

### ⭐ It checks its own work and shows you a Trust Score
After writing an answer, an independent AI "fact-checker" goes through it
sentence by sentence and verifies each claim against your sources. You get a
score like **"100% grounded (16/16 claims)"** — and if any sentence *couldn't* be
backed up, it's listed openly. Most tools *say* "grounded in your sources." This
one **measures it and shows you the number.**

### ⭐ Deep Research mode — a team of research assistants
Flip a toggle and a hard question gets handled like a small research team:

- a **lead** breaks your question into focused sub-questions,
- several **assistants** research each part in parallel (some using the
  connection map, some the meaning search),
- the lead **combines** their findings into one answer,
- and the **fact-checker** verifies the result and attaches the trust score.

You watch it happen live — the plan, each assistant finishing, then the verified
answer. This is the "multiple research agents" idea made real.

### ⭐ It can be the "trusted memory" for other AI assistants
There's a growing problem in AI: assistants and "agents" have terrible memory —
they cram raw documents into a limited workspace and hope the right facts are in
there. This product can plug directly into other AI tools (Claude, Cursor, and
anything that speaks the open **MCP** standard) and act as their **grounded
memory**: the agent asks *it* for connected, fact-checked context instead of
guessing. **No competitor on this list does this.**

### ⭐ It answers "how are these connected?" questions
Because it has a real map, it can trace a path — "A worked with B, who cited C,
which contradicts D" — and return the actual chain. A normal search tool can only
find passages that mention the words; it can't follow the links.

### ⭐ It tells you when your sources disagree
If one source supports a claim and another contradicts it, the answer says so
instead of pretending the matter is settled.

### ⭐ Every fact has a receipt, and it works for any topic
Each fact links to the exact source that asserted it, and the same engine works
for AI research, law, climate policy, finance — whatever you point it at.

---

## 5. How it compares to the tools you know

Here's the honest landscape. Each competitor is excellent at something — but each
is missing the combination above.

| | **This product** | NotebookLM | Perplexity | Elicit | scite | Microsoft GraphRAG | Glean |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Answers from **your own** sources | ✅ | ✅ | partly | partly | ❌ | ✅ | ✅ |
| Builds a real **connection map** | ✅ | ❌ | ❌ | ❌ | partly | ✅ | ✅ |
| Follows **multi-step connections** (A→?→B) | ✅ | ❌ | ❌ | ❌ | ❌ | partly | partly |
| Flags when **sources disagree** | ✅ | ❌ | ❌ | ❌ | partly | ❌ | ❌ |
| **Shows a trust score** (self-fact-checks) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Multi-agent deep research** | ✅ | ❌ | partly | ❌ | ❌ | ❌ | partly |
| Works as **memory for other AI agents** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Searches the **whole public web** | ❌ | ❌ | ✅ | partly | ❌ | ❌ | ❌ |
| **Audio summaries** (podcast) | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

**In plain terms:**

- **NotebookLM (Google)** — upload documents, ask questions, get cited answers and
  a neat audio summary. Polished and easy. But it reads text passage-by-passage:
  no connection map, no multi-step reasoning, no disagreement flags, no self-check.
- **Perplexity** — a brilliant AI search engine for the *public web* with
  citations. Great for "what's out there right now," but it's not your private,
  connected library, and it keeps no lasting map of how things relate.
- **Elicit / Consensus** — research helpers that find and summarize academic
  papers. Strong for literature review; they don't trace relationships or flag
  contradictions across your own collection.
- **scite** — shows whether papers support or contradict each other *through
  citations*. The closest thing to our disagreement feature — but limited to
  citation links between papers, not arbitrary claims in your sources.
- **Microsoft GraphRAG** — the closest *technical* cousin: it also builds a graph
  from documents. But it's a developer recipe, not a finished product, and it has
  no deep-research agents, no trust score, and no agent-memory plug-in.
- **Glean** — enterprise search with a knowledge graph across a company's internal
  tools. Powerful, but it's a closed corporate product for company data — not a
  research tool you point at your own sources, and it has no self-check score or
  agent-memory feature.

**The one-sentence positioning:** *it's the only one that builds a real connection
map of your own sources, fact-checks its own answers with a visible trust score,
runs a team of research agents on hard questions, and can serve as grounded memory
for other AI assistants.*

---

## 6. Who it's for

Anyone whose work is **"how are these things connected, who said what, and can I
trust it?"** — R&D and science teams, competitive and market intelligence, legal
and patent research, policy analysis, investment due diligence. Exactly the
situations where a confident-but-unsourced chatbot answer isn't good enough.

---

## 7. Does it actually work? (measured, not claimed)

The project holds itself to evidence, including its own report card:

| What we measured | Result |
|---|---|
| Answers backed by the sources (faithfulness) | **~91%** of claims grounded |
| The leftover "unsupported" rate | **~9%** (and shown openly, not hidden) |
| Picking the right search method for a question | **75%** (with a safety net that catches misses) |
| Finding the relevant material when it exists | **100%** in the test set |
| Correctly merging duplicate names (e.g. "J. Smith" = "John Smith") | **F1 88%** — improved from 33% after a measure-fix-remeasure cycle |
| Connection questions answered with real linked results | **5 out of 5** (plain search openly failed on some) |

And in a **live end-to-end test**, a Deep Research run on a real question returned
a fused, multi-part answer with a **"100% grounded (16/16)" trust score** — while
*honestly noting* the one detail its sources didn't cover, instead of inventing it.

---

## 8. Honest limitations (we name these on purpose)

- **The self-check is itself an AI** — a strong second opinion, not absolute
  truth. But a visible, measured trust score still beats a confident shrug.
- **Choosing the search method is ~75% accurate** — a built-in fallback hides most
  misses from you, but there's real room to improve.
- **It doesn't search the open web** (by design — it answers from *your* sources)
  and **doesn't make audio summaries** (NotebookLM's nice extra).
- **Deep Research answers are saved and browsable, but aren't yet a back-and-forth
  chat** — each deep run is a standalone, document-style report.

Naming these is the point: the product earns trust the same way its answers do —
by showing its work.

---

## 9. The bottom line

Most "AI over your documents" tools are a chatbot with a search box bolted on.
This is different: it builds a **real map of your knowledge**, **reasons over the
connections**, **tells you when sources disagree**, **fact-checks itself and shows
the score**, can run a **team of research agents** on hard questions, and can even
serve as the **trusted memory other AI assistants are missing**.

> **The pitch in one line:** *A research engine that understands how your sources
> connect, proves every answer against them with a visible trust score, and can be
> the grounded memory for the next generation of AI agents.*

---

*For the technical deep-dive (architecture, distributed systems, evaluation
methodology), see [`CLAUDE.md`](CLAUDE.md), the [`docs/`](docs) folder, and
[`docs/19-deep-research-and-mcp.md`](docs/19-deep-research-and-mcp.md) for the
Deep Research and agent-memory features.*
