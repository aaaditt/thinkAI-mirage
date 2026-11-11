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

const STATUS_ORDER = { proposed: 0, approved: 1, rejected: 2 };

export function depthLabel(depthCm: number, capCm: number): string {
  return depthCm > capCm ? `over ${capCm} cm` : `${Math.round(depthCm)} cm`;
}

function plannerNote(plan: PlanResult): string {
  if (plan.planner === "llm") return "Planned by the LLM (Azure OpenAI), then rule-checked.";
  if (plan.fallback_reason) return "LLM plan failed its checks. Rule-based planner used instead.";
  return "Planned by the rule-based planner (no LLM key set).";
}

function decisionLabel(action: Action): string {
  if (action.status === "rejected") return "✕ Rejected by operator";
  return action.decided_by === "demo_auto" ? "✓ Auto-approved for demo" : "✓ Approved by operator";
}

function ActionCard({ meta, action, busy, onDecide }: {
  meta: Meta;
  action: Action;
  busy: boolean;
  onDecide: Props["onDecide"];
}) {
  const { evidence } = action;
  return (
    <li className={`action ${action.status}`}>
      <div className="action-head">
        <span className={`action-type ${action.type}`}>{TYPE_LABEL[action.type]}</span>
        <span className="action-id">{action.id}</span>
      </div>
      <div className="action-target">{action.label}</div>
      <div className="action-when">
        From {clockLabel(action.start_hour)} ({offsetLabel(action.start_hour - meta.story.zero_hour)})
      </div>
      {action.message && <blockquote className="action-message">{action.message}</blockquote>}
      <p className="action-reason">{action.reason}</p>
      <dl className="evidence">
        <div>
          <dt>Forecast</dt>
          <dd>{depthLabel(evidence.forecast_depth_cm, meta.thresholds.display_cap_cm)}</dd>
        </div>
        <div>
          <dt>Lead</dt>
          <dd>{evidence.lead_hours} h</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{Math.round(evidence.confidence * 100)}%</dd>
        </div>
      </dl>
      {action.status === "proposed" ? (
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
      ) : (
        <div className={`action-status ${action.status} ${action.decided_by ?? ""}`}>
          {decisionLabel(action)}
        </div>
      )}
    </li>
  );
}

export function ActionQueue(props: Props) {
  const { meta, actions, pumpsAvailable, lastPlan, busy, demo, error } = props;
  const { onPlan, onDecide, onReset } = props;
  const sorted = [...actions].sort(
    (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || b.id.localeCompare(a.id),
  );
  const waiting = actions.filter((action) => action.status === "proposed").length;
  return (
    <section className="queue" aria-label="Agent action queue">
      <div className="queue-head">
        <h2>Agent proposals</h2>
        <span className="queue-count">{waiting} awaiting decision</span>
      </div>
      <div className="queue-tools">
        <button type="button" className="primary" disabled={busy} onClick={onPlan}>
          {busy && !demo ? "Working…" : "Ask agent for a plan"}
        </button>
        <button type="button" className="ghost" disabled={busy} onClick={onReset}>
          Reset
        </button>
      </div>
      {demo && (
        <p className="demo-note" role="status">
          Demo mode: proposals are being auto-approved. No operator is deciding.
        </p>
      )}
      <p className="note">
        Nothing takes effect until you approve it. Pumps available: {pumpsAvailable} (mock fleet).
        {lastPlan && ` ${plannerNote(lastPlan)}`}
      </p>
      {error && <p className="queue-error" role="alert">{error}</p>}
      {sorted.length === 0 ? (
        <p className="queue-empty">No proposals yet.</p>
      ) : (
        <ul className="actions">
          {sorted.map((action) => (
            <ActionCard key={action.id} meta={meta} action={action} busy={busy}
              onDecide={onDecide} />
          ))}
        </ul>
      )}
    </section>
  );
}
