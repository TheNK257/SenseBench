import csv
import json

import numpy as np
import pytest

from sensebench.synthetic import (
    COLUMNS,
    OVERHEAT_THRESHOLD_C,
    SLOW_COLUMNS,
    TIME_COLUMN,
    generate,
)


@pytest.fixture(scope="module")
def run():
    return generate(duration_s=600.0, rate_hz=100, seed=0)


def _fault(run, kind):
    (fault,) = [f for f in run.faults if f.kind == kind]
    return fault


def _window(run, fault, pad_s=0.0):
    return (run.time_s >= fault.start_s - pad_s) & (run.time_s <= fault.end_s + pad_s)


def test_same_seed_is_identical_and_different_seed_differs():
    a, b, c = generate(300, 100, seed=1), generate(300, 100, seed=1), generate(300, 100, seed=2)
    for name in COLUMNS:
        np.testing.assert_array_equal(a.signals[name], b.signals[name])
    assert not np.allclose(a.signals["wheel_speed_kmh"], c.signals["wheel_speed_kmh"])


def test_shape_rate_and_slow_channels(run):
    assert run.time_s.size == 60_000
    np.testing.assert_allclose(np.diff(run.time_s), 0.01)
    assert set(run.signals) == set(COLUMNS)
    for name in SLOW_COLUMNS:
        assert np.count_nonzero(~np.isnan(run.signals[name])) == 6_000  # 10 Hz


def test_values_are_physically_plausible(run):
    s = run.signals
    assert 30 < np.nanmean(s["wheel_speed_kmh"]) < 110
    assert np.nanmin(s["throttle_pct"]) >= 0 and np.nanmax(s["throttle_pct"]) <= 100
    assert np.nanmin(s["brake_pressure_bar"]) >= 0
    assert np.nanmax(np.abs(s["accel_y_g"])) < 2.0
    assert 20 < run.lap_time_s < 120


def test_overheat_is_the_only_time_above_threshold(run):
    fault = _fault(run, "overheat")
    temp = run.signals["motor_temp_c"]
    inside, outside = _window(run, fault), ~_window(run, fault, pad_s=2.0)
    assert np.nanmin(temp[inside]) > OVERHEAT_THRESHOLD_C - 0.5
    assert np.nanmax(temp[outside]) < OVERHEAT_THRESHOLD_C
    assert fault.end_s - fault.start_s > 30


def test_dropout_blanks_exactly_the_fault_window(run):
    fault = _fault(run, "dropout")
    brake = run.signals["brake_pressure_bar"]
    assert np.all(np.isnan(brake[_window(run, fault)]))
    assert not np.any(np.isnan(brake[~_window(run, fault)]))


def test_wheel_speed_disagrees_with_gps_only_during_mismatch(run):
    fault = _fault(run, "sensor_mismatch")
    gps = run.signals["gps_speed_kmh"]
    has_gps = ~np.isnan(gps)
    ratio = run.signals["wheel_speed_kmh"][has_gps] / gps[has_gps]
    inside = _window(run, fault)[has_gps]
    assert np.median(ratio[inside]) == pytest.approx(1.2, abs=0.02)
    assert np.median(ratio[~inside]) == pytest.approx(1.0, abs=0.02)


def test_brake_spike_rate_dwarfs_normal_braking(run):
    fault = _fault(run, "spike")
    rate = np.abs(np.diff(run.signals["brake_pressure_bar"])) * run.rate_hz  # bar/s
    near = _window(run, fault, pad_s=0.5)[1:]
    assert np.nanmax(rate[near]) > 5_000
    assert np.nanmax(rate[~near]) < 1_500


def test_write_produces_sparse_csv_and_ground_truth(tmp_path, run):
    csv_path, gt_path = run.write(tmp_path / "out")
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == [TIME_COLUMN, *COLUMNS]
    assert len(rows) == run.time_s.size + 1
    header = rows[0]
    gps_col = header.index("gps_lat")
    assert rows[1][gps_col] != "" and rows[2][gps_col] == ""  # slow column blank between samples

    truth = json.loads(gt_path.read_text(encoding="utf-8"))
    assert truth["clock"] == "relative" and truth["rate_hz"] == 100
    assert {f["kind"] for f in truth["faults"]} == {
        "overheat",
        "dropout",
        "sensor_mismatch",
        "spike",
    }
    assert truth["channels"]["motor_temp_c"] == {"unit": "degC", "rate_hz": 10}


@pytest.mark.parametrize(("duration", "rate"), [(299.0, 100), (600.0, 15), (600.0, 2000)])
def test_rejects_invalid_parameters(duration, rate):
    with pytest.raises(ValueError):
        generate(duration_s=duration, rate_hz=rate)
