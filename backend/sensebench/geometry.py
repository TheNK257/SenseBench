"""The one geometry module: every frame conversion, distance and direction goes through here.

Conventions (see CLAUDE.md):

- Ego frame: +x forward, +y left, +z up (right-handed).
- Bearing = atan2(y, x) in degrees: 0 = straight ahead, +90 = left.
- Coarse direction uses 90 degree sectors: front [-45, 45], left (45, 135), right (-135, -45),
  behind otherwise.
- Rotations are unit quaternions held internally as arrays in (w, x, y, z) order. Build them from
  named components (`quat(qw=..., qx=..., ...)`); never pass bare 4-element arrays in from outside.
- A `Transform` for a `parent -> child` pose maps child-frame points into the parent frame:
  ``p_parent = T.apply(p_child)``. The ego pose (`map -> ego`) therefore takes ego points to the
  map, and its inverse takes global (map) points into the ego frame. That inverse applies both the
  translation and the inverse rotation; translation alone leaves map-aligned axes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

FRONT = "front"
LEFT = "left"
RIGHT = "right"
BEHIND = "behind"
DIRECTIONS = (FRONT, LEFT, RIGHT, BEHIND)

_NORM_EPS = 1e-9
# Above this |dot| two quaternions are close enough that slerp degenerates; lerp instead.
_SLERP_LERP_THRESHOLD = 0.9995


# --------------------------------------------------------------------------- quaternions


def quat(qw: float, qx: float, qy: float, qz: float) -> NDArray[np.float64]:
    """Unit quaternion from named components (normalized; rejects zero or non-finite input)."""
    return _normalize(np.array([qw, qx, qy, qz], dtype=np.float64))


def quat_from_yaw(yaw_rad: float) -> NDArray[np.float64]:
    """Rotation of `yaw_rad` about +z (counter-clockwise seen from above)."""
    half = 0.5 * yaw_rad
    return np.array([np.cos(half), 0.0, 0.0, np.sin(half)])


def quat_multiply(a: NDArray[np.float64], b: NDArray[np.float64]) -> NDArray[np.float64]:
    """Hamilton product `a * b` (apply `b` first, then `a`)."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ]
    )


