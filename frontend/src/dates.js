import { DateTime } from "luxon";

/** IANA zone for “calendar day” presets (matches API default). */
export const REPORT_TIMEZONE = "America/Los_Angeles";

export const PRESET_KEYS = {
  TODAY: "today",
  YESTERDAY: "yesterday",
  LAST_7_DAYS: "last_7_days",
  LAST_30_DAYS: "last_30_days",
  CUSTOM: "custom"
};

/**
 * @param {string} preset
 * @returns {{ from: string, to: string } | null}
 */
export function presetToRange(preset) {
  const now = DateTime.now().setZone(REPORT_TIMEZONE);
  if (preset === PRESET_KEYS.TODAY) {
    const d = now.toISODate();
    return { from: d, to: d };
  }
  if (preset === PRESET_KEYS.YESTERDAY) {
    const y = now.minus({ days: 1 });
    const d = y.toISODate();
    return { from: d, to: d };
  }
  if (preset === PRESET_KEYS.LAST_7_DAYS) {
    const start = now.minus({ days: 6 }).startOf("day");
    return { from: start.toISODate(), to: now.toISODate() };
  }
  if (preset === PRESET_KEYS.LAST_30_DAYS) {
    const start = now.minus({ days: 29 }).startOf("day");
    return { from: start.toISODate(), to: now.toISODate() };
  }
  return null;
}
