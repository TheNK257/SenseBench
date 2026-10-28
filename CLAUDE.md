# SenseBench

Self-hostable tool for student robotics / automotive competition teams to load **recorded** runs, visualize all their telemetry in one place, and automatically flag anomalies and alerts with scene context ("why did this fire?").

**`ROADMAP.md` is the source of truth for features and status.** Tick its checkboxes as work lands and add a row to its decisions log when a design decision is made.

**`LOGBOOK.md` records every design discussion.** After any discussion that considers options or reaches a decision, append a dated entry (Discussed / Decided / Why / Follow-ups), including rejected alternatives. Revisions to earlier decisions get a new entry that points back to the old one; don't rewrite history.

The canonical data model is specified in `docs/data-model.md`.

## Status

M0 (foundation) is done locally: geometry module, synthetic generator, `sensebench serve` with `/healthz`, benchmark harness, CI workflow, optional Docker. Not yet pushed, so CI has never run; the Docker image build is untested.

Next: push and get a green CI run, then **M1**: data model + Parquet store + nuScenes and CSV adapters + `sensebench import/inspect`.

## Commands

Run from the repo root with the `sensebench` env (`C:\Users\naman_8fr9dqd\anaconda3\envs\sensebench`):

- `pip install -e "backend[dev]"`: install
- `pytest`: tests (`backend/tests`)
- `pytest backend/benchmarks`: performance budgets (`BUDGETS_S` in `backend/benchmarks/conftest.py`; every benchmark needs an entry)
- `ruff check . && ruff format --check .`: lint
- `sensebench synth <dir>` / `sensebench serve`

## Scope rules

- **Recorded data only.** Live ingestion is deferred (see ROADMAP "Deferred"); don't build it unless the user reopens it.
- **Portfolio project.** The showcase is a static read-only site with preloaded sample data: no uploads, no auth, no server. Teams get value by cloning/forking and self-hosting.
- **Format-agnostic core.** Nothing outside an adapter may know about a specific dataset or log format (no `CAM_FRONT`, sample tokens, `.pcd` assumptions in core code or the UI).
- **Everything free.** Only free, permissively usable dependencies and services. No AGPL dependencies (e.g. Ultralytics), no paid APIs, no API keys required. Check the licence before adding a dependency.

## Architecture (agreed)

```
Adapters (nuScenes, CSV/Parquet, MCAP/ROS2, PX4 ULog, later ROS1, ArduPilot)
   -> canonical model: Session -> Channels (typed) -> timestamped Messages
   -> Processors (to_ego, speed_from_pose, detection, tracking) emit new channels
   -> Alert engine (YAML rules: signal rules + scene-graph rules + statistical anomalies), run once at import
   -> UI: panels generated from available channels, one shared client-side timeline, alert timeline
```

- **Default install is one Python process** (`sensebench serve`): no Docker, no database server, works offline.
- Storage: **DuckDB + Parquet** per session folder; images/point clouds as files; `data/catalog.duckdb` for sessions, alerts and the **scene graph as node/edge tables**.
- **Neo4j is optional** (`docker compose --profile graph`): it loads the same graph for Cypher exploration. Core features must never require it.
- **Playback is client-driven:** the browser owns the clock and pulls data by time range. No server-side frame streaming.
- Adapters are separate packages under `adapters/<name>/`, registered via Python entry points.
- Detection is a *processor* (D-FINE or RT-DETR via ONNX Runtime): real team data has raw camera frames but no labels, so detection is what makes object-level alerts possible.
- Alerts are stored as intervals linked to the frame, signals and objects that triggered them.
- Stack: Python 3.12, FastAPI, Pydantic v2, PyArrow, DuckDB, NumPy, Typer, ruff, pytest · React + TypeScript + Vite, uPlot, MapLibre (OpenFreeMap / offline MBTiles), Cytoscape.js, zustand.

## Performance (no lag is a core requirement)

