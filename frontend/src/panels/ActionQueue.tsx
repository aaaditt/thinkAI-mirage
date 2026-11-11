import type { Action, ActionType, Meta, PlanResult } from "../api";
import { clockLabel, offsetLabel } from "./Timeline";

interface Props {
  meta: Meta;
  actions: Action[];
  pumpsAvailable: number;
  lastPlan: PlanResult | null;
  busy: boolean;
  /** True while Demo mode is approving on its own. */
  demo: boolean;
  error: string | null;
  onPlan: () => void;
  onDecide: (id: string, decision: "approve" | "reject") => void;
  onReset: () => void;
}

const TYPE_LABEL: Record<ActionType, string> = {
  stage_pump: "Stage pump",
  close_underpass: "Close underpass",
  area_alert: "Area alert",
  open_road: "Reopen road",
};

/** Same shapes as the map markers, so a card and its marker read as one thing. */
const TYPE_GLYPH: Record<ActionType, string> = {
  stage_pump: "pump",
  close_underpass: "closure",
  area_alert: "alert",
  open_road: "reopen",
};

function depthLabel(depthCm: number, capCm: number): string {
  return depthCm > capCm ? `over ${capCm} cm` : `${Math.round(depthCm)} cm`;
}

function plannerNote(plan: PlanResult): string {
  if (plan.planner === "llm") return "Last plan: LLM (Azure OpenAI), then rule-checked.";
  if (plan.fallback_reason) return "Last plan: the LLM plan failed its checks, so rules were used.";
  return "Last plan: rule-based planner (no LLM key set).";
}

function decisionLabel(action: Action): string {
  if (action.status === "rejected") return "Rejected";
  return action.decided_by === "demo_auto" ? "Auto-approved for demo" : "Approved by operator";
}

function Title({ action }: { action: Action }) {
  return (
    <>
      <span className={`glyph ${TYPE_GLYPH[action.type]}`} />
      <span className="action-type">{TYPE_LABEL[action.type]}</span>
      <span className="action-target">{action.label}</span>
    </>
  );
}

function Detail({ meta, action }: { meta: Meta; action: Action }) {
  const { evidence } = action;
  return (
    <>
      {action.message && <blockquote className="action-message">{action.message}</blockquote>}
      <p className="action-reason">{action.reason}</p>
      <p className="evidence">
        {depthLabel(evidence.forecast_depth_cm, meta.thresholds.display_cap_cm)} forecast,{" "}
        {evidence.lead_hours} h lead, confidence score {Math.round(evidence.confidence * 100)}%.
        Starts{" "}
        {clockLabel(action.start_hour)} ({offsetLabel(action.start_hour - meta.story.zero_hour)}).
      </p>
    </>
  );
}

function Proposal({ meta, action, busy, onDecide }: {
  meta: Meta;
  action: Action;
  busy: boolean;
  onDecide: Props["onDecide"];
}) {
  return (
    <li className="proposal">
      <div className="action-title">
        <Title action={action} />
      </div>
      <Detail meta={meta} action={action} />
      <div className="action-buttons">
        <button type="button" className="approve" disabled={busy}
          onClick={() => onDecide(action.id, "approve")}>
          Approve
        </button>
        <button type="button" className="reject" disabled={busy}
          onClick={() => onDecide(action.id, "reject")}>
          Reject
        </button>
      </div>
    </li>
  );
}

/** A decided action: one line, expandable to the agent's reason and evidence. */
function Decided({ meta, action }: { meta: Meta; action: Action }) {
  return (
    <li className={`decided ${action.status}`}>
      <details>
        <summary>
          <Title action={action} />
          <span className={`decision ${action.decided_by ?? ""}`}>{decisionLabel(action)}</span>
        </summary>
        <Detail meta={meta} action={action} />
      </details>
    </li>
  );
}

export function ActionQueue(props: Props) {
  const { meta, actions, pumpsAvailable, lastPlan, busy, demo, error } = props;
  const { onPlan, onDecide, onReset } = props;
  const newestFirst = [...actions].reverse();
  const waiting = newestFirst.filter((action) => action.status === "proposed");
  const decided = newestFirst.filter((action) => action.status !== "proposed");
  return (
    <section className="queue" aria-label="City: agent action queue">
      <div className="head">
        <h2>City</h2>
        <p>The agent proposes. A person decides.</p>
      </div>
      <div className="queue-tools">
        <button type="button" className="primary" disabled={busy} onClick={onPlan}>
          {busy && !demo ? "Working…" : "Ask agent for a plan"}
        </button>
        <button type="button" className="quiet" disabled={busy} onClick={onReset}>
          Reset
        </button>
      </div>
      {demo && (
        <p className="demo-note" role="status">
          Demo mode is approving proposals automatically. No operator is deciding.
        </p>
      )}
      <p className="note">
        {pumpsAvailable} pumps left in the mock fleet.
        {lastPlan && ` ${plannerNote(lastPlan)}`}
      </p>
      {error && <p className="queue-error" role="alert">{error}</p>}

      <div className="queue-scroll">
        <h3>
          Awaiting your decision <b>{waiting.length}</b>
        </h3>
        {waiting.length === 0 ? (
          <p className="queue-empty">
            {actions.length === 0
              ? "No proposals yet. Ask the agent for a plan, or start Demo mode."
              : "Nothing is waiting."}
          </p>
        ) : (
          <ul className="proposals">
            {waiting.map((action) => (
              <Proposal key={action.id} meta={meta} action={action} busy={busy}
                onDecide={onDecide} />
            ))}
          </ul>
        )}
        {decided.length > 0 && (
          <>
            <h3>
              Decided <b>{decided.length}</b>
            </h3>
            <ul className="decided-list">
              {decided.map((action) => (
                <Decided key={action.id} meta={meta} action={action} />
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
