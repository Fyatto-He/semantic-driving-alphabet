"""Who drives the ego.

Two sources of trajectories:

* ``"sumo"`` : SUMO's own driver model drives the ego as ordinary traffic. It obeys signs,
  signals and right of way, so it serves as a rule-following reference driver.
* a :class:`Script` : the ego is a SMARTS agent following an open-loop speed script. The
  script never looks at other traffic. That is deliberate: it lets us stage behaviour a
  rule-following driver would not produce (running a stop sign, entering a gap that is too
  small, waiting longer than needed) without the driver depending on the very labels we are
  trying to validate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from semalpha.mapinfo import MapInfo, RoutePath

SUMO = "sumo"


@dataclass(frozen=True)
class Hold:
    """Stop at a point on the route and stay there until a given simulation time."""

    at: str        # "entry": stop/yield line of the junction; "waiting_point": in-junction waiting position
    until: float   # seconds
    junction: int = 0  # which junction along the route (0 = first)


@dataclass(frozen=True)
class Script:
    why: str                       # what this script is meant to show
    cruise: float = 8.0            # m/s
    holds: Tuple[Hold, ...] = ()


class ScriptedDriver:
    """Turns a :class:`Script` into ``LaneWithContinuousSpeed`` actions."""

    DECEL = 2.0         # m/s^2 used to plan stops and slow-downs
    STOP_MARGIN = 1.0   # m between the front bumper and the hold point
    TURN_SPEED = 0.8    # fraction of an internal lane's speed limit to drive at

    def __init__(self, mapinfo: MapInfo, path: RoutePath, script: Script):
        self.mapinfo = mapinfo
        self.path = path
        self.script = script
        self._hold_s = []
        for hold in script.holds:
            j = path.junctions[hold.junction]
            s = j.entry_s if hold.at == "entry" else j.waiting_s
            if s is None:
                raise ValueError(f"junction {j.link.junction} has no waiting point on this route")
            self._hold_s.append((s, hold.until))
        # speed limits of the slow (in-junction) stretches of the route
        self._slow = [
            (path.starts[i], self.TURN_SPEED * mapinfo.speed_limit(lane))
            for i, lane in enumerate(path.lanes) if mapinfo.is_internal(lane)
        ]

    def act(self, obs) -> Tuple[float, int]:
        ego = obs.ego_vehicle_state
        s, _ = self.path.locate(ego.position[0], ego.position[1])
        front = s + ego.bounding_box.length / 2
        speed = self.script.cruise
        lane = self.path.lane_at(s)
        if self.mapinfo.is_internal(lane):
            speed = min(speed, self.TURN_SPEED * self.mapinfo.speed_limit(lane))
        for start, limit in self._slow:          # slow down in time for upcoming turns
            if start > front:
                speed = min(speed, (limit ** 2 + 2 * self.DECEL * (start - front)) ** 0.5)
        for hold_s, until in self._hold_s:
            gap = hold_s - front - self.STOP_MARGIN
            if obs.elapsed_sim_time < until and gap > -2.0:   # not released, not already past it
                speed = min(speed, (2 * self.DECEL * max(gap, 0.0)) ** 0.5)
                if gap < 0.3:
                    speed = 0.0
        return float(speed), 0
