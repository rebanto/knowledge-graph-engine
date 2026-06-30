/**
 * Single source of truth for the graph palette as raw hex values.
 *
 * CSS components should use the Tailwind tokens in index.css (text-node-person,
 * etc.). But d3 (GraphViewer), recharts (InsightCards) and inline `style`
 * colours (EntitySummary) need literal hex strings — those all import from here
 * instead of re-declaring their own copies, so the colours stay in lockstep with
 * the `--color-node-*` / `--color-*` tokens in index.css.
 */

// Warm ink + paper — surfaces and text (mirror of the index.css tokens).
export const INK = {
  950: "#090807",
  900: "#0c0b09",
  850: "#100e0b",
  800: "#14110d",
  750: "#1a1611",
  700: "#221c16",
  600: "#392f25",
} as const;

export const PAPER = {
  DEFAULT: "#ece4d6",
  dim: "#cdc3b2",
  muted: "#9b9082",
  faint: "#6d6557",
  ghost: "#4a4438",
} as const;

export const BRASS = "#d6a44e";

// Entity node colours, keyed by Neo4j label.
export const NODE_COLOR: Record<string, string> = {
  Paper: "#d6a44e",
  Person: "#5fb39a",
  Concept: "#b394e0",
  Organization: "#6f9fd6",
  Topic: "#de7fa0",
  Event: "#84c08f",
};
export const NODE_FALLBACK = PAPER.muted;

// Relationship edge colours, keyed by edge type.
export const EDGE_COLOR: Record<string, string> = {
  AUTHORED: "#5fb39a",
  CITED: "#d6a44e",
  FUNDED_BY: "#6f9fd6",
  COLLABORATED_WITH: "#7ca8d0",
  PUBLISHED_IN: "#de7fa0",
  SUPPORTS: "#84c08f",
  CONTRADICTS: "#e06a4f",
  CONFLICTS_WITH: "#e06a4f",
};
export const EDGE_FALLBACK = PAPER.faint;

// Semantic edge groupings used by the GraphViewer legend/links.
export const EDGE_GROUP_COLOR: Record<string, string> = {
  authorship: "#5fb39a",
  content: "#b394e0",
  concept: "#6f9fd6",
  citation: "#d6a44e",
  funding: "#c2873a",
  support: "#84c08f",
  conflict: "#e06a4f",
};

export const nodeColor = (type: string) => NODE_COLOR[type] ?? NODE_FALLBACK;
export const edgeColor = (type: string) => EDGE_COLOR[type] ?? EDGE_FALLBACK;
