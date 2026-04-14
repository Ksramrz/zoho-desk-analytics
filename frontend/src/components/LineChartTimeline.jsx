import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend
} from "recharts";

const palette = ["#1d4ed8", "#9333ea", "#0f766e", "#dc2626", "#16a34a", "#f59e0b", "#334155"];

export default function LineChartTimeline({ data, granularity, onGranularityChange }) {
  const keys = Object.keys((data && data[0]) || {}).filter((k) => k !== "bucket");
  return (
    <div className="rounded-xl bg-white p-4 shadow">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Activity over time</h2>
        <select
          className="rounded border border-slate-300 px-2 py-1 text-sm"
          value={granularity}
          onChange={(e) => onGranularityChange(e.target.value)}
        >
          <option value="day">Daily</option>
          <option value="week">Weekly</option>
        </select>
      </div>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="bucket" />
            <YAxis />
            <Tooltip />
            <Legend />
            {keys.map((k, idx) => (
              <Line key={k} type="monotone" dataKey={k} stroke={palette[idx % palette.length]} strokeWidth={2} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
