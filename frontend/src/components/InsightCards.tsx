import {
  BarChart as ReBarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type {
  Insight,
  BarChartInsight,
  FlowPathInsight,
  StatGridInsight,
  ComparisonTableInsight,
  TimelineInsight,
} from "../types";

// ── Entity type colors shared with GraphViewer ────────────────────────────────
const NODE_COLOR: Record<string, string> = {
  Person:       "#5fb39a",
  Paper:        "#d6a44e",
  Concept:      "#b394e0",
  Organization: "#6f9fd6",
  Topic:        "#de7fa0",
  Event:        "#84c08f",
};

const EDGE_COLOR: Record<string, string> = {
  AUTHORED:          "#5fb39a",
  CITED:             "#d6a44e",
  FUNDED_BY:         "#6f9fd6",
  COLLABORATED_WITH: "#7ca8d0",
  PUBLISHED_IN:      "#de7fa0",
  SUPPORTS:          "#84c08f",
  CONTRADICTS:       "#e06a4f",
  CONFLICTS_WITH:    "#e06a4f",
};

const BRASS = "#d6a44e";

// ── Card wrapper ──────────────────────────────────────────────────────────────
function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-800/40 p-4">
      {title && <p className="eyebrow mb-3 text-faint">{title}</p>}
      {children}
    </div>
  );
}

