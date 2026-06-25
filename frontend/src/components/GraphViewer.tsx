import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import {
  Loader2, Search, X, Maximize2, Plus, Minus, Eye, EyeOff, Crosshair,
} from "lucide-react";
import type { GraphData, GraphNode, NodeType } from "../types";
import { getGraph } from "../api";

// ── Visual vocabulary ────────────────────────────────────────────────────────

const NODE_COLOR: Record<NodeType, string> = {
  Paper:        "#d6a44e",
  Person:       "#5fb39a",
  Concept:      "#b394e0",
  Organization: "#6f9fd6",
  Topic:        "#de7fa0",
  Event:        "#84c08f",
};

// Edges are colored by semantic GROUP rather than by exact type — a dozen
// distinct edge colors reads as rainbow noise. The exact type still shows on the
// edge label when a node is focused, and in the detail panel.
type EdgeGroup = "authorship" | "content" | "concept" | "citation" | "funding" | "support" | "conflict";

const EDGE_GROUP_OF: Record<string, EdgeGroup> = {
  AUTHORED: "authorship", COLLABORATED_WITH: "authorship", AFFILIATED_WITH: "authorship",
  MENTIONS: "content", ABOUT: "content", PUBLISHED_IN: "content", PRESENTED_AT: "content",
  USES: "concept", PROPOSES: "concept", EXTENDS: "concept", IMPROVES: "concept",
  COMPARED_TO: "concept", EVALUATED_ON: "concept", APPLIED_TO: "concept",
  PART_OF: "concept", RELATED_TO: "concept",
  CITED: "citation",
  FUNDED_BY: "funding",
  SUPPORTS: "support",
  CONTRADICTS: "conflict", CONFLICTS_WITH: "conflict",
};

const GROUP_COLOR: Record<EdgeGroup, string> = {
  authorship: "#5fb39a",
  content:    "#b394e0",
  concept:    "#6f9fd6",
  citation:   "#d6a44e",
  funding:    "#c2873a",
  support:    "#84c08f",
  conflict:   "#e06a4f",
};

const GROUP_LABEL: Record<EdgeGroup, string> = {
  authorship: "Authorship",
  content:    "Paper → content",
  concept:    "Concept links",
  citation:   "Citations",
  funding:    "Funding",
  support:    "Supports",
  conflict:   "Conflict",
};

const EDGE_FALLBACK = "#6d6557";

function edgeGroup(type: string): EdgeGroup | null {
  return EDGE_GROUP_OF[type] ?? null;
}
function edgeColor(type: string, conflict: boolean): string {
  if (conflict) return GROUP_COLOR.conflict;
  const g = edgeGroup(type);
  return g ? GROUP_COLOR[g] : EDGE_FALLBACK;
}

// Soft "home positions" that keep node types loosely clustered.
const TYPE_ANCHOR: Partial<Record<NodeType, { ax: number; ay: number }>> = {
  Person:       { ax: 0.24, ay: 0.30 },
  Paper:        { ax: 0.62, ay: 0.26 },
  Concept:      { ax: 0.52, ay: 0.72 },
  Organization: { ax: 0.16, ay: 0.66 },
  Topic:        { ax: 0.82, ay: 0.60 },
  Event:        { ax: 0.50, ay: 0.14 },
};

interface SimNode extends GraphNode, d3.SimulationNodeDatum { id: string }
interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
  confidence: number | null;
  conflict: boolean;
}

