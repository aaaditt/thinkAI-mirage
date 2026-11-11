import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  autoApproveAction,
  decideAction,
  fetchFrame,
  fetchMeta,
  requestPlan,
  resetReplay,
  type Meta,
  type PlanResult,
  type ReplayFrame,
} from "./api";
import { DEMO_STEP_MS, runDemo } from "./demo";
import { MapView } from "./map/MapView";
import { About } from "./panels/About";
import { ActionQueue } from "./panels/ActionQueue";
import { AlertCard } from "./panels/AlertCard";
import { Payouts } from "./panels/Payouts";
import { rainField, Sky } from "./panels/Sky";
import { clockLabel, offsetLabel, type Speed, Timeline } from "./panels/Timeline";

type View = "risk" | "risk_uncorrected" | "risk_next_6h";
type Mode = "idle" | "playing" | "demo";

const VIEWS: { key: View; label: string }[] = [
  { key: "risk", label: "Now, sensor-corrected" },
  { key: "risk_uncorrected", label: "Now, model only" },
  { key: "risk_next_6h", label: "Worst in next 6 h" },
];
/** Time one replay hour stays on screen while playing at 1x. */
const PLAY_STEP_MS = 2500;
const NO_RAIN: number[] = [];

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function storyCaption(offset: number): string {
  if (offset === 0) return "peak recorded rain";
  return offset < 0 ? "before peak rain" : "after peak rain";
}

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch((reason: unknown) => setFatal(String(reason)));
  }, []);

  if (fatal) return <div className="fatal">Cannot reach the Mirage API. {fatal}</div>;
  if (!meta) return <div className="fatal">Loading replay…</div>;
  return <Console meta={meta} />;
}

