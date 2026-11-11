import type { Action, Alert } from "../api";
import { clockLabel } from "./Timeline";

interface Props {
  /** Approved alerts issued up to the shown hour, newest last. */
  alerts: Alert[];
  actions: Action[];
}

export function AlertCard({ alerts, actions }: Props) {
  const latest = alerts[alerts.length - 1];
  const auto =
    latest !== undefined &&
    actions.find((action) => action.id === latest.action_id)?.decided_by === "demo_auto";
  return (
    <section className="alert" aria-label="Latest approved area alert, phone preview">
      <div className="head">
        <h2>Area alert</h2>
        <p>In-app preview, never sent</p>
      </div>
      <div className="phone">
        <div className="phone-bar">
          <span>{latest ? clockLabel(latest.issued_hour) : "--:--"}</span>
          <span className="phone-notch" />
          <span>GST</span>
        </div>
        {latest ? (
          <div className="bubble">
            <div className="bubble-head">
              <b>Mirage area alert</b>
              <span>{latest.district}</span>
            </div>
            <p>{latest.message}</p>
          </div>
        ) : (
          <p className="phone-empty">No alert yet. Approve an area alert to preview it here.</p>
        )}
      </div>
      {latest && (
        <p className={auto ? "note auto" : "note"}>
          {auto ? "Auto-approved for demo." : "Approved by operator."}
        </p>
      )}
    </section>
  );
}
