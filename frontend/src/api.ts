// Types mirror backend/app/models.py.

import type { FeatureCollection } from "geojson";

export interface District {
  name: string;
  lat: number;
  lon: number;
}

export interface Meta {
  disclaimer: string;
  date: string;
  timezone: string;
  hours: number;
  bbox: [number, number, number, number]; // lon_min, lat_min, lon_max, lat_max
  grid_rows: number;
  grid_cols: number;
  rain_rows: number;
  rain_cols: number;
  rain_block: number;
  forecast_leads: number;
  segment_count: number;
  story: { zero_hour: number; start_hour: number; end_hour: number };
  thresholds: { caution_cm: number; impassable_cm: number; display_cap_cm: number };
  districts: District[];
  policies: Policy[];
}

/** A MOCK parametric policy. */
export interface Policy {
  id: string;
  business: string;
  district: string;
  lat: number;
  lon: number;
  tier: string;
  threshold_cm: number;
  duration_hours: number;
  amount_aed: number;
  sensor_id: string;
  sensor_distance_m: number;
}

/** Fired from simulated sensor readings only. No money moves. */
export interface PayoutEvent {
  policy_id: string;
  hour: number;
  measured_cm: number;
  amount_aed: number;
}

export interface SensorReading {
  id: string;
  lat: number;
  lon: number;
  at_underpass: boolean;
  depth_cm: number;
}

export interface ReplayFrame {
  hour: number;
  offset_hours: number;
  rain_mm: number[];
  rain_forecast_mm: number[][];
  /** One digit per road segment, in /api/roads order: 0 clear, 1 caution, 2 impassable. */
  risk: string;
  risk_uncorrected: string;
  risk_next_6h: string;
  counts: { clear: number; caution: number; impassable: number };
  sensors: SensorReading[];
  actions: Action[];
  closed_segments: number[];
  alerts: Alert[];
  pumps_available: number;
  payouts: PayoutEvent[];
  payout_total_aed: number;
}

export type ActionType = "stage_pump" | "close_underpass" | "area_alert" | "open_road";

/** A proposal from the agent. Only Approve gives it any effect. */
export interface Action {
  id: string;
  type: ActionType;
  status: "proposed" | "approved" | "rejected";
  target: string;
  label: string;
  lat: number;
  lon: number;
  start_hour: number;
  end_hour: number | null;
  proposed_hour: number;
  reason: string;
  evidence: { forecast_depth_cm: number; lead_hours: number; confidence: number };
  message: string | null;
}

export interface Alert {
  action_id: string;
  district: string;
  message: string;
  issued_hour: number;
}

export interface PlanResult {
  planner: "llm" | "rules";
  fallback_reason: string | null;
  actions: Action[];
}

async function request<T>(path: string, method: "GET" | "POST"): Promise<T> {
  const response = await fetch(path, { method });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `${path} failed: HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

const getJson = <T>(path: string) => request<T>(path, "GET");

export const fetchMeta = () => getJson<Meta>("/api/meta");
export const fetchRoads = () => getJson<FeatureCollection>("/api/roads");
export const fetchFrame = (hour: number) => getJson<ReplayFrame>(`/api/replay/${hour}`);
export const requestPlan = (hour: number) => request<PlanResult>(`/api/plan/${hour}`, "POST");
export const decideAction = (id: string, decision: "approve" | "reject") =>
  request<Action>(`/api/actions/${id}/${decision}`, "POST");
export const resetReplay = () => request<{ ok: boolean }>("/api/reset", "POST");