- **Pay at import, never during playback.** Alerts, scene graph, ego transforms, detection, LOD pyramids and image previews are precomputed and cached.
- The playback path does no computation and never waits on the network; prefetch into a bounded buffer and show "buffering" rather than stall the clock.
- Signals and point clouds go over the wire as binary (Arrow IPC / typed arrays), never JSON number arrays. Serve original image bytes; don't re-encode.
- Plot queries cost O(pixels), not O(samples) (min/max LOD pyramids).
- Canvas panels draw imperatively; React re-renders only on layout changes. Decode in Web Workers.
- Budgets (ROADMAP "Performance budgets") are enforced by CI benchmarks; a regression fails the build.
- Privacy: everything bundled (no runtime CDN), no telemetry, server binds to `localhost` by default.

## Coordinate conventions

- One convention everywhere: **ego frame, +x forward, +y left, +z up** (right-handed).
- Bearing = `atan2(y, x)`, so 0° = straight ahead, +90° = left.
- Coarse direction uses 90° sectors: `front` [-45°, 45°], `left` (45°, 135°), `right` (-135°, -45°), `behind` otherwise. Use exactly these four strings.
- All spatial math goes through **one geometry module**; never compute distance or direction from raw global coordinates.
- Global → ego requires subtracting the ego translation **and** applying the inverse ego rotation. Translation alone gives map-aligned axes, which silently breaks front/left/right.
- Quaternions are stored as named columns `qw, qx, qy, qz`, never as an ordered array.

## nuScenes adapter: known gotchas

- `sample_annotation.translation` is in the **global** frame, not ego-relative. Use the ego pose of the sample's `LIDAR_TOP` sample_data (annotations are synced to the lidar keyframe).
- Quaternions are stored as `[w, x, y, z]` (pyquaternion's order).
- Radar `.pcd` rows: `0 x, 1 y, 2 z, 3 dyn_prop, 4 id, 5 rcs, 6 vx, 7 vy, 8 vx_comp, 9 vy_comp, …`. Rows 6/7 still contain ego motion; use **8/9 (compensated)**. Points are in the **sensor frame**; apply the `calibrated_sensor` transform to get to ego.
- `nusc.box_velocity()` returns NaN for objects present in a single keyframe; convert to `null` before JSON (browsers can't `JSON.parse` `NaN`).
- OpenCV `imread` gives BGR and `imencode` expects BGR. Don't convert to RGB before encoding (it swaps red/blue).
- v1.0-mini has no CAN bus data; derive speed with the generic `speed_from_pose` processor (timestamps are microseconds).
- `sweeps/` (~4.4 GB of the 5.1 GB mini set) is unused if only keyframes are needed.
- nuScenes is CC BY-NC-SA: attribute it, non-commercial only, check terms before publishing frames in the showcase.

## Engineering principles

- Every bug fix lands with a regression test that fails on the old behaviour.
- No blocking work (image encode/decode, file parsing, inference, DB writes) on the async event loop; use a threadpool or worker.
- Pace playback against a monotonic deadline (`performance.now()`), not a fixed sleep after doing work.
- Make JSON NaN-safe at the boundary.
- Bound every buffer and cache; a long session must not grow memory.
- Health endpoints return a non-200 status when unhealthy.
- Tests that need external services (Neo4j, datasets) must use fakes or skip cleanly, so `pytest` passes on a fresh clone.

## Environment

- Windows 11; shell tools are Git Bash and PowerShell.
- Use the dedicated conda env `sensebench` (create it from Miniforge / conda-forge, not Anaconda defaults); bare `python` on PATH is Anaconda base and may lack dependencies. Teams install with `uv`.
- Docker Desktop is only needed for the optional Neo4j profile; it is often not running. Another local Neo4j container may already be bound to ports 7474/7687; stop it or remap.
- GPU: RTX 4050 Laptop (6 GB VRAM) — size perception models accordingly.
