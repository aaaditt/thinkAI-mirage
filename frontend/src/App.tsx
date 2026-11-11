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
import { Ground, type Lens } from "./panels/Ground";
import { Payouts } from "./panels/Payouts";
import { clockLabel, offsetLabel, type Speed, Timeline } from "./panels/Timeline";

type Mode = "idle" | "playing" | "demo";

/** Time one replay hour stays on screen while playing at 1x. */
const PLAY_STEP_MS = 2500;
const NO_RAIN: number[] = [];

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function storyCaption(offset: number): string {
  if (offset === 0) return "The hour of heaviest rain in the historical data";
  const hours = `${Math.abs(offset)} ${Math.abs(offset) === 1 ? "hour" : "hours"}`;
  return offset < 0 ? `${hours} before the heaviest rain` : `${hours} after the heaviest rain`;
}

function longDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** Per block: the heaviest hourly rain in the simulated forecast for the next 6 hours. */
function forecastPeak(frame: ReplayFrame): number[] {
  return frame.rain_mm.map((_, block) =>
    Math.max(0, ...frame.rain_forecast_mm.map((lead) => lead[block] ?? 0)),
  );
}

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch((reason: unknown) => setFatal(String(reason)));
  }, []);

  if (fatal) {
    return (
      <div className="fatal">
        Cannot reach the Mirage API. Start the backend on port 8000, then reload. ({fatal})
      </div>
    );
  }
  if (!meta) return <div className="fatal">Loading the replay…</div>;
  return <Console meta={meta} />;
}

function Console({ meta }: { meta: Meta }) {
  const { start_hour, end_hour, zero_hour } = meta.story;
  const [hour, setHour] = useState(start_hour);
  const [frame, setFrame] = useState<ReplayFrame | null>(null);
  const [lens, setLens] = useState<Lens>("risk");
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
    setLens("risk");
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
  const risk = frame ? frame[lens] : "";
  const rain = useMemo(() => {
    if (!frame) return NO_RAIN;
    return lens === "risk_next_6h" ? forecastPeak(frame) : frame.rain_mm;
  }, [frame, lens]);
  const offset = hour - zero_hour;

  return (
    <div className="app">
      <MapView
        meta={meta}
        risk={risk}
        rain={rain}
        sensors={frame?.sensors ?? []}
        actions={frame?.actions ?? []}
        payouts={frame?.payouts ?? []}
        hour={hour}
      />

      <aside className="rail rail-left">
        <header className="brand">
          <h1>
            Mirage <span lang="ar">سراب</span>
          </h1>
          <p className="badge">{meta.disclaimer}</p>
        </header>
        <Ground
          meta={meta}
          lens={lens}
          risk={risk}
          sensorCount={frame?.sensors.length ?? 0}
          onLens={setLens}
        />
        <AlertCard alerts={frame?.alerts ?? []} actions={frame?.actions ?? []} />
        <Payouts
          meta={meta}
          payouts={frame?.payouts ?? []}
          totalAed={frame?.payout_total_aed ?? 0}
        />
      </aside>

      <div className="clock">
        <div className="clock-offset">{offsetLabel(offset)}</div>
        <div className="clock-time">
          {clockLabel(hour)} GST, {longDate(meta.date)}
        </div>
        <div className="clock-caption">{storyCaption(offset)}</div>
      </div>

      <div className="stage-tools">
        <button
          type="button"
          className={demo ? "demo-button running" : "demo-button"}
          disabled={busy}
          onClick={demo ? stopDemo : startDemo}
        >
          {demo ? "Stop demo" : "Run demo"}
        </button>
        <button type="button" className="ghost" onClick={() => setAboutOpen(true)}>
          About
        </button>
      </div>

      <Timeline
        meta={meta}
        frame={frame}
        hour={hour}
        playing={mode === "playing"}
        speed={speed}
        locked={demo}
        onChange={(target) => void goTo(target)}
        onTogglePlay={togglePlay}
        onSpeed={setSpeed}
      />

      <aside className="rail rail-right">
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

      {aboutOpen && <About meta={meta} onClose={() => setAboutOpen(false)} />}
    </div>
  );
}
