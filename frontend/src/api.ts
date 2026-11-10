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
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} failed: HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export const fetchMeta = () => getJson<Meta>("/api/meta");
export const fetchRoads = () => getJson<FeatureCollection>("/api/roads");
export const fetchFrame = (hour: number) => getJson<ReplayFrame>(`/api/replay/${hour}`);
