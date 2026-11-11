import { useMemo } from "react";

import type { Meta, ReplayFrame } from "../api";

export const SPEEDS = [0.5, 1, 2] as const;
export type Speed = (typeof SPEEDS)[number];

interface Props {
  meta: Meta;
  frame: ReplayFrame | null;
  hour: number;
  playing: boolean;
  speed: Speed;
  /** True while Demo mode drives the clock. */
  locked: boolean;
  onChange: (hour: number) => void;
  onTogglePlay: () => void;
  onSpeed: (speed: Speed) => void;
}

export function offsetLabel(offset: number): string {
  if (offset === 0) return "T–0";
  return offset < 0 ? `T–${-offset} h` : `T+${offset} h`;
}

export function clockLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

function mean(values: number[]): number {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

type Kind = "recorded" | "forecast" | "beyond";

/**
 * The storm as a timeline: one rain bar per story hour. Hours up to the shown
 * one are the record; the next six are the simulated forecast issued now.
 */
export function Timeline(props: Props) {
  const { meta, frame, hour, playing, speed, locked, onChange, onTogglePlay, onSpeed } = props;
  const { start_hour, end_hour, zero_hour } = meta.story;
  const columns = Array.from({ length: end_hour - start_hour + 1 }, (_, i) => start_hour + i);
  const forecast = useMemo(() => (frame ? frame.rain_forecast_mm.map(mean) : []), [frame]);
  // One fixed scale for the whole replay, so bars never rescale between hours.
  const fullMm = Math.max(1, ...columns.map((column) => meta.rain_mean_mm[column] ?? 0)) * 1.1;

  const bar = (column: number): { kind: Kind; mm: number } => {
    if (column <= hour) return { kind: "recorded", mm: meta.rain_mean_mm[column] ?? 0 };
    // Only use the forecast once the frame on screen is the one for this hour.
    const ahead = frame?.hour === hour ? forecast[column - hour - 1] : undefined;
    return ahead === undefined ? { kind: "beyond", mm: 0 } : { kind: "forecast", mm: ahead };
  };

  return (
    <footer className="sky" aria-label="Sky: rainfall timeline">
      <div className="transport">
        <button type="button" className="play" disabled={locked} onClick={onTogglePlay}>
          {playing ? "Pause" : "Play"}
        </button>
        <div className="speeds" role="radiogroup" aria-label="Playback speed">
          {SPEEDS.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={speed === option}
              className={speed === option ? "speed active" : "speed"}
              disabled={locked}
              onClick={() => onSpeed(option)}
            >
              {option}×
            </button>
          ))}
        </div>
      </div>

      <div className="sky-main">
        <div className="head">
          <h2>Sky</h2>
          <p>Rain averaged over the study area, mm per hour</p>
          <ul className="sky-key">
            <li>
              <span className="key-swatch" />
              Historical (reanalysis)
            </li>
            <li>
              <span className="key-swatch forecast" />
              Forecast issued at {clockLabel(hour)} (simulated)
            </li>
          </ul>
        </div>
        <div className="hours">
          {columns.map((column) => {
            const { kind, mm } = bar(column);
            const state = column === hour ? "now" : column < hour ? "past" : "ahead";
            return (
              <button
                key={column}
                type="button"
                className={`hour ${state} ${kind}`}
                aria-current={column === hour ? "time" : undefined}
                aria-label={`${offsetLabel(column - zero_hour)}, ${clockLabel(column)}, ${
                  kind === "beyond" ? "beyond the forecast" : `${mm.toFixed(1)} mm ${kind === "recorded" ? "historical" : "simulated forecast"}`
                }`}
                disabled={locked}
                onClick={() => onChange(column)}
              >
                <span className="hour-track">
                  <span className="hour-mm">{kind === "beyond" ? "" : mm.toFixed(1)}</span>
                  <span className="hour-fill" style={{ flexGrow: Math.min(1, mm / fullMm) }} />
                  <span className="hour-gap" style={{ flexGrow: 1 - Math.min(1, mm / fullMm) }} />
                </span>
                <span className="hour-offset">{offsetLabel(column - zero_hour)}</span>
                <span className="hour-clock">{clockLabel(column)}</span>
              </button>
            );
          })}
        </div>
      </div>
    </footer>
  );
}
