# Mirage — project log

A plain, step-by-step record of what was done, in order, and where the project stands.
Newest phase is at the bottom. Updated at the end of every phase.

**Where we are right now:** Phases 1 and 2 are built and tested. Phase 2 produced results that are partly plausible and partly not; three decisions are waiting for you (see the end of Phase 2). Phase 3 has not started.

| Phase | What it is | Status |
|---|---|---|
| 0 | Plan and check the outside data services | Done |
| 1 | Download and store the data | Done |
| 2 | Rain forecast, flood model, simulated sensors | Built; decisions pending |
| 3 | API and a bare map | Not started |
| 4 | The agent that proposes actions | Not started |
| 5 | Insurance payouts | Not started |
| 6 | Polish for the demo | Not started |
| 7 | Make it safe to present | Not started |

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

### Decisions waiting for you
1. **Underpasses.** Proposal: lower each underpass's cells by an assumed depth (for example 3 m) so water collects there. This is an assumption, would be labelled as one, and makes the "close the underpass" story work. Without it, the agent has few underpasses worth closing.
2. **The 2 to 5 m depths.** Proposal: leave the model alone, show roads by risk class as planned, and display depths above 100 cm as "over 100 cm". Alternative: smooth the elevation to remove the artificial bowls, which changes every result.
3. **The story timing.** T–0 is 20:00, so the demo window (T–6 to T+2) is 14:00 to 22:00, and at T–6 about 60% of the eventual flooding is already there. The demo script's "8 a.m., before the rain" opening will not match. Either the script is reworded, or T–0 is redefined (for example, the hour flooding rises fastest, which would be nearer 16:00 to 17:00).

Also to watch in Phase 5: only 2 of 60 sensors read above 30 cm at T–0, so few payouts would fire unless sensors are placed where policies are.
