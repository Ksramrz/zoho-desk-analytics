import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend
} from "recharts";

const COLORS = {
  reply: "#2563eb",
  internal_note: "#7c3aed",
  comment: "#0891b2",
  handover: "#dc2626",
  status_change: "#16a34a"
};

export default function BarChartAgents({ data }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow">
      <h2 className="mb-4 text-lg font-semibold">Actions by agent</h2>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="agent_name" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Bar dataKey="reply" stackId="a" fill={COLORS.reply} />
            <Bar dataKey="internal_note" stackId="a" fill={COLORS.internal_note} />
            <Bar dataKey="comment" stackId="a" fill={COLORS.comment} />
            <Bar dataKey="handover" stackId="a" fill={COLORS.handover} />
            <Bar dataKey="status_change" stackId="a" fill={COLORS.status_change} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
