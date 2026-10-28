# SenseBench

Self-hostable telemetry viewer and alert engine for **student robotics and automotive teams** (Formula Student, BAJA, autonomous racing, rovers, drones). Load a recorded run, see every channel on one synced timeline, and get anomalies flagged automatically, with the scene context to understand *why* an alert fired.

- **Format-agnostic:** every log format is a small adapter into one data model ([docs/data-model.md](docs/data-model.md)).
- **Runs on a team laptop:** one Python process, no database server, works offline; your data never leaves the machine.
- **Free:** Apache-2.0, built only on free, permissively licensed components.

> **Status: early development (M0, foundation).** See [ROADMAP.md](ROADMAP.md) for what's planned and [LOGBOOK.md](LOGBOOK.md) for the design decisions behind it.

## Quick start (development)

Requires Python 3.12.

```bash
# with uv (recommended for teams)
uv venv && uv pip install -e "backend[dev]"

# or with conda (use Miniforge / conda-forge)
conda create -n sensebench -c conda-forge --override-channels python=3.12
conda activate sensebench
pip install -e "backend[dev]"
```

```bash
sensebench synth examples/out      # synthetic Formula-Student-style run with known faults
sensebench serve                   # http://127.0.0.1:8000/healthz
pytest                             # tests
pytest backend/benchmarks          # performance budgets
```

Configuration is optional: copy `.env.example` to `.env` to change the data directory, host or port.

Docker is optional too: `docker compose up`, or `docker compose --profile graph up` to add Neo4j for Cypher exploration of the scene graph.

## Layout

| Path | Contents |
|---|---|
| `backend/` | the `sensebench` Python package: geometry, storage, processors, alerts, API, CLI |
| `adapters/` | log-format adapters, one package each (nuScenes, CSV, MCAP, …) |
| `frontend/` | web UI (React + TypeScript) |
| `examples/` | sample rules and synthetic data |
| `docs/` | data model, adapter and rule guides |

## Licence

[Apache-2.0](LICENSE).