def quat_conjugate(q: NDArray[np.float64]) -> NDArray[np.float64]:
    """Inverse of a unit quaternion."""
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_to_matrix(q: NDArray[np.float64]) -> NDArray[np.float64]:
    """3x3 rotation matrix of a unit quaternion."""
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def yaw_of(q: NDArray[np.float64]) -> float:
    """Heading (rotation about +z) of a unit quaternion, in radians in (-pi, pi]."""
    w, x, y, z = q
    return float(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def slerp(q0: NDArray[np.float64], q1: NDArray[np.float64], alpha: float) -> NDArray[np.float64]:
    """Spherical interpolation from `q0` (alpha=0) to `q1` (alpha=1) along the shortest arc."""
    dot = float(np.dot(q0, q1))
    if dot < 0.0:  # q and -q are the same rotation; flip to take the short way round
        q1 = -q1
        dot = -dot
    if dot > _SLERP_LERP_THRESHOLD:
        return _normalize(q0 + alpha * (q1 - q0))
    theta = np.arccos(dot) * alpha
    ortho = _normalize(q1 - q0 * dot)
    return q0 * np.cos(theta) + ortho * np.sin(theta)


def _normalize(q: NDArray[np.float64]) -> NDArray[np.float64]:
    norm = float(np.linalg.norm(q))
    if not np.isfinite(norm) or norm < _NORM_EPS:
        raise ValueError(f"not a valid rotation quaternion: {q!r}")
    return q / norm


# --------------------------------------------------------------------------- transforms


@dataclass(frozen=True, eq=False)
class Transform:
    """Rigid transform `parent -> child`: `apply` maps child-frame points into the parent frame."""

    translation: NDArray[np.float64]  # (3,)
    rotation: NDArray[np.float64]  # (4,) unit quaternion, (w, x, y, z)

    def __post_init__(self) -> None:
        t = np.array(self.translation, dtype=np.float64).reshape(3)
        r = _normalize(np.array(self.rotation, dtype=np.float64).reshape(4))
        t.setflags(write=False)
        r.setflags(write=False)
        object.__setattr__(self, "translation", t)
        object.__setattr__(self, "rotation", r)

    @classmethod
    def from_components(
        cls, x: float, y: float, z: float, qw: float, qx: float, qy: float, qz: float
    ) -> Transform:
        return cls(np.array([x, y, z]), quat(qw, qx, qy, qz))

    @classmethod
    def from_yaw(cls, x: float, y: float, yaw_rad: float, z: float = 0.0) -> Transform:
        return cls(np.array([x, y, z]), quat_from_yaw(yaw_rad))

    @classmethod
    def identity(cls) -> Transform:
        return cls(np.zeros(3), np.array([1.0, 0.0, 0.0, 0.0]))

    def rotation_matrix(self) -> NDArray[np.float64]:
        return quat_to_matrix(self.rotation)

    def inverse(self) -> Transform:
        """`child -> parent` counterpart: maps parent-frame points into the child frame."""
        inv_rot = quat_conjugate(self.rotation)
        return Transform(-(quat_to_matrix(inv_rot) @ self.translation), inv_rot)

    def compose(self, other: Transform) -> Transform:
        """`self` after `other`: for `a -> b` composed with `b -> c`, returns `a -> c`."""
        return Transform(
            self.translation + self.rotation_matrix() @ other.translation,
            quat_multiply(self.rotation, other.rotation),
        )

    __matmul__ = compose

    def apply(self, points: ArrayLike) -> NDArray[np.float64]:
        """Map points of shape (..., 3) from the child frame into the parent frame."""
        pts = np.asarray(points, dtype=np.float64)
        if pts.shape[-1] != 3:
            raise ValueError(f"points must have shape (..., 3), got {pts.shape}")
        return pts @ self.rotation_matrix().T + self.translation


def interpolate_transform(a: Transform, b: Transform, alpha: float) -> Transform:
    """Linear interpolation of translation and slerp of rotation; alpha=0 gives `a`."""
    return Transform(
        a.translation + alpha * (b.translation - a.translation),
        slerp(a.rotation, b.rotation, alpha),
    )


def to_ego(points_global: ArrayLike, ego_pose: Transform) -> NDArray[np.float64]:
    """Global (map-frame) points into the ego frame, given the `map -> ego` pose."""
    return ego_pose.inverse().apply(points_global)


class PoseSeries:
    """Time-ordered samples of one `parent -> child` transform, interpolated on lookup."""

    def __init__(self, t_ns: ArrayLike, translations: ArrayLike, rotations: ArrayLike) -> None:
        t = np.asarray(t_ns, dtype=np.int64).reshape(-1)
        trans = np.asarray(translations, dtype=np.float64)
        rots = np.asarray(rotations, dtype=np.float64)
        if t.size == 0:
            raise ValueError("PoseSeries needs at least one sample")
        if trans.shape != (t.size, 3) or rots.shape != (t.size, 4):
            raise ValueError(
                f"expected translations ({t.size}, 3) and rotations ({t.size}, 4), "
                f"got {trans.shape} and {rots.shape}"
            )
        if np.any(np.diff(t) <= 0):
            raise ValueError("timestamps must be strictly increasing")
        norms = np.linalg.norm(rots, axis=1)
        if not np.all(np.isfinite(norms)) or np.any(norms < _NORM_EPS):
            raise ValueError("rotations contain an invalid quaternion")
        self._t = t
        self._trans = trans
        self._rots = rots / norms[:, None]

    def __len__(self) -> int:
        return int(self._t.size)

    @property
    def start_ns(self) -> int:
        return int(self._t[0])

    @property
    def end_ns(self) -> int:
        return int(self._t[-1])

    def at(self, t_ns: int) -> Transform:
        """Pose at `t_ns`; raises LookupError outside the recorded range (no extrapolation)."""
        if t_ns < self._t[0] or t_ns > self._t[-1]:
            raise LookupError(
                f"t_ns={t_ns} is outside the pose range [{self._t[0]}, {self._t[-1]}]"
            )
        i = int(np.searchsorted(self._t, t_ns, side="right")) - 1
        if self._t[i] == t_ns:
            return Transform(self._trans[i], self._rots[i])
        alpha = float(t_ns - self._t[i]) / float(self._t[i + 1] - self._t[i])
        return interpolate_transform(
            Transform(self._trans[i], self._rots[i]),
            Transform(self._trans[i + 1], self._rots[i + 1]),
            alpha,
        )


# --------------------------------------------------------------------------- bearing and direction


def bearing_deg(x: ArrayLike, y: ArrayLike) -> NDArray[np.float64] | float:
    """Bearing in degrees of an ego-frame position: 0 = ahead, +90 = left, range (-180, 180]."""
    b = np.degrees(np.arctan2(np.asarray(y, dtype=np.float64), np.asarray(x, dtype=np.float64)))
    return float(b) if b.ndim == 0 else b


def direction_from_bearing(bearing: ArrayLike) -> NDArray[np.str_] | str:
    """Coarse direction (`front`, `left`, `right`, `behind`) of a bearing in degrees."""
    b = np.asarray(bearing, dtype=np.float64)
    if not np.all(np.isfinite(b)):
        raise ValueError("bearing must be finite")
    out = np.select(
        [(b >= -45.0) & (b <= 45.0), (b > 45.0) & (b < 135.0), (b > -135.0) & (b < -45.0)],
        [FRONT, LEFT, RIGHT],
        default=BEHIND,
    )
    return str(out) if out.ndim == 0 else out


def direction_of(x: ArrayLike, y: ArrayLike) -> NDArray[np.str_] | str:
    """Coarse direction of an ego-frame position."""
    return direction_from_bearing(bearing_deg(x, y))


def distance_xy(x: ArrayLike, y: ArrayLike) -> NDArray[np.float64] | float:
    """Planar distance from the ego origin of an ego-frame position."""
    d = np.hypot(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
    return float(d) if d.ndim == 0 else d


# --------------------------------------------------------------------------- GPS (geodetic <-> ENU)

WGS84_A = 6_378_137.0  # semi-major axis, m
WGS84_E2 = 6.694_379_990_14e-3  # first eccentricity squared


@dataclass(frozen=True)
class GeoOrigin:
    """Reference point of a local East-North-Up frame (x east, y north, z up)."""

    lat_deg: float
    lon_deg: float
    alt_m: float = 0.0

    def _radii(self) -> tuple[float, float]:
        """Meridian (north-south) and prime-vertical (east-west) radii of curvature, in m."""
        s = np.sin(np.radians(self.lat_deg))
        denom = 1.0 - WGS84_E2 * s * s
        meridian = WGS84_A * (1.0 - WGS84_E2) / denom**1.5
        prime_vertical = WGS84_A / np.sqrt(denom)
        return float(meridian), float(prime_vertical)


def geodetic_to_enu(
    lat_deg: ArrayLike, lon_deg: ArrayLike, alt_m: ArrayLike, origin: GeoOrigin
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """WGS84 latitude/longitude/altitude into local ENU metres around `origin`.

    Tangent-plane approximation: accurate to centimetres over a few kilometres (a track or test
    field), not for continental distances.
    """
    meridian, prime_vertical = origin._radii()
    dlat = np.radians(np.asarray(lat_deg, dtype=np.float64) - origin.lat_deg)
    dlon_deg = (np.asarray(lon_deg, dtype=np.float64) - origin.lon_deg + 180.0) % 360.0 - 180.0
    north = dlat * (meridian + origin.alt_m)
    east = (
        np.radians(dlon_deg) * (prime_vertical + origin.alt_m) * np.cos(np.radians(origin.lat_deg))
    )
    up = np.asarray(alt_m, dtype=np.float64) - origin.alt_m
    return east, north, up


def enu_to_geodetic(
    east: ArrayLike, north: ArrayLike, up: ArrayLike, origin: GeoOrigin
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Inverse of `geodetic_to_enu` (same tangent-plane approximation)."""
    meridian, prime_vertical = origin._radii()
    lat = origin.lat_deg + np.degrees(
        np.asarray(north, dtype=np.float64) / (meridian + origin.alt_m)
    )
    lon = origin.lon_deg + np.degrees(
        np.asarray(east, dtype=np.float64)
        / ((prime_vertical + origin.alt_m) * np.cos(np.radians(origin.lat_deg)))
    )
    lon = (lon + 180.0) % 360.0 - 180.0
    alt = origin.alt_m + np.asarray(up, dtype=np.float64)
    return lat, lon, alt
