# Building Mirage with Claude Code — guide and prompts

This guide gets you from an empty folder to a working Mirage demo: a dark map of Dubai that replays the 16 April 2024 storm, predicts which streets flood, lets an AI agent propose actions for you to approve, and fires insurance payouts.

It comes with a second file, **`CLAUDE.md`**, which is the full technical spec. Claude Code reads that file automatically when it sits in your project folder.

---

## 1. What you'll end up with

| Engine | What the demo does | Real or simulated |
|---|---|---|
| **Sky** | 6-hour rainfall forecast per map cell | Real historical rainfall; the "forecast" is simulated from it |
| **Ground** | Flood depth per street, hour by hour | Real elevation and real roads; simplified flood model |
| **City** | AI agent proposes pumps, closures and area alerts; you approve | Real LLM (or rule-based fallback); mock pump fleet |
| **Shield** | Automatic payout when measured depth crosses a threshold | Mock policies and simulated sensors |

**Be upfront about this with judges.** A prototype that says "simulated sensors, simplified model" is credible; one that implies it has NCM radar or RTA camera feeds is not. The app shows a permanent "Prototype" badge for this reason.

Realistic effort: a weekend for a working version, another few evenings to polish.

---

## 2. Before you start

**Install**
- Python 3.11 or newer
- Node.js 20 or newer
- Git
- Claude Code, set up in your IDE or terminal

**Optional: an LLM key for the agent**
- The spec uses Azure OpenAI if you set three environment variables, because Imagine Cup entries are generally expected to use Microsoft's AI services. Check the current Imagine Cup rules for exactly what's required.
- Without a key the app still works, using a rule-based planner. Add the key later.

**No other accounts or keys are needed.** Rainfall and elevation come from Open-Meteo, roads from OpenStreetMap, and the basemap from a free style.

---

## 3. Setup (5 minutes)

1. Create a folder called `mirage` and open it in your IDE.
2. Run `git init` in it.
3. Copy **`CLAUDE.md`** into the folder root.
4. Start Claude Code in that folder.

---

## 4. The prompts

Run these in order, one phase at a time. Don't paste them all at once: each phase ends with something you can see and check, which is how you catch problems early.

### Phase 0 — Plan (no code yet)
```
Read CLAUDE.md fully. Don't write any code yet.

1. Summarise back to me, in under 15 lines, what we're building and what is real vs simulated.
2. Make one real request each to the Open-Meteo archive API, the Open-Meteo elevation API, the Overpass API and the dark basemap style URL. Confirm they work and show me the response shape. Tell me about any limits (coordinates per request, rate limits) that affect the design.
3. Propose the build plan as phases with a checkable result at the end of each.
4. List anything in CLAUDE.md that is unclear, risky or that you'd do differently, and wait for my answer.
```

### Phase 1 — Data
```
Build the data layer from CLAUDE.md: config.py and data_fetch.py.
Fetch and cache rainfall for 2024-04-16, elevation for the grid, and the road network. Tag tunnels and underpasses.
When done, show me: grid shape, total and peak hourly rainfall, elevation min/max, number of road segments and underpasses, and the size of each cached file. Save a quick PNG of the rainfall at its peak hour and the elevation map so I can see they look like Dubai.
```

### Phase 2 — Sky and Ground
```
Implement sky.py, ground.py and sensors.py with tests.
Run the full 24-hour simulation and show me: the hour of peak flooding, the 10 worst road segments with depths, and how many segments fall in each risk class per hour.
Save PNGs of flood depth at T–6h, T–2h and T–0.
Tell me honestly whether the results look plausible. If the reanalysis rainfall is too weak to flood anything, propose a RAIN_SCALE value and explain it — don't quietly tune numbers.
```

### Phase 3 — API and a bare map
```
Implement the FastAPI app and replay.py, then the minimum frontend: the dark map, roads coloured by risk class, and a timeline scrubber that calls /api/replay/{hour}.
Start both servers, open the app, and take a screenshot for me at T–6h and T–0.
```

