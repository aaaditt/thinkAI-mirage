// Demo mode: reset, then walk the story hour by hour, asking the agent for a
// plan and auto-approving it. Every approval is labelled "auto-approved for demo".

import type { Action } from "./api";

/** Nine story hours at 10 s each: the full run takes about 90 seconds at 1x. */
export const DEMO_STEP_MS = 10_000;
const BEFORE_PLAN = 0.15; // share of a step spent looking at the new hour
const BEFORE_APPROVE = 0.25; // share spent reading the proposals
const BETWEEN_APPROVALS_MS = 350;

export interface DemoSteps {
  reset: () => Promise<void>;
  showHour: (hour: number) => Promise<void>;
  plan: (hour: number) => Promise<Action[]>;
  autoApprove: (action: Action) => Promise<void>;
  refresh: (hour: number) => Promise<void>;
}

export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, Math.max(0, ms));
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

export async function runDemo(
  story: { start_hour: number; end_hour: number },
  steps: DemoSteps,
  stepMs: number,
  signal: AbortSignal,
): Promise<void> {
  await steps.reset();
  for (let hour = story.start_hour; hour <= story.end_hour; hour += 1) {
    signal.throwIfAborted();
    const stepEnds = performance.now() + stepMs;
    await steps.showHour(hour);
    await sleep(stepMs * BEFORE_PLAN, signal);
    const proposals = await steps.plan(hour);
    await sleep(stepMs * BEFORE_APPROVE, signal);
    for (const action of proposals) {
      await steps.autoApprove(action);
      await sleep(BETWEEN_APPROVALS_MS, signal);
    }
    await steps.refresh(hour);
    await sleep(stepEnds - performance.now(), signal);
  }
}
