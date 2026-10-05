"""Layer 2: relational predicates, evaluated for one frame.

A :class:`Scene` holds what depends only on the map and the ego's route. ``scene.view(frame)``
gives a :class:`View` with the relational facts of that frame; ``predicates.py`` turns
those into the propositions the automaton sees.

Other cars are judged from position, heading, speed and size only. Their routes are
unknown, so a car that could still take several movements is treated as possibly taking
any of them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

from shapely.geometry import Point
from shapely.ops import substring, unary_union

from semalpha import EGO
from semalpha.helpers import INF, Polyline, angle_diff, footprint, stopping_distance, time_to_cover
from semalpha.mapinfo import JunctionOnRoute, Link, MapInfo
from semalpha.record import Frame, Vehicle

SIGNAL_OPEN = ("GO", "CAUTION")   # for right of way, yellow counts as go


@dataclass(frozen=True)
class Region:
    """A junction as the driver experiences it. A roundabout's whole ring is one region."""

    parts: Tuple[JunctionOnRoute, ...]     # the SUMO junctions on the ego's route, in route order
    scope: Tuple[str, ...]                 # every junction of the region (a roundabout: all its nodes)
    meets: Tuple[Tuple[Link, float], ...]  # (other movement, where the ego's path first shares road with it)

    @property
    def entry_s(self) -> float:
        return self.parts[0].entry_s

    @property
    def exit_s(self) -> float:
        return self.parts[-1].exit_s

    @property
    def entry_link(self) -> Link:
        return self.parts[0].link

@dataclass(frozen=True)
class Conflict:
    """R7 path_conflict: one way another car's possible path meets the ego's remaining path."""

    other: str
    ego_movement: Link
    movement: Link      # the movement the other car may be making
    ego_in: float       # the shared area, in metres along the ego's route
    ego_out: float
    dist_in: float      # other car's front to the start of the shared area (<= 0: already in it)
    dist_out: float     # other car's rear to the point beyond which it is past the ego's path
    speed: float        # other car's speed
    inside: bool        # other car's front is past its own entry line


