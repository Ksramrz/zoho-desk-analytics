export default function ActionsTable({
  rows,
  page,
  total,
  pageSize,
  onPrev,
  onNext,
  agents,
  selectedAgent,
  selectedActionType,
  onAgentChange,
  onActionTypeChange
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="rounded-xl bg-white p-4 shadow">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <h2 className="mr-auto text-lg font-semibold">Actions</h2>
        <select
          className="rounded border border-slate-300 px-2 py-1 text-sm"
          value={selectedAgent}
          onChange={(e) => onAgentChange(e.target.value)}
        >
          <option value="">All agents</option>
          {agents.map((a) => (
            <option key={a.agent_id || a.agent_name} value={a.agent_id || ""}>
              {a.agent_name}
            </option>
          ))}
        </select>
        <select
          className="rounded border border-slate-300 px-2 py-1 text-sm"
          value={selectedActionType}
          onChange={(e) => onActionTypeChange(e.target.value)}
        >
          <option value="">All action types</option>
          <option value="reply">reply</option>
          <option value="internal_note">internal_note</option>
          <option value="comment">comment</option>
          <option value="handover">handover</option>
          <option value="status_change">status_change</option>
        </select>
      </div>
      <div className="overflow-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-slate-100 text-left">
              <th className="p-2">Date/time</th>
              <th className="p-2">Agent</th>
              <th className="p-2">Action type</th>
              <th className="p-2">Ticket number</th>
              <th className="p-2">Ticket subject</th>
              <th className="p-2">Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b">
                <td className="p-2">{new Date(r.action_timestamp).toLocaleString()}</td>
                <td className="p-2">{r.agent_name || "Unknown"}</td>
                <td className="p-2">{r.action_type}</td>
                <td className="p-2">{r.ticket_number}</td>
                <td className="p-2">{r.ticket_subject}</td>
                <td className="p-2">
                  {r.from_value && r.to_value ? `${r.from_value} -> ${r.to_value}` : r.to_value || "-"}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td className="p-3 text-slate-500" colSpan={6}>
                  No actions found for selected filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          type="button"
          className="rounded border px-3 py-1 disabled:opacity-50"
          disabled={page <= 1}
          onClick={onPrev}
        >
          Prev
        </button>
        <span className="text-sm">
          Page {page} / {totalPages}
        </span>
        <button
          type="button"
          className="rounded border px-3 py-1 disabled:opacity-50"
          disabled={page >= totalPages}
          onClick={onNext}
        >
          Next
        </button>
      </div>
    </div>
  );
}
