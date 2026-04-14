import { useMemo, useState } from "react";

const COLS = [
  { key: "agent_name", label: "Agent", numeric: false },
  { key: "reply", label: "Replies", numeric: true },
  { key: "comment", label: "Comments", numeric: true },
  { key: "internal_note", label: "Notes", numeric: true },
  { key: "handover", label: "Handovers", numeric: true },
  { key: "status_change", label: "Status", numeric: true },
  { key: "total", label: "Total", numeric: true }
];

function cmp(a, b, key, dir) {
  const va = a[key];
  const vb = b[key];
  if (typeof va === "number" && typeof vb === "number") {
    return dir * (va - vb);
  }
  return dir * String(va).localeCompare(String(vb), undefined, { sensitivity: "base" });
}

export default function AgentPerformanceTable({ agents }) {
  const [sortKey, setSortKey] = useState("total");
  const [sortDir, setSortDir] = useState(-1);

  const sorted = useMemo(() => {
    const rows = [...(agents || [])];
    rows.sort((a, b) => cmp(a, b, sortKey, sortDir));
    return rows;
  }, [agents, sortKey, sortDir]);

  const onHeader = (key) => {
    if (key === sortKey) setSortDir((d) => -d);
    else {
      setSortKey(key);
      setSortDir(key === "agent_name" ? 1 : -1);
    }
  };

  return (
    <div className="rounded-xl bg-white p-4 shadow">
      <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
        <h2 className="text-lg font-semibold">Performance by agent</h2>
        <p className="text-xs text-slate-500">
          Click a column to sort. Counts are replies, comments, internal notes, handovers, and status
          changes in the selected range.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-600">
              {COLS.map((c) => (
                <th key={c.key} className="whitespace-nowrap px-2 py-2 font-medium">
                  <button
                    type="button"
                    onClick={() => onHeader(c.key)}
                    className="inline-flex items-center gap-1 rounded hover:bg-slate-100"
                  >
                    {c.label}
                    {sortKey === c.key ? (sortDir < 0 ? " ▼" : " ▲") : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.agent_name} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-2 py-2 font-medium text-slate-900">{row.agent_name}</td>
                <td className="px-2 py-2 tabular-nums">{row.reply}</td>
                <td className="px-2 py-2 tabular-nums">{row.comment}</td>
                <td className="px-2 py-2 tabular-nums">{row.internal_note}</td>
                <td className="px-2 py-2 tabular-nums">{row.handover}</td>
                <td className="px-2 py-2 tabular-nums">{row.status_change}</td>
                <td className="px-2 py-2 tabular-nums font-semibold">{row.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length === 0 && (
        <p className="mt-3 text-sm text-slate-500">No agent actions in this date range.</p>
      )}
    </div>
  );
}
