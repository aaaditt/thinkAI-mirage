import type { Meta } from "../api";

interface Props {
  meta: Meta;
  hour: number;
  onChange: (hour: number) => void;
}

export function offsetLabel(offset: number): string {
  if (offset === 0) return "T–0";
  return offset < 0 ? `T–${-offset} h` : `T+${offset} h`;
}

export function clockLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

export function Timeline({ meta, hour, onChange }: Props) {
  const { start_hour, end_hour, zero_hour } = meta.story;
  const ticks = Array.from({ length: end_hour - start_hour + 1 }, (_, i) => start_hour + i);
  return (
    <div className="timeline">
      <input
        type="range"
        aria-label="Replay hour"
        min={start_hour}
        max={end_hour}
        step={1}
        value={hour}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <div className="timeline-ticks">
        {ticks.map((tick) => (
          <button
            key={tick}
            type="button"
            className={tick === hour ? "tick active" : "tick"}
            onClick={() => onChange(tick)}
          >
            <span>{offsetLabel(tick - zero_hour)}</span>
            <span className="tick-clock">{clockLabel(tick)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
