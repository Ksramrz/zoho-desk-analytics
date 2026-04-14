export default function SummaryCards({ agents }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {agents.map((a) => (
        <div key={a.agent_name} className="rounded-xl bg-white p-4 shadow">
          <div className="text-sm text-slate-500">{a.agent_name}</div>
          <div className="mt-1 text-2xl font-bold">{a.total}</div>
          <div className="mt-2 text-xs text-slate-600">
            Replies: {a.reply} | Notes: {a.internal_note} | Handovers: {a.handover}
          </div>
        </div>
      ))}
      {agents.length === 0 && <div className="text-sm text-slate-500">No data for selected date range.</div>}
    </div>
  );
}
