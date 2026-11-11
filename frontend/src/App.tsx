import { useCallback, useEffect, useRef, useState } from "react";

import {
  decideAction,
  fetchFrame,
  fetchMeta,
  requestPlan,
  resetReplay,
  type Meta,
  type PlanResult,
  type ReplayFrame,
} from "./api";
import { MapView } from "./map/MapView";
import { ActionQueue } from "./panels/ActionQueue";
import { Payouts } from "./panels/Payouts";
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
  const [fatal, setFatal] = useState<string | null>(null);
  const [lastPlan, setLastPlan] = useState<PlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [queueError, setQueueError] = useState<string | null>(null);
  const hourRef = useRef<number | null>(null);
  hourRef.current = hour;

  useEffect(() => {
    fetchMeta()
      .then((loaded) => {
        setMeta(loaded);
        setHour(loaded.story.start_hour);
      })
      .catch((reason: unknown) => setFatal(String(reason)));
  }, []);

  useEffect(() => {
    if (hour === null) return;
    let stale = false;
    fetchFrame(hour)
      .then((loaded) => {
        if (!stale) setFrame(loaded);
      })
      .catch((reason: unknown) => setFatal(String(reason)));
    return () => {
      stale = true;
    };
  }, [hour]);

  /**
   * Run one agent or operator request, then reload the frame. Buttons stay
   * disabled until the reloaded frame is on screen: after a pump approval the
   * server re-runs the simulation, and a stale card must not be clickable.
   */
  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setQueueError(null);
    try {
      await work();
    } catch (reason) {
      setQueueError(reason instanceof Error ? reason.message : String(reason));
    }
    try {
      const shownHour = hourRef.current;
      if (shownHour !== null) {
        const loaded = await fetchFrame(shownHour);
        if (hourRef.current === loaded.hour) setFrame(loaded);
      }
    } catch (reason) {
      setFatal(String(reason));
    } finally {
      setBusy(false);
    }
  }, []);

  if (fatal) return <div className="fatal">Cannot reach the Mirage API. {fatal}</div>;
  if (!meta || hour === null) return <div className="fatal">Loading replay…</div>;

  const shown = frame ? frame[view] : "";
  const count = (digit: string) => shown.split(digit).length - 1;

  return (
    <div className="app">
      <MapView
        meta={meta}
        risk={shown}
        actions={frame?.actions ?? []}
        payouts={frame?.payouts ?? []}
        hour={hour}
      />

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

        <Payouts
          meta={meta}
          payouts={frame?.payouts ?? []}
          totalAed={frame?.payout_total_aed ?? 0}
        />

        <ActionQueue
          meta={meta}
          actions={frame?.actions ?? []}
          pumpsAvailable={frame?.pumps_available ?? 0}
          lastPlan={lastPlan}
          busy={busy}
          error={queueError}
          onPlan={() => run(async () => setLastPlan(await requestPlan(hour)))}
          onDecide={(id, decision) => run(async () => void (await decideAction(id, decision)))}
          onReset={() =>
            run(async () => {
              await resetReplay();
              setLastPlan(null);
            })
          }
        />
      </aside>

      <footer className="bottombar">
        <Timeline meta={meta} hour={hour} onChange={setHour} />
      </footer>
    </div>
  );
}