class Scene:
    def __init__(self, mapinfo: MapInfo, ego_route, thresholds: SimpleNamespace, ego_end: float = 70.0):
        self.mapinfo = mapinfo
        self.th = thresholds
        self.path = mapinfo.route_path(ego_route)
        self.route = Polyline(list(self.path.line.coords))
        self.goal_s = self.path.starts[-1] + ego_end
        self._lines: Dict[Tuple[str, int], Polyline] = {}
        self._shared: Dict[Tuple[str, int, int], Tuple[float, float, float, float]] = {}
        self.regions = self._build_regions()
        self.junction_area = {n: mapinfo.junction_polygon(n) for r in self.regions for n in r.scope}
        self.approach_lanes = {
            r: {lane: Polyline(mapinfo.lane_shape(lane)) for n in r.scope for lane in mapinfo.lanes_into(n)}
            for r in self.regions
        }
        self._lane_length: Dict[str, float] = {}
        strips = [
            Polyline(mapinfo.lane_shape(l)).line.buffer(mapinfo.lane_width(l) / 2, cap_style="flat")
            for l in mapinfo.all_lanes() if len(mapinfo.lane_shape(l)) > 1
        ]
        areas = [mapinfo.junction_polygon(j) for j in mapinfo._links_by_junction]
        self.road = unary_union(strips + areas).buffer(0.3)

    # ---- static geometry ------------------------------------------------------------------

    def line(self, link: Link) -> Polyline:
        key = (link.junction, link.index)
        if key not in self._lines:
            self._lines[key] = Polyline(self.mapinfo.link_points(link))
        return self._lines[key]

    def lane_length(self, lane: str) -> float:
        if lane not in self._lane_length:
            self._lane_length[lane] = Polyline(self.mapinfo.lane_shape(lane)).length
        return self._lane_length[lane]

    def shared(self, ego: Link, other: Link) -> Tuple[float, float, float, float]:
        """Where the ego's movement and another movement share road.

        Returns (ego_in, ego_out, other_in, other_past), each measured from that movement's
        own entry line. Two paths share road where their centre lines are closer than two
        half-widths. Crossing paths: each car is past once beyond the far end of that
        stretch. Merging paths stay together to the end of the junction, so the ego is past
        only when it has left the junction, while the other car is past as soon as it is
        wholly beyond the point where the paths join (from there it is a car ahead in the
        ego's lane, not a crossing car).
        """
        key = (ego.junction, ego.index, other.index)
        if key not in self._shared:
            merge = ego.to_lane == other.to_lane
            ego_in, ego_out = self._overlap(self.line(ego), self.line(other), merge)
            other_in, other_out = self._overlap(self.line(other), self.line(ego), False)
            self._shared[key] = (ego_in, ego_out, other_in, other_in if merge else other_out)
        return self._shared[key]

    def _overlap(self, line: Polyline, other: Polyline, merge: bool) -> Tuple[float, float]:
        reach = 2 * self.th.conflict_half_width_m
        n = max(1, int(line.length / 0.25))
        samples = [i * line.length / n for i in range(n + 1)]
        dists = [other.line.distance(Point(*line.point_at(s))) for s in samples]
        close = [s for s, d in zip(samples, dists) if d < reach]
        if close:
            lo, hi = close[0], close[-1]
        else:   # marked as conflicting by the map but never that close: use the nearest point
            nearest = samples[dists.index(min(dists))]
            lo, hi = nearest - reach / 2, nearest + reach / 2
        return lo, (line.length if merge else hi)

    def _build_regions(self) -> List[Region]:
        groups: List[List[JunctionOnRoute]] = []
        for part in self.path.junctions:
            prev = groups[-1][-1] if groups else None
            on_ring = prev is not None and prev.link.to_lane.rsplit("_", 1)[0] in self.mapinfo.roundabout_edges
            if on_ring:
                groups[-1].append(part)
            else:
                groups.append([part])
        regions = []
        for parts in groups:
            nodes = tuple(p.link.junction for p in parts)
            scope = self.mapinfo.roundabout_nodes(nodes[0]) or nodes
            meets = tuple(
                (other, part.entry_s + self.shared(part.link, other)[0])
                for part in parts
                for other in self.mapinfo.links(part.link.junction)
                if self.mapinfo.paths_cross(part.link, other)
            )
            regions.append(Region(tuple(parts), scope, meets))
        return regions

    def view(self, frame: Frame) -> "View":
        return View(self, frame)


