"""Synthetic Formula-Student-style run with known injected faults.

Produces a wide CSV the way many team data loggers do (one time column, one column per signal,
slow signals left blank between their samples) plus `ground_truth.json` listing every injected
fault with its exact time interval. Alert rules can then be tested against known answers, and a
long generated run drives the performance benchmarks.

The car laps a closed track. Its speed comes from a curvature-limited profile (lateral grip, then
acceleration and braking limits), so wheel speed, GPS track, throttle, brake, steering and
accelerations are mutually consistent; only the injected faults break that consistency.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from sensebench.geometry import GeoOrigin, enu_to_geodetic

SLOW_RATE_HZ = 10
MIN_DURATION_S = 300.0
OVERHEAT_THRESHOLD_C = 80.0

TIME_COLUMN = "time_s"
# column -> unit; every signal is one scalar channel once imported
COLUMNS: dict[str, str] = {
    "wheel_speed_kmh": "km/h",
    "throttle_pct": "%",
    "brake_pressure_bar": "bar",
    "steering_deg": "deg",
    "accel_x_g": "g",
    "accel_y_g": "g",
    "gps_lat": "deg",
    "gps_lon": "deg",
    "gps_speed_kmh": "km/h",
    "motor_temp_c": "degC",
    "battery_voltage_v": "V",
}
SLOW_COLUMNS = frozenset(
    {"gps_lat", "gps_lon", "gps_speed_kmh", "motor_temp_c", "battery_voltage_v"}
)
_CSV_FORMATS = {"gps_lat": "%.7f", "gps_lon": "%.7f"}  # default "%.3f"

DEFAULT_ORIGIN = GeoOrigin(lat_deg=48.0, lon_deg=11.0, alt_m=500.0)

G = 9.81
V_MAX = 28.0  # m/s
A_LAT_MAX = 1.5 * G
A_ACCEL_MAX = 0.6 * G
A_BRAKE_MAX = 1.3 * G
BRAKE_PRESSURE_MAX_BAR = 60.0
PEDAL_SMOOTHING_S = 0.15  # drivers ramp pedals; keeps normal brake rate far below a fault spike
WHEELBASE_M = 1.53
STEERING_RATIO = 5.0

AMBIENT_C = 25.0
START_TEMP_C = 40.0
NORMAL_EQUILIBRIUM_C = 55.0
COOLING_TAU_S = 60.0
THERMAL_LOAD_WINDOW_S = 30.0
FAULTED_COOLING_FACTOR = 0.1  # cooling-system failure: 10% of normal heat rejection
OVERHEAT_WINDOW_S = 120.0

DROPOUT_S = 3.0
MISMATCH_S = 15.0
MISMATCH_GAIN = 1.2
SPIKE_S = 0.05
SPIKE_BAR = 80.0


@dataclass(frozen=True)
class Fault:
    kind: str  # overheat | dropout | sensor_mismatch | spike
    channels: tuple[str, ...]
    start_s: float  # first affected sample
    end_s: float  # last affected sample
    description: str


@dataclass
class SyntheticRun:
    time_s: NDArray[np.float64]
    signals: dict[str, NDArray[np.float64]]  # NaN where a slow signal has no sample or drops out
    faults: list[Fault]
    rate_hz: int
    seed: int
    lap_time_s: float
    origin: GeoOrigin

    @property
    def duration_s(self) -> float:
        return float(self.time_s[-1] + 1.0 / self.rate_hz)

    def ground_truth(self) -> dict:
        return {
            "generator": "sensebench.synthetic",
            "format_version": 1,
            "seed": self.seed,
            "duration_s": self.duration_s,
            "rate_hz": self.rate_hz,
            "slow_rate_hz": SLOW_RATE_HZ,
            "lap_time_s": self.lap_time_s,
            "clock": "relative",
            "time_column": TIME_COLUMN,
            "origin": asdict(self.origin),
            "channels": {
                name: {
                    "unit": unit,
                    "rate_hz": SLOW_RATE_HZ if name in SLOW_COLUMNS else self.rate_hz,
                }
                for name, unit in COLUMNS.items()
            },
            "faults": [asdict(f) for f in self.faults],
        }

    def write(self, out_dir: Path) -> tuple[Path, Path]:
        """Write `run.csv` and `ground_truth.json` into `out_dir`; returns both paths."""
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "run.csv"
        gt_path = out_dir / "ground_truth.json"

        columns = [np.char.mod("%.3f", self.time_s)]
        for name in COLUMNS:
            values = self.signals[name]
            text = np.char.mod(_CSV_FORMATS.get(name, "%.3f"), values)
            text[np.isnan(values)] = ""
            columns.append(text)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            f.write(",".join([TIME_COLUMN, *COLUMNS]) + "\n")
            f.writelines(",".join(row) + "\n" for row in zip(*columns, strict=True))

        gt_path.write_text(json.dumps(self.ground_truth(), indent=2) + "\n", encoding="utf-8")
        return csv_path, gt_path


def generate(duration_s: float = 600.0, rate_hz: int = 100, seed: int = 0) -> SyntheticRun:
    """Generate a deterministic run of `duration_s` seconds sampled at `rate_hz`."""
    if duration_s < MIN_DURATION_S:
        raise ValueError(f"duration_s must be at least {MIN_DURATION_S} s to fit every fault")
    if rate_hz % SLOW_RATE_HZ or not SLOW_RATE_HZ <= rate_hz <= 1000:
        raise ValueError(f"rate_hz must be a multiple of {SLOW_RATE_HZ} between 10 and 1000")

    rng = np.random.default_rng(seed)
    n = int(round(duration_s * rate_hz))
    t = np.arange(n) / rate_hz
    dt = 1.0 / rate_hz

    east, north, speed, curvature, lap_time = _drive(t)

    # Longitudinal acceleration with pedal-like smoothing, then the derived signals.
    a_long = _smooth(np.gradient(speed, dt), int(round(PEDAL_SMOOTHING_S * rate_hz)))
    a_lat = speed**2 * curvature
    throttle = np.where(a_long > -0.5, np.clip(25.0 + 75.0 * a_long / A_ACCEL_MAX, 0, 100), 0.0)
    brake = np.where(
        a_long < -0.5, np.clip(-a_long / A_BRAKE_MAX, 0, 1) * BRAKE_PRESSURE_MAX_BAR, 0.0
    )

    signals: dict[str, NDArray[np.float64]] = {
        "wheel_speed_kmh": speed * 3.6 + rng.normal(0, 0.3, n),
        "throttle_pct": np.clip(throttle + rng.normal(0, 0.5, n), 0, 100),
        "brake_pressure_bar": np.clip(brake + rng.normal(0, 0.1, n), 0, None),
        "steering_deg": np.degrees(np.arctan(WHEELBASE_M * curvature)) * STEERING_RATIO
        + rng.normal(0, 0.2, n),
        "accel_x_g": a_long / G + rng.normal(0, 0.02, n),
        "accel_y_g": a_lat / G + rng.normal(0, 0.02, n),
    }

    # Slow channels: computed on their own 10 Hz grid, blank in between.
    step = rate_hz // SLOW_RATE_HZ
    slow_idx = np.arange(0, n, step)
    t_slow = t[slow_idx]
    load = (throttle / 100.0) * (speed / V_MAX)  # 0..1 motor load proxy

    overheat_start = 0.2 * duration_s
    cooling_fault = (t_slow >= overheat_start) & (t_slow < overheat_start + OVERHEAT_WINDOW_S)
    temp_clean = _motor_temperature(load[slow_idx], cooling_fault, 1.0 / SLOW_RATE_HZ)
    over = np.flatnonzero(temp_clean > OVERHEAT_THRESHOLD_C)
    if over.size == 0 or np.any(np.diff(over) != 1):
        raise RuntimeError("overheat fault did not produce exactly one over-threshold interval")

    lat, lon, _ = enu_to_geodetic(
        east[slow_idx] + rng.normal(0, 0.5, slow_idx.size),
        north[slow_idx] + rng.normal(0, 0.5, slow_idx.size),
        np.zeros(slow_idx.size),
        DEFAULT_ORIGIN,
    )
    energy_used = np.cumsum(load[slow_idx]) / SLOW_RATE_HZ
    slow_values = {
        "gps_lat": lat,
        "gps_lon": lon,
        "gps_speed_kmh": speed[slow_idx] * 3.6 + rng.normal(0, 0.5, slow_idx.size),
        "motor_temp_c": temp_clean + rng.normal(0, 0.1, slow_idx.size),
        "battery_voltage_v": 580.0
        - 0.03 * energy_used
        - 20.0 * load[slow_idx]
        + rng.normal(0, 0.2, slow_idx.size),
    }
    for name, values in slow_values.items():
        full = np.full(n, np.nan)
        full[slow_idx] = values
        signals[name] = full

    faults = [
        Fault(
            kind="overheat",
            channels=("motor_temp_c",),
            start_s=float(t_slow[over[0]]),
            end_s=float(t_slow[over[-1]]),
            description=(
                f"cooling degraded to {FAULTED_COOLING_FACTOR:.0%} from {overheat_start:.1f} s "
                f"for {OVERHEAT_WINDOW_S:.0f} s; interval is where the noise-free temperature "
                f"exceeds {OVERHEAT_THRESHOLD_C:.0f} degC"
            ),
        ),
        _inject_dropout(signals, t, 0.55 * duration_s),
        _inject_mismatch(signals, t, 0.7 * duration_s),
        _inject_spike(signals, t, 0.85 * duration_s),
    ]
    return SyntheticRun(t, signals, faults, rate_hz, seed, lap_time, DEFAULT_ORIGIN)


# --------------------------------------------------------------------------- faults


def _inject_dropout(signals: dict[str, NDArray], t: NDArray, start: float) -> Fault:
    mask = (t >= start) & (t < start + DROPOUT_S)
    signals["brake_pressure_bar"][mask] = np.nan
    return _fault("dropout", ("brake_pressure_bar",), t, mask, "brake pressure sensor stops")


def _inject_mismatch(signals: dict[str, NDArray], t: NDArray, start: float) -> Fault:
    mask = (t >= start) & (t < start + MISMATCH_S)
    signals["wheel_speed_kmh"][mask] *= MISMATCH_GAIN
    return _fault(
        "sensor_mismatch",
        ("wheel_speed_kmh", "gps_speed_kmh"),
        t,
        mask,
        f"wheel speed reads x{MISMATCH_GAIN} (sensor gain fault); GPS speed unaffected",
    )


def _inject_spike(signals: dict[str, NDArray], t: NDArray, start: float) -> Fault:
    mask = (t >= start) & (t < start + SPIKE_S)
    signals["brake_pressure_bar"][mask] += SPIKE_BAR
    return _fault(
        "spike", ("brake_pressure_bar",), t, mask, f"+{SPIKE_BAR:.0f} bar brake pressure spike"
    )


def _fault(kind: str, channels: tuple[str, ...], t: NDArray, mask: NDArray, desc: str) -> Fault:
    idx = np.flatnonzero(mask)
    return Fault(kind, channels, float(t[idx[0]]), float(t[idx[-1]]), desc)


# --------------------------------------------------------------------------- vehicle model


def _drive(t: NDArray[np.float64]) -> tuple[NDArray, NDArray, NDArray, NDArray, float]:
    """Position (east, north), speed and signed curvature at times `t` while lapping the track."""
    x, y, curvature, ds = _track()
    v = _speed_profile(curvature, ds)

    # Time at each track point; the run starts on the line at racing speed ("flying lap").
    v_next = np.roll(v, -1)
    t_track = np.concatenate([[0.0], np.cumsum(ds / (0.5 * (v + v_next)))])
    lap_time = float(t_track[-1])
    tau = np.mod(t, lap_time)

    def along(values: NDArray) -> NDArray:
        return np.interp(tau, t_track, np.append(values, values[0]))

    return along(x), along(y), along(v), along(curvature), lap_time


def _arc(radius_m: float, angle_deg: float) -> tuple[float, float]:
    """Corner segment as (length, signed curvature); positive angle turns left."""
    return float(np.radians(abs(angle_deg)) * radius_m), float(np.sign(angle_deg) / radius_m)


# One lap as (length m, signed curvature 1/m) segments; curvature 0 is a straight. Straight
# lengths are nominal: `_close_lap` adjusts them so the lap ends where it started.
LAP_SEGMENTS = [
    (80.0, 0.0),  # east
    _arc(20, 90),
    (40.0, 0.0),  # north
    _arc(12, 90),
    (60.0, 0.0),  # west
    _arc(12, -45),  # chicane
    _arc(12, 90),
    _arc(12, -45),
    (40.0, 0.0),  # west
    _arc(9, 180),  # hairpin
    (30.0, 0.0),  # east
    _arc(15, -90),
    (25.0, 0.0),  # south
    _arc(25, 90),
]
TRACK_DS_M = 0.25
CURVATURE_SMOOTHING_M = 3.0  # corners ease in and out instead of a step in steering
MIN_STRAIGHT_M = 5.0


def _close_lap(segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Adjust straight lengths (minimum-norm change) so the lap's end point equals its start."""
    heading = 0.0
    arc_displacement = np.zeros(2)
    straight_dirs, straight_idx = [], []
    for i, (length, k) in enumerate(segments):
        if k == 0.0:
            straight_dirs.append([np.cos(heading), np.sin(heading)])
            straight_idx.append(i)
        else:
            turn = k * length
            arc_displacement += [
                (np.sin(heading + turn) - np.sin(heading)) / k,
                (np.cos(heading) - np.cos(heading + turn)) / k,
            ]
            heading += turn
    dirs = np.array(straight_dirs).T  # (2, n_straights)
    nominal = np.array([segments[i][0] for i in straight_idx])
    residual = -arc_displacement - dirs @ nominal
    lengths = nominal + dirs.T @ np.linalg.solve(dirs @ dirs.T, residual)
    if np.any(lengths < MIN_STRAIGHT_M):
        raise ValueError(f"lap segments cannot be closed with positive straights: {lengths}")
    closed = list(segments)
    for i, length in zip(straight_idx, lengths, strict=True):
        closed[i] = (float(length), 0.0)
    return closed