function Console({ meta }: { meta: Meta }) {
  const { start_hour, end_hour, zero_hour } = meta.story;
  const [hour, setHour] = useState(start_hour);
  const [frame, setFrame] = useState<ReplayFrame | null>(null);
  const [view, setView] = useState<View>("risk");
  const [rainLead, setRainLead] = useState(0);
  const [mode, setMode] = useState<Mode>("idle");
  const [speed, setSpeed] = useState<Speed>(1);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [lastPlan, setLastPlan] = useState<PlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hourRef = useRef(hour);
  const latestRequest = useRef(0);
  const demoAbort = useRef<AbortController | null>(null);

  /** Show `target`. Only the newest request may put its frame on screen. */
  const goTo = useCallback(async (target: number) => {
    hourRef.current = target;
    setHour(target);
    latestRequest.current += 1;
    const mine = latestRequest.current;
    try {
      const loaded = await fetchFrame(target);
      if (mine === latestRequest.current) setFrame(loaded);
    } catch (reason) {
      setError(`Could not load ${clockLabel(target)}: ${message(reason)}`);
    }
  }, []);

  useEffect(() => {
    void goTo(start_hour);
    return () => demoAbort.current?.abort();
  }, [goTo, start_hour]);

  // Play: step one hour at a time and stop at the end of the story.
  useEffect(() => {
    if (mode !== "playing") return;
    const timer = setTimeout(() => {
      if (hour >= end_hour) setMode("idle");
      else void goTo(hour + 1);
    }, PLAY_STEP_MS / speed);
    return () => clearTimeout(timer);
  }, [mode, hour, speed, end_hour, goTo]);

  /**
   * Run one agent or operator request, then reload the frame. Buttons stay
   * disabled until the reloaded frame is on screen: after a pump approval the
   * server re-runs the simulation, and a stale card must not be clickable.
   */
  const run = useCallback(
    async (work: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await work();
      } catch (reason) {
        setError(message(reason));
      }
      await goTo(hourRef.current);
      setBusy(false);
    },
    [goTo],
  );

  const togglePlay = () => {
    if (mode === "playing") return setMode("idle");
    if (hour >= end_hour) void goTo(start_hour);
    setMode("playing");
  };

  const startDemo = () => {
    const abort = new AbortController();
    demoAbort.current = abort;
    setMode("demo");
    setError(null);
    setView("risk");
    setRainLead(0);
    runDemo(
      meta.story,
      {
        reset: async () => {
          await resetReplay();
          setLastPlan(null);
        },
        showHour: goTo,
        plan: async (at) => {
          const plan = await requestPlan(at);
          setLastPlan(plan);
          await goTo(at);
          return plan.actions;
        },
        autoApprove: async ({ id }) => {
          try {
            const decided = await autoApproveAction(id);
            setFrame((shown) =>
              shown && { ...shown, actions: shown.actions.map((a) => (a.id === id ? decided : a)) },
            );
          } catch (reason) {
            setError(`${id} left for the operator: ${message(reason)}`);
          }
        },
        refresh: goTo,
      },
      DEMO_STEP_MS / speed,
      abort.signal,
    )
      .catch((reason: unknown) => {
        if (!abort.signal.aborted) setError(`Demo mode stopped: ${message(reason)}`);
      })
      .finally(() => {
        if (demoAbort.current === abort) setMode("idle");
      });
  };

  const stopDemo = () => {
    demoAbort.current?.abort();
    setMode("idle");
  };

  const demo = mode === "demo";
  const shown = frame ? frame[view] : "";
  const count = (digit: string) => shown.split(digit).length - 1;
  const rain = useMemo(() => (frame ? rainField(frame, rainLead) : NO_RAIN), [frame, rainLead]);
  const offset = hour - zero_hour;

  return (
    <div className="app">
      <MapView
        meta={meta}
        risk={shown}
        rain={rain}
        sensors={frame?.sensors ?? []}
        actions={frame?.actions ?? []}
        payouts={frame?.payouts ?? []}
        hour={hour}
      />

      <header className="topbar">
        <h1>
          Mirage <span lang="ar">سراب</span>
        </h1>
        <span className="badge">{meta.disclaimer}</span>
        <button
          type="button"
          className={demo ? "demo-button running" : "demo-button"}
          disabled={busy}
          onClick={demo ? stopDemo : startDemo}
        >
          {demo ? "■ Stop demo" : "▶ Demo mode"}
        </button>
        <button type="button" className="ghost" onClick={() => setAboutOpen(true)}>
          About
        </button>
      </header>

      <div className="left">
        <Sky frame={frame} lead={rainLead} onLead={setRainLead} />
        <AlertCard alerts={frame?.alerts ?? []} actions={frame?.actions ?? []} />
        <Payouts
          meta={meta}
          payouts={frame?.payouts ?? []}
          totalAed={frame?.payout_total_aed ?? 0}
        />
      </div>

      <aside className="panel">
        <div className="clock">
          <div className="clock-offset">{offsetLabel(offset)}</div>
          <div className="clock-side">
            <div className="clock-time">{clockLabel(hour)} GST</div>
            <div className="clock-caption">{meta.date}</div>
            <div className="clock-caption">{storyCaption(offset)}</div>
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
          <li>
            <span className="swatch sensor" />
            Simulated depth sensor
            <b>{frame?.sensors.length ?? 0}</b>
          </li>
          <li>
            <span className="swatch rain" />
            Rainfall (cyan haze, study area)
          </li>
        </ul>

        <ActionQueue
          meta={meta}
          actions={frame?.actions ?? []}
          pumpsAvailable={frame?.pumps_available ?? 0}
          lastPlan={lastPlan}
          busy={busy || demo}
          demo={demo}
          error={error}
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
        <Timeline
          meta={meta}
          hour={hour}
          playing={mode === "playing"}
          speed={speed}
          locked={demo}
          onChange={(target) => void goTo(target)}
          onTogglePlay={togglePlay}
          onSpeed={setSpeed}
        />
      </footer>

      {aboutOpen && <About meta={meta} onClose={() => setAboutOpen(false)} />}
    </div>
  );
}
