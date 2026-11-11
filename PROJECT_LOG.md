# Mirage — project log

A plain, step-by-step record of what was done, in order, and where the project stands.
Newest phase is at the bottom. Updated at the end of every phase.

**Where we are right now:** All seven phases are finished, tested, and pushed to GitHub. The screen was redesigned after Phase 6. The demo starts with one command (`python start.py`) and runs with no internet. What is left is listed under "Still open" at the end of Phase 7. A hosted copy runs at https://thinkai-mirage.vercel.app (see "Hosted demo on Vercel" at the bottom).

**Repository:** https://github.com/aaaditt/thinkAI-mirage (branch `main`). Every version is committed and pushed there.

| Phase | What it is | Status |
|---|---|---|
| 0 | Plan and check the outside data services | Done |
| 1 | Download and store the data | Done |
| 2 | Rain forecast, flood model, simulated sensors | Done |
| 3 | API and a bare map | Done |
| 4 | The agent that proposes actions | Done (LLM path untested against a live key) |
| 5 | Insurance payouts | Done |
| 6 | Polish for the demo | Done |
| 6b | Redesign of the screen | Done |
| 7 | Make it safe to present | Done |
| 8 | Hosted demo on Vercel | Done |

---

## Phase 0 — Plan and checks (no code)

**What happened, in order**
1. Read `CLAUDE.md` (the spec) and `MIRAGE_BUILD_GUIDE.md` (the phase-by-phase prompts).
2. Made one real request to each outside service to confirm it works and see what it returns.
3. Wrote a build plan with seven phases. You approved it.

**What the checks found**

| Service | Works? | What we learned |
|---|---|---|
| Open-Meteo archive (past rainfall) | Yes | Gives hourly rain in mm. It does not have a value for every point: it has one value per weather-model cell, each about 7 to 8 km across. |
| Open-Meteo elevation (ground height) | Yes | At most 100 points per request. Heights are mostly whole metres. |
| Overpass (OpenStreetMap roads) | Yes, but flaky | Returns each road as a line with tags such as `tunnel`, `bridge`, `layer`. |
| CARTO dark basemap | Yes | Needs no key, but needs internet for the map tiles. |

---

## Phase 1 — Data

Everything the demo needs from the internet was downloaded once and saved in the `data/` folder. After this, the demo does not need the internet for data.

### The three kinds of data

#### 1. Rainfall (real, historical)
- **What it is:** how many millimetres of rain fell in each hour of 16 April 2024.
- **Where from:** Open-Meteo archive API. No key, no account.
- **How it was taken:** asked for a lattice of 195 points over Dubai and a margin around it. Many points land in the same weather-model cell and return identical numbers, so duplicates were dropped.
- **How much:** 41 distinct cells × 24 hours = 984 numbers.
- **Why that much:** 41 is every distinct cell the source has for this area. Asking for more points would only return copies. This is the full detail available, not a sample.
- **What was done to it:** spread onto our 200 m map grid by inverse-distance weighting (each map cell takes a weighted average of the 41 source cells, nearer ones counting more).
- **Saved as:** `data/rain_points.json` (the raw 41 series, 7 KB) and `data/rain_truth.npy` (the gridded version, 24 × 150 × 161, 2.3 MB).
- **Where it is used:** the Sky engine. It is the "what really fell" record, and the simulated forecast is built from it.
- **The numbers:** 105.8 mm average over the area for the day; 135.9 mm in the wettest cell; heaviest hour is the one ending 16:00 Gulf time (26.8 mm in the wettest cell). Smaller bursts at 04:00 and 13:00 to 14:00.

