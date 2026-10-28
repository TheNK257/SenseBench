# SenseBench — Logbook

A running record of design discussions: what was considered, what was decided, and why.
`ROADMAP.md` holds the one-line decisions log and feature status; this file holds the reasoning behind them.

Newest entries at the bottom. Each entry: **Discussed** (options and trade-offs), **Decided**, **Why**, **Follow-ups**.

---

## 2026-10-27 — Project scope (summary of earlier sessions)

**Decided**
- Target users: student robotics / automotive competition teams (Formula Student, BAJA, autonomous racing, rovers, drones).
- Recorded data only; live ingestion deferred until after Phase 3.
- Portfolio project: the hosted instance is a read-only showcase; teams clone/fork and self-host.
- Neo4j for the scene graph and alert context only; time series in a dedicated store. *(Revised 2026-10-28, see entry 6.)*

## 2026-10-28 — Name

**Decided:** Named **Pitwall**, then renamed to **SenseBench** (folder + GitHub repo `TheNK257/SenseBench`).

---

## 2026-10-28 — Detailed planning session

### 1. Playback model: client-driven, not server streaming

**Discussed:** Server-pushed frame streaming over WebSockets (the usual live-dashboard approach) vs. the browser owning the playback clock and fetching data by time range.

**Decided:** The browser owns the clock and pulls data (`GET …/data?start=&end=`, `GET …/at?t=`). No per-client server streams.

**Why:** For recorded data, server streaming only adds problems: one stream/poll per viewer, drift from sleeping after work, unbounded buffers. Client pull makes every response cacheable, scales trivially, and enables a fully static showcase (entry 7). Monotonic pacing still applies on the client (`requestAnimationFrame` + `performance.now()`).

### 2. Canonical data model

**Decided** (full spec in `docs/data-model.md`):
- `Session → Channels (typed) → timestamped Messages` (rows in Parquet keyed by `t_ns`).
- **8 channel types:** `scalar`, `pose`, `image`, `pointcloud`, `objects`, `gps`, `imu`, `event`.
- **CAN folded into `scalar`:** a DBC-decoded CAN signal is a number plus metadata; raw CAN frame decoding is out of scope for v1.
- **One signal per scalar channel:** CSV column → channel; rules address one channel each.
- **Timestamps:** int64 nanoseconds (`t_ns`). Sessions declare `clock: utc | relative` (boot-time logs such as PX4 or microcontrollers). Per-channel `time_offset_ns` aligns clocks.
- **Frames:** reserved names `map` and `ego` (+x fwd, +y left, +z up). Static extrinsics in `session.json`; moving transforms are `pose` channels. Adapters store data in its native frame and declare it; a `to_ego` processor materializes ego-frame copies.
- **Quaternions as named columns** `qw, qx, qy, qz` so wxyz (nuScenes) vs xyzw (ROS) ordering can't be confused.
- Radar is a `pointcloud` with extra fields; the adapter maps motion-compensated velocity into `vx`/`vy`.

### 3. Storage

**Discussed:** TimescaleDB vs DuckDB + Parquet.

**Decided:** **DuckDB + Parquet.** One folder per session (`session.json`, `channels/*.parquet`, `blobs/`, `derived/`), plus `data/catalog.duckdb` for the session index and alerts.

