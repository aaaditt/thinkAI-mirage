import type { Meta } from "../api";

export type Lens = "risk" | "risk_uncorrected" | "risk_next_6h";

const LENSES: { key: Lens; label: string; note: string }[] = [
  { key: "risk", label: "Now", note: "Model depth, corrected by the simulated sensors." },
  { key: "risk_uncorrected", label: "Model only", note: "Model depth before the sensor correction." },
  { key: "risk_next_6h", label: "Next 6 h", note: "Worst depth and rain forecast over the next 6 hours." },
];

interface Props {
  meta: Meta;
  lens: Lens;
  /** One digit per road segment for the chosen lens. */
  risk: string;
  sensorCount: number;
  onLens: (lens: Lens) => void;
}

export function Ground({ meta, lens, risk, sensorCount, onLens }: Props) {
  const count = (digit: string) => (risk.split(digit).length - 1).toLocaleString();
  const { caution_cm, impassable_cm } = meta.thresholds;
  return (
    <section className="ground" aria-label="Ground: modelled flood depth on roads">
      <div className="head">
        <h2>Ground</h2>
        <p>Modelled flood depth on roads</p>
      </div>
      <div className="lens" role="radiogroup" aria-label="What the map shows">
        {LENSES.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={lens === key}
            className={lens === key ? "active" : undefined}
            onClick={() => onLens(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="note">{LENSES.find(({ key }) => key === lens)?.note}</p>

      <ul className="classes">
        <li>
          <span className="swatch impassable" />
          Impassable, over {impassable_cm} cm
          <b>{count("2")}</b>
        </li>
        <li>
          <span className="swatch caution" />
          Caution, {caution_cm} to {impassable_cm} cm
          <b>{count("1")}</b>
        </li>
        <li>
          <span className="swatch clear" />
          Clear
          <b>{count("0")}</b>
        </li>
      </ul>

      <ul className="symbols">
        <li>
          <span className="glyph sensor" />
          {sensorCount} sensors (simulated)
        </li>
        <li>
          <span className="glyph closure" />
          Closed underpass
        </li>
        <li>
          <span className="glyph pump" />
          Pump staged
        </li>
        <li>
          <span className="glyph payout" />
          Mock payout
        </li>
        <li className="wide">
          <span className="glyph frame" />
          Study area. Cyan haze is rain.
        </li>
      </ul>
    </section>
  );
}
