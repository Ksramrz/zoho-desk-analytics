export default function Header({
  dateFrom,
  dateTo,
  selectedPreset,
  onPresetChange,
  onDateFromChange,
  onDateToChange,
  onSyncNow,
  syncing
}) {
  return (
    <div className="rounded-xl bg-white p-4 shadow">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Desk Analytics</h1>
          <p className="mt-1 text-xs text-slate-500">
            Date presets and custom ranges use US Pacific calendar days (America/Los_Angeles).
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {[
            { key: "today", label: "Today" },
            { key: "yesterday", label: "Yesterday" },
            { key: "last_7_days", label: "Last 7 Days" },
            { key: "last_30_days", label: "Last 30 Days" },
            { key: "custom", label: "Custom" }
          ].map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => onPresetChange(item.key)}
              className={`rounded px-3 py-1.5 text-sm ${
                selectedPreset === item.key
                  ? "bg-slate-800 text-white"
                  : "bg-slate-200 text-slate-800 hover:bg-slate-300"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col text-sm">
            <span className="mb-1 text-slate-600">From</span>
            <input
              type="date"
              className="rounded border border-slate-300 px-3 py-2"
              value={dateFrom}
              onChange={(e) => onDateFromChange(e.target.value)}
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="mb-1 text-slate-600">To</span>
            <input
              type="date"
              className="rounded border border-slate-300 px-3 py-2"
              value={dateTo}
              onChange={(e) => onDateToChange(e.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={onSyncNow}
            disabled={syncing}
            className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {syncing ? "Syncing..." : "Sync now"}
          </button>
        </div>
      </div>
    </div>
  );
}