### Phase 4 — City (the agent)
```
Implement city.py: the Planner interface, RulePlanner, and LLMPlanner with the Azure OpenAI variables from CLAUDE.md.
Add the action queue panel with Approve and Reject, and make approved actions change the map (closed underpass markers, staged pumps adding local drainage).
Add a test proving no action takes effect without approval.
Show me the proposed actions at T–6h, T–4h and T–2h from RulePlanner, and from LLMPlanner if keys are set.
```

### Phase 5 — Shield
```
Implement shield.py with mock policies and the payout trigger reading only from the simulated sensors.
Add payout pins on the map and the payouts panel with a running total.
Show me the payout events for the full replay.
```

### Phase 6 — Polish for the demo
```
Polish the frontend per CLAUDE.md: the big T-minus clock, the phone-style alert card, Play/Pause with speed, the Prototype badge and the About drawer.
Add a "Demo mode" button that resets, plays from T–6h, and auto-approves the agent's actions with a visible "auto-approved for demo" label, so the full story runs hands-free in about 90 seconds.
Check the layout at 1920×1080 and 1366×768 and send me screenshots of both.
Then write the README: what it is, how to run it, what's real vs simulated, the model's limits, and data credits.
```

### Phase 7 — Hardening
```
Make the demo safe to present:
1. Run fully offline from the cache; confirm by disabling network access for one run.
2. One command to start everything (a script or Makefile).
3. Run all tests and fix failures.
4. Review the whole repo as a sceptical judge would: list any claim in the UI or README that overstates what the prototype does, and fix the wording.
```

---

## 5. Getting good results from Claude Code

- **Check each phase yourself.** Open the screenshots and the app. If the flood map doesn't look like Dubai, say so before moving on.
- **Describe what you see, not how to fix it.** "The roads near the coast are all red at T–6h, before any rain" is more useful than "change the threshold."
- **Ask why.** When it picks a number (drainage rate, noise level), ask what it's based on and have it record that in the README.
- **Commit after every phase** so you can roll back.
- **Keep the scope.** If you want heat or dust modes, finish the flood story first, then ask for them as a new phase.

---

## 6. Stretch goals (only after Phase 7)

- **Heat mode:** a street-level heat-risk layer from Open-Meteo's forecast temperature and humidity, with shift advice around the UAE midday break (12:30–15:00, 15 June–15 September).
- **Real nowcasting:** replace the simulated forecast with a small model trained on the rainfall grids.
- **Microsoft Aurora:** Aurora's code and weights are open. Running it needs a GPU and real setup time, so treat it as a separate project and feed its output through the same `RainSource` interface.
- **March 2026 storm:** add a second replay to show the system isn't tuned to one day.
- **Deploy:** host the frontend and API on Azure so judges can open a link.

---

## 7. Your 3-minute demo script

1. **Open on T–6 h.** "This is Dubai at 8 a.m. on 16 April 2024. The rain you see is the real record. Everything else is our prototype, with simulated sensors."
2. **Press Play, pause at T–4 h.** "Mirage is forecasting which streets flood. Here's the agent's plan — stage pumps at these underpasses. Nothing happens until a person approves." Click **Approve**.
3. **Pause at T–2 h.** Show the alert card. "One alert, one district, one time."
4. **Run to T–0.** "The underpasses were shut before the water arrived. Sensors confirm the depth — and that triggers these payouts automatically."
5. **Open About.** "Here's exactly what's real and what's simulated, and what we'd need from NCM and RTA to make it live."

---

## 8. If something goes wrong

| Problem | What to tell Claude Code |
|---|---|
| An API request fails or its format changed | "Make a real request, show me the response, and adapt the fetcher. Keep the cache format the same." |
| Nothing floods | "Show me rainfall totals and drainage per hour. Is the reanalysis too weak? Propose a RAIN_SCALE and justify it." |
| Everything floods | "Show the water balance per hour. Check the D8 routing isn't creating water." |
| The map is blank | "Check the browser console and the basemap style URL. Fall back to our own road layer on a plain dark background." |
| The LLM returns bad output | "Show me the raw response and the validation error. Confirm the fallback to RulePlanner worked." |
| The app is slow | "Profile /api/replay. Precompute and cache the timeline; downsample grids sent to the browser." |
