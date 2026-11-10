import { useEffect, useState } from "react";

import { fetchFrame, fetchMeta, type Meta, type ReplayFrame } from "./api";
import { MapView } from "./map/MapView";
import { clockLabel, offsetLabel, Timeline } from "./panels/Timeline";

type View = "risk" | "risk_uncorrected" | "risk_next_6h";

const VIEWS: { key: View; label: string }[] = [
  { key: "risk", label: "Now, sensor-corrected" },
  { key: "risk_uncorrected", label: "Now, model only" },
  { key: "risk_next_6h", label: "Worst in next 6 h" },
];

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [hour, setHour] = useState<number | null>(null);
  const [frame, setFrame] = useState<ReplayFrame | null>(null);
  const [view, setView] = useState<View>("risk");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMeta()
      .then((loaded) => {
        setMeta(loaded);
        setHour(loaded.story.start_hour);
      })
      .catch((reason: unknown) => setError(String(reason)));
  }, []);

  useEffect(() => {
    if (hour === null) return;
    let stale = false;
    fetchFrame(hour)
      .then((loaded) => {
        if (!stale) setFrame(loaded);
      })
      .catch((reason: unknown) => setError(String(reason)));
    return () => {
      stale = true;
    };
  }, [hour]);

  if (error) return <div className="fatal">Cannot reach the Mirage API. {error}</div>;
  if (!meta || hour === null) return <div className="fatal">Loading replay…</div>;

  const shown = frame ? frame[view] : "";
  const count = (digit: string) => shown.split(digit).length - 1;

  return (
    <div className="app">
      <MapView meta={meta} risk={shown} />

      <header className="topbar">
        <h1>
          Mirage <span lang="ar">سراب</span>
        </h1>
        <span className="badge">{meta.disclaimer}</span>
      </header>

      <aside className="panel">
        <div className="clock">
          <div className="clock-offset">{offsetLabel(hour - meta.story.zero_hour)}</div>
          <div className="clock-time">
            {clockLabel(hour)} GST · {meta.date}
          </div>
        </div>

        <div className="views" role="radiogroup" aria-label="Road risk view">
          {VIEWS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={view === key}
              className={view === key ? "view active" : "view"}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <ul className="legend">
          <li>
            <span className="swatch impassable" />
            Impassable, over {meta.thresholds.impassable_cm} cm
            <b>{count("2").toLocaleString()}</b>
          </li>
          <li>
            <span className="swatch caution" />
            Caution, {meta.thresholds.caution_cm}–{meta.thresholds.impassable_cm} cm
            <b>{count("1").toLocaleString()}</b>
          </li>
          <li>
            <span className="swatch clear" />
            Clear
            <b>{count("0").toLocaleString()}</b>
          </li>
        </ul>
        <p className="note">
          Road segments of {meta.segment_count.toLocaleString()}. Depths come from a simplified
          model, not a hydraulic one.
        </p>
      </aside>

      <footer className="bottombar">
        <Timeline meta={meta} hour={hour} onChange={setHour} />
      </footer>
    </div>
  );
}