class View:
    """Relational facts for one frame."""

    def __init__(self, scene: Scene, frame: Frame):
        self.scene, self.frame, self.th = scene, frame, scene.th
        self.ego: Vehicle = frame.vehicles[EGO]
        self.others: Dict[str, Vehicle] = {k: v for k, v in frame.vehicles.items() if k != EGO}
        self.s, _ = scene.path.locate(self.ego.x, self.ego.y)
        self.front = self.s + self.ego.length / 2
        self.rear = self.s - self.ego.length / 2
        # the junction ahead of, or around, the ego: the first one its rear has not left
        self.region: Optional[Region] = next((r for r in scene.regions if r.exit_s > self.rear), None)

    # ---- ego versus the junction (R1-R4, R13) ---------------------------------------------

    @property
    def dist_to_entry(self) -> float:
        """Front bumper to the entry line; negative once past it."""
        return self.region.entry_s - self.front if self.region else INF

    @property
    def inside(self) -> bool:                       # R3 in_junction(ego, J)
        return self.region is not None and self.front > self.region.entry_s

    @property
    def at_entry(self) -> bool:                     # R2 at_entry(ego, J)
        return 0 <= self.dist_to_entry <= self.th.entry_tolerance_m

    @property
    def approaching(self) -> bool:                  # R1 approaching(ego, J): close, but not yet at the line
        return self.th.entry_tolerance_m < self.dist_to_entry <= self.th.approach_horizon_m

    @property
    def active(self) -> bool:
        """The junction is close enough to matter: approaching it, at its line or inside it."""
        return self.approaching or self.at_entry or self.inside

    @property
    def before_shared_area(self) -> bool:           # R4 in_waiting_area(ego, J), generalised
        """Inside the junction but not yet on road shared with any movement that may currently
        move. Movements held at a red signal do not count, so the area shrinks when the
        lights change."""
        if not self.inside:
            return False
        starts = [s for link, s in self.region.meets if self.signal(link) != "STOP"]
        return bool(starts) and self.front < min(starts)

    @property
    def dist_to_shared(self) -> Optional[float]:
        """Front bumper to the first road shared with a movement that may currently move.
        Negative once on it; None if the ego's path through this junction shares no such road."""
        if self.region is None:
            return None
        starts = [s for link, s in self.region.meets if self.signal(link) != "STOP"]
        return min(starts) - self.front if starts else None

    @property
    def can_stop_before_entry(self) -> bool:        # R13
        return (self.region is not None and not self.inside
                and stopping_distance(self.ego.speed, self.th.comfortable_decel) <= self.dist_to_entry)

    # ---- control facing the ego (R5, R6) --------------------------------------------------

    def signal(self, link: Link) -> Optional[str]:
        return self.frame.signals.get(link.signal) if link.signal else None

    @property
    def entry_control(self) -> Optional[str]:
        return self.region.entry_link.control if self.active else None

    @property
    def entry_signal(self) -> Optional[str]:
        return self.signal(self.region.entry_link) if self.active else None

    # ---- ego versus other cars (R7-R9) ----------------------------------------------------

    def _placements(self, v: Vehicle) -> List[Tuple[Link, float]]:
        """Movements a car may be making, each with how far its centre is past that movement's
        entry line (negative while still on the approach lane)."""
        scene, th = self.scene, self.th
        here = Point(v.x, v.y)
        for node in self.region.scope:
            if not scene.junction_area[node].contains(here):
                continue
            fits, nearest = [], None
            for link in scene.mapinfo.links(node):
                line = scene.line(link)
                s, lateral = line.project(v.x, v.y)
                if nearest is None or lateral < nearest[0]:
                    nearest = (lateral, link, s)
                if (lateral <= th.commit_lateral_m
                        and angle_diff(v.yaw, line.heading_at(s)) <= math.radians(th.commit_heading_deg)):
                    fits.append((link, s))
            return fits or [(nearest[1], nearest[2])]
        best = None
        for lane, line in scene.approach_lanes[self.region].items():
            s, lateral = line.project(v.x, v.y)
            if lateral <= 2.0 and angle_diff(v.yaw, line.heading_at(s)) <= math.pi / 4:
                if best is None or lateral < best[0]:
                    best = (lateral, lane, s - line.length)
        if best is None:
            return []       # not on a lane leading into this junction: out of scope
        return [(link, best[2]) for link in scene.mapinfo.links_from(best[1])]

    def _possible_movements(self, v: Vehicle):
        """Every movement the car may still make inside this junction. On a roundabout that
        includes movements at later ring junctions it may drive on to, up to all but one of
        the ring's junctions (a car is not assumed to circle the whole ring)."""
        scene = self.scene

        def onward(link: Link, centre: float, hops: int):
            yield link, centre
            if hops and link.to_lane.rsplit("_", 1)[0] in scene.mapinfo.roundabout_edges:
                travelled = scene.line(link).length + scene.lane_length(link.to_lane)
                for nxt in scene.mapinfo.links_from(link.to_lane):
                    yield from onward(nxt, centre - travelled, hops - 1)

        for link, centre in self._placements(v):
            yield from onward(link, centre, max(len(self.region.scope) - 2, 0))

    def _ego_part(self, node: str) -> Optional[JunctionOnRoute]:
        return next((p for p in self.region.parts
                     if p.link.junction == node and p.exit_s > self.rear), None)

    @cached_property
    def conflicts(self) -> List[Conflict]:          # R7 path_conflict(ego, o), one entry per possible movement
        if not self.active:
            return []
        scene, found = self.scene, []
        for name, v in self.others.items():
            for link, centre in self._possible_movements(v):
                part = self._ego_part(link.junction)
                if part is None or link.index == part.link.index:
                    continue
                if not scene.mapinfo.paths_cross(part.link, link):
                    continue
                a_in, a_out, b_in, b_past = scene.shared(part.link, link)
                ego_in, ego_out = part.entry_s + a_in, part.entry_s + a_out
                front, rear = centre + v.length / 2, centre - v.length / 2
                if self.rear > ego_out or rear > b_past:
                    continue        # one of the two is already past
                found.append(Conflict(name, part.link, link, ego_in, ego_out,
                                      b_in - front, b_past - rear, v.speed, front > 0))
        return found

    def has_priority(self, c: Conflict) -> bool:    # R8 has_priority(ego, o)
        """Signs and priority come from the map's right-of-way table. A signal overrides it:
        a car facing red has no priority, except that a car already inside keeps it over
        cars still outside. The ego is never credited with priority while its signal is red."""
        ego_signal, other_signal = self.signal(c.ego_movement), self.signal(c.movement)
        if ego_signal is not None and ego_signal not in SIGNAL_OPEN:
            return False
        if other_signal is not None and other_signal not in SIGNAL_OPEN:
            return not c.inside
        return self.scene.mapinfo.must_yield(c.movement, c.ego_movement)

    def gap_safe(self, c: Conflict) -> bool:        # R9 gap_safe(ego, o)
        """If the ego goes now, the two cars use the shared area at least `gap_margin_s` apart,
        whichever goes first. The other car is assumed to keep its current speed (or, with
        `gap_other_at_least_limit`, to arrive no slower than the speed limit of its lane)."""
        th = self.th
        cap = self.scene.mapinfo.speed_limit(c.ego_movement.via[0])
        ego_arrives = time_to_cover(c.ego_in - self.front, self.ego.speed, th.gap_ego_accel, cap)
        ego_clears = time_to_cover(c.ego_out - self.rear, self.ego.speed, th.gap_ego_accel, cap)
        moving = c.speed >= th.stopped_speed
        speed = c.speed
        if moving and th.gap_other_at_least_limit:
            speed = max(speed, self.scene.mapinfo.speed_limit(c.movement.from_lane))
        other_arrives = 0.0 if c.dist_in <= 0 else (c.dist_in / speed if moving else INF)
        other_clears = c.dist_out / c.speed if moving else INF
        return (other_arrives - ego_clears >= th.gap_margin_s
                or ego_arrives - other_clears >= th.gap_margin_s)

    def can_yield(self, c: Conflict) -> bool:
        """The other car can still stop before reaching the shared area."""
        return c.dist_in > 0 and stopping_distance(c.speed, self.th.others_stop_decel) <= c.dist_in

    # ---- occupancy (R10, R11) -------------------------------------------------------------

    def _corridor(self, s0: float, s1: float):
        piece = substring(self.scene.path.line, s0, s1)
        return piece.buffer(self.th.conflict_half_width_m, cap_style="flat")

    @cached_property
    def path_blocked(self) -> bool:                 # R10 blocks_path(o, ego) for some o
        if not self.active:
            return False
        start = max(self.front, self.region.entry_s)
        if start >= self.region.exit_s:
            return False
        corridor = self._corridor(start, self.region.exit_s)
        along = math.radians(self.th.same_direction_deg)
        for v in self.others.values():
            s, _ = self.scene.route.project(v.x, v.y)
            if angle_diff(v.yaw, self.scene.route.heading_at(s)) <= along:
                continue    # travelling along the ego's own path: a leader, not an obstruction
            if footprint(v).intersects(corridor):
                return True
        return False

    @cached_property
    def exit_clear(self) -> bool:                   # R11 exit_clear(ego, J)
        if self.region is None:
            return True
        zone = self._corridor(self.region.exit_s,
                              self.region.exit_s + self.ego.length + self.th.exit_space_m)
        return not any(v.speed < self.th.exit_blocking_speed and footprint(v).intersects(zone)
                       for v in self.others.values())

    # ---- terminal facts -------------------------------------------------------------------

    def event(self, name: str) -> bool:
        return name in (self.frame.events or [])

    @cached_property
    def touching(self) -> bool:
        me = footprint(self.ego)
        return any(me.intersects(footprint(v)) for v in self.others.values())

    @property
    def on_road(self) -> bool:
        return self.scene.road.contains(Point(self.ego.x, self.ego.y))
