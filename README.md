# Mirage (سراب)

**Prototype — simulated sensors, simplified flood model.**

Mirage is a student demo by Team Everglow for ThinkAI'26 (a Microsoft Imagine Cup preliminary). It replays the Dubai storm of **16 April 2024** hour by hour on one dark map and shows how a rain forecast could be turned into street-level flood action.

It is not an operational system. Nothing in it is connected to any real sensor, camera, alerting service, fleet or insurer.

## What it shows

| Engine | What you see |
|---|---|
| **Sky** | Historical rain for each hour (a reanalysis, see below), and a simulated forecast for the next 6 hours. |
| **Ground** | Modelled flood depth on about 20,000 road segments, corrected each hour by simulated sensor readings. |
| **City** | An agent (rule-based unless Azure OpenAI keys are set) proposes actions: stage a pump, close an underpass, send an area alert. A person clicks Approve or Reject. Nothing takes effect without approval. |
| **Shield** | When a simulated sensor in an insured zone measures enough water, a mock parametric payout fires. |

The timeline runs from T–6 h to T+2 h. T–0 is 16:00 Gulf Standard Time, the hour of heaviest rain in the historical data; it is computed from that data.

## How to run it

You need Python 3.11 or newer and Node.js 20.19 or newer (22.12 or newer on the 22 line; built and tested with Python 3.11 and Node 26).

**1. Backend (first time only)**

```
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     (Windows)
.venv/bin/python -m pip install -r requirements.txt         (macOS / Linux)
```

**2. Data (first time only)**

The `data/` folder is not in the repository. Build it once:

```
cd backend
.venv/Scripts/python -m app.data_fetch all
```

This downloads rainfall, elevation and roads and caches them in `data/`. The elevation service has a free quota of roughly 5,000 points per hour, and the grid needs 6,075, so the fetch pauses and resumes; allow over an hour. After that the demo needs no internet for its data.

**3. Start it**

```
python start.py
```

This builds the frontend if it is missing or out of date, starts one server on port 8000 that serves both the API and the app, and opens http://localhost:8000 in your browser. The first start builds the replay and caches it in `data/timeline.npz`. Press Ctrl+C to stop.

- `python start.py --offline` opens the app with the online basemap switched off (see "Running with no internet").
- `python start.py --no-browser` does not open a browser.

