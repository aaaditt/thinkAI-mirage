import type { ReplayFrame } from "../api";

interface Props {
  frame: ReplayFrame | null;
  /** 0 = rain recorded this hour; 1..6 = simulated forecast for that many hours ahead. */
  lead: number;
  onLead: (lead: number) => void;
}

const BAR_FULL_MM = 12; // an area mean at or above this fills the bar

function mean(values: number[]): number {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

/** The rain field for a lead: the record for 0, the simulated forecast otherwise. */
export function rainField(frame: ReplayFrame, lead: number): number[] {
  return lead === 0 ? frame.rain_mm : (frame.rain_forecast_mm[lead - 1] ?? []);
}

export function Sky({ frame, lead, onLead }: Props) {
  const leads = frame ? [0, ...frame.rain_forecast_mm.map((_, index) => index + 1)] : [];
  return (
    <section className="card sky" aria-label="Sky: rainfall now and forecast">
      <div className="card-head">
        <h2>Sky</h2>
        <span className="card-meta">area-mean rain, mm/h</span>
      </div>
      <div className="bars" role="radiogroup" aria-label="Rain shown on the map">
        {frame &&
          leads.map((option) => {
            const mm = mean(rainField(frame, option));
            return (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={lead === option}
                className={lead === option ? "bar active" : "bar"}
                onClick={() => onLead(option)}
              >
                <span className="bar-value">{mm.toFixed(1)}</span>
                <span className="bar-track">
                  <span
                    className={option === 0 ? "bar-fill" : "bar-fill forecast"}
                    style={{ height: `${Math.min(100, (mm / BAR_FULL_MM) * 100)}%` }}
                  />
                </span>
                <span className="bar-label">{option === 0 ? "now" : `+${option}h`}</span>
              </button>
            );
          })}
      </div>
      <p className="note">
        Map shows {lead === 0 ? "rain recorded this hour" : `the simulated forecast for +${lead} h`}.
        “Now” is the historical record; +1 to +6 h are a simulated nowcast.
      </p>
    </section>
  );
}