def _track() -> tuple[NDArray, NDArray, NDArray, NDArray]:
    """Closed lap sampled every TRACK_DS_M: x (east), y (north), signed curvature, segment ds."""
    segments = _close_lap(LAP_SEGMENTS)
    counts = [max(1, round(length / TRACK_DS_M)) for length, _ in segments]
    curvature = np.repeat([k for _, k in segments], counts)
    window = int(round(CURVATURE_SMOOTHING_M / TRACK_DS_M))
    curvature = np.convolve(
        np.concatenate([curvature[-window:], curvature, curvature[:window]]),
        np.ones(window) / window,
        mode="same",
    )[window:-window]  # circular smoothing keeps the total turning angle
    curvature *= 2.0 * np.pi / (curvature.sum() * TRACK_DS_M)  # undo rounding: exactly one turn

    heading = np.concatenate([[0.0], np.cumsum(curvature * TRACK_DS_M)[:-1]])
    step_x, step_y = np.cos(heading) * TRACK_DS_M, np.sin(heading) * TRACK_DS_M
    x = np.concatenate([[0.0], np.cumsum(step_x)[:-1]])
    y = np.concatenate([[0.0], np.cumsum(step_y)[:-1]])
    # Discretization leaves the lap a few cm open; spread that gap evenly along the lap.
    frac = np.arange(x.size) / x.size
    x -= frac * step_x.sum()
    y -= frac * step_y.sum()
    ds = np.hypot(np.roll(x, -1) - x, np.roll(y, -1) - y)
    return x, y, curvature, ds