// ── Stat grid ─────────────────────────────────────────────────────────────────
function StatGridCard({ insight }: { insight: StatGridInsight }) {
  const cols = insight.stats.length <= 2 ? insight.stats.length : Math.min(insight.stats.length, 4);
  return (
    <Card>
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {insight.stats.map((s, i) => (
          <div key={i} className="flex flex-col gap-1">
            <span className="eyebrow text-faint">{s.label}</span>
            <span className="font-display text-[26px] font-medium tabular-nums leading-none text-paper">
              {s.value}
            </span>
            {s.subtitle && (
              <span className="text-[10.5px] leading-snug text-faint">{s.subtitle}</span>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Bar chart ─────────────────────────────────────────────────────────────────
const CustomTooltip = ({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-[12px] shadow-xl shadow-black/40">
      <p className="font-medium text-paper">{label}</p>
      <p className="mt-0.5 font-mono text-brass">{payload[0].value}</p>
    </div>
  );
};

function BarChartCard({ insight }: { insight: BarChartInsight }) {
  const isHorizontal = insight.data.length > 6 || insight.data.some((d) => d.name.length > 12);
  const color = insight.color ?? BRASS;
  const barSize = isHorizontal ? Math.max(10, 240 / insight.data.length) : undefined;
  const chartHeight = isHorizontal ? Math.max(180, insight.data.length * 28) : 220;

  return (
    <Card title={insight.title}>
      <ResponsiveContainer width="100%" height={chartHeight}>
        {isHorizontal ? (
          <ReBarChart layout="vertical" data={insight.data} margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#221c16" horizontal={false} />
            <XAxis
              type="number"
              tick={{ fill: "#6d6557", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              label={insight.x_label ? { value: insight.x_label, fill: "#4a4438", fontSize: 10, position: "insideBottom", offset: -2 } : undefined}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={140}
              tick={{ fill: "#9b9082", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: "#ffffff08" }} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={barSize}>
              {insight.data.map((_, i) => (
                <Cell key={i} fill={color} fillOpacity={0.75 + (i === 0 ? 0.25 : 0)} />
              ))}
            </Bar>
          </ReBarChart>
        ) : (
          <ReBarChart data={insight.data} margin={{ left: 8, right: 8, top: 4, bottom: 24 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#221c16" vertical={false} />
            <XAxis
              dataKey="name"
              tick={{ fill: "#9b9082", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              interval={0}
              angle={insight.data.length > 5 ? -30 : 0}
              textAnchor={insight.data.length > 5 ? "end" : "middle"}
            />
            <YAxis
              tick={{ fill: "#6d6557", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              label={insight.y_label ? { value: insight.y_label, fill: "#4a4438", fontSize: 10, angle: -90, position: "insideLeft" } : undefined}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: "#ffffff08" }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {insight.data.map((_, i) => (
                <Cell key={i} fill={color} fillOpacity={0.75 + (i === 0 ? 0.25 : 0)} />
              ))}
            </Bar>
          </ReBarChart>
        )}
      </ResponsiveContainer>
    </Card>
  );
}

// ── Flow path ─────────────────────────────────────────────────────────────────
function FlowPathCard({ insight }: { insight: FlowPathInsight }) {
  return (
    <Card title={insight.title ?? "Connection path"}>
      <div className="flex flex-wrap items-center gap-1.5">
        {insight.steps.map((step, i) => {
          const nodeColor = NODE_COLOR[step.entity_type] ?? "#9b9082";
          const relColor  = step.relation ? (EDGE_COLOR[step.relation] ?? "#6d6557") : "#6d6557";
          return (
            <div key={i} className="flex items-center gap-1.5">
              {step.relation && (
                <div className="flex items-center gap-1">
                  <span className="text-faint">—</span>
                  <span
                    className="rounded px-1.5 py-0.5 font-mono text-[9.5px] font-medium"
                    style={{ backgroundColor: `${relColor}22`, color: relColor }}
                  >
                    {step.relation}
                  </span>
                  <span className="text-faint">→</span>
                </div>
              )}
              <span
                className="rounded-lg border px-2.5 py-1 text-[12px] font-medium"
                style={{
                  borderColor: `${nodeColor}40`,
                  backgroundColor: `${nodeColor}12`,
                  color: nodeColor,
                }}
              >
                {step.entity}
                <span
                  className="ml-1.5 text-[9.5px] opacity-60"
                >
                  {step.entity_type}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ── Comparison table ──────────────────────────────────────────────────────────
function ComparisonTableCard({ insight }: { insight: ComparisonTableInsight }) {
  return (
    <Card title={insight.title}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[12.5px]">
          <thead>
            <tr className="border-b border-ink-700">
              {insight.columns.map((col, i) => (
                <th key={i} className="pb-2 pr-4 font-mono text-[11px] font-medium uppercase tracking-wide text-faint">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {insight.rows.map((row, ri) => (
              <tr key={ri} className="border-b border-ink-800 last:border-0">
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className={`py-2 pr-4 ${ci === 0 ? "font-medium text-paper" : "text-muted"}`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Timeline ──────────────────────────────────────────────────────────────────
function TimelineCard({ insight }: { insight: TimelineInsight }) {
  return (
    <Card title={insight.title ?? "Timeline"}>
      <div className="relative flex flex-col gap-0">
        {/* Vertical line */}
        <div className="absolute left-[19px] top-2 bottom-2 w-px bg-ink-700" />
        {insight.events.map((ev, i) => (
          <div key={i} className="relative flex gap-3 pb-4 last:pb-0">
            {/* Dot */}
            <div className="relative z-10 mt-0.5 flex h-10 w-10 flex-shrink-0 flex-col items-center justify-center rounded-full border border-ink-600 bg-ink-800 text-center">
              <span className="font-mono text-[9.5px] font-semibold leading-none text-brass">
                {ev.year}
              </span>
            </div>
            {/* Content */}
            <div className="min-w-0 flex-1 pt-1">
              <p className="text-[13px] font-medium leading-snug text-paper">{ev.label}</p>
              {ev.detail && (
                <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{ev.detail}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────
export function InsightCards({ insights }: { insights: Insight[] }) {
  if (!insights.length) return null;
  return (
    <div className="flex flex-col gap-3">
      {insights.map((ins, i) => {
        switch (ins.type) {
          case "stat_grid":
            return <StatGridCard key={i} insight={ins} />;
          case "bar_chart":
            return <BarChartCard key={i} insight={ins} />;
          case "flow_path":
            return <FlowPathCard key={i} insight={ins} />;
          case "comparison_table":
            return <ComparisonTableCard key={i} insight={ins} />;
          case "timeline":
            return <TimelineCard key={i} insight={ins} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
