# Mirage (سراب) — project spec for Claude Code

You are building **Mirage**, a working demo of an AI system that turns weather forecasts into street-level flood action for Dubai. It was pitched by Team Everglow at ThinkAI'26 (a Microsoft Imagine Cup preliminary). This is a **student prototype**: it must run on a laptop, be honest about what is simulated, and look good in a 3-minute live demo.

## What the demo must show
One screen, a dark map of Dubai, replaying the storm of **16 April 2024** hour by hour:
1. **Sky** — rainfall forecast for the next 6 hours, per grid cell.
2. **Ground** — predicted flood depth per street, updated each hour, corrected by (simulated) sensor readings.
3. **City** — an AI agent proposes actions (stage pumps, close underpasses, send area alerts). A human clicks **Approve** or **Reject**. Nothing is "sent" without approval.
4. **Shield** — when measured depth in an insured zone crosses a threshold, a parametric payout event fires automatically.

A timeline scrubber runs from T–6 h to T+2 h. Pressing Play animates the whole story.

## Honesty rules (non-negotiable)
- Never present simulated data as real. The UI shows a permanent badge: "Prototype — simulated sensors, simplified flood model".
- Real data: historical rainfall (Open-Meteo archive), elevation (Open-Meteo elevation API), roads (OpenStreetMap via Overpass).
- Simulated: the nowcast (derived from the historical record plus lead-time noise), camera/sensor depth readings, pump inventory, insurance policies, alerts (shown in-app only, never sent anywhere).
- We have **no** access to NCM radar, RTA cameras or NCEMA systems. Do not write code that scrapes or impersonates them. Model them behind interfaces (`RainSource`, `DepthSensorSource`, `AlertChannel`) with a simulated implementation, so a real one could be swapped in later.
- The flood model is a simplified surrogate, not a hydraulic model. Say so in the README and in the UI's "About" panel.