def _speed_profile(curvature: NDArray, ds: NDArray) -> NDArray:
    """Grip-limited speed, then acceleration (forward) and braking (backward) limits on the loop."""
    v = np.minimum(V_MAX, np.sqrt(A_LAT_MAX / np.maximum(np.abs(curvature), 1e-6)))
    n = v.size
    for _ in range(2):  # two passes so the limits wrap correctly around the closed loop
        for i in range(n):
            j = (i + 1) % n
            v[j] = min(v[j], np.sqrt(v[i] ** 2 + 2 * A_ACCEL_MAX * ds[i]))
    for _ in range(2):
        for i in range(n - 1, -1, -1):
            j = (i + 1) % n
            v[i] = min(v[i], np.sqrt(v[j] ** 2 + 2 * A_BRAKE_MAX * ds[i]))
    return v


def _motor_temperature(load: NDArray, cooling_fault: NDArray, dt: float) -> NDArray:
    """First-order thermal model; heating is scaled so normal running settles near 55 degC.

    Heating follows load averaged over `THERMAL_LOAD_WINDOW_S` (the motor's thermal mass), so
    per-corner load swings don't make the temperature wobble back and forth across a threshold.
    """
    load = _smooth(load, int(round(THERMAL_LOAD_WINDOW_S / dt)))
    k_cool = 1.0 / COOLING_TAU_S
    k_heat = (NORMAL_EQUILIBRIUM_C - AMBIENT_C) * k_cool / max(float(load.mean()), 1e-3)
    k_cool_now = np.where(cooling_fault, k_cool * FAULTED_COOLING_FACTOR, k_cool)
    temp = np.empty(load.size)
    current = START_TEMP_C
    for i in range(load.size):
        temp[i] = current
        current += dt * (k_heat * load[i] - k_cool_now[i] * (current - AMBIENT_C))
    return temp


def _smooth(values: NDArray, window: int) -> NDArray:
    if window <= 1:
        return values
    padded = np.pad(values, (window // 2, window - 1 - window // 2), mode="edge")
    return np.convolve(padded, np.ones(window) / window, mode="valid")
