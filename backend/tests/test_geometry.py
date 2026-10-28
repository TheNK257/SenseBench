import math

import numpy as np
import pytest

from sensebench.geometry import (
    BEHIND,
    FRONT,
    LEFT,
    RIGHT,
    GeoOrigin,
    PoseSeries,
    Transform,
    bearing_deg,
    direction_from_bearing,
    direction_of,
    distance_xy,
    enu_to_geodetic,
    geodetic_to_enu,
    quat,
    quat_from_yaw,
    slerp,
    to_ego,
    yaw_of,
)

# --------------------------------------------------------------------------- bearing / direction


def test_bearing_convention_zero_ahead_positive_left():
    assert bearing_deg(1, 0) == pytest.approx(0.0)
    assert bearing_deg(0, 1) == pytest.approx(90.0)
    assert bearing_deg(0, -1) == pytest.approx(-90.0)
    assert bearing_deg(-1, 0) == pytest.approx(180.0)


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [(1, 0, FRONT), (0, 1, LEFT), (0, -1, RIGHT), (-1, 0, BEHIND), (5, 0.1, FRONT)],
)
def test_direction_of_axes(x, y, expected):
    assert direction_of(x, y) == expected


@pytest.mark.parametrize(
    ("bearing", "expected"),
    [
        (45.0, FRONT),  # front is closed: [-45, 45]
        (-45.0, FRONT),
        (45.0001, LEFT),
        (134.9999, LEFT),
        (135.0, BEHIND),  # left is open at 135
        (-135.0, BEHIND),
        (-134.9999, RIGHT),
        (-45.0001, RIGHT),
        (180.0, BEHIND),
    ],
)
def test_direction_sector_boundaries(bearing, expected):
    assert direction_from_bearing(bearing) == expected


def test_direction_vectorized_returns_exactly_the_four_strings():
    angles = np.radians(np.arange(-179, 181))
    dirs = direction_of(np.cos(angles), np.sin(angles))
    assert isinstance(dirs, np.ndarray)
    assert set(dirs.tolist()) == {FRONT, LEFT, RIGHT, BEHIND}


def test_direction_rejects_nan_instead_of_guessing():
    with pytest.raises(ValueError):
        direction_from_bearing(float("nan"))


def test_distance_xy():
    assert distance_xy(3, 4) == pytest.approx(5.0)
    np.testing.assert_allclose(distance_xy([3, 0], [4, 2]), [5.0, 2.0])


# --------------------------------------------------------------------------- quaternions


def test_quat_normalizes_and_rejects_zero():
    np.testing.assert_allclose(quat(2, 0, 0, 0), [1, 0, 0, 0])
    with pytest.raises(ValueError):
        quat(0, 0, 0, 0)
    with pytest.raises(ValueError):
        quat(float("nan"), 0, 0, 0)


@pytest.mark.parametrize("yaw", [0.0, 0.3, -1.2, math.pi / 2, 3.0])
def test_yaw_roundtrip(yaw):
    assert yaw_of(quat_from_yaw(yaw)) == pytest.approx(yaw)


def test_slerp_endpoints_and_midpoint():
    q0, q1 = quat_from_yaw(0.0), quat_from_yaw(math.pi / 2)
    np.testing.assert_allclose(slerp(q0, q1, 0.0), q0, atol=1e-12)
    np.testing.assert_allclose(slerp(q0, q1, 1.0), q1, atol=1e-12)
    assert yaw_of(slerp(q0, q1, 0.5)) == pytest.approx(math.pi / 4)


def test_slerp_takes_shortest_path_when_quaternion_sign_flips():
    q0, q1 = quat_from_yaw(0.1), -quat_from_yaw(0.3)  # -q is the same rotation as q
    assert yaw_of(slerp(q0, q1, 0.5)) == pytest.approx(0.2)


# --------------------------------------------------------------------------- transforms


def test_global_to_ego_applies_rotation_not_just_translation():
    # Ego at (10, 5) facing map +y (yaw 90 deg). An object 3 m further along map +y is straight
    # AHEAD. Subtracting the translation alone would give (0, 3), i.e. "left": the classic bug.
    ego_pose = Transform.from_yaw(10.0, 5.0, math.pi / 2)
    local = to_ego([10.0, 8.0, 0.0], ego_pose)
    np.testing.assert_allclose(local, [3.0, 0.0, 0.0], atol=1e-12)
    assert direction_of(local[0], local[1]) == FRONT


