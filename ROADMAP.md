# SenseBench — Roadmap

## Vision

A self-hostable tool for **student robotics and automotive teams** (Formula Student, BAJA, autonomous racing, rovers, drones, competition robots) to load **recorded** runs, see all their telemetry in one place, and get **anomalies and alerts flagged automatically**, with enough context to understand *why* something fired.

Teams clone or fork the repo and run it on their own machine. A hosted instance exists only as a **read-only showcase** with sample data.

What sets it apart from generic dashboards: alerts can reason about the **scene** (what was around the vehicle, where, how fast), not just thresholds on single signals.

**Constraints:** everything free and permissively usable; lag-free on a team laptop (see *Performance budgets*); works offline; team data never leaves the machine.

## Status legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[-]` dropped

Reasoning behind decisions lives in `LOGBOOK.md`; the data model spec is `docs/data-model.md`.

---

## Phase 0 — Foundation (M0)

- [x] Add `LICENSE` (Apache-2.0)
- [x] `git init`, create the GitHub repo
- [x] Project layout: `backend/`, `frontend/`, `adapters/`, `docs/`, `examples/`
- [x] Geometry module: ego-frame transforms, pose interpolation, direction classifier, GPS ↔ ENU, with tests (`backend/sensebench/geometry.py`)
- [x] Single-process default: `sensebench serve` runs with no Docker and no DB server (only `/healthz` so far)
- [~] `docker compose up` as an optional path; `--profile graph` adds Neo4j (config validated; image build untested, Docker Desktop was off)
- [~] CI: lint + tests (Ubuntu + Windows) + benchmarks on every push (workflow written; first run pending push)
- [x] Performance benchmark harness (`pytest backend/benchmarks`, own timing fixture with per-benchmark budgets); fails on budget regressions
- [x] Synthetic data generator (`sensebench synth`, `sensebench.synthetic`): Formula-Student-style run with known injected faults
- [x] Config via `.env` with a committed `.env.example`; no machine-specific paths
- [x] `.gitignore` covers datasets, caches, venvs, editor folders, `.claude/settings.local.json` from day one

## Phase 1 — Data model + adapters (M1, M5)

The core idea: one internal data model; every log format is a small adapter at the edge.

- [~] Define the canonical model: **Session** → **Channels** (typed streams) → **timestamped Messages** (agreed; spec in `docs/data-model.md`, to implement)
- [ ] Channel types: `scalar`, `pose`, `image`, `pointcloud`, `objects`, `gps`, `imu`, `event` (CAN signals are `scalar`)
- [ ] Coordinate frames + transforms as first-class data (static extrinsics + `pose` channels; `to_ego` processor)
- [ ] Storage: DuckDB + Parquet per session · blobs on disk · `catalog.duckdb` for sessions, alerts, scene graph tables
- [ ] Import-time precompute: scalar LOD pyramids (min/max), image previews (~480p), Parquet sorted by `t_ns`
- [ ] Adapter interface (entry-point packages under `adapters/`), documented well enough that a team can write their own in an afternoon
- [ ] Adapters:
  - [ ] nuScenes (M1; rich multi-sensor data with ground truth)
  - [ ] CSV / Parquet (M1; CAN loggers, DAQ systems, microcontroller logs)
  - [ ] MCAP / ROS 2 bag (M5)
  - [ ] PX4 ULog (M5, drones)
  - [ ] ROS 1 bag (stretch)
  - [ ] ArduPilot DataFlash / MAVLink `.tlog` (stretch)
- [ ] Session import: CLI first (`sensebench import path/to/log`, `sensebench inspect`), upload UI later
- [ ] Find public sample datasets for each adapter (see *Sample data* below)

## Phase 2 — Visualization (M2)

React + TypeScript + Vite. Panels draw imperatively to canvas; React only handles layout.

