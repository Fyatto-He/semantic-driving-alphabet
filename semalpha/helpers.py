"""Layer 1: numeric and geometric helpers. Never exposed to the automaton."""
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence, Tuple

import yaml
from shapely.geometry import LineString, Point, Polygon

INF = float("inf")


def load_thresholds(path: Path | str | None = None) -> SimpleNamespace:
    path = Path(path) if path else Path(__file__).with_name("thresholds.yaml")
    return SimpleNamespace(**yaml.safe_load(path.read_text(encoding="utf-8")))


def stopping_distance(speed: float, decel: float) -> float:
    return speed * speed / (2 * decel)


def time_to_cover(distance: float, speed: float, accel: float = 0.0, speed_cap: float = INF) -> float:
    """Seconds to travel `distance` from `speed`, accelerating at `accel` up to `speed_cap`.

    A car already faster than the cap is assumed to keep its speed (it is never assumed to slow).
    """
    if distance <= 0:
        return 0.0
    cap = max(speed_cap, speed)
    if accel <= 0 or speed >= cap:
        return distance / speed if speed > 0 else INF
    ramp = (cap * cap - speed * speed) / (2 * accel)       # distance needed to reach the cap
    if distance <= ramp:
        return (-speed + math.sqrt(speed * speed + 2 * accel * distance)) / accel
    return (cap - speed) / accel + (distance - ramp) / cap


def angle_diff(a: float, b: float) -> float:
    """Absolute difference between two angles, in radians, in [0, pi]."""
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def footprint(v) -> Polygon:
    """Rectangle occupied by a vehicle (anything with x, y, yaw, length, width)."""
    c, s = math.cos(v.yaw), math.sin(v.yaw)
    hl, hw = v.length / 2, v.width / 2
    return Polygon([
        (v.x + c * dx - s * dy, v.y + s * dx + c * dy)
        for dx, dy in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw))
    ])


class Polyline:
    """A centre line with distance-along / distance-from queries."""

    def __init__(self, points: Sequence[Tuple[float, float]]):
        clean = []
        for p in points:
            if not clean or math.dist(clean[-1], p) > 1e-6:
                clean.append((p[0], p[1]))
        self.line = LineString(clean)
        self.length = self.line.length

    def project(self, x: float, y: float) -> Tuple[float, float]:
        """(distance along the line, distance from it)."""
        p = Point(x, y)
        return self.line.project(p), self.line.distance(p)

    def point_at(self, s: float) -> Tuple[float, float]:
        p = self.line.interpolate(min(max(s, 0.0), self.length))
        return p.x, p.y

    def heading_at(self, s: float) -> float:
        a = self.point_at(s - 0.25)
        b = self.point_at(s + 0.25)
        return math.atan2(b[1] - a[1], b[0] - a[0])
