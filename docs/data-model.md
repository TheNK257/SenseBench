# Canonical data model

Status: **agreed 2026-10-28** (see `LOGBOOK.md`). Field-level details may be refined during M1; record any change in the logbook.

Every log format is converted by an adapter into this model. Nothing outside an adapter knows about a specific dataset or format.

```
Session ──< Channel ──< Message (Parquet rows, keyed by t_ns)
   └── static_transforms (sensor extrinsics)
```

## Time

- All timestamps are **int64 nanoseconds**, column `t_ns`.
- `session.clock` is `utc` (epoch-based) or `relative` (time since boot / log start, e.g. PX4, microcontroller logs).
- `channel.time_offset_ns` (default 0) is added on read to align channels recorded on different clocks.

## Session (`session.json`)

| Field | Type | Notes |
|---|---|---|
| `id` | string | slug, stable across re-imports |
| `name` | string | |
| `source_format` | string | adapter name |
| `start_ns`, `end_ns` | int64 | |
| `clock` | `utc` \| `relative` | |
| `platform` | object | free-form vehicle/robot description |
| `tags` | string[] | |
| `static_transforms` | Transform[] | `{parent, child, x, y, z, qw, qx, qy, qz}` |
| `channels` | Channel[] | |

## Channel

| Field | Type | Notes |
|---|---|---|
| `id` | string | used for file names |
| `name` | string | any string; core never interprets it |
| `type` | enum | one of the 8 types below |
| `frame_id` | string? | coordinate frame the data is expressed in |
| `unit` | string? | scalar channels |
| `nominal_rate_hz` | float? | |
| `message_count` | int | |
| `time_offset_ns` | int64 | default 0 |
| `metadata` | object | e.g. camera intrinsics, CAN message/signal names, `parent_frame`/`child_frame` for poses |

## Channel types (Arrow row schemas)

| Type | Columns | Notes |
|---|---|---|
| `scalar` | `t_ns, value:f64` | one signal per channel; decoded CAN signals are scalars |
| `pose` | `t_ns, x, y, z, qw, qx, qy, qz` | transform `parent_frame → child_frame`; ego pose is `map → ego` |
| `image` | `t_ns, blob, encoding, width, height` | `blob` is a path to the encoded image |
| `pointcloud` | `t_ns, blob` | blob is an Arrow/NPY table: `x, y, z` + optional `intensity, vx, vy, rcs, …` |
| `objects` | `t_ns, track_id?, class, score?, x, y, z, length, width, height, yaw, vx?, vy?, source` | long format, one row per object per timestamp; `source` = `ground_truth` or `detector:<name>` |
| `gps` | `t_ns, lat, lon, alt, fix, hdop?` | |
| `imu` | `t_ns, ax, ay, az, gx, gy, gz` (+ optional `qw, qx, qy, qz`) | |
| `event` | `t_ns, level, text, fields:json` | log messages, lap markers |

Columns marked `?` are nullable. Floats that are NaN in the source become null.

## Coordinate frames

- Reserved frames: `map` (global) and `ego` (vehicle body: +x forward, +y left, +z up, right-handed).
- Sensor frames are named by the adapter and connected to `ego` via `static_transforms`.
- Moving transforms are `pose` channels, looked up with interpolation (lerp for translation, slerp for rotation).
- Quaternions are always four named columns (`qw, qx, qy, qz`), never an ordered array.
- Adapters store data in its native frame and declare `frame_id`. The `to_ego` processor writes ego-frame copies of `objects` and `pointcloud` channels, which rules and the top-down view consume.
- All frame conversion goes through the geometry module.

## On-disk layout

```
data/sessions/<id>/
  session.json
  channels/<channel_id>.parquet        # sorted by t_ns, sized row groups
  channels/<channel_id>.lod/           # min/max pyramid for scalar channels
  blobs/<channel_id>/…                 # extracted images/clouds (+ previews), or refs into a dataset root
  derived/<processor>@<version>-<config_hash>/
data/catalog.duckdb                    # session index, alerts, alert evidence, scene graph tables
```