## Stack
- **Backend:** Python 3.11+, FastAPI, NumPy, Pydantic. Tests with pytest. Dependencies via `uv` or `pip` + `requirements.txt`.
- **Frontend:** React + TypeScript + Vite, MapLibre GL JS for the map, no CSS framework needed beyond plain CSS modules or Tailwind (your choice; keep it small).
- **Basemap:** a free dark vector style that needs no API key (for example CARTO "dark matter" GL style). Verify the URL loads before depending on it; if it fails, fall back to a plain dark background with the OSM road layer we already fetch.
- **LLM for the agent:** provider-agnostic `Planner` interface with two implementations:
  - `LLMPlanner` — uses Azure OpenAI when `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_DEPLOYMENT` are set (Imagine Cup favours Microsoft's stack). Use structured JSON output validated by Pydantic.
  - `RulePlanner` — deterministic fallback used when no keys are set, so the demo always works offline.
- No database. Precomputed data lives in `data/` as JSON / NumPy files. No auth. No Docker required.

## Repository layout
```
mirage/
  CLAUDE.md
  README.md
  backend/
    app/
      main.py            # FastAPI app, CORS, routes
      config.py          # bbox, grid size, thresholds, env vars
      data_fetch.py      # one-off scripts: rainfall, elevation, roads -> data/
      sky.py             # nowcast from historical record + lead-time noise
      ground.py          # flood surrogate model
      sensors.py         # simulated depth sensors (independent index)
      city.py            # Planner interface, RulePlanner, LLMPlanner
      shield.py          # parametric policies + trigger logic
      replay.py          # builds the full timeline once, caches to data/
      models.py          # Pydantic schemas shared by routes
    tests/
  frontend/
    src/
      App.tsx
      map/               # MapLibre setup, layers
      panels/            # Timeline, ActionQueue, AlertCard, Payouts, About
      api.ts
  data/                  # generated; git-ignored except small samples
```

## Domain constants
- Bounding box (Dubai urban core): lat 25.03–25.30, lon 55.10–55.42.
- Grid: about 200 m cells (roughly 150 × 160). Keep it configurable.
- Replay window: 16 April 2024, 00:00–23:00 Gulf Standard Time (UTC+4), hourly.
- "T–0" for the story is the hour of peak modelled flooding; compute it from the model rather than hard-coding 14:20.
- Focus districts for labels and policies: Al Barsha (~25.11, 55.20), Al Quoz (~25.14, 55.24), Business Bay (~25.185, 55.27). Treat coordinates as approximate.

## The four engines — how to implement them simply

### Sky (`sky.py`)
- Fetch hourly precipitation for a coarse lattice of points across the bbox from the Open-Meteo **archive** API for 2024-04-16, then interpolate to the grid. Cache to `data/rain_truth.npy`.
- Note in the README: reanalysis rainfall understates the true peak of this storm. Add a configurable `RAIN_SCALE` factor (default 1.0) and document it.
- A "forecast issued at hour h for hour h+k" = truth at h+k, blurred spatially and perturbed with noise that grows with lead time k (k = 1…6). Seeded RNG so replays are identical.

### Ground (`ground.py`)
- Elevation per grid cell from the Open-Meteo **elevation** API (batch requests; respect its per-request coordinate limit; cache to `data/elevation.npy`).
- Surrogate model per hourly step: add rainfall depth to each cell; route a fraction of water to the lowest of the 8 neighbours (D8), iterate a few sub-steps; subtract a constant drainage capacity per hour; clamp at zero. Output: water depth (cm) per cell per hour.
- Map cell depths onto road segments (OSM highways fetched via Overpass, simplified, cached as GeoJSON). A segment's depth = max depth of the cells it crosses. Tag underpasses/tunnels where OSM has `tunnel=yes` or `layer<0`.
- Risk classes: <10 cm clear, 10–30 cm caution, >30 cm impassable. Configurable.
- "Correction": where a simulated sensor exists, nudge the model cell toward the sensor value (simple weighted blend). Show before/after in the UI as "camera-corrected".

### City (`city.py`)
- Input to the planner: top N at-risk segments and districts for the next 6 hours, pump inventory (mock: 12 pumps, 6 tankers with depot locations), currently active actions.
- Output (Pydantic): a list of `Action {id, type: stage_pump|close_underpass|area_alert|open_road, target, start_hour, reason, evidence: {forecast_depth_cm, lead_hours, confidence}}`.
- `area_alert` text must be area-based (a district), never route-based, under 160 characters, with a concrete time. Example: "Flooding expected in Al Barsha from ~14:20. Avoid underpasses. Delay travel, or leave before 13:30."
- Every action enters a queue with status `proposed`. Only a human click moves it to `approved` or `rejected`. Approved actions change the simulation where sensible (a closed underpass is drawn as closed; a staged pump adds local drainage capacity).
- `LLMPlanner` prompt: give the model the structured situation as JSON, the action schema, and hard rules (max pumps available, no alerts with lead time under 1 hour unless depth is already >30 cm, at most one alert per district per 3 hours). Validate the response; on any validation failure fall back to `RulePlanner` and log it.

### Shield (`shield.py`)
- Mock policies: ~40 small businesses with a district, a location and a trigger (e.g. "≥30 cm measured for ≥1 hour → AED 20,000").
- Trigger reads **only** from `sensors.py` (the independent index), never from the forecast. Emit `PayoutEvent {policy_id, hour, measured_cm, amount_aed}`.

## API (keep it small)
- `GET /api/meta` — bbox, grid shape, hours, districts, disclaimer text.
- `GET /api/replay/{hour}` — rainfall grid summary, forecast for next 6 h (downsampled), road-segment risk classes, sensor readings, active actions, payouts so far.
- `GET /api/roads` — GeoJSON once.
- `POST /api/plan/{hour}` — run the planner, return proposed actions.
- `POST /api/actions/{id}/approve` and `/reject`.
- `POST /api/reset`.
Precompute the baseline timeline at startup (or load the cache) so `/api/replay/{hour}` is instant.

## Frontend requirements
- Full-screen dark map; palette: background `#0B1220`, cyan `#3CCFE0`, amber `#F2A93B`, sand text `#E6ECF3`. Headings in Space Grotesk, labels in JetBrains Mono, body in Inter (load via Google Fonts; fall back gracefully offline).
- Layers: rainfall (soft cyan heat layer), roads coloured by risk class (also vary line width or dash so colour is not the only signal), closed underpasses (amber marker with label), pumps (diamond), payout pins.
- Right-hand panel: big clock ("T–6 h … T–0"), action queue with Approve/Reject buttons and the agent's reason + evidence, the latest approved alert rendered as a phone-style card, payouts list with running total.
- Bottom: timeline scrubber with Play/Pause and speed.
- "About" drawer: what is real, what is simulated, model limits, data credits (Open-Meteo, © OpenStreetMap contributors).
- Must look right at 1920×1080 on a projector and be usable at 1366×768.

## How to work
- Build in the phases listed in the build guide; after each phase, run the tests and the app, and tell me exactly what works and what does not.
- Before using any external API or tile URL, make one real request to confirm the endpoint and response shape; do not assume from memory. If something has changed, adapt and tell me.
- Cache every external fetch in `data/` so the demo runs with no internet.
- Write tests for: grid/interpolation shapes, D8 routing conserving or losing water only through drainage, trigger logic, planner output validation, the "no action without approval" rule.
- Keep functions small and typed. No dead code, no speculative features. If a requirement here is unclear or seems wrong, ask me rather than guessing.
- Never commit secrets. Read keys from environment variables; provide `.env.example`.
