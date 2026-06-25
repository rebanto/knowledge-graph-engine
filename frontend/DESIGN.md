# Lattice — design language

A reference for the interface so it stays coherent as it grows. If you're
adding UI, reach for what's already here before inventing new colours,
type, or spacing.

## Voice

Lattice is a research instrument, not a chatbot. The tone is dry, exact,
and a little literary — the voice of a good archivist. We don't say
"AI-powered", "unlock insights", or "intelligent". We don't use emoji in
the product. When there's nothing to show, we say so plainly and with a
bit of character ("The graph is quiet for now.") rather than with a
cheerful marketing blank slate.

Every claim the system shows traces back to a source. The copy should
never imply the machine *knows* things — it *finds* them.

## Colour — "warm ink + brass"

All tokens live in `src/index.css` under `@theme`. Use the generated
utilities (`bg-ink-800`, `text-paper`, `text-brass`); don't hard-code hex
in components except inside the graph canvas / charts, where colours are
passed to D3 and Recharts as values.

- **Ink** (`ink-950`…`ink-500`) — warm, brown-shifted near-blacks for
  surfaces. Never cold grey.
- **Paper** (`paper`, `paper-dim`, `muted`, `faint`, `ghost`) — the text
  ramp, a warm off-white down to a whisper.
- **Brass** (`brass`, `brass-bright`, `brass-dim`) — the one accent. It is
  also the graph signal colour. Primary actions are brass with ink text —
  not white pills.
- **Retrieval signals** — `graph` (brass), `vector` (verdigris),
  `hybrid` (plum). Reused on routing badges and node types.
- **Flag** (`flag`, `flag-dim`) — a warm vermilion for conflicts and
  errors. Not a fire-engine red.

## Type

- **Fraunces** (`.font-display` / `font-serif`) — display only: the
  wordmark, page headlines, question titles, big numerals, empty-state
  lines. This is where the personality lives.
- **Inter** (`font-sans`, the default) — all UI text, labels, buttons.
- **JetBrains Mono** (`font-mono`) — data: IDs, Cypher, counts, edge
  types, the `.eyebrow` small-caps section labels.

## Motifs

- **Eyebrow** (`.eyebrow`) — tracked small-caps mono labels above
  sections. The connective tissue of the layout.
- **Drop cap** — the first answer paragraph opens with an illuminated
  brass serif capital (`.prose-answer`). The signature flourish.
- **Dot grid** (`.dot-grid`) — a faint graph-paper texture for large empty
  surfaces.
- **Hairlines** — borders are `ink-700`/`ink-650`; structure is implied,
  not boxed in.

## Components

Hand-built React + Tailwind v4 + `lucide-react`. No component library —
if it isn't here, build it in the same idiom rather than pulling one in.