**Why:** Recorded data is write-once/read-many (Parquet's sweet spot). DuckDB is embedded (no server, no container), sessions are portable folders, and window functions cover z-score / EWMA / rate-of-change rules. TimescaleDB would add a server and slow row ingest for no benefit.

### 4. Adapters, processors, alert rules

**Decided:**
- **Adapters are separate packages** under `adapters/<name>/`, registered via Python entry points. Heavy deps (nuscenes-devkit, mcap, pyulog) stay optional; teams can `pip install` their own adapter without forking. Interface: `can_open`, `sessions`, `describe`, `read` (yields Arrow record batches validated against the channel type's schema).
- **Processors** share that shape (channels in → new channels out), cached by `name@version-config_hash`. First ones: `to_ego`, `speed_from_pose` (generic replacement for "derive speed from ego poses"), later `detect`, `track`.
- **Alert engine** evaluates rules **once over the whole session at import**, vectorized (DuckDB / NumPy). Alerts are intervals with peak value, severity, and evidence; firings within `merge_gap` group into one incident.
- **Role aliases** in rules (`@ego_speed` → a team's actual channel name), so starter rule packs work for any team without renaming channels.

### 5. Frontend

**Decided:** **React + TypeScript + Vite**, with uPlot (plots), MapLibre (maps), Canvas 2D (top-down), Cytoscape.js (scene graph), dockview or react-grid-layout (layouts), zustand (shared timeline state).

**Why React and not something lighter:** the hot path (drawing panels each frame) bypasses React entirely; React only re-renders on layout changes, so its overhead doesn't matter and its ecosystem does.

### 6. Constraint: everything free; efficient on team laptops

**Discussed:** User requirement: keep everything free, and no lag while monitoring telemetry because teams run it on their own machines. Each component was audited for cost/licence and weight.

**Decided:**

| Item | Problem | Replacement |
|---|---|---|
| Ultralytics YOLO | AGPL-3.0; commercial use needs a paid licence; clashes with an Apache-2.0 repo | **D-FINE or RT-DETR** (Apache-2.0) via **ONNX Runtime** (MIT), CUDA or CPU. Verify licences upstream before adopting. |
| Map tiles | OSM public tiles forbid heavy use; tracks often have no internet | **OpenFreeMap** online (free, no key) + **self-hosted MBTiles/PMTiles** offline |
| Anaconda defaults channel | Terms of service can apply to organisations | **Miniforge** (conda-forge) for development; **uv** for team installs |
| Showcase hosting | Free tiers (HF Spaces, Render, Fly) are uncertain or sleep | **Static site** (entry 7) |
| Docker Desktop | Free for personal/education/small orgs, but heavy | Made **optional** |
| **Neo4j** | Free (GPLv3 Community) but a JVM server: 1–2 GB RAM idle, 10–20 s startup, forces Docker | **Optional add-on** (see below) |

**Neo4j decision (revises the 2026-10-27 entry):** The scene graph is computed in-process via the geometry module and stored as **node/edge tables in DuckDB** by default. Spatial rules and the "why did this fire?" view read those tables. Neo4j becomes an **optional profile** (`docker compose --profile graph`) that loads the same graph for Cypher exploration and graph visualization.

**Considered and rejected:** Kùzu (embedded Cypher DB, the ideal fit) was archived in October 2025; its forks (RyuGraph, LadybugDB) are too young to depend on.

**Result:** default install is one Python process with no Docker and no DB server: `uv pip install sensebench` → `sensebench import …` → `sensebench serve`. Works offline.

**No-lag design rule:** *pay at import, never during playback; the playback path does no computation and never waits on the network.*
- Import-time: min/max LOD pyramids per scalar channel (plot queries cost O(pixels), not O(samples)); alerts, scene graph, ego transforms, derived speed, and detection precomputed and cached; ~480p image previews for scrubbing (full res when paused); Parquet sorted by `t_ns` with sized row groups.
- Transport: binary (Arrow IPC / typed arrays) for signals and point clouds, never JSON number arrays; original image bytes served without re-encoding, `Cache-Control: immutable`; blocking work in a threadpool.
- Client: playback clock reads only in-memory buffers; bounded prefetch ring ahead of the playhead; late data shows last frame + "buffering" badge instead of stalling; canvas panels draw imperatively; Arrow parsing and `createImageBitmap` decoding in Web Workers.
- **Performance budgets enforced in CI** (pytest-benchmark, large synthetic session): scrub → frame < 50 ms; timeline 60 fps; pan/zoom on a 10M-sample channel < 16 ms draw; session open < 1 s; default idle RAM < 300 MB.
- **Privacy:** fully offline (all JS/fonts bundled, no runtime CDN), no telemetry, server binds to `localhost` by default.

### 7. Showcase hosting

**Decided:** Static build on **GitHub Pages or Cloudflare Pages**, querying precomputed Parquet in the browser with **DuckDB-WASM**. The frontend gets two data sources behind one interface: HTTP API (self-host) and static files (showcase). Scheduled for M7.

**Why:** zero cost, never sleeps, nothing to maintain.

**Follow-up:** nuScenes is CC BY-NC-SA. A public showcase must attribute it and stay non-commercial; check the terms before publishing frames.

### 8. Licence and tooling

**Decided:**
- **Apache-2.0** (matches ROS 2, includes a patent grant).
- Python 3.12, FastAPI, Pydantic v2, PyArrow, DuckDB, NumPy, Typer (CLI), ruff, pytest.
- Dev conda env renamed `pitwall` → **`sensebench`**, created from Miniforge.

### 9. Synthetic data generator

**Decided:** Ship a generator in `examples/synthetic/` that produces a Formula-Student-style run with **known injected faults** (overheating, sensor dropout, wheel-speed vs GPS disagreement).

**Why:** No public team CSV logs are confirmed yet. Known faults give the alert engine exact ground truth ("this rule fires in [t1, t2]"), and a large generated session drives the CI performance benchmarks.

### 10. Build order

**Decided:** milestones, each ending in something demoable:

| # | Milestone |
|---|---|
| M0 | Licence, layout, `.gitignore`, CI, geometry module + tests, synthetic generator, benchmark harness |
| M1 | Data model + schemas + Parquet store + nuScenes **and** CSV adapters + `sensebench import/inspect` |
| M2 | UI slice: session list, timeline, camera, plot, top-down, auto layout |
| M3 | Signal alerts, grouping, alert timeline, jump-to |
| M4 | Scene graph (DuckDB), spatial/TTC rules, "why did this fire?" view; optional Neo4j profile |
| M5 | MCAP/ROS 2 + PX4 ULog adapters, map panel |
| M6 | Detection (D-FINE/RT-DETR via ONNX Runtime) + tracking + ego lifting, eval vs nuScenes GT |
| M7 | Static showcase, run-report export, rule packs, README GIFs |

**Why nuScenes and CSV together in M1:** two very different formats are the real test that the model is format-agnostic. A strong portfolio stopping point is M0–M4 plus one robotics format; ROS 1 and ArduPilot are stretch goals.

**Known risks:** clock misalignment across channels in team data (per-channel offset); 2D→ego lifting without depth assumes flat ground (fine for cones, weaker in general).

**Status at end of session:** all of the above agreed by the user. GitHub repo exists and is empty; no commits yet. Next: start M0.

---

## 2026-10-28 — M0 implementation notes

### 11. Benchmark harness without pytest-benchmark

**Discussed:** The plan named pytest-benchmark. Its latest release (5.3.0) crashes on pytest 9.2: it reads `node._nodeid`, which pytest removed. Options: pin an older pytest, or write our own timing fixture.

**Decided:** Own fixture, `within_budget`, in `backend/benchmarks/conftest.py` (~40 lines). It runs a warm-up call, then times rounds until 0.5 s has been measured (minimum 5 rounds), fails if the **median** exceeds the test's entry in `BUDGETS_S`, and prints a budget table at the end of the run.

**Why:** One fewer dependency, and no pin that breaks again on the next pytest upgrade. We only need "under a ceiling", not pytest-benchmark's comparisons. Revises the "pytest-benchmark" mention in entry 6.

**Why median, not mean:** in two consecutive local runs the pose-lookup mean jumped from 33 µs to 85 µs (budget 100 µs) while the best stayed at 32 µs. Occasional OS/GC stalls skew the mean of microsecond-scale calls, which would make CI flaky; the median ignores them.

**First numbers (dev laptop, median):** 1M points into the ego frame ~15–20 ms (budget 150); direction of 1M points ~55–80 ms (300); one pose lookup ~35–80 µs (budget raised from 100 to 250 µs: even the median swings run to run on the laptop, and the budget's job is to catch an O(n) regression, which would cost milliseconds); 1-hour synthetic run ~0.2 s (3 s).

### 12. Synthetic generator: placement and vehicle model

**Decided:**
- It lives in the package (`sensebench.synthetic`, CLI `sensebench synth <dir>`), not `examples/synthetic/`, because tests and benchmarks import it. `examples/README.md` documents usage. Revises entry 9's path.
- **Lap built from straights and arcs** (a chicane, a 9 m hairpin), closed exactly by a minimum-norm adjustment of the straight lengths. A first attempt with a polar curve produced cusps (0.6 m radius) and an unrealistic 85–98 km/h mean speed. Result: a 454 m lap in 25.5 s at a 65 km/h mean, 40 km/h in the hairpin, 1.57 g peak lateral.
- **Motor heating follows load averaged over 30 s** (thermal mass). Without this, lap-to-lap load swings made the temperature cross 80 °C several times, so the overheat fault had no single clean interval. After the change, 0 of 100 seed/duration combinations failed. A guard raises if this ever regresses.
- **Pedals are smoothed over 0.15 s**, so normal brake-pressure rates stay below about 800 bar/s while the injected spike is about 8000 bar/s, which makes the rate-of-change fault unambiguous.

### 13. Geometry API details

**Decided:**
- Quaternions are (w, x, y, z) arrays in memory, built only from named components (`quat(qw, qx, qy, qz)`, `Transform.from_components`).
- `Transform` follows parent→child semantics (`p_parent = T.apply(p_child)`); `to_ego(points, ego_pose)` applies the inverse. A regression test covers the "translation only" bug: an object ahead of a yawed ego must classify as `front`, not `left`.
- `PoseSeries.at` raises `LookupError` outside the recorded range rather than clamping or extrapolating, so a bad lookup can't silently return wrong data.
- `direction_from_bearing` raises on NaN instead of defaulting to `behind`.
- GPS ↔ ENU uses a WGS84 tangent-plane approximation (cm-accurate over a few km, which covers a track or test field) and handles the antimeridian.

### 14. Packaging and environment

**Decided:** `backend/pyproject.toml` (setuptools, editable install `pip install -e "backend[dev]"`); root `ruff.toml` (`src = ["backend"]`) and `pytest.ini` (`testpaths = backend/tests`, so plain `pytest` skips benchmarks). The conda env `sensebench` was created with `-c conda-forge --override-channels` (no Anaconda defaults). The container runs as a non-root user; compose publishes ports on `127.0.0.1` only; Neo4j is pinned to `5.26-community` with a 1 GB heap.

**Follow-ups:**
- Docker image build untested (Docker Desktop was not running); `docker compose config` validates.
- CI's first run happens on the first push.
- Starlette warns that its httpx-based TestClient is deprecated in favour of `httpx2`; revisit before it becomes an error.
- `PoseSeries.at` costs about 33 µs per scalar call; add a vectorized lookup in M1 before processors call it per message.
