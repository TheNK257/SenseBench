import math

import numpy as np

from sensebench.geometry import PoseSeries, Transform, direction_of, quat_from_yaw, to_ego

N_POINTS = 1_000_000


def test_to_ego_1m_points(within_budget):
    points = np.random.default_rng(0).uniform(-100, 100, (N_POINTS, 3))
    pose = Transform.from_yaw(12.0, -4.0, 0.7)
    within_budget(to_ego, points, pose)


def test_direction_1m_points(within_budget):
    xy = np.random.default_rng(0).uniform(-100, 100, (2, N_POINTS))
    within_budget(direction_of, xy[0], xy[1])


def test_pose_lookup(within_budget):
    n = 100_000  # ~3 h of ego poses at 10 Hz
    t = np.arange(n, dtype=np.int64) * 100_000_000
    yaws = np.linspace(0, 20 * math.pi, n)
    series = PoseSeries(
        t, np.c_[np.arange(n), np.zeros(n), np.zeros(n)], [quat_from_yaw(y) for y in yaws]
    )
    within_budget(series.at, int(t[n // 2] + 37_000_000))
