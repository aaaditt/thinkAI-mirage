import { useEffect } from "react";

import type { Meta } from "../api";
import { clockLabel } from "./Timeline";

interface Props {
  meta: Meta;
  onClose: () => void;
}

export function About({ meta, onClose }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="About Mirage"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawer-head">
          <h2>About Mirage</h2>
          <button type="button" className="ghost" onClick={onClose} autoFocus>
            Close
          </button>
        </div>
        <p>
          A student prototype by Team Everglow (ThinkAI'26). It replays the Dubai storm of{" "}
          {meta.date} hour by hour and shows how a forecast could become street-level action. T–0
          is {clockLabel(meta.story.zero_hour)} GST, the hour of heaviest rain in the historical data.
        </p>

        <h3>Real data</h3>
        <ul>
          <li>
            Hourly rainfall for {meta.date}: Open-Meteo historical archive. This is a reanalysis, a
            model-based reconstruction on cells 7 to 8 km wide, not rain-gauge or radar readings.
          </li>
          <li>Ground elevation: Open-Meteo elevation API.</li>
          <li>Roads, tunnels and underpasses: OpenStreetMap, via Overpass.</li>
        </ul>

        <h3>Simulated</h3>
        <ul>
          <li>
            The rain forecast: the historical record, blurred and with noise that grows with lead
            time.
          </li>
          <li>All depth sensors and “camera” readings. No real camera or gauge is connected.</li>
          <li>Pumps, tankers and depots (a mock fleet).</li>
          <li>
            All {meta.policies.length} insurance policies, businesses and payouts. No money moves.
          </li>
          <li>Alerts. They appear in this app only and are never sent anywhere.</li>
        </ul>

        <h3>Model limits</h3>
        <ul>
          <li>
            The flood model is a simplified surrogate, not a hydraulic model. Rain is added to
            grid cells of about 200 m, part of the water flows to the lowest neighbour, and a
            fixed drainage rate is removed. It is not calibrated against observed flooding.
          </li>
          <li>
            Depths are indicative. Deep values are shown as “over {meta.thresholds.display_cap_cm}{" "}
            cm”.
          </li>
          <li>Reanalysis rainfall understates the true peak of this storm.</li>
          <li>Underpass dips are assumed; the elevation data cannot see them.</li>
          <li>
            The “truth” the simulated sensors read is a second run of the same model, so the
            sensor correction shows the mechanism, not real forecast skill.
          </li>
          <li>
            The confidence score on each proposal is a fixed function of lead time, not a
            calibrated probability.
          </li>
          <li>
            Without an Azure OpenAI key the agent is a fixed set of rules, not a language model.
            The language-model path has not been run against a live key.
          </li>
          <li>
            We have no access to NCM radar, RTA cameras or NCEMA systems. They are modelled behind
            interfaces with simulated stand-ins.
          </li>
        </ul>

        <h3>Human in the loop</h3>
        <p>
          The agent only proposes. Nothing takes effect until someone clicks Approve. Demo mode
          approves automatically so the story can run hands-free, and labels every such action
          “auto-approved for demo”.
        </p>

        <h3>Data credits</h3>
        <ul>
          <li>Weather and elevation data by Open-Meteo.com (CC BY 4.0).</li>
          <li>Roads © OpenStreetMap contributors (ODbL).</li>
          <li>Basemap © CARTO, © OpenStreetMap contributors.</li>
        </ul>
      </aside>
    </div>
  );
}
