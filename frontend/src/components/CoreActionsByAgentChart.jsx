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
  comment: "#0891b2",
  handover: "#dc2626"
};

const NumberTip = ({ active, payload, label }) => {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload.reduce((acc, item) => {
    acc[item.dataKey] = item.value || 0;
    return acc;
  }, {});
  const total = (row.reply || 0) + (row.comment || 0) + (row.handover || 0);
  return (
    <div className="rounded border bg-white p-2 text-xs shadow">
      <div className="mb-1 font-semibold">{label}</div>
      <div>Replies: {row.reply || 0}</div>
      <div>Comments: {row.comment || 0}</div>
      <div>Handovers: {row.handover || 0}</div>
      <div className="mt-1 border-t pt-1 font-semibold">Total: {total}</div>
    </div>
  );
};

export default function CoreActionsByAgentChart({ data, dateFrom, dateTo }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow">
      <h2 className="text-lg font-semibold">Replies, Comments, Handovers by Agent</h2>
      <div className="mb-3 text-xs text-slate-500">
        Date range: {dateFrom} to {dateTo}
      </div>
      <div className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="agent_name" />
            <YAxis />
            <Tooltip content={<NumberTip />} />
            <Legend />
            <Bar dataKey="reply" stackId="core" fill={COLORS.reply} name="Replies" />
            <Bar dataKey="comment" stackId="core" fill={COLORS.comment} name="Comments" />
            <Bar dataKey="handover" stackId="core" fill={COLORS.handover} name="Handovers" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
