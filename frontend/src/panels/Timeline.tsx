import type { Meta } from "../api";

export const SPEEDS = [0.5, 1, 2] as const;
export type Speed = (typeof SPEEDS)[number];

interface Props {
  meta: Meta;
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

export function Timeline(props: Props) {
  const { meta, hour, playing, speed, locked, onChange, onTogglePlay, onSpeed } = props;
  const { start_hour, end_hour, zero_hour } = meta.story;
  const ticks = Array.from({ length: end_hour - start_hour + 1 }, (_, i) => start_hour + i);
  return (
    <div className="timeline">
      <div className="transport">
        <button type="button" className="play" disabled={locked} onClick={onTogglePlay}>
          {playing ? "❚❚ Pause" : "▶ Play"}
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
      <div className="scrubber">
        <input
          type="range"
          aria-label="Replay hour"
          min={start_hour}
          max={end_hour}
          step={1}
          value={hour}
          disabled={locked}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <div className="timeline-ticks">
          {ticks.map((tick) => (
            <button
              key={tick}
              type="button"
              className={tick === hour ? "tick active" : "tick"}
              disabled={locked}
              onClick={() => onChange(tick)}
            >
              <span>{offsetLabel(tick - zero_hour)}</span>
              <span className="tick-clock">{clockLabel(tick)}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