- [ ] Session browser (list runs, duration, channels, alert count)
- [ ] Global timeline with scrubbing; client-owned playback clock; every panel synced to the same timestamp
- [ ] Bounded prefetch buffer ahead of the playhead; late data shows last frame + "buffering" badge, never stalls the clock
- [ ] Binary transport (Arrow IPC / typed arrays) for signals and point clouds; decoding in Web Workers
- [ ] Panels built from whatever channels a session has (no layout hardcoded per dataset):
  - [ ] Camera / image
  - [ ] Top-down 2D view (ego, objects, radar/lidar points)
  - [ ] Time-series plots (uPlot; multiple signals, zoom, cursor)
  - [ ] Map / GPS track (MapLibre; OpenFreeMap online, MBTiles/PMTiles offline) (M5)
  - [ ] Scene graph view (Cytoscape.js; reads DuckDB graph tables) (M4)
- [ ] Saved layouts per team
- [ ] Frontend talks to the backend by relative URLs (no hardcoded `localhost`)
- [ ] Fully offline: all JS/fonts bundled, no runtime CDN

## Phase 3 — Alerts & anomalies (core goal, M3–M4)

- [ ] Rules defined in YAML, version-controlled alongside a team's code
- [ ] Role aliases (`@ego_speed` → team's channel) so rule packs work across teams
- [ ] Rules evaluated once per session at import, vectorized (DuckDB / NumPy)
- [ ] Rule types:
  - [ ] Threshold / range (e.g. motor temp > 80 °C)
  - [ ] Rate of change (e.g. brake pressure spike)
  - [ ] Signal dropout / stale channel (sensor health)
  - [ ] Cross-signal consistency (e.g. wheel speed vs GPS speed disagree)
  - [ ] Spatial / scene-graph rules (e.g. object in critical zone ahead while speed > X; time-to-collision < 2 s) (M4)
  - [ ] Statistical anomalies (z-score / EWMA), no ML required
- [ ] Alerts stored as intervals with evidence, linked to the frame, signals and objects that triggered them
- [ ] Scene graph built in-process, stored as DuckDB node/edge tables (M4)
- [ ] Optional Neo4j profile loads the same graph for Cypher exploration (M4)
- [ ] Alert timeline in the UI; clicking an alert jumps playback to that moment
- [ ] "Why did this fire?" view: rule, values, and scene-graph snapshot at that moment
- [ ] Severity levels, alert grouping (`merge_gap`: one incident, not 40 duplicate alerts)
- [ ] Export a run report (Markdown/PDF) with alerts and plots (M7)
- [ ] Starter rule packs per competition type (Formula Student, BAJA, rover, drone) (M7)

## Phase 4 — Perception pipeline (M6)

Most team data has raw camera frames but no labelled objects; detection is what makes scene-level alerts possible on real data.

- [ ] Processor interface: consumes channels, emits new channels, cached by `name@version-config_hash`
- [ ] Built-in processors: `to_ego`, `speed_from_pose`
- [ ] 2D object detection: **D-FINE or RT-DETR (Apache-2.0) via ONNX Runtime**, sized for a 6 GB laptop GPU, CPU fallback (verify licences upstream; no Ultralytics/AGPL)
- [ ] Class mapping configurable per team (e.g. cones for Formula Student, not pedestrians)
- [ ] Multi-object tracking (stable IDs across frames)
- [ ] Lift 2D detections into the ego frame (camera calibration + ground plane or depth/lidar)
- [ ] Evaluate against nuScenes ground truth; detector-vs-ground-truth disagreement becomes an anomaly type
- [ ] Runs once at import, never during playback

## Phase 5 — Showcase hosting & self-host (M7)

- [ ] Static read-only showcase on GitHub Pages or Cloudflare Pages: precomputed Parquet queried in the browser with DuckDB-WASM (no server, no cost)
- [ ] Frontend data-source interface with two implementations: HTTP API (self-host) and static files (showcase)
- [ ] Check nuScenes licence (CC BY-NC-SA) terms before publishing frames; attribute it
- [ ] Container image(s) published to GHCR for teams who prefer Docker
- [ ] Self-hosting guide: hardware requirements, `uv` install, importing your first run, writing a rule
- [ ] Demo GIFs/screenshots in README

---

## Performance budgets

Enforced by the CI benchmark harness against a large synthetic session. Principle: *pay at import, never during playback.*

| Metric | Budget |
|---|---|
| Scrub → frame visible | < 50 ms |
| Timeline playback | 60 fps |
| Pan/zoom draw on a 10M-sample channel | < 16 ms |
| Open a session | < 1 s |
| Idle RAM, default install | < 300 MB |

## Build order

| # | Milestone |
|---|---|
| M0 | Foundation (Phase 0) |
| M1 | Data model + storage + nuScenes and CSV adapters + CLI |
| M2 | UI slice: session list, timeline, camera, plot, top-down |
| M3 | Signal alerts, grouping, alert timeline |
| M4 | Scene graph, spatial/TTC rules, "why" view, optional Neo4j |
| M5 | MCAP/ROS 2 + PX4 ULog adapters, map panel |
| M6 | Perception pipeline |
| M7 | Static showcase, reports, rule packs, README polish |

Portfolio-ready stopping point: M0–M4 plus one robotics format.

---

## Deferred (not in current scope)

- **Live ingestion.** Every team's stack differs, so the likely approach is *not* to support stacks individually but to publish one simple ingest protocol plus thin clients (Python lib, ROS 2 bridge node, maybe Foxglove WebSocket protocol compatibility). Revisit after Phase 3.
- Multi-user accounts / team workspaces on a shared server
- ML-based anomaly detection (isolation forest, autoencoders) beyond the statistical rules
- 3D view (point clouds in 3D)
- Raw CAN frame decoding (DBC); v1 takes already-decoded signals

## Sample data (to find / verify)

| Format | Candidates | Status |
|---|---|---|
| nuScenes | v1.0-mini (available locally) | have |
| Synthetic FS-style CSV | `sensebench synth` generator with injected faults | have |
| MCAP / ROS 2 | Foxglove example MCAP files, public ROS 2 bags | to verify |
| ROS 1 bag | KITTI raw → rosbag conversions, university datasets | to verify |
| CSV / CAN / DAQ | Formula Student / BAJA team logs shared publicly | to verify |
| PX4 ULog | PX4 Flight Review public logs | to verify |
| Images (cones) | FSOCO dataset (Formula Student cones) | to verify |

## Decisions log

| Date | Decision |
|---|---|
| 2026-10-27 | Target users: student robotics / automotive competition teams |
| 2026-10-27 | Recorded data only; live ingestion deferred |
| 2026-10-27 | Portfolio project: hosted as read-only showcase; teams clone/fork to self-host |
| 2026-10-27 | Neo4j kept for scene graph + alert context only; time series go to a dedicated store *(revised 2026-10-28)* |
| 2026-10-28 | Project name: **Pitwall** |
| 2026-10-28 | Renamed to **SenseBench** (folder + GitHub repo) |
| 2026-10-28 | Client-owned playback clock; browser pulls data by time range (no server streaming) |
| 2026-10-28 | Canonical model agreed: 8 channel types, CAN as `scalar`, one signal per scalar channel, int64 ns timestamps, named quaternion columns (`docs/data-model.md`) |
| 2026-10-28 | Time-series store: **DuckDB + Parquet** |
| 2026-10-28 | Frontend: **React + TypeScript + Vite** (uPlot, MapLibre, Cytoscape.js, zustand) |
| 2026-10-28 | Licence: **Apache-2.0** |
| 2026-10-28 | Adapters are separate entry-point packages; rules use role aliases (`@ego_speed`) |
| 2026-10-28 | Everything free: D-FINE/RT-DETR via ONNX Runtime (not Ultralytics), OpenFreeMap + offline tiles, Miniforge/uv (not Anaconda defaults) |
| 2026-10-28 | Neo4j becomes optional; default scene graph stored as DuckDB tables; default install is one process, no Docker |
| 2026-10-28 | Showcase is a static site (GitHub/Cloudflare Pages + DuckDB-WASM) |
| 2026-10-28 | Performance budgets enforced in CI; alerts/detection/scene graph precomputed at import |
| 2026-10-28 | Keep `LOGBOOK.md` with the reasoning behind every discussion and decision |
| 2026-10-28 | Benchmarks use an own timing fixture instead of pytest-benchmark (incompatible with pytest 9.2) |
| 2026-10-28 | Synthetic generator lives in the package (`sensebench.synthetic`, `sensebench synth`) so tests and benchmarks can import it |
