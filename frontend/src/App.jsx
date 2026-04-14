import { useEffect, useMemo, useState } from "react";
import {
  fetchActions,
  fetchAgents,
  fetchKpis,
  fetchSummary,
  fetchSyncStatus,
  fetchTimeline,
  triggerSync
} from "./api";
import { PRESET_KEYS, presetToRange } from "./dates";
import Header from "./components/Header";
import AgentPerformanceTable from "./components/AgentPerformanceTable";
import CoreActionsByAgentChart from "./components/CoreActionsByAgentChart";
import BarChartAgents from "./components/BarChartAgents";
import LineChartTimeline from "./components/LineChartTimeline";
import ActionsTable from "./components/ActionsTable";
import SyncStatus from "./components/SyncStatus";

export default function App() {
  const initial = presetToRange(PRESET_KEYS.LAST_30_DAYS);

  const [dateFrom, setDateFrom] = useState(initial.from);
  const [dateTo, setDateTo] = useState(initial.to);
  const [selectedPreset, setSelectedPreset] = useState(PRESET_KEYS.LAST_30_DAYS);
  const [granularity, setGranularity] = useState("day");
  const [summary, setSummary] = useState([]);
  const [kpis, setKpis] = useState({
    incoming_tickets: 0,
    modified_tickets: 0,
    touched_tickets: 0,
    total_actions: 0
  });
  const [timelineRows, setTimelineRows] = useState([]);
  const [actions, setActions] = useState({ total: 0, page: 1, page_size: 50, items: [] });
  const [agents, setAgents] = useState([]);
  const [syncLogs, setSyncLogs] = useState([]);
  const [page, setPage] = useState(1);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [selectedActionType, setSelectedActionType] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [toast, setToast] = useState("");
  const pageSize = 50;
  const applyPreset = (preset) => {
    if (preset === PRESET_KEYS.CUSTOM) {
      setSelectedPreset(PRESET_KEYS.CUSTOM);
      return;
    }
    const window = presetToRange(preset);
    if (!window) return;
    setSelectedPreset(preset);
    setDateFrom(window.from);
    setDateTo(window.to);
    setPage(1);
  };

  useEffect(() => {
    fetchAgents().then((r) => setAgents(r.agents || [])).catch(console.error);
  }, []);

  useEffect(() => {
    fetchKpis(dateFrom, dateTo).then(setKpis).catch(console.error);
    fetchSummary(dateFrom, dateTo).then((r) => setSummary(r.agents || [])).catch(console.error);
    fetchTimeline(dateFrom, dateTo, granularity).then((r) => setTimelineRows(r.rows || [])).catch(console.error);
  }, [dateFrom, dateTo, granularity]);

  useEffect(() => {
    fetchActions({
      dateFrom,
      dateTo,
      agentId: selectedAgent || undefined,
      actionType: selectedActionType || undefined,
      page,
      pageSize
    })
      .then(setActions)
      .catch(console.error);
  }, [dateFrom, dateTo, selectedAgent, selectedActionType, page]);

  useEffect(() => {
    const load = () => fetchSyncStatus().then((r) => setSyncLogs(r.logs || [])).catch(console.error);
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  const timelineData = useMemo(() => {
    const map = new Map();
    for (const row of timelineRows) {
      const bucket = row.bucket_start.slice(0, 10);
      const key = bucket;
      if (!map.has(key)) map.set(key, { bucket: bucket });
      map.get(key)[row.agent_name] = row.total_actions;
    }
    return Array.from(map.values());
  }, [timelineRows]);

  const onSyncNow = async () => {
    try {
      setSyncing(true);
      await triggerSync();
      setToast("Sync triggered");
      setTimeout(() => setToast(""), 2500);
    } catch (e) {
      setToast(`Sync failed: ${e.message}`);
      setTimeout(() => setToast(""), 3500);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 p-4 md:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <Header
          dateFrom={dateFrom}
          dateTo={dateTo}
          selectedPreset={selectedPreset}
          onPresetChange={applyPreset}
          onDateFromChange={(v) => {
            setSelectedPreset(PRESET_KEYS.CUSTOM);
            setDateFrom(v);
            setPage(1);
          }}
          onDateToChange={(v) => {
            setSelectedPreset(PRESET_KEYS.CUSTOM);
            setDateTo(v);
            setPage(1);
          }}
          onSyncNow={onSyncNow}
          syncing={syncing}
        />
        {toast && <div className="rounded bg-slate-800 px-3 py-2 text-sm text-white">{toast}</div>}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl bg-white p-4 shadow">
            <div className="text-xs text-slate-500">Incoming Tickets</div>
            <div className="mt-1 text-2xl font-bold">{kpis.incoming_tickets}</div>
          </div>
          <div className="rounded-xl bg-white p-4 shadow">
            <div className="text-xs text-slate-500">Modified Tickets</div>
            <div className="mt-1 text-2xl font-bold">{kpis.modified_tickets}</div>
          </div>
          <div className="rounded-xl bg-white p-4 shadow">
            <div className="text-xs text-slate-500">Tickets Touched (Agent Actions)</div>
            <div className="mt-1 text-2xl font-bold">{kpis.touched_tickets}</div>
          </div>
          <div className="rounded-xl bg-white p-4 shadow">
            <div className="text-xs text-slate-500">Total Agent Actions</div>
            <div className="mt-1 text-2xl font-bold">{kpis.total_actions}</div>
          </div>
        </div>
        <AgentPerformanceTable agents={summary} />
        <CoreActionsByAgentChart data={summary} dateFrom={dateFrom} dateTo={dateTo} />
        <BarChartAgents data={summary} />
        <LineChartTimeline
          data={timelineData}
          granularity={granularity}
          onGranularityChange={setGranularity}
        />
        <ActionsTable
          rows={actions.items || []}
          page={actions.page || 1}
          total={actions.total || 0}
          pageSize={actions.page_size || pageSize}
          agents={agents}
          selectedAgent={selectedAgent}
          selectedActionType={selectedActionType}
          onAgentChange={(v) => {
            setSelectedAgent(v);
            setPage(1);
          }}
          onActionTypeChange={(v) => {
            setSelectedActionType(v);
            setPage(1);
          }}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => p + 1)}
        />
        <SyncStatus logs={syncLogs} />
      </div>
    </div>
  );
}