export function GraphViewer({ workspaceId }: { workspaceId: string }) {
  const svgRef       = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const zoomRef      = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const simRef       = useRef<d3.Simulation<SimNode, SimLink> | null>(null);

  const [data, setData]           = useState<GraphData | null>(null);
  const [loading, setLoading]     = useState(true);
  const [selected, setSelected]   = useState<SimNode | null>(null);
  const [hovered, setHovered]     = useState<{ node: SimNode; x: number; y: number } | null>(null);
  const [hiddenTypes, setHiddenTypes]   = useState<Set<NodeType>>(new Set());
  const [hiddenGroups, setHiddenGroups] = useState<Set<EdgeGroup>>(new Set());
  const [search, setSearch]       = useState("");
  const [zoomLevel, setZoomLevel] = useState(1);

  // Live mirrors of reactive state so D3 callbacks read current values without
  // rebuilding the simulation.
  const hoveredIdRef    = useRef<string | null>(null);
  const selectedIdRef   = useRef<string | null>(null);
  const hiddenTypesRef  = useRef(hiddenTypes);
  const hiddenGroupsRef = useRef(hiddenGroups);
  const searchRef       = useRef(search);

  const nodeSelRef      = useRef<d3.Selection<SVGCircleElement, SimNode, SVGGElement, unknown> | null>(null);
  const linkSelRef      = useRef<d3.Selection<SVGLineElement, SimLink, SVGGElement, unknown> | null>(null);
  const labelGRef       = useRef<d3.Selection<SVGGElement, SimNode, SVGGElement, unknown> | null>(null);
  const edgeLabelSelRef = useRef<d3.Selection<SVGTextElement, SimLink, SVGGElement, unknown> | null>(null);
  const neighborsRef    = useRef<Map<string, Set<string>>>(new Map());
  const rScaleRef       = useRef<(d: number) => number>(() => 6);

  // Stable handles to the scene's internal callbacks so reactive effects can
  // trigger a re-highlight / label relayout without rebuilding the simulation.
  const relayoutRef       = useRef<() => void>(() => {});
  const applyHighlightRef = useRef<() => void>(() => {});

  useEffect(() => {
    setLoading(true);
    setSelected(null);
    setHovered(null);
    getGraph(workspaceId, 250)
      .then(setData)
      .finally(() => setLoading(false));
  }, [workspaceId]);

  useEffect(() => { hiddenTypesRef.current = hiddenTypes; }, [hiddenTypes]);
  useEffect(() => { hiddenGroupsRef.current = hiddenGroups; }, [hiddenGroups]);
  useEffect(() => { searchRef.current = search; }, [search]);
  useEffect(() => { selectedIdRef.current = selected?.id ?? null; }, [selected]);

  // ── Counts for the legend ──────────────────────────────────────────────────
  const typeCounts = useMemo(() => {
    const c = new Map<NodeType, number>();
    for (const n of data?.nodes ?? []) c.set(n.type, (c.get(n.type) ?? 0) + 1);
    return c;
  }, [data]);

  const presentGroups = useMemo(() => {
    const c = new Map<EdgeGroup, number>();
    for (const e of data?.edges ?? []) {
      const g = e.conflict ? "conflict" : edgeGroup(e.type);
      if (g) c.set(g, (c.get(g) ?? 0) + 1);
    }
    return c;
  }, [data]);

  // ── Camera helpers ─────────────────────────────────────────────────────────
  const zoomToFit = useCallback((duration = 700) => {
    if (!svgRef.current || !containerRef.current || !zoomRef.current) return;
    const g = svgRef.current.querySelector<SVGGElement>("g.root");
    if (!g) return;
    const box = g.getBBox();
    if (!box.width || !box.height) return;
    const W = containerRef.current.clientWidth;
    const H = containerRef.current.clientHeight;
    const pad = 80;
    const scale = Math.min((W - pad * 2) / box.width, (H - pad * 2) / box.height) * 0.95;
    const tx = (W - box.width * scale) / 2 - box.x * scale;
    const ty = (H - box.height * scale) / 2 - box.y * scale;
    const t = d3.zoomIdentity.translate(tx, ty).scale(scale);
    const sel = d3.select(svgRef.current);
    // duration 0 applies instantly (transitions rely on rAF, which embedded /
    // backgrounded contexts can throttle — the initial fit must not depend on it).
    if (duration > 0) sel.transition().duration(duration).call(zoomRef.current.transform, t);
    else sel.call(zoomRef.current.transform, t);
  }, []);

  const nudgeZoom = useCallback((factor: number) => {
    if (!svgRef.current || !zoomRef.current) return;
    d3.select(svgRef.current).transition().duration(200)
      .call(zoomRef.current.scaleBy, factor);
  }, []);

  const centerOn = useCallback((node: SimNode, k = 1.6) => {
    if (!svgRef.current || !containerRef.current || !zoomRef.current) return;
    if (node.x == null || node.y == null) return;
    const W = containerRef.current.clientWidth;
    const H = containerRef.current.clientHeight;
    const t = d3.zoomIdentity.translate(W / 2 - node.x * k, H / 2 - node.y * k).scale(k);
    d3.select(svgRef.current).transition().duration(550)
      .call(zoomRef.current.transform, t);
  }, []);

  // ── Build / rebuild the scene when data changes ────────────────────────────
  useEffect(() => {
    if (!data || !svgRef.current || !containerRef.current) return;

    const W = containerRef.current.clientWidth || 800;
    const H = containerRef.current.clientHeight || 600;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const defs = svg.append("defs");
    // One arrow marker per group (+ conflict) tinted to match the edge color.
    ([...Object.keys(GROUP_COLOR)] as EdgeGroup[]).forEach((g) => {
      defs.append("marker")
        .attr("id", `arw-${g}`)
        .attr("viewBox", "0 -4 8 8").attr("refX", 7).attr("refY", 0)
        .attr("markerWidth", 5).attr("markerHeight", 5).attr("orient", "auto")
        .append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", GROUP_COLOR[g]);
    });

    // ── Data prep ──────────────────────────────────────────────────────────
    const nodes: SimNode[] = data.nodes.map((n) => ({ ...n, id: n.name }));
    const links: SimLink[] = data.edges.map((e) => ({
      source: e.source, target: e.target,
      type: e.type, confidence: e.confidence, conflict: e.conflict,
    }));

    const neighbors = new Map<string, Set<string>>();
    for (const e of data.edges) {
      if (!neighbors.has(e.source)) neighbors.set(e.source, new Set());
      if (!neighbors.has(e.target)) neighbors.set(e.target, new Set());
      neighbors.get(e.source)!.add(e.target);
      neighbors.get(e.target)!.add(e.source);
    }
    neighborsRef.current = neighbors;

    const degExtent = d3.extent(nodes, (n) => n.degree) as [number, number];
    const rScale = d3.scaleSqrt()
      .domain([degExtent[0] || 0, degExtent[1] || 1]).range([5, 22]);
    rScaleRef.current = (d) => rScale(d);
    const degMax = degExtent[1] || 1;

    // ── Zoom ────────────────────────────────────────────────────────────────
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.05, 6])
      .on("zoom", (ev) => {
        root.attr("transform", ev.transform);
        setZoomLevel(ev.transform.k);
        scheduleLabelRelayout();
      });
    zoomRef.current = zoom;
    svg.call(zoom).on("dblclick.zoom", null);
    // Click on empty canvas clears selection.
    svg.on("click", () => setSelected(null));

    const root = svg.append("g").attr("class", "root");

    // ── Forces ────────────────────────────────────────────────────────────
    const sim = d3.forceSimulation<SimNode, SimLink>(nodes)
      .force("link",
        d3.forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance((l) => {
            const s = l.source as SimNode, t = l.target as SimNode;
            return s.type === t.type ? 46 : 72;
          })
          .strength(0.55))
      .force("charge",
        d3.forceManyBody<SimNode>()
          .strength((d) => -160 - d.degree * 6)
          .distanceMax(360))
      .force("collide", d3.forceCollide<SimNode>((d) => rScale(d.degree) + 6).iterations(2))
      .force("x", d3.forceX<SimNode>((d) => (TYPE_ANCHOR[d.type as NodeType]?.ax ?? 0.5) * W).strength(0.05))
      .force("y", d3.forceY<SimNode>((d) => (TYPE_ANCHOR[d.type as NodeType]?.ay ?? 0.5) * H).strength(0.05))
      .alphaDecay(0.02)
      .velocityDecay(0.4);
    simRef.current = sim;

    // ── Edges ─────────────────────────────────────────────────────────────
    const link = root.append("g").attr("class", "links")
      .selectAll<SVGLineElement, SimLink>("line")
      .data(links).join("line")
      .attr("stroke", (d) => edgeColor(d.type, d.conflict))
      .attr("stroke-width", (d) => (d.conflict ? 2.2 : 1.3))
      .attr("stroke-dasharray", (d) => (d.conflict ? "5,4" : "none"))
      .attr("opacity", 0.42)
      .attr("marker-end", (d) => `url(#arw-${d.conflict ? "conflict" : edgeGroup(d.type) ?? "concept"})`);

    // ── Edge labels (revealed on focus) ──────────────────────────────────────
    const edgeLabel = root.append("g").attr("class", "edge-labels")
      .selectAll<SVGTextElement, SimLink>("text")
      .data(links).join("text")
      .text((d) => d.type)
      .attr("font-size", 8).attr("font-family", "ui-monospace, monospace")
      .attr("fill", (d) => edgeColor(d.type, d.conflict))
      .attr("text-anchor", "middle").attr("dominant-baseline", "middle")
      .attr("paint-order", "stroke").attr("stroke", "#0c0b09").attr("stroke-width", 3)
      .attr("pointer-events", "none").attr("opacity", 0);

    // ── Nodes ─────────────────────────────────────────────────────────────
    const node = root.append("g").attr("class", "nodes")
      .selectAll<SVGCircleElement, SimNode>("circle")
      .data(nodes).join("circle")
      .attr("r", (d) => rScale(d.degree))
      .attr("fill", (d) => NODE_COLOR[d.type] ?? "#888")
      .attr("stroke", "#0c0b09").attr("stroke-width", 1.5)
      .style("cursor", "pointer")
      .on("click", (e, d) => {
        e.stopPropagation();
        setSelected((prev) => (prev?.id === d.id ? null : d));
      })
      .on("dblclick", (e, d) => { e.stopPropagation(); setSelected(d); centerOn(d); })
      .on("mouseenter", (e, d) => {
        hoveredIdRef.current = d.id;
        const rect = containerRef.current!.getBoundingClientRect();
        setHovered({ node: d, x: e.clientX - rect.left, y: e.clientY - rect.top });
        applyHighlight();
      })
      .on("mousemove", (e, d) => {
        const rect = containerRef.current!.getBoundingClientRect();
        setHovered({ node: d, x: e.clientX - rect.left, y: e.clientY - rect.top });
      })
      .on("mouseleave", () => { hoveredIdRef.current = null; setHovered(null); applyHighlight(); })
      .call(
        d3.drag<SVGCircleElement, SimNode>()
          .on("start", (e) => { if (!e.active) sim.alphaTarget(0.2).restart(); })
          .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

    // ── Labels: a <g> per node holding a halo'd <text> ───────────────────────
    const labelG = root.append("g").attr("class", "labels")
      .selectAll<SVGGElement, SimNode>("g")
      .data(nodes).join("g")
      .attr("pointer-events", "none").attr("opacity", 0);
    labelG.append("text")
      .text((d) => (d.name.length > 30 ? d.name.slice(0, 30) + "…" : d.name))
      .attr("font-size", 11).attr("font-family", "Inter, system-ui, sans-serif")
      .attr("font-weight", 500).attr("fill", "#ece4d6")
      .attr("paint-order", "stroke").attr("stroke", "#0c0b09").attr("stroke-width", 3.5)
      .attr("stroke-linejoin", "round")
      .attr("dy", "0.34em");

    nodeSelRef.current      = node;
    linkSelRef.current      = link;
    labelGRef.current       = labelG;
    edgeLabelSelRef.current = edgeLabel;

    // ── Label visibility: zoom-adaptive, collision-avoiding ──────────────────
    // Runs on a rAF so zoom/tick storms coalesce into one relayout per frame.
    let relayoutQueued = false;
    function scheduleLabelRelayout() {
      if (relayoutQueued) return;
      relayoutQueued = true;
      requestAnimationFrame(() => { relayoutQueued = false; relayoutLabels(); });
    }
    function relayoutLabels() {
      const t = d3.zoomTransform(svg.node()!);
      const focusId = hoveredIdRef.current ?? selectedIdRef.current;
      const focusSet = focusId
        ? new Set([focusId, ...(neighbors.get(focusId) ?? [])])
        : null;
      const searchLo = searchRef.current.trim().toLowerCase();
      const hiddenT = hiddenTypesRef.current;

      // Priority order: focus → search hits → high degree.
      const ordered = [...nodes].sort((a, b) => {
        const af = focusSet?.has(a.id) ? 1 : 0, bf = focusSet?.has(b.id) ? 1 : 0;
        if (af !== bf) return bf - af;
        return b.degree - a.degree;
      });

      const placed: { x1: number; y1: number; x2: number; y2: number }[] = [];
      const visible = new Set<string>();
      const FONT = 11;
      for (const n of ordered) {
        if (hiddenT.has(n.type)) continue;
        if (n.x == null || n.y == null) continue;
        const isFocus = focusSet?.has(n.id) ?? false;
        const isSearch = !!searchLo && n.name.toLowerCase().includes(searchLo);
        // When something is focused, only its neighborhood gets labels.
        if (focusSet && !isFocus) continue;
        // Otherwise gate the long tail by zoom so we never clutter when zoomed out.
        if (!focusSet && !isSearch) {
          const screenR = rScaleRef.current(n.degree) * t.k;
          if (screenR < 6 && t.k < 1.4 && n.degree < degMax * 0.5) continue;
        }
        const [sx, sy] = t.apply([n.x, n.y]);
        const w = Math.min(n.name.length, 30) * FONT * 0.56 + 10;
        const r = rScaleRef.current(n.degree) * t.k + 5;
        const box = { x1: sx + r, y1: sy - FONT * 0.7, x2: sx + r + w, y2: sy + FONT * 0.7 };
        const hit = placed.some((p) => box.x1 < p.x2 && box.x2 > p.x1 && box.y1 < p.y2 && box.y2 > p.y1);
        if (hit && !isFocus && !isSearch) continue;
        placed.push(box);
        visible.add(n.id);
      }

      labelG
        .attr("opacity", (d) => (visible.has(d.id) ? 1 : 0))
        .attr("transform", (d) => `translate(${(d.x ?? 0) + rScaleRef.current(d.degree) + 5},${d.y ?? 0})`);
    }
    // Expose for the highlight effect.
    relayoutRef.current = relayoutLabels;

    // ── Reactive highlight (dim non-focused) ─────────────────────────────────
    function applyHighlight() {
      const focusId = hoveredIdRef.current ?? selectedIdRef.current;
      const focusSet = focusId ? new Set([focusId, ...(neighbors.get(focusId) ?? [])]) : null;
      const searchLo = searchRef.current.trim().toLowerCase();
      const hiddenT = hiddenTypesRef.current;
      const hiddenG = hiddenGroupsRef.current;
      const selId = selectedIdRef.current;

      node
        .attr("opacity", (d) => {
          if (hiddenT.has(d.type)) return 0.04;
          if (searchLo && !d.name.toLowerCase().includes(searchLo)) return 0.12;
          if (focusSet && !focusSet.has(d.id)) return 0.14;
          return 1;
        })
        .attr("stroke", (d) => (selId === d.id ? "#fff" : "#0c0b09"))
        .attr("stroke-width", (d) => (selId === d.id ? 3 : 1.5));

      link.attr("opacity", (d) => {
        const s = (d.source as SimNode), tt = (d.target as SimNode);
        const g = d.conflict ? "conflict" : edgeGroup(d.type);
        if (g && hiddenG.has(g)) return 0;
        if (hiddenT.has(s.type) || hiddenT.has(tt.type)) return 0;
        if (focusSet) return focusSet.has(s.id) && focusSet.has(tt.id) ? 0.9 : 0.04;
        return d.conflict ? 0.7 : 0.4;
      });

      edgeLabel.attr("opacity", (d) => {
        if (!focusSet) return 0;
        const s = (d.source as SimNode), tt = (d.target as SimNode);
        const g = d.conflict ? "conflict" : edgeGroup(d.type);
        if (g && hiddenG.has(g)) return 0;
        return focusSet.has(s.id) && focusSet.has(tt.id) ? 1 : 0;
      });

      relayoutLabels();
    }
    applyHighlightRef.current = applyHighlight;

    // ── Position everything from current node coordinates ────────────────────
    function ticked() {
      link
        .attr("x1", (d) => {
          const s = d.source as SimNode, t2 = d.target as SimNode;
          const dx = (t2.x! - s.x!), dy = (t2.y! - s.y!), len = Math.hypot(dx, dy) || 1;
          return s.x! + (dx / len) * (rScale(s.degree) + 1);
        })
        .attr("y1", (d) => {
          const s = d.source as SimNode, t2 = d.target as SimNode;
          const dx = (t2.x! - s.x!), dy = (t2.y! - s.y!), len = Math.hypot(dx, dy) || 1;
          return s.y! + (dy / len) * (rScale(s.degree) + 1);
        })
        .attr("x2", (d) => {
          const s = d.source as SimNode, t2 = d.target as SimNode;
          const dx = (t2.x! - s.x!), dy = (t2.y! - s.y!), len = Math.hypot(dx, dy) || 1;
          return t2.x! - (dx / len) * (rScale(t2.degree) + 4);
        })
        .attr("y2", (d) => {
          const s = d.source as SimNode, t2 = d.target as SimNode;
          const dx = (t2.x! - s.x!), dy = (t2.y! - s.y!), len = Math.hypot(dx, dy) || 1;
          return t2.y! - (dy / len) * (rScale(t2.degree) + 4);
        });

      node.attr("cx", (d) => d.x!).attr("cy", (d) => d.y!);

      labelG.attr("transform", (d) =>
        `translate(${(d.x ?? 0) + rScale(d.degree) + 5},${d.y ?? 0})`);

      edgeLabel
        .attr("x", (d) => ((d.source as SimNode).x! + (d.target as SimNode).x!) / 2)
        .attr("y", (d) => ((d.source as SimNode).y! + (d.target as SimNode).y!) / 2 - 4);
    }
    sim.on("tick", ticked);

    // Pre-warm the layout synchronously so the graph is correctly positioned on
    // the FIRST paint — no "explode from the center" animation, and it works
    // even where rAF (and therefore d3's force timer) is throttled. After this
    // we stop the timer; dragging a node restarts it on demand.
    sim.alpha(1);
    for (let i = 0; i < 280 && sim.alpha() > sim.alphaMin(); i++) sim.tick();
    sim.stop();
    ticked();
    zoomToFit(0);
    relayoutLabels();

    return () => { sim.stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // Re-run highlight when reactive filter/selection state changes. Hover is
  // handled imperatively in the mouse handlers, so it isn't a dependency here.
  useEffect(() => {
    applyHighlightRef.current();
  }, [selected, hiddenTypes, hiddenGroups, search, data]);

  // ── Filter toggles ──────────────────────────────────────────────────────
  function toggleType(t: NodeType) {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });
  }
  function toggleGroup(g: EdgeGroup) {
    setHiddenGroups((prev) => {
      const next = new Set(prev);
      next.has(g) ? next.delete(g) : next.add(g);
      return next;
    });
  }

  const connections = useMemo(() => {
    if (!selected || !data) return [];
    return data.edges
      .filter((e) => e.source === selected.name || e.target === selected.name)
      .map((e) => ({
        ...e,
        otherName: e.source === selected.name ? e.target : e.source,
        direction: e.source === selected.name ? ("out" as const) : ("in" as const),
      }))
      .sort((a, b) => a.type.localeCompare(b.type));
  }, [selected, data]);

  const selectedType = useMemo(() => {
    if (!selected || !data) return null;
    return data.nodes.find((n) => n.name === selected.name)?.type ?? selected.type;
  }, [selected, data]);

  function jumpTo(name: string) {
    const t = data?.nodes.find((n) => n.name === name);
    if (t) {
      const sn = { ...t, id: t.name } as SimNode;
      // carry over live x/y from the simulation if present
      const live = simRef.current?.nodes().find((n) => n.id === name);
      if (live) { sn.x = live.x; sn.y = live.y; }
      setSelected(sn);
      if (live) centerOn(live);
    }
  }

  // Zoom to the first search hit.
  useEffect(() => {
    const q = search.trim().toLowerCase();
    if (!q || !simRef.current) return;
    const hit = simRef.current.nodes().find((n) => n.name.toLowerCase().includes(q));
    if (hit) centerOn(hit, 1.3);
  }, [search, centerOn]);

  const isEmpty = !loading && data && data.nodes.length === 0;

  return (
    <div className="relative flex h-full w-full">
      <div ref={containerRef} className="relative flex-1 overflow-hidden">
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center">
            <div className="flex items-center gap-2 text-muted">
              <Loader2 size={16} className="animate-spin text-brass" />
              <span className="text-[12px]">Laying out the graph…</span>
            </div>
          </div>
        )}

        {isEmpty && (
          <div className="dot-grid absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 text-center">
            <Crosshair size={22} className="text-ghost" />
            <p className="font-display text-[16px] font-medium text-paper-dim">Nothing connected yet</p>
            <p className="max-w-xs text-[12px] text-muted">
              Add sources and let them finish reading — the entities they mention,
              and the lines between them, show up here.
            </p>
          </div>
        )}

        <svg ref={svgRef} className="h-full w-full" style={{ display: "block" }} />

        {/* Hover tooltip */}
        {hovered && (
          <div
            className="pointer-events-none absolute z-30 max-w-[240px] rounded-lg border border-ink-600 bg-ink-850/95 px-3 py-2 shadow-xl shadow-black/40 backdrop-blur-sm"
            style={{
              left: Math.min(hovered.x + 14, (containerRef.current?.clientWidth ?? 9999) - 250),
              top: hovered.y + 14,
            }}
          >
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
                style={{ backgroundColor: NODE_COLOR[hovered.node.type] }} />
              <span className="text-[12.5px] font-semibold leading-tight text-paper">
                {hovered.node.name}
              </span>
            </div>
            <p className="mt-1 pl-[18px] text-[11px] text-muted">
              {hovered.node.type} · {hovered.node.degree} connection
              {hovered.node.degree !== 1 ? "s" : ""}
            </p>
            <p className="mt-0.5 pl-[18px] text-[10.5px] text-faint">click to inspect · double-click to focus</p>
          </div>
        )}

        {/* Top-left: search */}
        <div className="absolute left-4 top-4 z-10 flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-900/85 px-2.5 py-1.5 backdrop-blur-sm">
          <Search size={13} className="text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Find a node…"
            className="w-40 bg-transparent text-[12px] text-paper outline-none placeholder:text-faint"
          />
          {search && (
            <button onClick={() => setSearch("")} className="text-muted hover:text-paper-dim">
              <X size={12} />
            </button>
          )}
        </div>

        {/* Top-right: camera controls */}
        <div className="absolute right-4 top-4 z-10 flex flex-col gap-1.5">
          <div className="flex flex-col overflow-hidden rounded-lg border border-ink-700 bg-ink-900/85 backdrop-blur-sm">
            <button onClick={() => nudgeZoom(1.4)} title="Zoom in"
              className="p-1.5 text-muted hover:bg-ink-750 hover:text-brass"><Plus size={14} /></button>
            <button onClick={() => nudgeZoom(0.7)} title="Zoom out"
              className="border-t border-ink-700 p-1.5 text-muted hover:bg-ink-750 hover:text-brass"><Minus size={14} /></button>
            <button onClick={() => zoomToFit()} title="Fit to view"
              className="border-t border-ink-700 p-1.5 text-muted hover:bg-ink-750 hover:text-brass"><Maximize2 size={13} /></button>
          </div>
          <div className="rounded-md border border-ink-700 bg-ink-900/85 px-1.5 py-0.5 text-center font-mono text-[10px] tabular-nums text-faint backdrop-blur-sm">
            {Math.round(zoomLevel * 100)}%
          </div>
        </div>

        {/* Bottom-left: stats + legend */}
        <div className="absolute bottom-4 left-4 z-10 flex max-h-[68vh] w-[188px] flex-col gap-1 overflow-y-auto rounded-lg border border-zinc-800/60 bg-zinc-950/85 px-3 py-2.5 backdrop-blur-sm scrollbar-thin">
          {data && (
            <p className="mb-1 text-[10.5px] text-zinc-500">
              <span className="font-medium text-zinc-300">{data.nodes.length}</span> nodes ·{" "}
              <span className="font-medium text-zinc-300">{data.edges.length}</span> edges
            </p>
          )}

          <p className="mb-0.5 mt-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-zinc-600">
            Node types
          </p>
          {(Object.keys(NODE_COLOR) as NodeType[])
            .filter((t) => (typeCounts.get(t) ?? 0) > 0)
            .map((t) => {
              const off = hiddenTypes.has(t);
              return (
                <button key={t} onClick={() => toggleType(t)}
                  className={`group flex items-center gap-2 rounded px-1 py-0.5 text-[11px] hover:bg-zinc-800/40 ${off ? "opacity-35" : ""}`}>
                  <span className="h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: NODE_COLOR[t] }} />
                  <span className="flex-1 text-left text-zinc-300">{t}</span>
                  <span className="tabular-nums text-[10px] text-zinc-600">{typeCounts.get(t)}</span>
                  {off
                    ? <EyeOff size={11} className="text-zinc-600" />
                    : <Eye size={11} className="text-zinc-700 opacity-0 group-hover:opacity-100" />}
                </button>
              );
            })}

          {presentGroups.size > 0 && (
            <>
              <p className="mb-0.5 mt-2 text-[10px] uppercase tracking-wider text-zinc-600">Edge types</p>
              {(Object.keys(GROUP_COLOR) as EdgeGroup[])
                .filter((g) => (presentGroups.get(g) ?? 0) > 0)
                .map((g) => {
                  const off = hiddenGroups.has(g);
                  return (
                    <button key={g} onClick={() => toggleGroup(g)}
                      className={`group flex items-center gap-2 rounded px-1 py-0.5 text-[11px] hover:bg-zinc-800/40 ${off ? "opacity-35" : ""}`}>
                      <span className="h-[2px] w-4 flex-shrink-0 rounded"
                        style={{ backgroundColor: GROUP_COLOR[g] }} />
                      <span className="flex-1 text-left text-zinc-400">{GROUP_LABEL[g]}</span>
                      <span className="tabular-nums text-[10px] text-zinc-600">{presentGroups.get(g)}</span>
                    </button>
                  );
                })}
            </>
          )}
        </div>
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="flex w-72 flex-shrink-0 flex-col border-l border-zinc-800/60 bg-zinc-950/60 p-4">
          <button onClick={() => setSelected(null)}
            className="mb-3 self-start text-[11px] text-zinc-500 hover:text-zinc-300">✕ close</button>

          <div className="flex items-start gap-2">
            <span className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full"
              style={{ backgroundColor: NODE_COLOR[(selectedType as NodeType) ?? "Concept"] }} />
            <p className="text-[13px] font-semibold leading-snug text-zinc-100">{selected.name}</p>
          </div>
          <div className="mt-1 flex items-center gap-2 pl-[18px]">
            <span className="rounded px-1.5 py-0.5 text-[10px] font-medium"
              style={{
                backgroundColor: `${NODE_COLOR[(selectedType as NodeType) ?? "Concept"]}22`,
                color: NODE_COLOR[(selectedType as NodeType) ?? "Concept"],
              }}>{selectedType}</span>
            <span className="text-[11px] text-zinc-600">
              {connections.length} connection{connections.length !== 1 ? "s" : ""}
            </span>
          </div>

          <button onClick={() => { const live = simRef.current?.nodes().find((n) => n.id === selected.id); if (live) centerOn(live); }}
            className="mt-3 flex items-center justify-center gap-1.5 rounded-md border border-zinc-800/70 py-1.5 text-[11px] text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200">
            <Crosshair size={12} /> Focus on graph
          </button>

          <p className="mt-4 text-[11px] font-medium uppercase tracking-wider text-zinc-600">Connections</p>
          <div className="mt-2 flex flex-col gap-1 overflow-y-auto scrollbar-thin">
            {connections.map((c, i) => {
              const col = edgeColor(c.type, c.conflict);
              return (
                <button key={i} onClick={() => jumpTo(c.otherName)}
                  className="flex flex-col gap-0.5 rounded-md px-2 py-1.5 text-left hover:bg-zinc-800/50">
                  <span className="truncate text-[11.5px] text-zinc-300">{c.otherName}</span>
                  <span className="flex items-center gap-1 font-mono text-[10px] text-zinc-600">
                    {c.direction === "out" ? "→" : "←"}
                    <span className="rounded px-1 py-0.5 text-[9.5px]"
                      style={{ backgroundColor: `${col}20`, color: col }}>{c.type}</span>
                    {c.conflict && <span className="text-rose-400">conflict</span>}
                  </span>
                </button>
              );
            })}
            {connections.length === 0 && (
              <p className="px-2 text-[11px] text-zinc-600">No connections in view.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
