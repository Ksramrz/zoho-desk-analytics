import { REPORT_TIMEZONE } from "./dates";

const json = async (res) => {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
};

const tzParams = () => ({ report_timezone: REPORT_TIMEZONE });

export const fetchSummary = (dateFrom, dateTo) => {
  const q = new URLSearchParams({
    date_from: dateFrom,
    date_to: dateTo,
    ...tzParams()
  });
  return fetch(`/api/summary?${q}`).then(json);
};

export const fetchKpis = (dateFrom, dateTo) => {
  const q = new URLSearchParams({
    date_from: dateFrom,
    date_to: dateTo,
    ...tzParams()
  });
  return fetch(`/api/kpis?${q}`).then(json);
};

export const fetchTimeline = (dateFrom, dateTo, granularity) => {
  const q = new URLSearchParams({
    date_from: dateFrom,
    date_to: dateTo,
    granularity,
    ...tzParams()
  });
  return fetch(`/api/timeline?${q}`).then(json);
};

export const fetchAgents = () => fetch("/api/agents").then(json);

export const fetchActions = ({
  dateFrom,
  dateTo,
  agentId,
  actionType,
  page = 1,
  pageSize = 50
}) => {
  const q = new URLSearchParams({
    date_from: dateFrom,
    date_to: dateTo,
    page: String(page),
    page_size: String(pageSize),
    ...tzParams()
  });
  if (agentId) q.set("agent_id", agentId);
  if (actionType) q.set("action_type", actionType);
  return fetch(`/api/actions?${q.toString()}`).then(json);
};

export const fetchSyncStatus = () => fetch("/api/sync/status").then(json);
export const triggerSync = () => fetch("/api/sync/trigger", { method: "POST" }).then(json);