#### 2. Elevation (real)
- **What it is:** height of the ground above sea level, in metres.
- **Where from:** Open-Meteo elevation API. No key.
- **How it was taken:** in batches of 100 points (the service's limit).
- **How much:** 6,075 points, one every 400 m (a 75 × 81 lattice).
- **Why that much:** the map grid has 24,150 cells at 200 m. The service counts every point against a free quota of roughly 5,000 points per hour and 10,000 per day, so the full grid would have taken two to three days. You chose to sample every second cell instead. The cells in between are filled by straight-line (bilinear) interpolation. Dubai is very flat and the source gives whole metres, so little real detail is lost.
- **Saved as:** `data/elevation.npy` (150 × 161, 94 KB).
- **Where it is used:** the Ground engine. Water flows from higher cells to lower ones.
- **The numbers:** lowest −11 m, highest 70 m, middle value 5.5 m. About 30% of cells are exactly 0 m (the sea).

#### 3. Roads (real)
- **What it is:** the road network as lines, with names and tags.
- **Where from:** OpenStreetMap, through the Overpass API. No key.
- **How it was taken:** one query for the whole area.
- **How much:** 16,242 road segments: motorway, trunk, primary, secondary, tertiary, and their slip roads.
- **Why that much:** these are the roads people drive through the city on. Small residential streets (another 27,217) were left out so the map stays fast. The list of road classes is one line in `config.py` if we want more later.
- **What was done to it:** each line was simplified (points that move the line by less than 5 m removed). Each road was tagged `underpass` if OpenStreetMap says `tunnel=yes` or a negative `layer`, and `bridge` if it is a bridge.
- **Saved as:** `data/roads.geojson` (3.7 MB).
- **Where it is used:** the Ground engine (flood depth per road) and the map.
- **The numbers:** 132 underpasses, 718 bridges.

### What went wrong in Phase 1, and what was done
1. **Overpass failed four times** with a server error (502), then worked. The fetcher waits and retries by itself.
2. **Elevation hit the hourly limit** after about 5,000 points. The first run saved progress only every 20 batches, so about 1,000 fetched points were lost. Fixed: it now saves after every batch and a re-run only asks for what is missing.
3. **Decision (yours):** fetch elevation at 400 m instead of 200 m.
4. **A background download was stopped** by Claude Code because the laptop was low on memory. Nothing was lost; it was resumed later.
5. **Elevation hit the daily limit** with 35 points left (a thin strip on the north-east edge). A temporary stand-in was built so work could continue.
6. **You changed your IP address** and the last 35 points were fetched. Elevation is now complete and fully real. The temporary stand-in code was deleted.

### Files written in Phase 1
- `backend/app/config.py` — the map area, grid size, file locations, settings.
- `backend/app/data_fetch.py` — the three downloaders and a `report` command.
- `backend/scripts/preview_data.py` — draws check pictures into `data/previews/`.
- `backend/tests/test_data_layer.py` — 9 tests, all passing.

### Does it look like Dubai?
Yes. In `data/previews/elevation.png` you can see the diagonal coastline, Palm Jumeirah, the World islands, Dubai Creek and the desert rising to the south-east.

---

## Three issues carried from Phase 1 into Phase 2

These were spotted in the Phase 1 pictures. This is how each is handled.

### 1. Sea cells
- **Problem:** about 30% of the grid is open sea at 0 m. If rain is added there like anywhere else, the model would report the Gulf as "flooded".
- **Handling:** any cell at or below 0 m is treated as open water. Water that reaches it leaves the model and is counted as "lost to open water". Its flood depth is always zero.

### 2. Deep pits near Business Bay and Ras Al Khor
- **Problem:** 51 cells are below −3 m, down to −11 m. Left alone they would swallow water and show absurd depths.
- **What they are:** their positions match real water bodies: Business Bay lagoon and the Dubai Water Canal, Ras Al Khor lagoon, and Dubai Marina. They are not errors to be flooded; they are water.
- **Handling:** the same rule as the sea covers them (at or below 0 m = open water). This is a change from my first idea, which was to leave them and watch. The single rule is simpler and matches what they are.

### 3. Bridges
- **Problem:** 718 road segments are bridges. A bridge crosses above the ground, so it should not take the flood depth of the ground underneath it.
- **Handling:** bridge segments always get depth 0. This is an assumption (the deck stays above the water), and it is stated in the model limits.

---

## Phase 2 — Rain forecast, flood model, sensors

No new data was downloaded in this phase. Everything here is computed from the three Phase 1 files.

### What was built, in order
1. **`backend/app/sky.py` — the rain forecast.** It is simulated, not a weather model. A forecast made at hour *h* for *k* hours ahead is the real rain for that hour, blurred and multiplied by a random error pattern. Blur and error both grow with *k*. The randomness is seeded, so every replay gives the same numbers.
2. **`backend/app/ground.py` — the flood model.** For each hour: add the rain; six times over, let each cell pass water to its lowest neighbour; remove 0.5 cm for drainage; never go below zero. It also works out which grid cells each road crosses and gives each road the depth of its deepest cell.
3. **`backend/app/sensors.py` — simulated sensors.** 60 sensors on road cells, 20 of them at underpasses. Each reading is the simulated depth at that spot plus measurement noise.
4. **`backend/scripts/run_simulation.py`** — runs the 24 hours and prints the report below.
5. **Tests:** 34 in total across the project, all passing. They cover: the forecast is repeatable and gets worse with lead time; water routing never creates or destroys water; water is lost only to drainage and open water; depth never goes negative; the sensor-correction blend; road-to-cell mapping; risk classes.

### How the three carried-over issues were handled
All three were done as written in the section above: open water at or below 0 m is a sink (7,306 of 24,150 cells), the pits are covered by the same rule, and bridges always read 0.

### Settings used (all are assumptions, none were tuned)
| Setting | Value | Meaning |
|---|---|---|
| `RAIN_SCALE` | 1.0 | Rain used exactly as recorded |
| `DRAINAGE_CM_PER_HOUR` | 0.5 | Water removed from each land cell per hour |
| `ROUTING_SUBSTEPS` | 6 | Water can travel up to 6 cells (1.2 km) per hour |
| `FLOW_FRACTION` | 0.5 | Share of a cell's water that may move per sub-step |
| Risk classes | under 10 cm clear, 10 to 30 caution, over 30 impassable | From the spec |

### Results of the 24-hour run
- **Water accounting is exact.** Largest error 3 × 10⁻¹¹ cm. Rain in = drained + lost to open water + still on the ground, every hour.
- **Peak flooding hour (T–0): 20:00.** Not 14:20 as in the pitch, and later than the rain peak (16:00), because water keeps collecting after the rain eases.
- **Road segments impassable:** 0 at midnight, 510 by 06:00, 1,086 at 14:00 (T–6), 1,643 at 18:00 (T–2), 1,816 at 20:00 (T–0), 1,808 at 23:00.
- **Flooded land cells at T–0:** 1,679 of 16,844. Middle depth 49 cm; one in ten is over 116 cm; 29 cells are over 200 cm; the deepest is about 5 m.
- **Worst roads at T–0:** Baghdad Street (318 cm), then roads near 25.09, 55.33 and 1 Street near 25.23, 55.35 (261 cm).
- **Underpasses at T–0:** 110 clear, 6 caution, 16 impassable, of 132.
- **Sensors at T–0:** 2 of 60 read above 30 cm.
- **Forecast error from T–6:** 0.2 mm average at 1 hour ahead, rising to 1.0 to 2.7 mm at 2 to 6 hours ahead.
- **RAIN_SCALE:** no change proposed. Plenty floods at 1.0.

Pictures: `data/previews/flood_Tminus_6h.png`, `flood_Tminus_2h.png`, `flood_Tminus_0.png`.

### Honest verdict: is it plausible?
**Plausible**
- The timing shape. Flooding starts in the early morning, builds through the afternoon, and does not drain away by night. That matches how the real day went in broad terms.
- The typical depth. A middle value of about 50 cm in flooded spots is believable for this storm.

**Not plausible**
- **The deepest spots.** Depths of 2 to 5 m are not real. The elevation data is in whole metres and sampled every 400 m, which creates artificial bowls about a metre deep or more. The model fills them. These are artefacts of the data, not predictions.
- **The pattern is speckled.** Flooding appears as scattered dots across the whole city instead of following known trouble spots. Same cause.
- **Underpasses barely flood.** In reality underpasses flood first. The elevation data shows the ground surface, not the dip of an underpass, so the model does not know they are low.
- **Nothing drains.** Raising drainage eightfold (0.5 to 4 cm/h) only cut impassable roads at T–0 from 1,816 to 933 and the deepest cell from 498 to 401 cm. Drainage is not the lever; the bowls are.

### Decisions that were waiting for you (answered: see Phase 2b)
1. **Underpasses.** Proposal: lower each underpass's cells by an assumed depth (for example 3 m) so water collects there. This is an assumption, would be labelled as one, and makes the "close the underpass" story work. Without it, the agent has few underpasses worth closing.
2. **The 2 to 5 m depths.** Proposal: leave the model alone, show roads by risk class as planned, and display depths above 100 cm as "over 100 cm". Alternative: smooth the elevation to remove the artificial bowls, which changes every result.
3. **The story timing.** T–0 is 20:00, so the demo window (T–6 to T+2) is 14:00 to 22:00, and at T–6 about 60% of the eventual flooding is already there. The demo script's "8 a.m., before the rain" opening will not match. Either the script is reworded, or T–0 is redefined (for example, the hour flooding rises fastest, which would be nearer 16:00 to 17:00).

Also to watch in Phase 5: only 2 of 60 sensors read above 30 cm at T–0, so few payouts would fire unless sensors are placed where policies are.

---

## Phase 2b — Your three decisions, applied

You said to go ahead with all three recommendations. This is what was done, including two things that did not go as first described.

### 1. Underpasses are now dips
- Every land cell crossed by an underpass is lowered by an **assumed 3 m** (`UNDERPASS_DEPTH_M`). 142 cells were lowered.
- The open-water rule still uses the original heights, so a lowered underpass is never mistaken for sea.
- **Side effect found and fixed:** ordinary roads that share a grid cell with an underpass were picking up the dip's depth and showing as flooded. Now an underpass sees the full depth in the dip, and a surface road in the same cell floods only once the dip is full.
- **Known limit:** a grid cell is 200 m × 200 m, far bigger than a real underpass, so each dip holds too much water and takes some from its surroundings. Total impassable roads at 20:00 fell from 1,816 to 1,604 for this reason.

### 2. Very deep values are shown as "over 100 cm"
- The model itself is unchanged. A display rule (`DISPLAY_DEPTH_CAP_CM = 100`) reports anything deeper as "over 100 cm", because depths beyond that come from artificial bowls in the elevation data.

### 3. T–0 is redefined
- **First attempt (what I recommended):** T–0 = the hour in which the most roads become impassable. I said this would give 16:00. It did not. The storm came in three waves (04:00, 13:00, 16:00) and, once underpasses were added, the 04:00 wave had the largest one-hour jump. T–0 at 04:00 leaves no room for a T–6 lead-in.
- **What is used now:** T–0 = the hour of heaviest recorded rain averaged over the area, limited to hours that leave room for T–6 h and T+2 h. This gives **16:00**. It is computed from the data, not typed in. It is a storytelling anchor, not a model prediction, and I chose this rule partly because it gives the window you approved. It is one small function (`story_zero_hour` in `sky.py`) if you want a different rule.
- `CLAUDE.md` was updated to state the new definition.

### Results after the changes
The demo window is now **10:00 to 18:00** (T–6 to T+2).

| Moment | Hour | Roads impassable | Underpasses impassable (of 132) |
|---|---|---|---|
| T–6 | 10:00 | 500 | 43 |
| T–2 | 14:00 | 929 | 78 |
| T–0 | 16:00 | 1,211 | 86 |
| T+2 | 18:00 | 1,476 | 90 |

- Flooded land cells at T–0: 1,362, middle depth 37 cm. 13 cells are still over 200 cm (deepest 431 cm): the artificial-bowl problem remains and is only hidden by the display rule.
- Sensors reading above 30 cm at T–0: 11 of 60 (was 2), because 20 sensors sit at underpasses.
- Flooding roughly doubles between T–6 and T–0, and 43 more underpasses go under in that time. That is the material the agent will work with in Phase 4.
- Tests: 38, all passing.

### Still true, still a limit
- Morning flooding from the 04:00 wave is already on the ground at T–6 (500 roads). The demo cannot honestly open on a dry city.
- The speckled pattern and the handful of extreme depths are unchanged.

---

## Phase 3 — API and a bare map

No new data was downloaded. This phase turns the Phase 2 engines into a web app.

### What was built, in order
1. **`backend/app/replay.py` — the timeline.** Runs the whole day once and saves the result to `data/timeline.npz` (2.7 MB). It takes about 6 seconds the first time; after that it loads from the file. It is rebuilt automatically if any setting or data file changes.
2. **`backend/app/models.py`** — the shapes of the data the API sends.
3. **`backend/app/main.py` — the API.** Three addresses:
   - `/api/meta`: map area, grid size, the story window, districts, the disclaimer text.
   - `/api/roads`: the road lines, sent once (about 500 KB compressed).
   - `/api/replay/{hour}`: everything for one hour. Answers in about 10 milliseconds.
4. **`frontend/`** — a React + TypeScript app built with Vite, with a MapLibre map.

### Two flood runs, kept apart
- **"What really happened":** the flood model driven by the recorded rain. Nothing on screen reads this directly. Only the simulated sensors do. It is still the simplified model; there is no real flood-depth data anywhere in this project.
- **"What the system thinks":** the flood model driven by its own 1-hour rain forecast, then pulled toward the sensor readings each hour. This is what the map shows.
- From the second one, the model is also run 6 hours ahead on forecast rain, every hour, to give "worst in the next 6 hours".

### What you see on screen
- A dark map of Dubai (CARTO dark basemap; if it cannot be reached, a plain dark background with our own roads).
- Roads coloured **and** thickened by risk: thin blue-grey = clear, medium amber = caution, thick red = impassable. Thickness is there so colour is not the only signal.
- Top left: the name and the permanent badge "Prototype — simulated sensors, simplified flood model".
- Right: the clock (T–6 h … T+2 h), three views (now sensor-corrected / now model only / worst in next 6 h), and counts per class.
- Bottom: the timeline scrubber from T–6 h (10:00) to T+2 h (18:00).

### Problems found on the first screenshot, and what was done
1. **Whole roads lit up from one wet spot.** A road was one OpenStreetMap "way", and some are kilometres long. One flooded cell painted the entire way red. Fix: every road longer than 400 m is cut into equal pieces of at most 400 m (`MAX_SEGMENT_M`). Segments went from 16,242 to **20,577**; the longest now crosses 5 grid cells instead of 93. Underpass segments went from 132 to 149 for the same reason.
2. **The map credit overlapped the timeline.** Moved above it.
3. **Newer library versions than expected** (MapLibre 6, TypeScript 7, Vite 8). MapLibre 6 changed how it is imported and how its background worker is loaded; the code was written against the installed version after checking it.

### Numbers now (after the road split)
| Moment | Hour | Impassable | Caution | Forecast impassable within 6 h |
|---|---|---|---|---|
| T–6 | 10:00 | 598 | 401 | 1,512 |
| T–2 | 14:00 | 1,122 | 710 | 1,980 |
| T–0 | 16:00 | 1,422 | 925 | 2,082 |
| T+2 | 18:00 | 1,784 | 1,020 | 2,085 |

Of 20,577 segments. Sensors reading above 30 cm at T–0: 14 of 60.

### Screenshots
`data/previews/app_T-6h_1920.png` and `data/previews/app_T-0_1920.png` (1920 × 1080). The `data/` folder is not uploaded to GitHub, so these are on this laptop only.

### Tests
54 backend tests, all passing. New ones cover: timeline shapes, no negative or missing values, bridges staying dry, the API answers, road ids matching risk positions, and road splitting. The frontend passes its type check. There are no automated frontend tests yet.

### Known limits after Phase 3
- **The sensor correction is almost invisible.** Sensors cover 60 of 16,844 land cells, so "sensor-corrected" and "model only" give nearly the same road counts. The mechanism works; its effect on the map is tiny.
- **Roads were slow to appear once.** On one page load the coloured roads were still missing after 7 seconds; on reload they were there. Not yet investigated.
- **Not on screen yet:** rainfall layer, sensors, Play button, About panel. The data for rainfall and sensors is already in the API; drawing them is Phase 6.
- **The laptop ran low on memory** and Claude Code stopped both servers after the screenshots were taken. Nothing was lost.

### How to run it
Two terminals:
```
cd backend
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```
```
cd frontend
npm run dev
```
Then open http://localhost:5173

---

## Phase 4 — City: the agent and the approval queue

No new data was downloaded. The pump fleet, depots and alerts are all invented for the demo.

### What was built, in order
1. **`backend/app/city.py`** — the whole City engine:
   - **Sites.** Road pieces are grouped back into whole roads. Underpass carriageways that share a grid cell are merged, so one physical underpass is one site. There are 68 underpass sites.
   - **Situation.** What the agent is given each time: the 10 most urgent underpasses and 5 deepest roads for the next 6 hours, an outlook for each of the three districts, the pump stock, and every action so far.
   - **`RulePlanner`.** A fixed set of rules. Works with no internet and no key.
   - **`LLMPlanner`.** Sends the situation, the answer format and the hard rules to Azure OpenAI and reads back a plan.
   - **`validate_plan`.** The hard rules, checked on every plan from either planner.
   - **`Session`.** Holds the queue of actions and applies human decisions.
2. **Four new API addresses:** ask for a plan, approve an action, reject an action, reset.
3. **Frontend:** an "Agent proposals" panel with the reason, the evidence and Approve / Reject buttons, plus map markers for approved closures ("CLOSED") and staged pumps (a diamond labelled "PUMP").

### The rule: nothing happens without approval
- A planner can only produce proposals. Each one enters the queue as `proposed`.
- The simulation is only ever handed the list of **approved** actions. Proposed and rejected ones never reach it.
- A test proposes actions, then rejects them, and checks the entire timeline is identical to the baseline, byte for byte, with no closures, no alerts and no pumps used.
- A decision is final. Approving twice, or approving a pump when none are left, is refused.

### What each approved action does
| Action | Effect |
|---|---|
| Stage pump | Adds drainage at that underpass from its start hour (assumed 2.5 cm per hour over one grid cell, about 1,000 m³ per hour). The flood simulation is re-run. |
| Close underpass | Shown as "CLOSED" on the map from its start hour. Does not change the water. |
| Area alert | The text is stored in the app and attached to that hour. It is never sent anywhere. |
| Reopen road | Ends a closure. |

### The hard rules checked on every plan
- Targets must come from the situation (no invented places).
- Only underpasses can be closed.
- No more pumps than are available.
- An alert must name its district, give a clock time, be at most 160 characters, and never mention a road or a route.
- No alert with under 1 hour of lead time unless the district is already flooded.
- At most one alert per district per 3 hours.
- Nothing may start in the past.

If the LLM's plan breaks any rule, or the reply is not valid, or the network fails, the whole plan is thrown away, the reason is logged, and `RulePlanner` answers instead.

### What the rule planner proposed on the real replay
No Azure key is set on this laptop, so all of this is from `RulePlanner`.

**T–6 h (10:00)** — 10 proposals
- Close 4 underpasses from 11:00, each forecast to pass 30 cm within 2 hours. One is on Al Ittihad Road; three are unnamed.
- Stage 3 pumps from 11:00 at three of them.
- Alerts for Al Barsha ("from ~11:00"), Al Quoz ("from ~13:00") and Business Bay ("from ~14:00").

**T–4 h (12:00)** — 4 proposals
- Close 4 more underpasses now: Zaa'beel Palace Street, Al Asayel Street (Business Bay), Airport Road, Al Ittihad Road. Each floods within 1 hour, which is too late to stage a pump.
- No alerts: each district had one less than 3 hours earlier.

**T–2 h (14:00)** — 10 proposals
- Close 4 underpasses (3 from 15:00, 1 from 17:00), including Al Badaa' Street and Sheikh Zayed Road.
- Stage 3 pumps from 15:00.
- A second alert for each district, "from ~16:00".

Example alert, 99 characters: *"Flooding expected in Al Barsha from ~16:00. Avoid underpasses. Delay travel, or leave before 15:00."*

### How much the pumps help (be honest about this)
Not much. At the pumped underpasses the modelled depth at T–0 dropped by 2 to 15 cm, for example 112 cm to 97 cm. No pumped underpass stayed passable, and the city-wide count of impassable roads at T–0 did not change (1,422 either way). One assumed pump is small next to the water collecting in a 200 m grid cell. In this prototype the pumps show the mechanism, not a meaningful benefit.

### Problems found and fixed in this phase
1. **Duplicate underpasses.** Each carriageway is a separate OpenStreetMap way, so the planner proposed two closures and two pumps for one underpass. Fixed by merging underpass ways that share a grid cell.
2. **Slow batch approvals.** Each pump approval re-ran the simulation (about 4 seconds). The re-run now happens on the next read, so several approvals in a row cost one re-run when driven through the API.
3. **Buttons re-enabled too early (found in the browser test).** After approving a pump, the buttons came back before the refreshed data arrived, so the same card could be clicked again and the server refused with "already approved". The server's guard held and nothing was applied twice. The buttons now stay disabled until the refreshed data is on screen.
4. **A leftover dev server.** When Claude Code stopped the servers for low memory earlier, the frontend's Node process survived and kept its port. It was found and stopped.

### Tests
100 backend tests, all passing. 46 are new for this phase: planner behaviour, every hard rule, the LLM fallback (bad text, wrong format, rule-breaking, network failure), the approval gate, and the API.

### Not verified, and known limits
- **The Azure OpenAI path has never talked to a real Azure endpoint.** There is no key here. It is tested with stand-in replies only. The first run with a real key may need fixes.
- **Approving pumps one by one in the screen is slow:** about 4 seconds each, because each click reloads the hour.
- **Most underpasses are unnamed** in OpenStreetMap, so they show as "Unnamed underpass (lat, lon)".
- **Two pump markers can sit on top of each other** when their underpasses are close.
- **"Reopen road" never fires in this replay**, because almost nothing drains during the day. It is tested with made-up situations.
- **Tankers** exist only as numbers in the mock inventory. Nothing uses them.
- **The confidence figure** is a simple formula from the lead time (95% minus 8 points per hour), not a measured skill score.

### Screenshots
`data/previews/app_agent_proposed_1920.png` (ten proposals, map unchanged) and `data/previews/app_agent_approved_T-0_1920.png` (after approving, at T–0, with CLOSED and PUMP markers). On this laptop only.

---

## Phase 5 — Shield: parametric payouts

No new data was downloaded. Every policy, business and amount is invented.

### What was built, in order
1. **Sensor placement was changed first** (`backend/app/sensors.py`). See "The problem found" below.
2. **`backend/app/shield.py`** — mock policies and the payout trigger.
3. **API:** `/api/meta` now lists the 40 mock policies; each hour's frame carries the payouts fired so far and the running total.
4. **Frontend:** a "Shield payouts" panel with the running total and a list, and an "AED" pin on the map at each paid business.

### The problem found, and the decision made
- The 60 sensors from Phase 2 were placed at underpasses and at random road cells across the whole city. Almost none were in the three insured districts: zero within 2.5 km of Al Barsha, and the few near Al Quoz and Business Bay stayed dry.
- With that layout Shield would have paid almost nothing, for a reason that has nothing to do with flooding.
- **Decision:** a parametric product needs its gauge inside the insured zone. So 24 of the 60 sensors (8 per district) are now placed on road cells at **terrain low points** inside each district.
- **Why this is not cheating:** the low points are chosen from elevation only (how far a cell sits below its neighbours). Flood results are never used to choose them. It mirrors how real gauges are sited: where water collects.
- The sensor split is now 20 at underpasses, 24 district gauges, 16 other roads. Total still 60.
- Side effect: the sensor correction now touches different cells, so road counts shifted slightly (for example 1,417 impassable at T–0, was 1,422).

### How a policy works
- 40 mock small businesses, spread over the three districts (14 / 13 / 13), each placed at random within 1.5 km of its district centre.
- Each policy is tied to the **nearest gauge in its own district**. The distance is recorded: median about 1 km, largest about 1.8 km. That gap is real "basis risk": the business is paid on what the gauge reads, not on the water at its own door.
- Three invented tiers:

| Tier | Trigger | Payout |
|---|---|---|
| Basic | 30 cm or more in 1 hourly reading | AED 20,000 |
| Sustained | 30 cm or more in 2 hourly readings in a row | AED 30,000 |
| Severe | 50 cm or more in 1 hourly reading | AED 50,000 |

- Each policy pays at most once, at the first hour its trigger is met.

### The rule: payouts read sensors only
- `shield.py` is handed a table of sensor readings and nothing else.
- It does not import the forecast or the flood model at all. A test reads the file's imports and fails if that ever changes.
- So a payout cannot be caused by a prediction, only by a (simulated) measurement.

### Payout events for the full replay
**10 of 40 policies paid, AED 380,000 in total.**

| Hour | Policy | Tier | Measured | Gauge | Payout |
|---|---|---|---|---|---|
| 03:00 | Al Quoz Auto Garage 08 | Severe | 52 cm | S031 | AED 50,000 |
| 03:00 | Al Quoz Cafe 14 | Severe | 52 cm | S031 | AED 50,000 |
| 03:00 | Al Quoz Grocery 26 | Severe | 52 cm | S031 | AED 50,000 |
| 03:00 | Al Barsha Phone Repair 31 | Basic | 42 cm | S023 | AED 20,000 |
| 03:00 | Al Quoz Cafe 38 | Severe | 52 cm | S031 | AED 50,000 |
| 04:00 | Al Quoz Auto Garage 11 | Sustained | 64 cm | S031 | AED 30,000 |
| 04:00 | Al Barsha Warehouse 25 | Sustained | 68 cm | S023 | AED 30,000 |
| 15:00 (T–1) | Al Quoz Bakery 20 | Sustained | 40 cm | S029 | AED 30,000 |
| 16:00 (T–0) | Business Bay Auto Garage 03 | Basic | 52 cm | S038 | AED 20,000 |
| 16:00 (T–0) | Business Bay Grocery 24 | Severe | 52 cm | S038 | AED 50,000 |

Running total: AED 280,000 already paid when the demo window opens at 10:00; AED 380,000 from 16:00 onward.

### What this means for the demo
- **Seven payouts happen before the demo starts** (03:00 to 04:00, the early-morning wave). At T–6 the panel already shows AED 280,000.
- **Three happen inside the window**, two of them exactly at T–0. That is the "sensors confirm the depth, payouts fire" moment.
- **30 policies never pay.** Their gauge stayed under the trigger. Only 13 of the 24 district gauges are the nearest gauge to any policy, and several of those stay dry.

### Problems found and fixed
1. **Sensors not in the insured districts** (above).
2. **Map pins drawn as full-width bars** (found in the browser check). The pin's style overrode the positioning MapLibre applies to markers. Fixed by styling an inner element.

### Tests
119 backend tests, all passing. 19 are new: the trigger at, below and above the threshold; "sustained" needing consecutive hours; one payout per policy; each policy reading only its own gauge; policies indexed to the nearest gauge in their own district; the imports check; and the API totals.

### Known limits
- **Readings are hourly snapshots.** "30 cm for 1 hour" means one hourly reading at or above 30 cm. There is nothing finer than an hour in this replay.
- **Policies sharing a gauge pay together.** Four Al Quoz policies paid at the same moment off gauge S031. That is how an index product behaves, but it looks clustered.
- **Pins can overlap** where paid businesses are close.
- **The right-hand panel is getting crowded.** Payouts and proposals now share it. Phase 6 will sort out the layout, including at 1366 × 768.

### Screenshot
`data/previews/app_shield_T-0_1920.png` (on this laptop only).

---

## Phase 6 — Polish for the demo

No new data was downloaded. This phase is almost all frontend, plus one small backend change.

### What was built, in order
1. **Who approved is now recorded** (backend). Each action carries `decided_by`: `operator` or `demo_auto`. The approve route takes `?by=demo_auto`, which only Demo mode sends. Anything else is refused.
2. **New layout.** The right-hand panel was too crowded, so the screen now has three areas around the map:
   - **Left column:** Sky (rain now and forecast), the phone-style alert card, Shield payouts.
   - **Right panel:** the big T-minus clock, the road view switch, the legend, the agent's queue.
   - **Bottom bar:** Play/Pause, speed, and the timeline.
3. **Rainfall layer** on the map: a soft cyan haze, one pixel per block of grid cells, stretched over the study area.
4. **Sensors on the map:** 60 small rings. A ring fills amber or red and grows as its reading rises. Hovering shows the reading.
5. **Sky card:** seven bars, "now" plus +1 h to +6 h, showing area-mean rain. Clicking a bar puts that rain field on the map. Forecast bars are hatched so "simulated" does not depend on colour.
6. **Phone-style alert card:** shows the latest approved area alert, with "In-app preview only. Nothing is sent to any phone."
7. **Play / Pause with speed** (0.5×, 1×, 2×). At 1× each hour stays for 2.5 seconds. Play stops at T+2 h.
8. **Demo mode** button (see below).
9. **About drawer:** what is real, what is simulated, the model's limits, the human-in-the-loop rule, data credits.
10. **README.md** written: what it is, how to run it, real vs simulated, limits, credits.

### How Demo mode works
- It resets the replay, then for each hour from T–6 h to T+2 h: shows the hour, asks the agent for a plan, pauses so the proposals can be read, approves them one by one, then reloads the map.
- Every approval it makes is marked on the server as `demo_auto` and shown as **"Auto-approved for demo"** in an amber dashed box on the card. The alert card says the same. A banner in the queue says no operator is deciding.
- While it runs, the Approve/Reject buttons, Play and the scrubber are locked. "Stop demo" ends it at once.
- **Measured run time: about 95 seconds at 1×** (the target was about 90). Each hour is budgeted 10 seconds; hours with many approvals run a little over. At 2× it took 59 seconds.
- In one full run it approved 52 actions. Payouts ended at AED 380,000, the same as with no actions: the pumps did not stop any payout trigger.

### Problems found and fixed
1. **The map did not refit when the window changed size.** Found when the browser went from 1366 × 768 to 1920 × 1080 and the city stayed small. This would have happened when going full screen on the projector. The map now refits on every resize.
2. **A frame could arrive out of order** if two requests for different hours overlapped. Only the newest request may now update the screen.
3. **The rain layer hid the roads at the peak hour.** Its opacity was lowered.

### Layout check
Checked in a real browser at both sizes. At 1366 × 768 everything fits with no page scroll; the payout list and the queue scroll inside their own cards, and the payout list shows about two entries at a time.

### Tests
122 backend tests, all passing. 3 are new: an operator approval is recorded as `operator`; a Demo mode approval is recorded as `demo_auto`; an unknown decider is refused and the action stays proposed. The frontend passes its type check and production build. There are no automated frontend tests; the screen was checked by running it.

### Known limits
- **The rain haze is a hard-edged rectangle.** That is the edge of the study area, not of the rain. The legend says "study area".
- **The rain looks almost uniform.** The source has cells 7 to 8 km wide, so there is little spatial detail to show.
- **After a full demo the map is busy:** dozens of CLOSED and PUMP markers, some overlapping, more so at 1366 × 768.
- **Changing speed during Demo mode is locked.** Pick the speed before starting.
- **The basemap and fonts still need internet.** Offline behaviour is Phase 7.
- **The LLM planner is still untested against a live Azure key.**

### Screenshots
On this laptop only, in `data/previews/`: `app_phase6_T-0_1920.png`, `app_phase6_T-0_1366.png`, `app_phase6_about_1366.png`, and `app_demo_T-0_1920.png` (Demo mode running).

---

## Phase 6b — Redesign of the screen

You asked for a proper design pass before Phase 7. The palette and the three typefaces stayed as the spec sets them; the structure changed.

### What was wrong before
- Six identical floating cards competed with each other. Nothing led.
- The timeline, the spine of the story, was a default browser slider.
- The map was buried under large CLOSED and PUMP text tags.
- After a demo the queue was 52 tall cards with two visible.

### What changed
1. **The storm is the timeline.** The bottom strip (Sky) is a rain chart with one bar per hour. Hours up to the one on screen are solid (historical data); the next six are hatched (the simulated forecast issued at that hour). As the replay plays, hatched bars become solid. Clicking a bar jumps to that hour. This replaced both the slider and the old Sky card.
2. **One loud element: the countdown.** A very large T-minus clock sits directly on the map, over the sea, with no box.
3. **Docked rails instead of floating cards.** Left: brand and the Prototype badge, Ground, the alert preview, Shield. Right: the City queue. Sections are split by thin lines and named after their engine.
4. **Small shape markers.** Square = closed underpass, diamond = pump, teardrop = mock payout, ring = sensor. The same shapes appear in the legend and on the queue rows. Names show on hover.
5. **A dashed frame marks the study area,** so the edge of the rain haze reads as the edge of our data, not the edge of the storm.
6. **A scannable queue.** Proposals waiting for a decision are full cards. Decided ones collapse to one line and open on click.
7. **One view switch** (Now / Model only / Next 6 h) changes the roads and the rain together. The old "click a forecast bar to show that rain on the map" control was removed; "Next 6 h" shows the peak forecast rain instead.

### Backend change
`/api/meta` now also returns the area-mean historical rain for each hour (24 numbers), which the rain chart needs. One assertion added to the meta test.

### Problem found and fixed
- **The map was fitted into the wrong part of the screen.** The map sat under the rails and relied on uneven padding to centre the city; the offset was not honoured. The map element now sits between the rails, with even padding.

### Something to be aware of
During two test runs Demo mode stopped early, and in one of them two approvals were recorded as "operator". Only a click on Approve can produce that, and the test browser window was open on this laptop, so the likely cause is clicks in that window. Three later runs (two online, one with the network blocked) all finished at T+2 with no errors. The cause was not proven, so if Demo mode ever stops by itself, that needs another look.

---

## Phase 7 — Make it safe to present

### 1. Runs with no internet
- **Fonts are now bundled** with the app (Fontsource packages). Google Fonts is no longer contacted.
- **One server.** The backend now serves the built frontend too, so the demo is one process on port 8000. This also uses less memory; the laptop had stopped both servers for low memory during this phase.
- **Basemap fallback.** If the CARTO basemap cannot be fetched, the app shows a plain dark background with our cached roads, and labels for the three focus districts.
- **`?offline` switch** (or `python start.py --offline`) skips the basemap on purpose, for venue Wi-Fi that is slow rather than absent.
- **How it was checked:** every browser request not to localhost was blocked, then Demo mode was run end to end. It finished at T+2 with 52 auto-approvals and no errors. The only outside request attempted was the basemap. Screenshot: `data/previews/app_offline_T-0_1920.png`.
- **Limit of that check:** it blocks the browser's requests. It is not the same as switching Wi-Fi off. The backend makes no outside requests unless Azure keys are set, but it was not run with the network adapter disabled.

### 2. One command
`python start.py` checks the setup, builds the frontend if it is missing or older than the source, starts the server and opens the browser. Tested with `--no-browser`; the automatic browser opening was not exercised.

### 3. Tests
124 backend tests, all passing. 2 are new: the built frontend is served next to the API; the API still works when the frontend was never built. The frontend type check and production build pass.

### 4. The sceptical-judge review: wording that overstated, and the fix
| Where | It said | Problem | Now says |
|---|---|---|---|
| Sky strip, clock, About, README | "Recorded" rain | The Open-Meteo archive is a reanalysis: a model reconstruction, not gauge or radar readings | "Historical (reanalysis)", explained in About and the README |
| Ground heading | "Flood depth on roads" | It is model output, not measured depth | "Modelled flood depth on roads" |
| Shield heading and legend | "Parametric payouts", "Payout fired" | Reads as real money | "Mock parametric payouts", "Mock payout" |
| Proposal cards | "63% confidence" | A fixed function of lead time, not a calibrated probability | "confidence score 63%", explained in About and the README |
| About | Sensor correction shown without caveat | The "truth" the sensors read is the same model | Added to About (it was already in the README) |
| About, README | "The agent" | Without Azure keys it is a fixed set of rules, and the LLM path has never run against a live key | Said plainly in About and the README |
| README | Nothing on whether actions help | Pumps did not change any payout in our runs | Stated under limits |

### Still open
- **The LLM planner has never been run against a live Azure OpenAI key.**
- **No automated frontend tests.** The screen is checked by running it.
- **Not tested with the network adapter actually off,** only with browser requests blocked.
- **At 1366 × 768 the left rail scrolls slightly** so that a few payouts are always visible.
- **Older sections of this log** still describe the Phase 6 layout and the two-server way of running; the README is the current reference.

### Screenshots
On this laptop only, in `data/previews/`: `app_final_T-6h_1920.png`, `app_final_demo_T-2h_1920.png`, `app_final_T-0_1920.png`, `app_final_T-0_1366.png`, `app_final_about_1366.png`, `app_offline_T-0_1920.png`.

---

## Phase 8 — Hosted demo on Vercel

**Live link: https://thinkai-mirage.vercel.app**

### What was done, in order
1. **Entry point and config.** `api/index.py` exposes the FastAPI app as one Vercel function. `vercel.json` builds the frontend as static files and sends `/api/*` to the function. A root `requirements.txt` lists only what the function needs (numpy, fastapi, pydantic).
2. **The data cache is uploaded with the deployment.** `data/` is not in git, so `.vercelignore` is set to upload it anyway (about 9 MB).
3. **The replay cache was made portable.** It used to be tied to each data file's modified time, which changes when files are copied to a server, so the hosted copy would have rebuilt the replay on every cold start and then failed to save it to a read-only disk. It is now tied to the files' contents, and a failed save is logged and ignored.
4. **Deployed and checked.** The site, `/api/meta`, `/api/replay/16` and `/api/roads` all answered. A full Demo mode run on the live site finished at T+2 with 52 auto-approvals, AED 380,000 of mock payouts and no failed requests. It took 83 seconds at 2x, against about 60 on the laptop.
5. **README rewritten** with the live link, two screenshots (in `docs/`), a two-minute walkthrough, how it works, the API, and a section on the hosted copy.

### Limits of the hosted copy
- **Everyone shares one action queue.** There are no sessions. Two visitors at once see and change the same proposals.
- **The queue can reset by itself.** It lives in the function's memory. When Vercel stops the function after a quiet period, the next visit starts clean. Under load Vercel may run several copies, each with its own queue. Only single-visitor use was tested.
- **Slower than local, and needs internet.** For the judged presentation, run it locally with `python start.py`.
- **The rule-based planner only.** No Azure keys are set on Vercel.
- **Redeploying is manual:** `vercel deploy --prod` from a machine that has the `data/` folder. Vercel had connected the GitHub repository by itself, and the first push started a build with no data, which would have broken the live site. The automatic GitHub deploy was disconnected for this project and the site redeployed from the laptop. A first visit after a quiet period takes about 5 seconds to answer.

### Tests
124 backend tests, all passing after the cache change.