def test_ego_points_to_global_and_back():
    ego_pose = Transform.from_components(4.0, -2.0, 1.0, *quat(0.9, 0.1, -0.2, 0.3))
    pts = np.array([[1.0, 2.0, 3.0], [-4.0, 0.5, 0.0]])
    np.testing.assert_allclose(to_ego(ego_pose.apply(pts), ego_pose), pts, atol=1e-12)


def test_inverse_composes_to_identity():
    t = Transform.from_components(1.0, 2.0, 3.0, *quat(0.5, 0.5, -0.5, 0.5))
    ident = t @ t.inverse()
    np.testing.assert_allclose(ident.translation, [0, 0, 0], atol=1e-12)
    np.testing.assert_allclose(np.abs(ident.rotation), [1, 0, 0, 0], atol=1e-12)


def test_compose_chains_parent_child_transforms():
    # map -> ego, then ego -> sensor: a sensor point reaches the map through both.
    map_ego = Transform.from_yaw(10.0, 0.0, math.pi / 2)
    ego_sensor = Transform.from_yaw(2.0, 0.0, 0.0)
    map_sensor = map_ego @ ego_sensor
    p_sensor = np.array([1.0, 0.0, 0.0])
    np.testing.assert_allclose(map_sensor.apply(p_sensor), [10.0, 3.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(
        map_sensor.apply(p_sensor), map_ego.apply(ego_sensor.apply(p_sensor)), atol=1e-12
    )


def test_apply_handles_batches_and_rejects_bad_shape():
    t = Transform.from_yaw(1.0, 1.0, 0.0)
    assert t.apply(np.zeros((5, 7, 3))).shape == (5, 7, 3)
    with pytest.raises(ValueError):
        t.apply(np.zeros((4, 2)))


def test_transform_is_immutable():
    t = Transform.identity()
    with pytest.raises(ValueError):
        t.translation[0] = 1.0


# --------------------------------------------------------------------------- pose series


def _series() -> PoseSeries:
    return PoseSeries(
        t_ns=[0, 1_000_000_000],
        translations=[[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]],
        rotations=[quat_from_yaw(0.0), quat_from_yaw(math.pi / 2)],
    )


def test_pose_series_interpolates_translation_and_rotation():
    mid = _series().at(500_000_000)
    np.testing.assert_allclose(mid.translation, [5.0, 0.0, 0.0])
    assert yaw_of(mid.rotation) == pytest.approx(math.pi / 4)


def test_pose_series_exact_sample_and_bounds():
    s = _series()
    np.testing.assert_allclose(s.at(1_000_000_000).translation, [10.0, 0.0, 0.0])
    assert (s.start_ns, s.end_ns, len(s)) == (0, 1_000_000_000, 2)
    with pytest.raises(LookupError):
        s.at(-1)
    with pytest.raises(LookupError):
        s.at(1_000_000_001)


def test_pose_series_validates_input():
    with pytest.raises(ValueError):
        PoseSeries([1, 0], [[0, 0, 0], [0, 0, 0]], [[1, 0, 0, 0], [1, 0, 0, 0]])
    with pytest.raises(ValueError):
        PoseSeries([0, 1], [[0, 0, 0]], [[1, 0, 0, 0], [1, 0, 0, 0]])
    with pytest.raises(ValueError):
        PoseSeries([0], [[0, 0, 0]], [[0, 0, 0, 0]])


# --------------------------------------------------------------------------- GPS


def test_one_degree_of_latitude_is_about_111_km():
    origin = GeoOrigin(48.0, 11.0)
    _, north, _ = geodetic_to_enu(49.0, 11.0, 0.0, origin)
    assert float(north) == pytest.approx(111_200, rel=0.005)


def test_enu_geodetic_roundtrip_at_track_scale():
    origin = GeoOrigin(48.0, 11.0, 500.0)
    east = np.array([0.0, 250.0, -800.0])
    north = np.array([0.0, -400.0, 1200.0])
    up = np.array([0.0, 1.0, -2.0])
    e2, n2, u2 = geodetic_to_enu(*enu_to_geodetic(east, north, up, origin), origin)
    np.testing.assert_allclose(e2, east, atol=1e-6)
    np.testing.assert_allclose(n2, north, atol=1e-6)
    np.testing.assert_allclose(u2, up, atol=1e-9)


def test_geodetic_handles_antimeridian():
    origin = GeoOrigin(0.0, 179.9999)
    east, _, _ = geodetic_to_enu(0.0, -179.9999, 0.0, origin)
    assert float(east) == pytest.approx(22.3, abs=0.1)  # 0.0002 deg east, not 360 deg west