For development with hot reload, run the two servers separately instead: `.venv/Scripts/python -m uvicorn app.main:app --port 8000` in `backend/`, and `npm run dev` in `frontend/` (then open http://localhost:5173).

**4. Tests**

```
cd backend
.venv/Scripts/python -m pytest
```

## Running with no internet

Once `data/` exists and the frontend has been built once, the demo needs no internet:

- All data comes from the `data/` cache. The fonts are bundled with the app.
- The only thing fetched at run time is the CARTO basemap. If it cannot be reached, the app falls back to a plain dark background with our cached road layer and labels for the three focus districts.
- **On venue Wi-Fi that is slow rather than absent, use `python start.py --offline`.** The automatic fallback only triggers when the basemap style cannot be fetched at all within 4 seconds; on a flaky connection the style can load and its tiles then arrive slowly or not at all.

This was checked by blocking every request that was not to localhost and running Demo mode end to end. That check blocks the browser's requests; it is not the same as switching Wi-Fi off, though the backend makes no outside requests unless Azure OpenAI keys are set.

## Using the demo

- **Run demo** (top of the map) resets the replay, plays from T–6 h to T+2 h, asks the agent for a plan each hour and approves it automatically. The whole story takes about 90 to 100 seconds at 1× speed (about 60 at 2×). Every action approved this way is labelled "Auto-approved for demo", on its row and under the alert preview.
- **Sky** (bottom strip) is both the rain chart and the timeline. Each bar is one hour of area-mean rain. Solid bars are the historical data; hatched bars are the simulated forecast issued at the hour on screen. Click a bar to jump to that hour.
- **Play / Pause** and the speed buttons (0.5×, 1×, 2×) step through the hours without touching the agent.
- **Ask agent for a plan** puts proposals in the City queue. Use **Approve** or **Reject** on each card. Decided actions collapse to one line; click one to see the agent's reason again. **Reset** clears everything.
- **Ground** has three views: "Now" (model corrected by the simulated sensors), "Model only", and "Next 6 h" (worst forecast depth and forecast rain).
- **About** lists what is real, what is simulated, and the model's limits.

## The agent and Azure OpenAI

With no keys set, the agent is a deterministic rule-based planner, so the demo always works offline.

To use Azure OpenAI instead, set these environment variables in the terminal that starts the backend (the app does not read a `.env` file by itself; `.env.example` lists the names):

```
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_KEY
AZURE_OPENAI_DEPLOYMENT
```

The LLM's plan is validated against the same rules. If it fails validation, or the call fails, the rule-based planner is used and the screen says so. The LLM path has unit tests but has **not** been run against a live Azure key.

## What is real and what is simulated

**Real**

- Hourly rainfall for 16 April 2024, from the Open-Meteo historical archive. This is a reanalysis: a model-based reconstruction of the weather, not rain-gauge or radar readings.
- Ground elevation, from the Open-Meteo elevation API.
- Roads, tunnels and underpasses, from OpenStreetMap through the Overpass API.

**Simulated**

- **The rain forecast.** It is the historical record, blurred and perturbed with noise that grows with lead time. It is not a real nowcast.
- **All depth sensors.** The 60 sensors read a second run of the flood model driven by the recorded rain, with noise added. No real camera or gauge is involved.
- **Pumps, tankers and depots.** A mock fleet of 12 pumps and 6 tankers.
- **Insurance.** All 40 policies, businesses, triggers, amounts and payouts are invented. No money moves.
- **Alerts.** They are shown inside the app only and are never sent anywhere.

We have no access to NCM radar, RTA cameras or NCEMA systems, and the code does not scrape or imitate them. They sit behind interfaces (`RainSource`, `DepthSensorSource`, `AlertChannel`) with simulated implementations, so a real source could be swapped in later.

## Limits of the model

- **The flood model is a simplified surrogate, not a hydraulic model.** Each hour it adds rain to grid cells of about 200 m, moves part of the water to the lowest of the 8 neighbouring cells, removes a fixed drainage rate, and repeats. It has no pipes, no culverts, no buildings and no flow physics. Its parameters are assumptions; it is not calibrated against observed flooding.
- **Depths are indicative only.** The model piles water into low cells, so deep values are shown as "over 100 cm".
- **Rainfall is understated.** The archive is a reanalysis with cells 7 to 8 km wide. It gives about 106 mm over the area for the day and understates the true peak of this storm. `RAIN_SCALE` (default 1.0, an environment variable) multiplies the record if you want to explore heavier rain; any value other than 1.0 is no longer the recorded data.
- **Elevation is coarse.** It was sampled every 400 m in whole metres and interpolated. It cannot see underpasses, so a 3 m dip is assumed wherever OpenStreetMap tags a tunnel or a negative layer.
- **The "truth" the sensors read is the same model.** Sensor correction therefore shows the mechanism, not real forecast skill.
- **Payouts carry basis risk.** A policy is paid on its nearest gauge, typically about 1 km away, not on the water at the business's door. Readings are hourly snapshots.
- **The confidence score on a proposal is not a probability.** It is a fixed function of lead time (95% minus 8 points per hour of lead), not calibrated against anything.
- **Pumps did not change any payout in our runs.** A full Demo mode run ends with the same AED 380,000 of mock payouts as a run with no actions.
- **Approved actions have simple effects.** A pump adds local drainage; a closure is drawn on the map. Traffic is not modelled.

## Data credits

- Weather and elevation data by [Open-Meteo.com](https://open-meteo.com/), licensed CC BY 4.0.
- Roads © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, licensed ODbL.
- Basemap © [CARTO](https://carto.com/attributions), © OpenStreetMap contributors.
- Fonts: Inter, Space Grotesk and JetBrains Mono (SIL Open Font License), bundled through Fontsource.

## More detail

`PROJECT_LOG.md` is a phase-by-phase record of what was built, what went wrong and what was decided. `CLAUDE.md` is the project spec.
