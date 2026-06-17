import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { Loader2, Search, X, ZoomIn } from "lucide-react";
import type { GraphData, GraphNode, NodeType } from "../types";
import { getGraph } from "../api";

const NODE_COLOR: Record<NodeType, string> = {
  Paper:        "#c9974a",
  Person:       "#4fb3a3",
  Concept:      "#9b8cf0",
  Organization: "#6b9bd1",
  Topic:        "#d97a9c",
  Event:        "#7cb88f",
};

const EDGE_TYPE_COLOR: Record<string, string> = {
  AUTHORED:          "#4fb3a3",
  CITED:             "#c9974a",
  FUNDED_BY:         "#6b9bd1",
  COLLABORATED_WITH: "#7ca8d0",
  PUBLISHED_IN:      "#d97a9c",
  SUPPORTS:          "#7cb88f",
  CONTRADICTS:       "#e2574c",
  CONFLICTS_WITH:    "#e2574c",
};
const EDGE_FALLBACK  = "#52525b";
const CONFLICT_COLOR = "#e2574c";

function edgeColor(type: string, conflict: boolean): string {
  if (conflict) return CONFLICT_COLOR;
  return EDGE_TYPE_COLOR[type] ?? EDGE_FALLBACK;
}

// Soft "home positions" that keep node types clustered without forcing them apart
const TYPE_ANCHOR: Partial<Record<NodeType, { ax: number; ay: number }>> = {
  Person:       { ax: 0.28, ay: 0.30 },
  Paper:        { ax: 0.65, ay: 0.28 },
  Concept:      { ax: 0.50, ay: 0.70 },
  Organization: { ax: 0.18, ay: 0.62 },
  Topic:        { ax: 0.80, ay: 0.62 },
  Event:        { ax: 0.50, ay: 0.18 },
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

  const [data, setData]         = useState<GraphData | null>(null);
  const [loading, setLoading]   = useState(true);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<NodeType>>(new Set());
  const [search, setSearch] = useState("");

  const nodeSelRef      = useRef<d3.Selection<SVGCircleElement, SimNode, SVGGElement, unknown> | null>(null);
  const linkSelRef      = useRef<d3.Selection<SVGLineElement, SimLink, SVGGElement, unknown> | null>(null);
  const labelSelRef     = useRef<d3.Selection<SVGTextElement, SimNode, SVGGElement, unknown> | null>(null);
  const edgeLabelSelRef = useRef<d3.Selection<SVGTextElement, SimLink, SVGGElement, unknown> | null>(null);
  const neighborsRef    = useRef<Map<string, Set<string>>>(new Map());

  useEffect(() => {
    setLoading(true);
    setSelected(null);
    getGraph(workspaceId, 150)
      .then(setData)
      .finally(() => setLoading(false));
  }, [workspaceId]);

  const zoomToFit = useCallback(() => {
    if (!svgRef.current || !containerRef.current || !zoomRef.current) return;
    const g = svgRef.current.querySelector<SVGGElement>("g.root");
    if (!g) return;
    const box = g.getBBox();
    if (!box.width || !box.height) return;
    const W = containerRef.current.clientWidth;
    const H = containerRef.current.clientHeight;
    const pad = 60;
    const scale = Math.min(
      (W - pad * 2) / box.width,
      (H - pad * 2) / box.height,
    ) * 0.92;
    const tx = (W - box.width * scale) / 2 - box.x * scale;
    const ty = (H - box.height * scale) / 2 - box.y * scale;
    d3.select(svgRef.current)
      .transition()
      .duration(700)
      .call(zoomRef.current.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }, []);

  useEffect(() => {
    if (!data || !svgRef.current || !containerRef.current) return;

    const W = containerRef.current.clientWidth;
    const H = containerRef.current.clientHeight;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    // ── Arrow marker defs (one per edge type) ───────────────────────────────
    const defs = svg.append("defs");
    const markerKeys = [...new Set(data.edges.map((e) => e.type)), "__conflict__"];
    markerKeys.forEach((t) => {
      const color = t === "__conflict__" ? CONFLICT_COLOR : (EDGE_TYPE_COLOR[t] ?? EDGE_FALLBACK);
      defs.append("marker")
        .attr("id", `arrow-${t}`)
        .attr("viewBox", "0 -4 8 8")
        .attr("refX", 9)
        .attr("refY", 0)
        .attr("markerWidth", 5)
        .attr("markerHeight", 5)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-4L8,0L0,4")
        .attr("fill", color);
    });

    // ── Data prep ────────────────────────────────────────────────────────────
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
    const rScale = d3.scaleSqrt().domain([degExtent[0] || 0, degExtent[1] || 1]).range([4, 17]);

    // ── Canvas groups ─────────────────────────────────────────────────────────
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 5])
      .on("zoom", (ev) => root.attr("transform", ev.transform));
    zoomRef.current = zoom;
    svg.call(zoom);

    const root = svg.append("g").attr("class", "root");

    // ── Force simulation — tighter with type clustering ───────────────────────
    const sim = d3.forceSimulation<SimNode, SimLink>(nodes)
      .force("link",
        d3.forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance((l) => {
            // Shorter distance between same-type nodes
            const s = l.source as SimNode, t = l.target as SimNode;
            return s.type === t.type ? 40 : 60;
          })
          .strength(0.65),
      )
      .force("charge",
        d3.forceManyBody<SimNode>()
          .strength((d) => -120 - d.degree * 4)   // hubs repel more
          .distanceMax(280),
      )
      .force("collide", d3.forceCollide<SimNode>((d) => rScale(d.degree) + 3))
      .force("x", d3.forceX<SimNode>((d) => {
        const anchor = TYPE_ANCHOR[d.type as NodeType];
        return anchor ? anchor.ax * W : W / 2;
      }).strength(0.06))
      .force("y", d3.forceY<SimNode>((d) => {
        const anchor = TYPE_ANCHOR[d.type as NodeType];
        return anchor ? anchor.ay * H : H / 2;
      }).strength(0.06))
      .alphaDecay(0.018)
      .velocityDecay(0.38);

    simRef.current = sim;

    // ── Render: edges ─────────────────────────────────────────────────────────
    const link = root.append("g")
      .selectAll<SVGLineElement, SimLink>("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => edgeColor(d.type, d.conflict))
      .attr("stroke-width", (d) => d.conflict ? 2 : 1.4)
      .attr("stroke-dasharray", (d) => d.conflict ? "4,3" : "none")
      .attr("opacity", 0.5)
      .attr("marker-end", (d) => `url(#arrow-${d.conflict ? "__conflict__" : d.type})`);

    // ── Render: edge labels (hidden by default, shown on focus) ─────────────
    const edgeLabel = root.append("g")
      .selectAll<SVGTextElement, SimLink>("text")
      .data(links)
      .join("text")
      .text((d) => d.type)
      .attr("font-size", 7)
      .attr("font-family", "ui-monospace, monospace")
      .attr("fill", (d) => edgeColor(d.type, d.conflict))
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("pointer-events", "none")
      .attr("opacity", 0);

    // ── Render: nodes ─────────────────────────────────────────────────────────
    const node = root.append("g")
      .selectAll<SVGCircleElement, SimNode>("circle")
      .data(nodes)
      .join("circle")
      .attr("r", (d) => rScale(d.degree))
      .attr("fill", (d) => NODE_COLOR[d.type] ?? "#888")
      .attr("stroke", "#0a0a0c")
      .attr("stroke-width", 1.5)
      .style("cursor", "pointer")
      .on("click", (_e, d) => setSelected((prev) => prev?.id === d.id ? null : d))
      .on("mouseenter", (_e, d) => setHoveredId(d.id))
      .on("mouseleave", () => setHoveredId(null))
      .call(
        d3.drag<SVGCircleElement, SimNode>()
          .on("start", (e) => { if (!e.active) sim.alphaTarget(0.25).restart(); })
          .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }),
      );

    // ── Render: labels ────────────────────────────────────────────────────────
    const label = root.append("g")
      .selectAll<SVGTextElement, SimNode>("text")
      .data(nodes)
      .join("text")
      .text((d) => d.name.length > 26 ? d.name.slice(0, 26) + "…" : d.name)
      .attr("font-size", 9.5)
      .attr("font-family", "Inter, sans-serif")
      .attr("fill", "#a1a1aa")
      .attr("pointer-events", "none")
      .attr("dx", (d) => rScale(d.degree) + 4)
      .attr("dy", 3.5)
      .attr("opacity", 0);

    nodeSelRef.current      = node;
    linkSelRef.current      = link;
    labelSelRef.current     = label;
    edgeLabelSelRef.current = edgeLabel;

    const degMax = degExtent[1] || 1;

    sim.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x!)
        .attr("y1", (d) => (d.source as SimNode).y!)
        .attr("x2", (d) => (d.target as SimNode).x!)
        .attr("y2", (d) => (d.target as SimNode).y!);

      node.attr("cx", (d) => d.x!).attr("cy", (d) => d.y!);

      label
        .attr("x", (d) => d.x!)
        .attr("y", (d) => d.y!)
        // Show labels for high-degree nodes always (hot during tick)
        .attr("opacity", (d) => d.degree >= degMax * 0.35 ? 1 : 0);

      edgeLabel
        .attr("x", (d) => ((d.source as SimNode).x! + (d.target as SimNode).x!) / 2)
        .attr("y", (d) => ((d.source as SimNode).y! + (d.target as SimNode).y!) / 2 - 5);
    });

    sim.on("end", () => {
      // After layout stabilises, zoom to fit the graph
      setTimeout(zoomToFit, 80);
    });

    return () => { sim.stop(); };
  }, [data, zoomToFit]);

  // ── Highlight effect (reactive, no sim rebuild) ───────────────────────────
  useEffect(() => {
    if (!nodeSelRef.current || !linkSelRef.current || !labelSelRef.current
        || !edgeLabelSelRef.current || !data) return;

    const focusId   = hoveredId ?? selected?.id ?? null;
    const focusSet  = focusId
      ? new Set([focusId, ...(neighborsRef.current.get(focusId) ?? [])])
      : null;
    const searchLo  = search.trim().toLowerCase();
    const typeByName = new Map(data.nodes.map((n) => [n.name, n.type]));
    const degMax     = Math.max(...data.nodes.map((n) => n.degree), 1);

    nodeSelRef.current
      .attr("opacity", (d) => {
        if (hiddenTypes.has(d.type)) return 0;
        if (searchLo && !d.name.toLowerCase().includes(searchLo)) return 0.1;
        if (focusSet && !focusSet.has(d.id)) return 0.15;
        return 1;
      })
      .attr("stroke", (d) => selected?.id === d.id ? "#fff" : "#0a0a0c")
      .attr("stroke-width", (d) => selected?.id === d.id ? 2.5 : 1.5);

    linkSelRef.current.attr("opacity", (d) => {
      const s = (d.source as SimNode).id ?? (d.source as unknown as string);
      const t = (d.target as SimNode).id ?? (d.target as unknown as string);
      if ((hiddenTypes.has(typeByName.get(s) as NodeType)) || (hiddenTypes.has(typeByName.get(t) as NodeType))) return 0;
      if (focusSet) return focusSet.has(s) && focusSet.has(t) ? 0.9 : 0.05;
      return d.conflict ? 0.75 : 0.5;
    });

    edgeLabelSelRef.current.attr("opacity", (d) => {
      if (!focusSet) return 0;
      const s = (d.source as SimNode).id ?? (d.source as unknown as string);
      const t = (d.target as SimNode).id ?? (d.target as unknown as string);
      return focusSet.has(s) && focusSet.has(t) ? 1 : 0;
    });

    labelSelRef.current.attr("opacity", (d) => {
      if (hiddenTypes.has(d.type)) return 0;
      if (searchLo) return d.name.toLowerCase().includes(searchLo) ? 1 : 0.06;
      if (focusSet) return focusSet.has(d.id) ? 1 : 0.06;
      return d.degree >= degMax * 0.35 ? 1 : 0;
    });
  }, [hoveredId, selected, hiddenTypes, search, data]);

  function toggleType(t: NodeType) {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
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
        direction:  e.source === selected.name ? ("out" as const) : ("in" as const),
      }));
  }, [selected, data]);

  function jumpTo(name: string) {
    const t = data?.nodes.find((n) => n.name === name);
    if (t) setSelected({ ...t, id: t.name });
  }

  const presentEdgeTypes = useMemo(
    () => Array.from(new Set((data?.edges ?? []).map((e) => e.type))).sort(),
    [data],
  );

  return (
    <div className="relative flex h-full w-full">
      <div ref={containerRef} className="relative flex-1">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 size={18} className="animate-spin text-zinc-500" />
          </div>
        )}
        <svg ref={svgRef} className="h-full w-full" />

        {/* Search */}
        <div className="absolute left-4 top-4 flex items-center gap-2 rounded-lg border border-zinc-800/60 bg-zinc-950/85 px-2.5 py-1.5 backdrop-blur-sm">
          <Search size={13} className="text-zinc-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Find node…"
            className="w-36 bg-transparent text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600"
          />
          {search && (
            <button onClick={() => setSearch("")} className="text-zinc-500 hover:text-zinc-300">
              <X size={12} />
            </button>
          )}
        </div>

        {/* Zoom-to-fit */}
        <button
          onClick={zoomToFit}
          title="Zoom to fit"
          className="absolute right-4 top-4 rounded-lg border border-zinc-800/60 bg-zinc-950/85 p-1.5 text-zinc-500 backdrop-blur-sm hover:text-zinc-300 transition-colors"
        >
          <ZoomIn size={14} />
        </button>

        {/* Legend */}
        <div className="absolute bottom-4 left-4 flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto rounded-lg border border-zinc-800/60 bg-zinc-950/85 px-3 py-2.5 backdrop-blur-sm scrollbar-thin">
          <p className="mb-0.5 text-[10px] uppercase tracking-wider text-zinc-600">Nodes</p>
          {(Object.keys(NODE_COLOR) as NodeType[]).map((t) => (
            <button
              key={t}
              onClick={() => toggleType(t)}
              className={`flex items-center gap-2 text-[11px] transition-opacity ${hiddenTypes.has(t) ? "opacity-35" : ""} text-zinc-400`}
            >
              <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ backgroundColor: NODE_COLOR[t] }} />
              {t}
            </button>
          ))}

          {presentEdgeTypes.length > 0 && (
            <>
              <p className="mb-0.5 mt-2 text-[10px] uppercase tracking-wider text-zinc-600">Edges</p>
              {presentEdgeTypes.map((t) => (
                <div key={t} className="flex items-center gap-2 text-[11px] text-zinc-500">
                  <span className="h-[2px] w-4 flex-shrink-0 rounded" style={{ backgroundColor: EDGE_TYPE_COLOR[t] ?? EDGE_FALLBACK }} />
                  {t}
                </div>
              ))}
              <div className="mt-1 flex items-center gap-2 border-t border-zinc-800/60 pt-1.5 text-[11px] text-zinc-400">
                <span className="h-0.5 w-3 flex-shrink-0 rounded bg-[#e2574c]" />
                Conflict
              </div>
            </>
          )}
        </div>
      </div>

      {/* Selected node detail panel */}
      {selected && (
        <div className="flex w-72 flex-shrink-0 flex-col border-l border-zinc-800/60 bg-zinc-950/60 p-4">
          <button
            onClick={() => setSelected(null)}
            className="mb-3 self-start text-[11px] text-zinc-500 hover:text-zinc-300"
          >
            ✕ close
          </button>

          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
              style={{ backgroundColor: NODE_COLOR[selected.type] }} />
            <p className="text-[13px] font-semibold leading-snug text-zinc-100">{selected.name}</p>
          </div>
          <p className="mt-0.5 pl-[18px] text-[11px] text-zinc-500">{selected.type}</p>
          <p className="mt-0.5 pl-[18px] text-[11px] text-zinc-600">
            {connections.length} connection{connections.length !== 1 ? "s" : ""}
          </p>

          <p className="mt-4 text-[11px] font-medium uppercase tracking-wider text-zinc-600">
            Connections
          </p>
          <div className="mt-2 flex flex-col gap-1 overflow-y-auto scrollbar-thin">
            {connections.map((c, i) => {
              const rc = EDGE_TYPE_COLOR[c.type] ?? EDGE_FALLBACK;
              return (
                <button
                  key={i}
                  onClick={() => jumpTo(c.otherName)}
                  className="flex flex-col gap-0.5 rounded-md px-2 py-1.5 text-left hover:bg-zinc-800/50"
                >
                  <span className="truncate text-[11.5px] text-zinc-300">{c.otherName}</span>
                  <span className="flex items-center gap-1 font-mono text-[10px] text-zinc-600">
                    {c.direction === "out" ? "→" : "←"}
                    <span className="rounded px-1 py-0.5 text-[9.5px]"
                      style={{ backgroundColor: `${rc}20`, color: rc }}>
                      {c.type}
                    </span>
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
