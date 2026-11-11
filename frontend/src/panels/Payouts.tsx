import type { Meta, PayoutEvent } from "../api";
import { clockLabel, offsetLabel } from "./Timeline";

interface Props {
  meta: Meta;
  payouts: PayoutEvent[];
  totalAed: number;
}

export function aed(amount: number): string {
  return `AED ${amount.toLocaleString("en-US")}`;
}

export function Payouts({ meta, payouts, totalAed }: Props) {
  const policies = new Map(meta.policies.map((policy) => [policy.id, policy]));
  const newestFirst = [...payouts].reverse();
  return (
    <section className="payouts" aria-label="Shield payouts">
      <div className="head">
        <h2>Shield</h2>
        <p>Mock parametric payouts</p>
      </div>
      <div className="payout-total">{aed(totalAed)}</div>
      <p className="note">
        {payouts.length} of {meta.policies.length} mock policies triggered by simulated sensors. No
        money moves.
      </p>
      {newestFirst.length > 0 && (
        <ul className="payout-list">
          {newestFirst.map((event) => {
            const policy = policies.get(event.policy_id);
            return (
              <li key={event.policy_id}>
                <span className="payout-who">{policy?.business ?? event.policy_id}</span>
                <span className="payout-amount">{aed(event.amount_aed)}</span>
                <span className="payout-why">
                  {clockLabel(event.hour)} ({offsetLabel(event.hour - meta.story.zero_hour)}),{" "}
                  {Math.round(event.measured_cm)} cm at gauge {policy?.sensor_id}. Trigger:{" "}
                  {policy?.threshold_cm} cm for {policy?.duration_hours} h.
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
