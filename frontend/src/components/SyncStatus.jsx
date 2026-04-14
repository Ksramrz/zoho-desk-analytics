export default function SyncStatus({ logs }) {
  const latest = logs?.[0];
  return (
    <div className="rounded-xl bg-white p-4 shadow">
      <h2 className="mb-2 text-lg font-semibold">Sync status</h2>
      {latest ? (
        <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <span className="text-slate-500">Last sync end: </span>
            {new Date(latest.sync_end).toLocaleString()}
          </div>
          <div>
            <span className="text-slate-500">Tickets processed: </span>
            {latest.tickets_processed}
          </div>
          <div>
            <span className="text-slate-500">Actions inserted: </span>
            {latest.actions_inserted}
          </div>
          <div>
            <span className="text-slate-500">Status: </span>
            <span className={latest.status === "success" ? "text-green-600" : "text-red-600"}>{latest.status}</span>
          </div>
        </div>
      ) : (
        <div className="text-sm text-slate-500">No sync history yet.</div>
      )}
    </div>
  );
}
