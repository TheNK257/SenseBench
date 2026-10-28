# Adapters

Each log format is converted into SenseBench's canonical data model ([../docs/data-model.md](../docs/data-model.md)) by an adapter. Adapters are the **only** code that knows about a specific format or dataset.

Every adapter is its own small Python package in `adapters/<name>/`, registered through a Python entry point. That keeps heavy format libraries optional, and lets a team `pip install` its own adapter without forking SenseBench.

The adapter interface and the first adapters (nuScenes, CSV/Parquet) arrive in **M1**; see the roadmap.
